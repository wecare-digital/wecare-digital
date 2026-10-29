#!/usr/bin/env python3
"""Verify the immutable customer-commerce `live` artifact against repository source."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

import boto3

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'amplify/functions/ai/customer-commerce-mcp'
REGION = 'us-east-1'
FUNCTION = 'wecare-customer-commerce-mcp'
ALIAS = 'live'
RUNTIME_FILES = (
    'index.py',
    'handler.py',
    'customer_oauth.py',
    'customer_oauth_config.py',
    'customer_oauth_store.py',
    'customer_oauth_web.py',
    'customer_oauth_authorize.py',
    'connection_assets.py',
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_hash(files: dict[str, bytes]) -> str:
    return sha256(
        b''.join(name.encode() + b'\0' + files[name] for name in RUNTIME_FILES)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()

    local = {name: (SOURCE / name).read_bytes() for name in RUNTIME_FILES}
    lam = boto3.client('lambda', region_name=REGION)
    alias = lam.get_alias(FunctionName=FUNCTION, Name=ALIAS)
    deployed = lam.get_function(
        FunctionName=FUNCTION,
        Qualifier=alias['FunctionVersion'],
    )
    with urllib.request.urlopen(deployed['Code']['Location'], timeout=120) as response:
        zip_bytes = response.read()

    expected_code_sha = base64.b64encode(
        hashlib.sha256(zip_bytes).digest()
    ).decode()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = {item.filename for item in archive.infolist() if not item.is_dir()}
        remote = {
            name: archive.read(name)
            for name in RUNTIME_FILES
            if name in names
        }

    config = deployed['Configuration']
    environment = (config.get('Environment') or {}).get('Variables') or {}
    missing = sorted(set(RUNTIME_FILES) - names)
    extra = sorted(names - set(RUNTIME_FILES))
    differs = sorted(
        name for name in RUNTIME_FILES
        if name in remote and sha256(local[name]) != sha256(remote[name])
    )
    local_source_hash = source_hash(local)
    report = {
        'function': FUNCTION,
        'alias': ALIAS,
        'version': alias['FunctionVersion'],
        'codeSha256': config.get('CodeSha256', ''),
        'calculatedCodeSha256': expected_code_sha,
        'localSourceSha256': local_source_hash,
        'deployedSourceSha256': environment.get('SOURCE_SHA256', ''),
        'runtimeFiles': list(RUNTIME_FILES),
        'missing': missing,
        'extra': extra,
        'differs': differs,
        'matches': (
            not missing
            and not extra
            and not differs
            and config.get('CodeSha256') == expected_code_sha
            and environment.get('SOURCE_SHA256') == local_source_hash
        ),
    }
    text = json.dumps(report, indent=2) + '\n'
    print(text, end='')
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text)
    if not report['matches']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
