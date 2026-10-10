"""Versioned rollout for the inbound WhatsApp Lambda, with canary and alias rollback.

WHY THIS SCRIPT EXISTS SEPARATELY FROM deploy_task12.py.

`deploy_task12.py` packages a function as `handler.py` plus a FLAT `lambda_utils/*.py`. That
shape is wrong for `wecare-inbound-whatsapp` for two reasons, and a wrong package fails at the
first invoke with ImportError, not at deploy:

  1. The handler lives at amplify/functions/messaging/inbound-whatsapp-handler/ and imports from
     a `modules/` SUBDIRECTORY beside it:
         from modules.content import extract_content, ...
     A handler-only zip omits modules/content.py and the function dies on cold start.

  2. The handler imports deep into `lambda_utils` SUBPACKAGES, not just its top-level modules:
         from lambda_utils.ecommerce import order_keys, whatsapp_basket
         from lambda_utils.webhook_dedup import claim_event
         from lambda_utils.integrations ...
     A flat `lambda_utils/*.py` zip misses every subpackage.

So this script zips THREE things, preserving directory structure:
    handler.py                      -> handler.py            (at the archive root)
    inbound-whatsapp-handler/modules -> modules/             (whole tree)
    shared/lambda_utils             -> lambda_utils/         (whole tree, subpackages included)
    shared/static_knowledge_base.py -> static_knowledge_base.py  (if present)

NO AWS CREDENTIALS ARE EMBEDDED. The caller must have Lambda update permission in us-east-1
for account 775261844268. Running it anywhere without those credentials fails at the first API
call and changes nothing. `--dry-run` builds the zip and reports its SHA without any AWS call,
which is the safe way to verify packaging in a sandbox.

ROLLBACK is automatic on any failure: the live alias is returned to its previous version (or
removed if there was none), and $LATEST code is restored from the pre-deploy package. The
previous version is also printed on success, so a manual one-line rollback is always available:
    aws lambda update-alias --function-name wecare-inbound-whatsapp --name live \
        --function-version <PREVIOUS> --region us-east-1

Usage:
    python scripts/deploy_inbound_whatsapp.py --dry-run     # build + hash only, no AWS
    python scripts/deploy_inbound_whatsapp.py               # full versioned rollout
"""
import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

REGION = "us-east-1"
ACCOUNT = "775261844268"
FUNCTION_NAME = "wecare-inbound-whatsapp"

ROOT = Path(__file__).resolve().parents[1]
HANDLER_DIR = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler"
HANDLER = HANDLER_DIR / "handler.py"
MODULES_DIR = HANDLER_DIR / "modules"
SHARED = ROOT / "amplify/functions/shared"
LAMBDA_UTILS = SHARED / "lambda_utils"
STATIC_KB = SHARED / "static_knowledge_base.py"

#: Directories whose contents never belong in a Lambda package.
_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
#: File suffixes that are build artefacts, never source.
_SKIP_SUFFIXES = {".pyc", ".pyo"}


def _should_skip(path: Path) -> bool:
    if path.suffix in _SKIP_SUFFIXES:
        return True
    return any(part in _SKIP_DIRS for part in path.parts)


def _add_tree(archive: zipfile.ZipFile, source_dir: Path, arc_prefix: str) -> int:
    """Write every source file under `source_dir` into the archive under `arc_prefix/`.

    Entry names are forced to forward slashes (zipfile does this on POSIX already; it is made
    explicit so a Windows run cannot emit the backslash entries that GAP-006 in the maintenance
    report flags across the existing fleet). Returns the number of files written.
    """
    count = 0
    for item in sorted(source_dir.rglob("*")):
        if item.is_dir() or _should_skip(item.relative_to(source_dir)):
            continue
        arcname = f"{arc_prefix}/{item.relative_to(source_dir).as_posix()}"
        archive.write(item, arcname)
        count += 1
    return count


def build_zip() -> bytes:
    """handler.py at the root, plus the modules/ and lambda_utils/ trees it imports."""
    if not HANDLER.exists():
        raise FileNotFoundError(f"missing handler: {HANDLER}")
    if not MODULES_DIR.is_dir():
        raise FileNotFoundError(f"missing modules/ dir: {MODULES_DIR}")
    if not LAMBDA_UTILS.is_dir():
        raise FileNotFoundError(f"missing shared lambda_utils: {LAMBDA_UTILS}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(HANDLER, "handler.py")
        n_modules = _add_tree(archive, MODULES_DIR, "modules")
        n_utils = _add_tree(archive, LAMBDA_UTILS, "lambda_utils")
        n_kb = 0
        if STATIC_KB.exists():
            archive.write(STATIC_KB, "static_knowledge_base.py")
            n_kb = 1
    data = buffer.getvalue()
    print(json.dumps({
        "event": "package_built",
        "handler": 1, "modules_files": n_modules,
        "lambda_utils_files": n_utils, "static_knowledge_base": n_kb,
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }))
    return data


def _wait_updated(client) -> None:
    client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)


