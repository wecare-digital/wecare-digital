"""Stage the exact reviewed standalone OTP handler; never publish or move aliases."""
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

TARGET = "wecare-customer-whatsapp-auth"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise SystemExit("Expected pinned source revision")
    spec, = (spec for spec in deploy.SPECS if spec.name == TARGET)
    if not spec.standalone:
        raise SystemExit("OTP handler must remain standalone")
    data, members = deploy.build_zip(spec)
    if set(members) != {"handler.py"}:
        raise SystemExit("Unexpected OTP package members")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist() != ["handler.py"] or archive.read("handler.py") != members["handler.py"]:
            raise SystemExit("OTP archive differs from source")
        compile(archive.read("handler.py"), "handler.py", "exec")
    digest = hashlib.sha256(data).digest()
    args.output.mkdir(parents=True, exist_ok=True)
    name = TARGET + ".zip"
    (args.output / name).write_bytes(data)
    manifest = {"sourceCommit": args.commit, "function": TARGET, "file": name,
                "sha256": digest.hex(), "codeSha256": base64.b64encode(digest).decode("ascii"),
                "sourceSha256": hashlib.sha256(members["handler.py"]).hexdigest(),
                "bytes": len(data), "members": ["handler.py"]}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
