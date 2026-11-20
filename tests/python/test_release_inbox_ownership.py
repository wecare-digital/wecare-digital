"""Surgical live Lambda ownership patch never overwrites unrelated code."""
import importlib.util
import io
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_inbox_ownership", ROOT / "scripts/release_inbox_ownership.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def prior_handler():
    desired = release.SOURCE.read_text()
    s = desired.replace("import logging\nimport re\nimport time\nimport boto3", "import logging\nimport boto3", 1)
    extra = (
        "THREAD_OWNERSHIP_TABLE = os.environ.get('THREAD_OWNERSHIP_TABLE', 'stack-wecare-digital-ThreadOwnershipTable')\n"
        "_META_SENDER_PHONE_IDS = frozenset({'1016149501586345', '1055232054343117'})\n"
        "_SAFE_BSUID = re.compile(r'^[A-Za-z0-9._:-]{1,160}$')\n"
    )
    s = s.replace(extra, "", 1)
    begin = s.index(release.BEGIN)
    end = s.index(release.OLD_END, begin)
    s = s[:begin] + release.OLD_READ_ONE + s[end:]
    begin = s.index(release.HELPER_BEGIN)
    end = s.index(release.OLD_END, begin)
    s = s[:begin] + s[end + 2:]
    assert "threadOwnership" not in s
    return s.encode("utf-8")


def zip_original():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("handler.py", prior_handler())
        z.writestr("unrelated.py", b"PRESERVED")
    return out.getvalue()


def test_exact_patch_preserves_all_other_code():
    patch, report = release.patched_zip(zip_original(), release.SOURCE.read_bytes())
    assert report["modifiedFiles"] == ["handler.py"]
    assert report["preservedFiles"] == 1
    with zipfile.ZipFile(io.BytesIO(patch)) as z:
        assert z.read("unrelated.py") == b"PRESERVED"
        output = z.read("handler.py").decode()
        assert "def _read_standby_thread_ownership(" in output
        assert "ConsistentRead=True" in output
        assert "message['threadOwnership']" in output


def test_wrong_deployed_version_is_rejected():
    with pytest.raises(RuntimeError, match="patch anchor"):
        release.patch_runtime(b"def handler(): return 1", release.SOURCE.read_bytes())
    patch, _ = release.patched_zip(zip_original(), release.SOURCE.read_bytes())
    with zipfile.ZipFile(io.BytesIO(patch)) as z:
        with pytest.raises(RuntimeError, match="already present"):
            release.patch_runtime(z.read("handler.py"), release.SOURCE.read_bytes())
