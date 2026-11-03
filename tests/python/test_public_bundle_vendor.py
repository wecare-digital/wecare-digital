"""The public-bundle guard must distinguish exact vendor bytes from injected keys."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bundle_guard', ROOT / 'scripts/verify_public_bundle_secrets.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
VENDOR = ROOT / 'node_modules/pdfjs-dist/wasm/openjpeg_nowasm_fallback.js'


@pytest.fixture
def asset(tmp_path):
    if not VENDOR.exists():
        pytest.skip('Run npm ci for the pinned vendor-asset integration test')
    path = tmp_path / guard.PDFJS_GENERATED_ASSET
    path.parent.mkdir(parents=True)
    path.write_bytes(VENDOR.read_bytes())
    return path


def test_exact_generated_asset_is_not_reported_as_an_aws_credential(asset):
    failures, _ = guard.scan_file(asset, 'out/' + guard.PDFJS_GENERATED_ASSET)
    assert failures == []


def test_same_shape_outside_exact_vendor_path_still_fails(asset):
    failures, _ = guard.scan_file(asset, 'out/_next/static/chunks/app.js')
    assert any(row['kind'] == 'aws access key' for row in failures)


def test_changed_vendor_asset_or_injected_credential_still_fails(asset):
    asset.write_bytes(asset.read_bytes() + b'\n//' + ('ASIA' + 'BCDEFGHIJKLMNOPQ').encode())
    failures, _ = guard.scan_file(asset, 'out/' + guard.PDFJS_GENERATED_ASSET)
    assert len([row for row in failures if row['kind'] == 'aws access key']) == 2
