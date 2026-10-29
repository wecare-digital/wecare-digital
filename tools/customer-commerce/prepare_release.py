"""Build deterministic customer-commerce runtime and CloudFormation artifacts.

No AWS request or deployment is performed. The runtime zip contains the exact
reviewed source modules, making repository-to-Lambda drift file-comparable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import zipfile

from customer_commerce_template import (
    EXPECTED_ACCOUNT,
    EXPECTED_REGION,
    ROUTES,
    RUNTIME_BUCKET,
    build_template,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'amplify/functions/ai/customer-commerce-mcp'
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


def canonical_dial_codes() -> list[tuple[str, str, list[int]]]:
    text = (ROOT / 'src/lib/dialCodes.ts').read_text()
    return [
        (code, country, [int(number) for number in re.findall(r'\d+', lengths)])
        for code, country, lengths in re.findall(
            r"\{ code: '([^']+)', country: '([^']+)', nationalDigits: \[([^\]]*)\] \}",
            text,
        )
    ]


def validated_sources() -> dict[str, bytes]:
    assets = runpy.run_path(str(SOURCE / 'connection_assets.py'))
    expected = canonical_dial_codes()
    actual = assets.get('DIAL_COUNTRIES')
    if not expected or expected != actual:
        raise ValueError('connection_assets.py differs from src/lib/dialCodes.ts')

    files: dict[str, bytes] = {}
    for name in RUNTIME_FILES:
        path = SOURCE / name
        data = path.read_bytes()
        compile(data, str(path), 'exec')
        files[name] = data
    combined = b'\n'.join(files[name] for name in RUNTIME_FILES)
    if b'def form(' in combined or b'BRAND_LOGO' in combined:
        raise ValueError('Backend presentation leaked into runtime source')
    return files


def write_zip(path: Path, files: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in RUNTIME_FILES:
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return path.read_bytes()


def build(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    files = validated_sources()
    zip_bytes = write_zip(output / 'customer-commerce-runtime.zip', files)
    runtime_hash = hashlib.sha256(zip_bytes).hexdigest()
    source_hash = hashlib.sha256(
        b''.join(name.encode() + b'\0' + files[name] for name in RUNTIME_FILES)
    ).hexdigest()
    runtime_key = f'deployments/customer-commerce/{source_hash}/runtime.zip'
    template = build_template(source_hash, runtime_key)
    template_text = json.dumps(template, separators=(',', ':'))
    if len(template_text.encode()) > 51200:
        raise ValueError('Modular template unexpectedly exceeds direct CloudFormation limit')
    (output / 'customer-commerce-stack.json').write_text(template_text + '\n')

    manifest = {
        'sourceSha256': source_hash,
        'runtimeZipSha256': runtime_hash,
        'runtimeBytes': len(zip_bytes),
        'templateBytes': len(template_text.encode()),
        'templateRequiresS3': False,
        'runtimeBucket': RUNTIME_BUCKET,
        'runtimeKey': runtime_key,
        'expectedAccount': EXPECTED_ACCOUNT,
        'expectedRegion': EXPECTED_REGION,
        'providerWrites': False,
        'deploymentExecuted': False,
        'publicSubmissionReady': False,
        'routes': list(ROUTES.values()),
        'runtimeFiles': list(RUNTIME_FILES),
        'presentationOwner': 'src/pages/auth.tsx',
        'backendRendersHtml': False,
        'countries': [],
        'countriesMeaning': (
            'All offered countries; fulfillment remains validated separately.'
        ),
    }
    (output / 'release-manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n'
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output)))


if __name__ == '__main__':
    main()
