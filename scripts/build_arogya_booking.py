#!/usr/bin/env python3
"""Build the appointment Lambda using runtime boto3 and the repository shared code."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    sources = {'handler.py': ROOT / 'amplify/functions/ecommerce/arogya-booking/handler.py'}
    shared = ROOT / 'amplify/functions/shared'
    for path in (shared / 'lambda_utils').rglob('*.py'):
        if '__pycache__' not in path.parts:
            sources[path.relative_to(shared).as_posix()] = path
    archive = output / 'arogya-booking.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, path in sorted(sources.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).digest()
    manifest = {'stack': 'wecare-arogya-booking', 'account': '775261844268', 'region': 'us-east-1',
        's3Bucket': 'cdk-hnb659fds-assets-775261844268-us-east-1',
        's3Key': f'arogya-booking/releases/{digest.hex()}.zip',
        'codeSha256': base64.b64encode(digest).decode(), 'sha256': digest.hex(),
        'bytes': archive.stat().st_size}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    build(parser.parse_args().output)
