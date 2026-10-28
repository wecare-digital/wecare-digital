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


PROVIDER_PARAMETERS = {'google-cloud': 'GoogleCloudRedirectUri', 'google-ads': 'GoogleAdsRedirectUri',
    'plivo': 'PlivoRedirectUri', 'sinch': 'SinchIndiaRedirectUri'}


def build(dependencies, output, chat_redirect_uri=None, chat_discovery=False,
        separate_providers=False, provider_redirects=None):
    if chat_redirect_uri is not None:
        import re
        if len(chat_redirect_uri) > 256 or not re.fullmatch(r'https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,256}', chat_redirect_uri):
            raise ValueError("Use the exact callback URL supplied by ChatGPT connection setup")
    output.mkdir(parents=True, exist_ok=True)
    installed = {d.metadata["Name"].lower(): d.version for d in importlib.metadata.distributions(path=[str(dependencies)])}
    expected = dict(line.split("==") for line in (SOURCE / "requirements.txt").read_text().splitlines() if line)
    if installed != expected:
        raise ValueError("Dependency directory does not match the pinned adapter requirements")
    sources = {"handler.py": SOURCE / "handler.py", "provider_adapters.py": SOURCE / "provider_adapters.py",
        "chat_oauth.py": SOURCE / "chat_oauth.py",
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
            "CodeSha256": base64.b64encode(digest).decode(),
            "AlarmTopic": "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"}}
    if chat_redirect_uri is not None:
        manifest["parameters"]["ChatRedirectUri"] = chat_redirect_uri
    if chat_discovery:
        manifest["parameters"]["ChatDiscoveryEnabled"] = "true"
    if separate_providers:
        manifest['parameters']['SeparateProvidersEnabled'] = 'true'
    for provider, callback in (provider_redirects or {}).items():
        import re
        if provider not in PROVIDER_PARAMETERS or len(callback) > 256 or not re.fullmatch(
                r'https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,256}', callback):
            raise ValueError('Use a supported provider and its exact ChatGPT callback')
        manifest['parameters'][PROVIDER_PARAMETERS[provider]] = callback
    if provider_redirects:
        manifest['parameters']['ProviderConfigRevision'] = hashlib.sha256(
            json.dumps(provider_redirects, sort_keys=True).encode()).hexdigest()
    manifest["templateSha256"] = hashlib.sha256(Path(manifest["template"]).read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"zip": str(archive), "sha256": digest.hex(), "bytes": archive.stat().st_size}))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dependencies", required=True, type=Path)
    parser.add_argument("--output", default=ROOT / ".scratch/workspace-mcp/release", type=Path)
    parser.add_argument("--chat-redirect-uri", help="Exact ChatGPT callback; omitted preserves existing stack setting")
    parser.add_argument("--chat-discovery", action="store_true", help="Provision discovery before obtaining the exact host callback; MCP remains protected")
    parser.add_argument('--separate-providers', action='store_true', help='Expose four provider-specific MCP endpoints')
    parser.add_argument('--provider-redirect', action='append', default=[], metavar='PROVIDER=CALLBACK',
        help='Exact callback for a separate provider plugin; repeat for different providers')
    args = parser.parse_args()
    redirects = {}
    for entry in args.provider_redirect:
        provider, separator, callback = entry.partition('=')
        if not separator or provider in redirects:
            parser.error('Each provider redirect must be supplied exactly once as PROVIDER=CALLBACK')
        redirects[provider] = callback
    build(args.dependencies, args.output, args.chat_redirect_uri, args.chat_discovery,
        args.separate_providers, redirects)
