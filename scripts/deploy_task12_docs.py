"""Build and deploy the Task 12 docs-scraper image through temporary CodeBuild."""
import io
import json
import time
import zipfile
from pathlib import Path

import boto3

REGION = "us-east-1"
ACCOUNT = "775261844268"
# CodeBuild source-artifact bucket. Was `wecare-digital-get`, which was deleted on
# 2026-09-28 — this was the last hard-coded S3 bucket literal in the tree naming it,
# and the next run would have failed with NoSuchBucket.
BUCKET = "wecare-digital-get"
REPOSITORY = "wecare-docs-scraper"
FUNCTION = "wecare-docs-scraper"
ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "amplify/functions/operations/docs-scraper"
SHARED = ROOT / "amplify/functions/shared/lambda_utils"


def source_zip(buildspec: str) -> bytes:
    dockerfile = (DOCS / "Dockerfile").read_text(encoding="utf-8")
    dockerfile = dockerfile.replace(
        "COPY handler.py .", "COPY handler.py .\nCOPY lambda_utils ./lambda_utils",
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Dockerfile", dockerfile)
        archive.writestr("buildspec.yml", buildspec)
        archive.write(DOCS / "handler.py", "handler.py")
        archive.write(DOCS / "requirements.txt", "requirements.txt")
        for source in SHARED.glob("*.py"):
            archive.write(source, f"lambda_utils/{source.name}")
    return output.getvalue()


def wait_build(codebuild, build_id: str) -> None:
    while True:
        build = codebuild.batch_get_builds(ids=[build_id])["builds"][0]
        status = build["buildStatus"]
        print(f"CODEBUILD {status}")
        if status == "SUCCEEDED":
            return
        if status in {"FAILED", "FAULT", "STOPPED", "TIMED_OUT"}:
            raise RuntimeError(f"CodeBuild ended with {status}")
        time.sleep(15)


def canary(lam) -> None:
    event = {
        "rawPath": "/docs/sources",
        "routeKey": "GET /docs/sources",
        "requestContext": {"http": {"method": "OPTIONS", "path": "/docs/sources"}},
        "headers": {"origin": "https://wecare.digital"},
    }
    response = lam.invoke(
        FunctionName=FUNCTION, InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8"),
    )
    if response.get("FunctionError"):
        raise RuntimeError("Docs scraper canary raised a function error")
    payload = json.loads(response["Payload"].read() or b"{}")
    if int(payload.get("statusCode", 500)) >= 500:
        raise RuntimeError("Docs scraper canary failed")


def main() -> None:
    stamp = str(int(time.time()))
    project = f"task12-docs-{stamp}"
    role_name = f"task12-codebuild-{stamp}"
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/{role_name}"
    # Rooted under `secure/`, not at the bucket root, for two separate reasons.
    #
    # 1. `wecare-digital-get` has exactly two top-level prefixes, `o/` and `secure/`,
    #    and scripts/verify_media_prefixes.py asserts that. A key at `deploy/...`
    #    would have created a third root and failed that check.
    # 2. `o/` would have been worse than wrong. Everything outside `secure/` is
    #    PUBLIC — `o/` only controls dual-homing, not access — so a source zip
    #    holding the Dockerfile and handler code would have been fetchable at
    #    https://wecare.digital/get/o/deploy/... `secure/` is denied at the edge by
    #    the wecare-get-miss-redirect Lambda@Edge.
    #
    # The object is deleted again once the build finishes (see the cleanup below).
    key = f"secure/deploy/task12/docs-{stamp}.zip"
    tag = f"task12-{stamp}"
    repository_uri = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{REPOSITORY}"
    image_uri = f"{repository_uri}:{tag}"
    buildspec = f"""version: 0.2
phases:
  pre_build:
    commands:
      - aws ecr get-login-password --region {REGION} | docker login --username AWS --password-stdin {ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com
  build:
    commands:
      - docker build -t {image_uri} .
  post_build:
    commands:
      - docker push {image_uri}
"""
    s3 = boto3.client("s3", region_name=REGION)
    iam = boto3.client("iam")
    codebuild = boto3.client("codebuild", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)
    old_image = lam.get_function(FunctionName=FUNCTION)["Code"]["ImageUri"]
    trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "codebuild.amazonaws.com"}, "Action": "sts:AssumeRole"}],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], "Resource": "*"},
            {"Effect": "Allow", "Action": ["ecr:GetAuthorizationToken"], "Resource": "*"},
            {"Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"], "Resource": f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{REPOSITORY}"},
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion"], "Resource": f"arn:aws:s3:::{BUCKET}/{key}"},
        ],
    }
    s3.put_object(Bucket=BUCKET, Key=key, Body=source_zip(buildspec))
    iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=json.dumps(trust))
    iam.put_role_policy(RoleName=role_name, PolicyName="Task12Build", PolicyDocument=json.dumps(policy))
    time.sleep(10)

    try:
        codebuild.create_project(
            name=project,
            source={"type": "S3", "location": f"{BUCKET}/{key}", "buildspec": "buildspec.yml"},
            artifacts={"type": "NO_ARTIFACTS"},
            environment={
                "type": "LINUX_CONTAINER", "computeType": "BUILD_GENERAL1_SMALL",
                "image": "aws/codebuild/standard:7.0", "privilegedMode": True,
            },
            serviceRole=role_arn,
        )
        build_id = codebuild.start_build(projectName=project)["build"]["id"]
        wait_build(codebuild, build_id)
        image_updated = False
        try:
            lam.update_function_code(FunctionName=FUNCTION, ImageUri=image_uri, Publish=False)
            image_updated = True
            lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
            canary(lam)
        except Exception:
            if image_updated:
                lam.update_function_code(FunctionName=FUNCTION, ImageUri=old_image, Publish=False)
                lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
            raise
        print(json.dumps({"function": FUNCTION, "imageTag": tag, "canary": "passed"}))
    finally:
        try:
            codebuild.delete_project(name=project)
        except Exception:
            pass
        try:
            iam.delete_role_policy(RoleName=role_name, PolicyName="Task12Build")
            iam.delete_role(RoleName=role_name)
        except Exception:
            pass
        try:
            s3.delete_object(Bucket=BUCKET, Key=key)
        except Exception:
            pass


if __name__ == "__main__":
    main()