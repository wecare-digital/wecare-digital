"""Provision the dedicated WECARE.DIGITAL protected-blog auto-audit Lambda.

Creates/updates:
- least-privilege execution role;
- wecare-blog-auto-audit Lambda;
- CloudWatch log retention;
- EventBridge Scheduler role and daily schedule.

Usage:
    python scripts/provision_blog_auto_audit.py
    python scripts/provision_blog_auto_audit.py --no-schedule
"""
from __future__ import annotations

import argparse
import io
import json
import time
import zipfile
from pathlib import Path

import boto3

REGION = "us-east-1"
ACCOUNT = "775261844268"
ROOT = Path(__file__).resolve().parents[1]
FUNCTION_DIR = ROOT / "amplify" / "functions" / "operations" / "blog-auto-audit"

FUNCTION_NAME = "wecare-blog-auto-audit"
EXEC_ROLE = "wecare-blog-auto-audit-role"
SCHEDULER_ROLE = "wecare-blog-auto-audit-scheduler-role"
SCHEDULE_NAME = "wecare-blog-auto-audit-daily"
TABLE_NAME = "stack-wecare-digital-SeoToolsTable"
LOG_GROUP = f"/aws/lambda/{FUNCTION_NAME}"
SCHEDULE_EXPRESSION = "cron(30 2 * * ? *)"  # 08:00 Asia/Kolkata, daily.


def _package() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("handler.py", "rules.py"):
            path = FUNCTION_DIR / name
            if not path.exists():
                raise FileNotFoundError(path)
            archive.write(path, name)
    return buf.getvalue()


def ensure_execution_role() -> str:
    iam = boto3.client("iam", region_name=REGION)
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    try:
        iam.create_role(
            RoleName=EXEC_ROLE,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Least-privilege role for protected blog audit and deterministic safe fixes.",
        )
    except iam.exceptions.EntityAlreadyExistsException:
        iam.update_assume_role_policy(RoleName=EXEC_ROLE, PolicyDocument=json.dumps(trust))

    table_arn = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE_NAME}"
    iam.put_role_policy(
        RoleName=EXEC_ROLE,
        PolicyName="blog-auto-audit",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "BlogTableOnly",
                    "Effect": "Allow",
                    "Action": [
                        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                        "dynamodb:Query", "dynamodb:DescribeTable",
                    ],
                    "Resource": [table_arn, f"{table_arn}/index/*"],
                },
                {
                    "Sid": "FunctionLogs",
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{LOG_GROUP}:*",
                },
            ],
        }),
    )
    return f"arn:aws:iam::{ACCOUNT}:role/{EXEC_ROLE}"


def ensure_function(role_arn: str) -> None:
    lam = boto3.client("lambda", region_name=REGION)
    code = _package()
    env = {
        "LOG_LEVEL": "INFO",
        "SEO_TOOLS_TABLE": TABLE_NAME,
        "BLOG_AUTO_APPLY": "true",
        "BLOG_AUTO_MAX_WRITES": "50",
    }
    try:
        lam.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except lam.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=code)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        lam.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Handler="handler.handler",
            Role=role_arn,
            Timeout=300,
            MemorySize=256,
            Environment={"Variables": env},
        )
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    else:
        # IAM role propagation is eventually consistent.
        for attempt in range(6):
            try:
                lam.create_function(
                    FunctionName=FUNCTION_NAME,
                    Runtime="python3.12",
                    Handler="handler.handler",
                    Role=role_arn,
                    Code={"ZipFile": code},
                    Timeout=300,
                    MemorySize=256,
                    Environment={"Variables": env},
                    Architectures=["x86_64"],
                )
                break
            except lam.exceptions.InvalidParameterValueException:
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
        lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)


def ensure_logs() -> None:
    logs = boto3.client("logs", region_name=REGION)
    try:
        logs.create_log_group(logGroupName=LOG_GROUP)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=90)


def ensure_schedule() -> None:
    iam = boto3.client("iam", region_name=REGION)
    scheduler = boto3.client("scheduler", region_name=REGION)
    fn_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}"

    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "scheduler.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}},
        }],
    }
    try:
        iam.create_role(
            RoleName=SCHEDULER_ROLE,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Invoke the protected blog auto-audit Lambda on schedule.",
        )
    except iam.exceptions.EntityAlreadyExistsException:
        iam.update_assume_role_policy(
            RoleName=SCHEDULER_ROLE,
            PolicyDocument=json.dumps(trust),
        )

    iam.put_role_policy(
        RoleName=SCHEDULER_ROLE,
        PolicyName="invoke-blog-auto-audit",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": fn_arn,
            }],
        }),
    )
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/{SCHEDULER_ROLE}"
    target = {
        "Arn": fn_arn,
        "RoleArn": role_arn,
        "Input": json.dumps({"apply": True, "source": "scheduler"}),
        "RetryPolicy": {"MaximumRetryAttempts": 1},
    }
    common = {
        "ScheduleExpression": SCHEDULE_EXPRESSION,
        "ScheduleExpressionTimezone": "UTC",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "State": "ENABLED",
        "Description": "Daily protected-blog audit and exact deterministic safe-fix sweep.",
        "Target": target,
    }

    def put(op):
        for attempt in range(6):
            try:
                op(Name=SCHEDULE_NAME, **common)
                return
            except scheduler.exceptions.ValidationException:
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)

    try:
        put(scheduler.create_schedule)
    except scheduler.exceptions.ConflictException:
        put(scheduler.update_schedule)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-schedule", action="store_true")
    args = parser.parse_args()

    role_arn = ensure_execution_role()
    ensure_logs()
    ensure_function(role_arn)
    if not args.no_schedule:
        ensure_schedule()
    print(json.dumps({
        "function": FUNCTION_NAME,
        "table": TABLE_NAME,
        "schedule": None if args.no_schedule else SCHEDULE_NAME,
        "scheduleExpression": None if args.no_schedule else SCHEDULE_EXPRESSION,
        "autoApply": True,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
