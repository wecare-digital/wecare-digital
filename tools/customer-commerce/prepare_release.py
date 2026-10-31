"""Build deterministic customer-commerce runtime and CloudFormation artifacts.

No AWS request or deployment is performed. The runtime zip contains the exact
reviewed source modules, making repository-to-Lambda drift file-comparable.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import zipfile

from customer_commerce_template import (
    EXPECTED_REGION,
    ROUTES,
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
        (
            code,
            country,
            [int(number) for number in re.findall(r'\d+', lengths)],
        )
        for code, country, lengths in re.findall(
            r"\{ code: '([^']+)', country: '([^']+)', "
            r'nationalDigits: \[([^\]]*)\] \}',
            text,
        )
    ]


def assigned_literal(path: Path, name: str):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f'{name} not found in {path}')


def canonical_return_paths() -> list[str]:
    frontend_text = (ROOT / 'src/lib/safeReturnPath.ts').read_text()
    block = re.search(
        r'ALLOWED_CUSTOMER_RETURN_PATHS\s*=\s*\[(.*?)\]\s*as const',
        frontend_text,
        re.S,
    )
    if not block:
        raise ValueError('Frontend customer return-path allowlist unavailable')
    frontend = set(re.findall(r"'(/[^']*)'", block.group(1)))
    backend = set(
        assigned_literal(
            SOURCE / 'customer_oauth_config.py',
            'WEBSITE_RETURNS',
        )
    )
    if frontend != backend:
        raise ValueError(
            'Frontend/backend customer return paths differ: '
            f'frontend_only={sorted(frontend - backend)} '
            f'backend_only={sorted(backend - frontend)}'
        )

    services_text = (ROOT / 'src/config/services.ts').read_text()
    service_paths = set(
        re.findall(r"\bpath\s*:\s*'([^']+)'", services_text)
    )
    if not service_paths or (service_paths - {'/vault/'}) & frontend:
        raise ValueError(
            'Retired public service page returns must not be allowlisted: '
            f'{sorted((service_paths - {'/vault/'}) & frontend)}'
        )
    required = {'/', '/checkout/', '/orders/', '/blog/', '/vault/'}
    if not required <= frontend:
        raise ValueError(
            f'Required customer return paths missing: '
            f'{sorted(required - frontend)}'
        )
    return sorted(frontend)


def validated_sources() -> tuple[dict[str, bytes], list[str]]:
    assets = runpy.run_path(str(SOURCE / 'connection_assets.py'))
    expected = canonical_dial_codes()
    actual = assets.get('DIAL_COUNTRIES')
    if not expected or expected != actual:
        raise ValueError(
            'connection_assets.py differs from src/lib/dialCodes.ts'
        )
    return_paths = canonical_return_paths()

    files: dict[str, bytes] = {}
    for name in RUNTIME_FILES:
        path = SOURCE / name
        data = path.read_bytes()
        compile(data, str(path), 'exec')
        files[name] = data
    combined = b'\n'.join(files[name] for name in RUNTIME_FILES)
    if b'def form(' in combined or b'BRAND_LOGO' in combined:
        raise ValueError('Backend presentation leaked into runtime source')
    return files, return_paths


def validated_runtime_bucket(value: str) -> str:
    bucket = str(value or '').strip()
    if not re.fullmatch(
        r'(?=.{3,63}$)(?!-)(?!.*\.\.)(?!.*\.-)(?!.*-\.)'
        r'[a-z0-9][a-z0-9.-]*[a-z0-9]',
        bucket,
    ):
        raise ValueError(
            'A valid CUSTOMER_COMMERCE_RUNTIME_BUCKET is required'
        )
    return bucket


def write_zip(path: Path, files: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in RUNTIME_FILES:
            info = zipfile.ZipInfo(
                name,
                date_time=(2020, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return path.read_bytes()


def build(output: Path, runtime_bucket: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    bucket = validated_runtime_bucket(runtime_bucket)
    files, return_paths = validated_sources()
    zip_bytes = write_zip(
        output / 'customer-commerce-runtime.zip',
        files,
    )
    runtime_hash = hashlib.sha256(zip_bytes).hexdigest()
    source_hash = hashlib.sha256(
        b''.join(
            name.encode() + b'\0' + files[name]
            for name in RUNTIME_FILES
        )
    ).hexdigest()
    runtime_key = f'customer-commerce/{source_hash}/runtime.zip'
    template = build_template(source_hash, runtime_key, bucket)
    template_text = json.dumps(template, separators=(',', ':'))
    if len(template_text.encode()) > 51200:
        raise ValueError(
            'Modular template unexpectedly exceeds direct CloudFormation limit'
        )
    (output / 'customer-commerce-stack.json').write_text(
        template_text + '\n'
    )

    manifest = {
        'sourceSha256': source_hash,
        'runtimeZipSha256': runtime_hash,
        'runtimeBytes': len(zip_bytes),
        'templateBytes': len(template_text.encode()),
        'templateRequiresS3': False,
        'runtimeBucket': bucket,
        'runtimeKey': runtime_key,
        'expectedRegion': EXPECTED_REGION,
        'providerWrites': False,
        'deploymentExecuted': False,
        'publicSubmissionReady': False,
        'routes': list(ROUTES.values()),
        'runtimeFiles': list(RUNTIME_FILES),
        'websiteReturns': return_paths,
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
    parser.add_argument(
        '--runtime-bucket',
        default=os.environ.get('CUSTOMER_COMMERCE_RUNTIME_BUCKET', ''),
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.runtime_bucket)))


if __name__ == '__main__':
    main()
