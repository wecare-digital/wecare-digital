#!/usr/bin/env python3
"""Provision WhatsApp operational analytics infrastructure and read-only smoke IAM.

Safe default is dry-run. --apply creates/updates only:
- analytics exporter runtime/deploy roles;
- read-only post-deploy smoke role;
- exporter log retention;
- four Glue external tables;
- 400-day S3 analytics retention;
- two exporter failure alarms;
- hourly EventBridge trigger when the exporter Lambda already exists.

Lambda code is released through the repository's explicit operational deployment path; GitHub Actions are retired.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
FUNCTION = "wecare-whatsapp-analytics-export"
BUCKET = "wecare-digital-get"
PREFIX = "secure/d/public/whatsapp/analytics/operational"
DATABASE = "wecare_analytics"
RULE = "wecare-whatsapp-operational-analytics"
SNS = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"
RUNTIME_ROLE = "wecare-whatsapp-analytics-export-role"
DEPLOY_ROLE = "wecare-whatsapp-analytics-deploy-oidc"
SMOKE_ROLE = "wecare-whatsapp-smoke-oidc"
SOURCE_TABLES = [
    "stack-wecare-digital-WhatsAppOutboundTable",
    "stack-wecare-digital-FlowSubmissionTable",
    "stack-wecare-digital-OrderTable",
    "stack-wecare-digital-SystemEventTable",
]

DATASETS = {
    "whatsapp_delivery_lifecycle": ("delivery_lifecycle", [
        ("record_id","string"),("event_time","string"),("status","string"),
        ("template_name","string"),("template_category","string"),
        ("whatsapp_message_id","string"),("payment_reference_id","string"),
        ("waba_id","string"),("phone_number_id","string"),("message_type","string"),
        ("direction","string"),("is_template","boolean"),
    ]),
    "whatsapp_flow_submissions": ("flow_submissions", [
        ("submission_id","string"),("submission_number","string"),("flow_code","string"),
        ("flow_id","string"),("status","string"),("payment_status","string"),
        ("created_at","string"),("updated_at","string"),("order_id","string"),
        ("payment_reference_id","string"),("channel","string"),
    ]),
    "whatsapp_orders": ("orders", [
        ("order_id","string"),("short_id","string"),("order_number","string"),
        ("source","string"),("channel","string"),("order_status","string"),
        ("status","string"),("payment_status","string"),("amount_paise","bigint"),
        ("currency","string"),("created_at","string"),("updated_at","string"),
        ("reference_id","string"),("finalization_stage","string"),
    ]),
    "whatsapp_template_lifecycle": ("template_lifecycle", [
        ("event_id","string"),("event_type","string"),("waba_id","string"),
        ("phone_number_id","string"),("severity","string"),("acknowledged","boolean"),
        ("created_at","bigint"),("template_name","string"),("status","string"),
        ("quality","string"),("category","string"),("language","string"),
        ("reason_code","string"),("error_code","string"),
    ]),
}


def github_trust() -> dict:
    return {"Version":"2012-10-17","Statement":[{
        "Effect":"Allow",
        "Principal":{"Federated":f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"},
        "Action":"sts:AssumeRoleWithWebIdentity",
        "Condition":{"StringEquals":{
            "token.actions.githubusercontent.com:sub":
                "repo:wecare-digital@319896805/wecare-digital@1342943014:ref:refs/heads/wecare.digital",
            "token.actions.githubusercontent.com:aud":"sts.amazonaws.com",
        }},
    }]}


def runtime_policy() -> dict:
    return {"Version":"2012-10-17","Statement":[
        {"Sid":"ReadOperationalSources","Effect":"Allow","Action":["dynamodb:Scan"],
         "Resource":[f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{x}" for x in SOURCE_TABLES]},
        {"Sid":"WriteAnalyticsOnly","Effect":"Allow","Action":["s3:PutObject"],
         "Resource":[f"arn:aws:s3:::{BUCKET}/{PREFIX}/*"]},
        {"Sid":"WriteLogs","Effect":"Allow","Action":["logs:CreateLogStream","logs:PutLogEvents"],
         "Resource":[f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{FUNCTION}:*"]},
        {"Sid":"WriteXRay","Effect":"Allow",
         "Action":["xray:PutTraceSegments","xray:PutTelemetryRecords"],"Resource":"*"},
    ]}


def deploy_policy() -> dict:
    arn=f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}"
    return {"Version":"2012-10-17","Statement":[
        {"Sid":"DeployExporterOnly","Effect":"Allow","Action":[
            "lambda:CreateFunction","lambda:GetFunctionConfiguration","lambda:GetAlias",
            "lambda:GetFunction","lambda:UpdateFunctionCode","lambda:UpdateFunctionConfiguration",
            "lambda:PublishVersion","lambda:CreateAlias","lambda:UpdateAlias",
        ],"Resource":[arn,f"{arn}:*"]},
        {"Sid":"PassExporterRuntimeRoleOnly","Effect":"Allow","Action":["iam:PassRole"],
         "Resource":[f"arn:aws:iam::{ACCOUNT}:role/{RUNTIME_ROLE}"]},
    ]}


def smoke_policy() -> dict:
    names=["wecare-commerce","wecare-checkout",
           "wecare-inbound-whatsapp","wecare-outbound-whatsapp",
           "wecare-whatsapp-business-api","wecare-service-api","wecare-workspace-mcp"]
    resources=[]
    for name in names:
        arn=f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}"
        resources += [arn, f"{arn}:*"]
    return {"Version":"2012-10-17","Statement":[
        {"Sid":"ReadLiveLambdaConfig","Effect":"Allow",
         "Action":["lambda:GetFunctionConfiguration","lambda:GetFunctionConcurrency"],
         "Resource":resources},
        {"Sid":"InvokeBoundedOperationalReads","Effect":"Allow","Action":["lambda:InvokeFunction"],
         "Resource":[
             f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:wecare-whatsapp-business-api:live",
             f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:wecare-service-api:live",
         ]},
        {"Sid":"ReadReconciliationRule","Effect":"Allow",
         "Action":["events:DescribeRule","events:ListTargetsByRule"],
         "Resource":f"arn:aws:events:{REGION}:{ACCOUNT}:rule/wecare-whatsapp-delivery-reconciliation"},
        {"Sid":"ReadAlarmState","Effect":"Allow","Action":["cloudwatch:DescribeAlarms"],"Resource":"*"},
    ]}


def table_input(name: str, dataset: str, columns: list[tuple[str,str]]) -> dict:
    location=f"s3://{BUCKET}/{PREFIX}/{dataset}/"
    return {
        "Name":name,
        "Description":"Privacy-bounded WhatsApp operational analytics; excludes customer PII/content.",
        "StorageDescriptor":{
            "Columns":[{"Name":n,"Type":t} for n,t in columns],
            "Location":location,
            "InputFormat":"org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat":"org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "SerdeInfo":{"SerializationLibrary":"org.openx.data.jsonserde.JsonSerDe",
                         "Parameters":{"ignore.malformed.json":"true","case.insensitive":"true"}},
        },
        "PartitionKeys":[{"Name":"snapshot_date","Type":"string"},{"Name":"snapshot_hour","Type":"string"}],
        "TableType":"EXTERNAL_TABLE",
        "Parameters":{
            "classification":"json","projection.enabled":"true",
            "projection.snapshot_date.type":"date","projection.snapshot_date.format":"yyyy-MM-dd",
            "projection.snapshot_date.range":"2026-01-01,NOW","projection.snapshot_date.interval":"1",
            "projection.snapshot_date.interval.unit":"DAYS",
            "projection.snapshot_hour.type":"integer","projection.snapshot_hour.range":"0,23",
            "projection.snapshot_hour.digits":"2",
            "storage.location.template":location+"snapshot_date=${snapshot_date}/snapshot_hour=${snapshot_hour}/",
        },
    }


def ensure_role(iam, name: str, trust: dict, policy_name: str, policy: dict) -> None:
    try:
        iam.get_role(RoleName=name)
        iam.update_assume_role_policy(RoleName=name, PolicyDocument=json.dumps(trust))
    except iam.exceptions.NoSuchEntityException:
        iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust),
                        Description="WECARE WhatsApp operational hardening", MaxSessionDuration=3600)
    iam.put_role_policy(RoleName=name, PolicyName=policy_name, PolicyDocument=json.dumps(policy))


def apply() -> dict:
    iam=boto3.client("iam",region_name=REGION)
    logs=boto3.client("logs",region_name=REGION)
    glue=boto3.client("glue",region_name=REGION)
    s3=boto3.client("s3",region_name=REGION)
    cw=boto3.client("cloudwatch",region_name=REGION)
    events=boto3.client("events",region_name=REGION)
    lamb=boto3.client("lambda",region_name=REGION)

    ensure_role(iam,RUNTIME_ROLE,
                {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]},
                "WhatsAppOperationalAnalyticsRuntime",runtime_policy())
    ensure_role(iam,DEPLOY_ROLE,github_trust(),"WhatsAppOperationalAnalyticsDeploy",deploy_policy())
    ensure_role(iam,SMOKE_ROLE,github_trust(),"WhatsAppReadOnlyPostDeploySmoke",smoke_policy())

    log_group=f"/aws/lambda/{FUNCTION}"
    try: logs.create_log_group(logGroupName=log_group)
    except logs.exceptions.ResourceAlreadyExistsException: pass
    logs.put_retention_policy(logGroupName=log_group,retentionInDays=90)

    try: glue.get_database(Name=DATABASE)
    except glue.exceptions.EntityNotFoundException: glue.create_database(DatabaseInput={"Name":DATABASE})
    for name,(dataset,cols) in DATASETS.items():
        value=table_input(name,dataset,cols)
        try:
            glue.get_table(DatabaseName=DATABASE,Name=name)
            glue.update_table(DatabaseName=DATABASE,TableInput=value)
        except glue.exceptions.EntityNotFoundException:
            glue.create_table(DatabaseName=DATABASE,TableInput=value)

    try: rules=s3.get_bucket_lifecycle_configuration(Bucket=BUCKET).get("Rules",[])
    except ClientError as e:
        if e.response.get("Error",{}).get("Code")!="NoSuchLifecycleConfiguration": raise
        rules=[]
    rules=[r for r in rules if r.get("ID")!="wecare-whatsapp-operational-analytics-retention"]
    rules.append({"ID":"wecare-whatsapp-operational-analytics-retention","Status":"Enabled",
                  "Filter":{"Prefix":PREFIX+"/"},"Expiration":{"Days":400},
                  "NoncurrentVersionExpiration":{"NoncurrentDays":30}})
    s3.put_bucket_lifecycle_configuration(Bucket=BUCKET,LifecycleConfiguration={"Rules":rules})

    for alarm,namespace,metric,dims in [
        ("wecare-whatsapp-analytics-export-errors","AWS/Lambda","Errors",[{"Name":"FunctionName","Value":FUNCTION}]),
        ("wecare-whatsapp-analytics-eventbridge-failures","AWS/Events","FailedInvocations",[{"Name":"RuleName","Value":RULE}]),
    ]:
        cw.put_metric_alarm(AlarmName=alarm,Namespace=namespace,MetricName=metric,Dimensions=dims,
                            Statistic="Sum",Period=3600,EvaluationPeriods=1,DatapointsToAlarm=1,
                            Threshold=0,ComparisonOperator="GreaterThanThreshold",
                            TreatMissingData="notBreaching",AlarmActions=[SNS])

    scheduled=False
    try:
        lamb.get_function_configuration(FunctionName=FUNCTION,Qualifier="live")
        rule=events.put_rule(Name=RULE,ScheduleExpression="rate(1 hour)",State="ENABLED",
                             Description="Hourly privacy-bounded WhatsApp operational analytics snapshot.")
        events.put_targets(Rule=RULE,Targets=[{"Id":"analytics-export",
            "Arn":f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}:live"}])
        try:
            lamb.add_permission(FunctionName=FUNCTION,Qualifier="live",
                StatementId="EventBridgeWhatsAppOperationalAnalytics",
                Action="lambda:InvokeFunction",Principal="events.amazonaws.com",SourceArn=rule["RuleArn"])
        except lamb.exceptions.ResourceConflictException: pass
        scheduled=True
    except lamb.exceptions.ResourceNotFoundException:
        pass

    return {"roles":[RUNTIME_ROLE,DEPLOY_ROLE,SMOKE_ROLE],"glueTables":sorted(DATASETS),
            "retentionDays":400,"scheduleInstalled":scheduled}


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    if not args.apply:
        print(json.dumps({"apply":False,"roles":[RUNTIME_ROLE,DEPLOY_ROLE,SMOKE_ROLE],
                          "glueTables":sorted(DATASETS),"retentionDays":400,
                          "schedule":"rate(1 hour) after Lambda exists"},indent=2))
        return 0
    try:
        print(json.dumps(apply(),indent=2))
        return 0
    except ClientError as exc:
        print(f"AWS error: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    sys.exit(main())
