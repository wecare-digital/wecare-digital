"""Provision the WABA2 Meta catalog sync using the proven primary sync implementation.

WABA1 keeps:
  function wecare-meta-catalog-sync
  catalog 1457045652952851
  token field access_token

WABA2 gets an independent function/alias/stream trigger/backstop:
  function wecare-meta-catalog-sync-waba2
  catalog 1317472650427643
  token field access_token_waba2

Both read the same ProductsTable authority and retain the same dry-run / exact-plan approval gates.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "provision_meta_catalog_sync.py"

spec = importlib.util.spec_from_file_location("meta_catalog_sync_provision_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

base.FUNCTION = "wecare-meta-catalog-sync-waba2"
# Reuse the same least-privilege role: permissions are identical (same secret, approvals table,
# ProductsTable and stream). A second fleet/shared role is not introduced.
base.ROLE = "wecare-meta-catalog-sync-role"
base.POLICY = "wecare-meta-catalog-sync-reads"
base.LOG_GROUP = "/aws/lambda/wecare-meta-catalog-sync-waba2"
base.SCHEDULE_RULE = "wecare-meta-catalog-sync-waba2-schedule"
base.ENVIRONMENT = dict(base.ENVIRONMENT)
base.ENVIRONMENT.update({
    "META_TOKEN_FIELD": "access_token_waba2",
    "META_CATALOG_ID": "1317472650427643",
})


if __name__ == "__main__":
    raise SystemExit(base.main())
