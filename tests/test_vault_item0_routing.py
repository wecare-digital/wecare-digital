"""item 0 — the retired Vault Flow is never routed, and the Vault review dispatch resolves.

Two invariants this pins:

  1. WD_Vault_Design_v1 / 1735480734227899 is RETIRED. It may appear as a reference-only entry
     in the self-service directory, but it must never be an active inbound Flow trigger, and the
     canonical map must keep vault = NONE. (Entry is a website CTA + the ₹49 catalog item.)

  2. secure-files' `_queue_vault_review` async-invokes internalAction "vaultReview". Before item 0
     the whatsapp-business-api handler had no such branch, so the review was a silent no-op. This
     asserts the branch now exists and points at the Vault review sender (not the submit-request
     one).

No boto3, no network — reads source and execs the small nodes needed.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_customer_idea_entry import load_entry  # noqa: E402

VAULT_RETIRED_ID = '1735480734227899'
INBOUND = ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py'
BUSINESS_API = ROOT / 'amplify/functions/messaging/whatsapp-business-api/handler.py'
PY_CANON = ROOT / 'amplify/functions/shared/lambda_utils/canonical_flows.py'


def _canon():
    ns: dict = {}
    exec(PY_CANON.read_text(encoding='utf-8'), ns)
    return ns['CANONICAL_FLOWS']


def test_canonical_vault_and_subscribe_have_no_flow():
    canon = _canon()
    assert canon['vault'][0] is None and canon['vault'][1] == 'NONE'
    assert canon['subscribe'][0] is None and canon['subscribe'][1] == 'NONE'


def test_retired_vault_id_is_not_an_active_inbound_trigger():
    ns, _ = load_entry()
    for key, trigger in ns['DEFAULT_FLOW_TRIGGERS'].items():
        assert trigger.get('flowId') != VAULT_RETIRED_ID, (
            f"retired Vault flow {VAULT_RETIRED_ID} is wired as the '{key}' trigger"
        )
    # And there is no 'vault' trigger at all — the keyword is a website CTA.
    assert 'vault' not in ns['DEFAULT_FLOW_TRIGGERS']


def test_vault_review_dispatch_is_routed():
    """The business-api handler routes internalAction 'vaultReview' to the Vault review sender."""
    src = BUSINESS_API.read_text(encoding='utf-8')
    assert "'vaultReview'" in src, 'no vaultReview branch in the internalAction router'
    # It must import the Vault review sender, not silently fall through to the submit-request one.
    assert re.search(r'from flows\.paid_vault import send_review', src), (
        'vaultReview must route to flows.paid_vault.send_review'
    )


def test_secure_files_queues_the_matching_action():
    """secure-files sends exactly the internalAction the handler now routes."""
    sec = ( ROOT / 'amplify/functions/core/secure-files/handler.py' ).read_text(encoding='utf-8')
    assert '"vaultReview"' in sec, 'secure-files no longer queues vaultReview'
