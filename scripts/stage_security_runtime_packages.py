"""Stage reviewed runtime Lambda packages; never change live AWS resources."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import deploy_all_lambdas as deploy

TARGETS = (
    "wecare-inbound-whatsapp",
    "wecare-whatsapp-calling",
    "wecare-notification-worker",
    "wecare-razorpay-webhook",
    "wecare-catalog-management",
    "wecare-product-image-gen",
    "wecare-payments-read",
    "wecare-marketing-ads",
    "wecare-push-notifications",
    "wecare-whatsapp-business-api",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise SystemExit("Expected a pinned source revision")
    specs = {s.name: s for s in deploy.SPECS if s.name in TARGETS}
    if set(specs) != set(TARGETS):
        raise SystemExit("Security release target missing from canonical deploy map")
    args.output.mkdir(parents=True, exist_ok=True)
    summary = {"sourceCommit": args.commit, "packages": {}}
    for name in TARGETS:
        data, members = deploy.build_zip(specs[name])
        if "handler.py" not in members or not any(k.startswith("lambda_utils/") for k in members):
            raise SystemExit("Incomplete runtime package: " + name)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sorted(archive.namelist()) != sorted(members) or archive.testzip() is not None:
                raise SystemExit("Invalid package: " + name)
            for key in members:
                if archive.read(key) != members[key]:
                    raise SystemExit("Archive differs from source: " + name)
                if key.endswith(".py"):
                    compile(members[key], key, "exec")
        digest = hashlib.sha256(data).digest()
        filename = name + ".zip"
        (args.output / filename).write_bytes(data)
        summary["packages"][name] = {
            "file": filename, "sha256": digest.hex(),
            "codeSha256": base64.b64encode(digest).decode("ascii"),
            "bytes": len(data), "members": len(members),
            "handlerSha256": hashlib.sha256(members["handler.py"]).hexdigest(),
        }
    (args.output / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
