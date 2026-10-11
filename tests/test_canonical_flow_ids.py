"""The canonical WABA 1 flow ids are consistent everywhere, and the stale ids stay dead.

WHY THIS FILE EXISTS
--------------------
Flow ids for the customer-service capabilities used to be hand-copied as literals across six
surfaces — the inbound handler's DEFAULT_FLOW_TRIGGERS and five workspace/config files. They
drifted badly: the same capability named three or four DIFFERENT ids, several of them unused
DRAFT design-duplicates or DEPRECATED flows, while the real retained flow sat elsewhere. The
workspace confidently advertised doors that pointed at the wrong flow.

THE FIX THIS GUARDS
-------------------
Two canonical modules — src/lib/canonicalFlows.ts and
amplify/functions/shared/lambda_utils/canonical_flows.py — are the single source of truth, in
two languages that cannot import each other. This test:

  1. asserts the two twins agree id-for-id and status-for-status;
  2. asserts every canonical id (and status) matches the live-Meta readback
     outputs/flow-retirement-2026-10-09.json (its `keepIds` is the retained plan);
  3. asserts the inbound handler's DEFAULT_FLOW_TRIGGERS resolves to the canonical ids;
  4. forbids the known-stale/deprecated literals from reappearing anywhere in the wired
     source — a literal cannot drift if a literal is not allowed to exist.

No boto3, no network — reads files and execs only the handler nodes `load_entry` needs.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_customer_idea_entry import load_entry  # noqa: E402

TS_CANON = ROOT / 'src/lib/canonicalFlows.ts'
PY_CANON = ROOT / 'amplify/functions/shared/lambda_utils/canonical_flows.py'
READBACK = ROOT / 'outputs/flow-retirement-2026-10-09.json'

# The wired surfaces that must not restate a stale id as a literal.
WIRED_FILES = [
    ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py',
    ROOT / 'src/pages/workspace/forms/selfservice.tsx',
    ROOT / 'src/pages/workspace/engage/whatsapp/settings.tsx',
    ROOT / 'src/pages/workspace/engage/whatsapp/scripts.tsx',
    ROOT / 'src/pages/workspace/dashboard/system-architecture.tsx',
]

# Non-canonical ids that previously appeared for an in-scope capability and must stay gone.
# (WD_Vault_Design_v1 1735480734227899 is deliberately NOT here — it is a reference-only
# draft shown in the selfservice directory, never routed.)
STALE_IDS = {
    '1469093721293830': '01.WD_SR_v3 draft (wrong Submit Request)',
    '931522532810297': 'old Submit Request literal',
    '959792226650003': 'WD_Request_Amendment_Design_v1 draft (wrong Amendment)',
    '1533536534833353': 'old Amendment literal',
    '1605008471323578': 'WD_Drop_Docs_Design_v1 draft (wrong Drop Docs)',
    '1737801600902350': 'old Drop Docs literal',
    '1262971692700761': '02.WD_Profile DEPRECATED (subscribe)',
    '951987930811295': '02.WD_Profile DEPRECATED (subscribe, WABA2)',
    '1557815099200456': 'old Subscribe literal',
    '1486454129852338': '02.WD_TR draft (track)',
    '973888792200167': 'WD Track Request DEPRECATED',
}

# The retained plan, per outputs/flow-retirement-2026-10-09.json keepIds + the .md table.
EXPECTED = {
    'orders': ('2167802357142172', 'DRAFT'),
    'submit_request': ('1107164111921876', 'PUBLISHED'),
    'amend_request': ('3678132465672138', 'DRAFT'),
    'drop_docs': ('1211063631104445', 'DRAFT'),
    'shipments': ('849713848195607', 'DRAFT'),
    'leave_review': ('1578178897413815', 'PUBLISHED'),
    'vault': (None, 'NONE'),
    'subscribe': (None, 'NONE'),
    'track_request': (None, 'NONE'),
}


def _load_py_canon():
    ns: dict = {}
    exec(PY_CANON.read_text(encoding='utf-8'), ns)
    return ns['CANONICAL_FLOWS']


def _ts_entry(capability: str):
    """Pull (flowId, status) for a capability out of canonicalFlows.ts without a JS engine."""
    src = TS_CANON.read_text(encoding='utf-8')
    # match: capability: { ... flowId: '...'|null|REVIEW_FLOW_ID, status: 'X', ... }
    block = re.search(
        capability + r":\s*\{[^}]*?flowId:\s*(null|REVIEW_FLOW_ID|'[0-9]+')[^}]*?status:\s*'([A-Z]+)'",
        src, re.S)
    assert block, f'{capability} not found in canonicalFlows.ts'
    raw, status = block.group(1), block.group(2)
    if raw == 'null':
        flow_id = None
    elif raw == 'REVIEW_FLOW_ID':
        flow_id = '1578178897413815'
    else:
        flow_id = raw.strip("'")
    return flow_id, status


def test_python_canonical_matches_the_readback():
    canon = _load_py_canon()
    for cap, (fid, status) in EXPECTED.items():
        assert cap in canon, f'{cap} missing from canonical_flows.py'
        assert canon[cap][0] == fid, f'{cap} python flowId {canon[cap][0]} != {fid}'
        assert canon[cap][1] == status, f'{cap} python status {canon[cap][1]} != {status}'


def test_typescript_twin_agrees_with_python():
    canon = _load_py_canon()
    for cap, row in canon.items():
        fid, status = row[0], row[1]
        ts_id, ts_status = _ts_entry(cap)
        assert ts_id == fid, f'{cap} TS flowId {ts_id} != python {fid}'
        assert ts_status == status, f'{cap} TS status {ts_status} != python {status}'


def test_canonical_ids_are_in_the_readback_keepids():
    data = json.loads(READBACK.read_text(encoding='utf-8'))
    keep = set(data.get('keepIds', []))
    for cap, (fid, _status) in EXPECTED.items():
        if fid is not None:
            assert fid in keep, f'{cap} canonical id {fid} is not in readback keepIds'


def test_inbound_handler_uses_canonical_ids():
    ns, _ = load_entry()
    triggers = ns['DEFAULT_FLOW_TRIGGERS']
    # The in-scope capabilities present in DEFAULT_FLOW_TRIGGERS resolve to the canonical id
    # (or None, which the handler stores as an empty/None flowId and the flow sender no-ops).
    checks = {
        'submit_request': '1107164111921876',
        'amend_request': '3678132465672138',
        'drop_docs': '1211063631104445',
        'leave_review': '1578178897413815',
        'customer_idea': '1578178897413815',
    }
    for cap, fid in checks.items():
        assert triggers[cap]['flowId'] == fid, f"{cap} trigger flowId != canonical {fid}"
    # Subscribe + track must NOT carry a (deprecated/draft) id any more.
    assert not triggers['subscribe'].get('flowId'), 'subscribe must have no canonical flow'
    assert 'flowId2' not in triggers['subscribe'], 'deprecated subscribe flowId2 must be gone'
    assert not triggers['track_request'].get('flowId'), 'track_request must have no canonical flow'


def test_stale_ids_are_not_restated_anywhere():
    offenders = []
    for path in WIRED_FILES:
        text = path.read_text(encoding='utf-8')
        for sid, why in STALE_IDS.items():
            if sid in text:
                offenders.append(f'{path.relative_to(ROOT)} still contains {sid} ({why})')
    assert not offenders, 'stale flow ids resurfaced:\n' + '\n'.join(offenders)
