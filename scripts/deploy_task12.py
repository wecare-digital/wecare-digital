"""Versioned Task 12 Lambda rollout with safe canaries and alias rollback."""
import io
import json
import time
import urllib.request
import zipfile
from pathlib import Path

import boto3

REGION = "us-east-1"
ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared/lambda_utils"
FUNCTIONS = {
    "wecare-messages-read": "amplify/functions/core/messages-read/handler.py",
    "wecare-outbound-whatsapp": "amplify/functions/messaging/outbound-whatsapp/handler.py",
    "wecare-push-notifications": "amplify/functions/messaging/push-notifications/handler.py",
    "wecare-scheduled-messages": "amplify/functions/messaging/scheduled-messages/handler.py",
    "wecare-waba-management": "amplify/functions/messaging/waba-management/handler.py",
    "wecare-whatsapp-calling": "amplify/functions/messaging/whatsapp-calling/handler.py",
    "wecare-whatsapp-voice": "amplify/functions/messaging/whatsapp-voice/handler.py",
    "wecare-invoice-engine": "amplify/functions/payments/invoice-engine/handler.py",
}


def package(handler_path: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / handler_path, "handler.py")
        for source in SHARED.glob("*.py"):
            archive.write(source, f"lambda_utils/{source.name}")
        knowledge = ROOT / "amplify/functions/shared/static_knowledge_base.py"
        if knowledge.exists():
            archive.write(knowledge, knowledge.name)
    return output.getvalue()


def current_package(client, function_name: str) -> bytes:
    location = client.get_function(FunctionName=function_name)["Code"]["Location"]
    with urllib.request.urlopen(location, timeout=120) as response:
        return response.read()


def wait_version(client, function_name: str, version: str) -> None:
    deadline = time.time() + 600
    while time.time() < deadline:
        config = client.get_function_configuration(
            FunctionName=function_name, Qualifier=version,
        )
        state = config.get("State", "Active")
        snap = config.get("SnapStart", {}).get("OptimizationStatus", "On")
        if state == "Active" and snap != "InProgress":
            return
        if state == "Failed" or snap == "Failed":
            raise RuntimeError(f"{function_name}:{version} failed to activate")
        time.sleep(5)
    raise TimeoutError(f"Timed out activating {function_name}:{version}")


def canary(client, function_name: str, version: str) -> None:
    event = {
        "rawPath": "/__task12_canary__",
        "requestContext": {"http": {"method": "OPTIONS", "path": "/__task12_canary__"}},
        "headers": {"origin": "https://wecare.digital"},
    }
    response = client.invoke(
        FunctionName=function_name,
        Qualifier=version,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8"),
    )
    if response.get("FunctionError"):
        raise RuntimeError(f"{function_name}:{version} canary raised a function error")
    payload = json.loads(response["Payload"].read() or b"{}")
    status = int(payload.get("statusCode", 500))
    if status >= 500:
        raise RuntimeError(f"{function_name}:{version} canary returned HTTP {status}")


def promote(client, function_name: str, version: str):
    aliases = client.list_aliases(FunctionName=function_name).get("Aliases", [])
    live = next((item for item in aliases if item.get("Name") == "live"), None)
    previous = live.get("FunctionVersion") if live else None
    if live:
        client.update_alias(
            FunctionName=function_name, Name="live", FunctionVersion=version,
            RoutingConfig={"AdditionalVersionWeights": {}},
        )
    else:
        client.create_alias(
            FunctionName=function_name, Name="live", FunctionVersion=version,
            Description="Task 12 production alias",
        )
    return previous


def rollback(client, promoted):
    for function_name, previous in reversed(promoted):
        if previous:
            client.update_alias(
                FunctionName=function_name, Name="live",
                FunctionVersion=previous,
                RoutingConfig={"AdditionalVersionWeights": {}},
            )
            print(f"ROLLBACK {function_name} -> v{previous}")
        else:
            client.delete_alias(FunctionName=function_name, Name="live")
            print(f"ROLLBACK removed new live alias for {function_name}")


def restore_packages(client, packages) -> None:
    for function_name, payload in reversed(list(packages.items())):
        try:
            client.update_function_code(
                FunctionName=function_name, ZipFile=payload, Publish=False,
            )
            client.get_waiter("function_updated_v2").wait(FunctionName=function_name)
            print(f"ROLLBACK restored $LATEST for {function_name}")
        except Exception as error:
            print(f"ROLLBACK FAILED restoring $LATEST for {function_name}: {error}")


def main() -> None:
    client = boto3.client("lambda", region_name=REGION)
    promoted = []
    previous_packages = {}
    try:
        for function_name, handler_path in FUNCTIONS.items():
            print(f"DEPLOY {function_name}")
            previous_packages[function_name] = current_package(client, function_name)
            client.update_function_code(
                FunctionName=function_name, ZipFile=package(handler_path), Publish=False,
            )
            client.get_waiter("function_updated_v2").wait(FunctionName=function_name)
            published = client.publish_version(
                FunctionName=function_name,
                Description="Task 12 hardened production release",
            )
            version = published["Version"]
            wait_version(client, function_name, version)
            canary(client, function_name, version)
            previous = promote(client, function_name, version)
            promoted.append((function_name, previous))
            print(f"PROMOTED {function_name} v{version} (previous v{previous or 'none'})")
    except Exception:
        rollback(client, promoted)
        restore_packages(client, previous_packages)
        raise
    print(json.dumps({"deployed": len(promoted), "functions": [name for name, _ in promoted]}))


if __name__ == "__main__":
    main()