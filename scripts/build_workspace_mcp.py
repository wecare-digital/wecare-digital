#!/usr/bin/env python3
"""Build reproducible Lambda ZIP and an offline CloudFormation deployment manifest.

Install the dedicated pinned requirements into --dependencies first. No AWS calls.
The resulting ZIP is portable: the adapter dependencies contain no native wheels.
"""
import argparse
import base64
import hashlib
import importlib.metadata
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "amplify/functions/ai/workspace-mcp"


def build(dependencies, output):
    output.mkdir(parents=True, exist_ok=True)
    installed = {d.metadata["Name"].lower(): d.version for d in importlib.metadata.distributions(path=[str(dependencies)])}
    expected = dict(line.split("==") for line in (SOURCE / "requirements.txt").read_text().splitlines() if line)
    if installed != expected:
        raise ValueError("Dependency directory does not match the pinned adapter requirements")
    sources = {"handler.py": SOURCE / "handler.py", "provider_adapters.py": SOURCE / "provider_adapters.py",
        "workspace-mcp.json": ROOT / "config/workspace-mcp.json"}
    for file in dependencies.rglob("*"):
        if file.is_file() and "__pycache__" not in file.parts and file.suffix not in {".pyc", ".pyo"}:
            if file.suffix in {".so", ".dylib"}: raise ValueError("Native dependencies are not allowed in this portable bundle")
            sources[file.relative_to(dependencies).as_posix()] = file
    archive = output / "workspace-mcp.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, file in sorted(sources.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, file.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).digest()
    key = "workspace-mcp/releases/" + digest.hex() + ".zip"
    manifest = {"stack": "wecare-workspace-mcp", "region": "us-east-1", "account": "775261844268",
        "sha256": digest.hex(), "codeSha256": base64.b64encode(digest).decode(), "bytes": archive.stat().st_size,
        "s3Bucket": "cdk-hnb659fds-assets-775261844268-us-east-1", "s3Key": key,
        "template": str(ROOT / "amplify/infra/workspace-mcp.json"), "dependencies": installed,
        "parameters": {"CodeBucket": "cdk-hnb659fds-assets-775261844268-us-east-1", "CodeKey": key,
            "CodeSha256": base64.b64encode(digest).decode(), "GithubTokenField": "token",
            "AlarmTopic": "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"zip": str(archive), "sha256": digest.hex(), "bytes": archive.stat().st_size}))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dependencies", required=True, type=Path)
    parser.add_argument("--output", default=ROOT / ".scratch/workspace-mcp/release", type=Path)
    args = parser.parse_args()
    build(args.dependencies, args.output)
