"""Read-only guard against restoring retired Meta catalog write tooling."""
import ast
from pathlib import Path
deploy = Path("scripts/deploy_all_lambdas.py").read_text()
alarms = Path("scripts/provision_payment_rail_alarms.py").read_text()
ast.parse(deploy)
ast.parse(alarms)
assert 'Spec(\n        "wecare-meta-catalog-sync",' not in deploy
# Reject literal backslash-n embedded in source comments (a prior merged defect).
assert not any(line.lstrip().startswith('#') and r'\n    #' in line for line in deploy.splitlines())
assert any('Cognito CustomMessage trigger:' in line for line in deploy.splitlines())
assert '"alarmName": "wecare-catalog-sync-drift"' not in alarms
assert '"alarmName": "wecare-catalog-sync-failure"' not in alarms
# The retired Meta sync must not regain a ProductsTable event source or
# a runnable operator command that recreates schedules or enables writes.
catalog = Path("amplify/catalog-resources.ts").read_text()
assert "addCatalogStreamTrigger" not in catalog
assert "DynamoEventSource" not in catalog
retired = (
    "scripts/provision_meta_catalog_sync.py",
    "scripts/provision_meta_catalog_sync_waba2.py",
    "scripts/open_meta_release_gate.py",
    "scripts/deploy_meta_catalog_safe_release.py",
    "scripts/decode_meta_plan.py",
)
for file in retired:
    assert not Path(file).exists(), "Retired Meta sync reactivation script restored: " + file
