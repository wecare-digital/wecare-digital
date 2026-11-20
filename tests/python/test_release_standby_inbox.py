"""Pure ZIP patching contract for the narrow standby inbox Lambda release."""

import importlib.util
import io
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "standby_release_script", ROOT / "scripts/release_standby_inbox.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


OLD_WRITER = '''import logging
logger = logging.getLogger(__name__)
def store_standby_message(phone_number_id, bsuid="", wa_id="", message=None, content=""):
    try:
        _get_table().put_item(Item={"test": 1})
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning('{"event":"standby_context_write_failed","error":"%s"}',
                       type(exc).__name__)
        return False
'''


def original_zip():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("handler.py", "def handler(event, context): return {}")
        z.writestr("lambda_utils/message_store.py", "def build_message_item(): pass\n")
        z.writestr(release.WRITER, OLD_WRITER)
        z.writestr("lambda_utils/unrelated.py", "UNCHANGED")
    return out.getvalue()


def test_minimal_release_changes_only_writer_and_adds_projection():
    projection = b"def mirror(*args, **kwargs): return True\n"
    patched, info = release.patched_zip(original_zip(), projection)
    assert set(info["modifiedFiles"]) == {release.WRITER, release.PROJECTION}
    assert info["retainedFiles"] == 3
    with zipfile.ZipFile(io.BytesIO(patched)) as z:
        assert set(z.namelist()) == {
            "handler.py",
            "lambda_utils/message_store.py",
            release.WRITER,
            release.PROJECTION,
            "lambda_utils/unrelated.py",
        }
        assert z.read("lambda_utils/unrelated.py") == b"UNCHANGED"
        assert z.read("handler.py") == b"def handler(event, context): return {}"
        writer = z.read(release.WRITER).decode()
        assert "standby_inbox.mirror(" in writer
        assert "standby_inbox_projection_retry_needed" in writer
        assert z.read(release.PROJECTION) == projection


def test_release_refuses_a_repeated_or_different_deployed_writer():
    patched, _ = release.patched_zip(original_zip(), b"def mirror(): return True\n")
    with pytest.raises(RuntimeError, match="already deployed"):
        release.patched_zip(patched, b"def mirror(): return True\n")
    with pytest.raises(RuntimeError, match="anchor"):
        release.patch_writer(OLD_WRITER.replace('return True', 'return False').encode())


def test_release_refuses_missing_runtime_dependency():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as writer:
        writer.writestr(release.WRITER, OLD_WRITER)
    with pytest.raises(RuntimeError, match="dependencies"):
        release.patched_zip(z.getvalue(), b"def mirror(): return True\n")
