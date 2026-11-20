"""Verify narrow live ZIP updates for provider-named standby conversations."""

import importlib.util
import io
from pathlib import Path
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "standby_names_release", ROOT / "scripts/release_standby_names.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

WRITER = '''import logging
logger=logging.getLogger(__name__)
from typing import Dict, Any, Optional
def store_standby_message(phone_number_id: str, *, bsuid: str = "", wa_id: str = "",
                          message: Dict[str, Any], content: str = "",
                          now: Optional[int] = None) -> bool:
    try:
        _get_table().put_item(Item={
            "content": str(content or "")[:4000],
            "messageTimestamp": 123,
        })
        projected=standby_inbox.mirror(
                phone_number_id, bsuid=bsuid, wa_id=wa_id,
                message=message, content=content,
            )
        return True
    except Exception:
        return False
'''
HANDLER = '\n'.join([
    'def handler(event, context):',
    '    if True:',
    '        if True:',
    '            if True:',
    '                if True:',
    '                    if True:',
    '                        if True:',
    '                            _mp, _mb, _mw = _thread_identity(value, _m)',
    '                            if thread_ownership.store_standby_message(',
    '                                    _mp or _pid, bsuid=_mb or _bsuid, wa_id=_mw or _waid,',
    '                                    message=_m, content=_c):',
    '                                _stored += 1',
]) + '\n'

def make_zip(writer=WRITER, handler=HANDLER):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(release.WRITER, writer)
        z.writestr(release.HANDLER, handler)
        z.writestr(release.PROJECTION, "def mirror(*args): return True\n")
        z.writestr("lambda_utils/message_store.py", "def build_message_item(): pass\n")
        z.writestr("unrelated.py", "PRESERVE")
    return out.getvalue()


def test_surgical_zip_updates_only_three_files():
    out, summary = release.patched_zip(make_zip(), b"def mirror(*args): return True\n")
    assert set(summary["modifiedFiles"]) == {
        release.WRITER, release.HANDLER, release.PROJECTION
    }
    assert summary["preservedOtherFiles"] == 2
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        assert z.read("unrelated.py") == b"PRESERVE"
        assert b"sender_name=sender_name" in z.read(release.WRITER)
        assert b"sender_name=_sender_name" in z.read(release.HANDLER)
        assert b"profile_name_from_contacts" in z.read(release.HANDLER)


def test_runtime_drift_refused_before_any_package_writes():
    with pytest.raises(RuntimeError, match="patch anchor"):
        release.patched_zip(make_zip(writer="def unrelated(): pass\n"), b"def mirror(): pass")
    with pytest.raises(RuntimeError, match="patch anchor"):
        release.patched_zip(make_zip(handler="def unrelated(): pass\n"), b"def mirror(): pass")
