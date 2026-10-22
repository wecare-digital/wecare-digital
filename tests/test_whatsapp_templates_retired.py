from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
RETIRED = "wecare-whatsapp-templates"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_retired_template_lambda_is_absent_from_active_deployment_sources():
    assert RETIRED not in read("scripts/deploy_all_lambdas.py")
    assert RETIRED not in read("amplify/iam-policies.ts")
    assert RETIRED not in read("amplify/backend-resources.ts")
    manifest = json.loads(read("config/lambda-env-manifest.json"))
    assert RETIRED not in manifest["functions"]
    assert not (ROOT / "amplify/functions/messaging/whatsapp-templates/handler.py").exists()


def test_operational_template_callers_use_canonical_runtime():
    provisioner = read("scripts/provision_file_delivery_template.py")
    versions = read("packages/config/vendorVersions.ts")
    for source in (provisioner, versions):
        assert "wecare-whatsapp-template-management:live" in source
        assert "wecare-whatsapp-templates:live" not in source