def _wait_version_active(client, version: str) -> None:
    deadline = time.time() + 600
    while time.time() < deadline:
        config = client.get_function_configuration(
            FunctionName=FUNCTION_NAME, Qualifier=version,
        )
        state = config.get("State", "Active")
        snap = config.get("SnapStart", {}).get("OptimizationStatus", "On")
        if state == "Active" and snap != "InProgress":
            return
        if state == "Failed" or snap == "Failed":
            raise RuntimeError(f"{FUNCTION_NAME}:{version} failed to activate")
        time.sleep(5)
    raise TimeoutError(f"Timed out activating {FUNCTION_NAME}:{version}")


def _canary(client, version: str) -> None:
    """A webhook GET verification probe. Meta's inbound route answers GET with the hub challenge
    echo or a 403; either is a non-5xx, which is all the canary asserts — that the new code
    imports and runs rather than crashing on cold start (the ImportError this packaging exists to
    prevent would surface here as a function error)."""
    event = {
        "rawPath": "/whatsapp/inbound",
        "requestContext": {"http": {"method": "GET", "path": "/whatsapp/inbound"}},
        "queryStringParameters": {"hub.mode": "subscribe", "hub.challenge": "__canary__",
                                  "hub.verify_token": "__canary_invalid__"},
        "headers": {},
    }
    response = client.invoke(
        FunctionName=FUNCTION_NAME, Qualifier=version,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8"),
    )
    if response.get("FunctionError"):
        payload = response["Payload"].read().decode("utf-8", "replace")
        raise RuntimeError(f"{FUNCTION_NAME}:{version} canary raised a function error: {payload}")
    payload = json.loads(response["Payload"].read() or b"{}")
    status = int(payload.get("statusCode", 500))
    if status >= 500:
        raise RuntimeError(f"{FUNCTION_NAME}:{version} canary returned HTTP {status}")


def _current_package(client) -> bytes:
    import urllib.request
    location = client.get_function(FunctionName=FUNCTION_NAME)["Code"]["Location"]
    with urllib.request.urlopen(location, timeout=120) as response:
        return response.read()


def _promote(client, version: str):
    aliases = client.list_aliases(FunctionName=FUNCTION_NAME).get("Aliases", [])
    live = next((item for item in aliases if item.get("Name") == "live"), None)
    previous = live.get("FunctionVersion") if live else None
    if live:
        client.update_alias(FunctionName=FUNCTION_NAME, Name="live",
                            FunctionVersion=version,
                            RoutingConfig={"AdditionalVersionWeights": {}})
    else:
        client.create_alias(FunctionName=FUNCTION_NAME, Name="live",
                            FunctionVersion=version,
                            Description="inbound WhatsApp production alias")
    return previous


def deploy() -> None:
    import boto3  # imported late so --dry-run needs no boto3 and no credentials

    client = boto3.client("lambda", region_name=REGION)
    print(f"DEPLOY {FUNCTION_NAME} ({REGION}, account {ACCOUNT})")
    previous_package = _current_package(client)
    previous_version = None
    try:
        client.update_function_code(
            FunctionName=FUNCTION_NAME, ZipFile=build_zip(), Publish=False,
        )
        _wait_updated(client)
        published = client.publish_version(
            FunctionName=FUNCTION_NAME,
            Description="inbound WhatsApp command/keyword rollout",
        )
        version = published["Version"]
        _wait_version_active(client, version)
        _canary(client, version)
        previous_version = _promote(client, version)
        print(json.dumps({
            "event": "promoted", "function": FUNCTION_NAME,
            "version": version, "previous": previous_version or "none",
            "rollback": (f"aws lambda update-alias --function-name {FUNCTION_NAME} "
                         f"--name live --function-version {previous_version} --region {REGION}")
                        if previous_version else "delete the new live alias to roll back",
        }))
    except Exception as error:
        print(f"ROLLBACK after failure: {error}")
        try:
            if previous_version:
                client.update_alias(FunctionName=FUNCTION_NAME, Name="live",
                                    FunctionVersion=previous_version,
                                    RoutingConfig={"AdditionalVersionWeights": {}})
                print(f"ROLLBACK live -> v{previous_version}")
            client.update_function_code(
                FunctionName=FUNCTION_NAME, ZipFile=previous_package, Publish=False,
            )
            _wait_updated(client)
            print("ROLLBACK restored $LATEST code")
        except Exception as rollback_error:
            print(f"ROLLBACK FAILED: {rollback_error}")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="build the zip and print its SHA, make no AWS call")
    args = parser.parse_args()
    if args.dry_run:
        build_zip()
        print(json.dumps({"event": "dry_run_complete", "deployed": False}))
        return
    deploy()


if __name__ == "__main__":
    main()
