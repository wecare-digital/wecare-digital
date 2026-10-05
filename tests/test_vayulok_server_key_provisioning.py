"""The two VayuLok provisioning scripts, asserted offline.

Nothing here runs gcloud, calls AWS, or reaches Google. Both scripts import `boto3`
but build no client at import, so loading them performs no I/O; every test that
exercises a transport patches `urllib.request.urlopen` or `subprocess.run`.

What this pins, and why each one is worth a test rather than a reading:

  * the gcloud project is pinned centrally, so `api-keys create` cannot mint a key
    in whatever project the ambient config happens to name;
  * no key value ever reaches argv or stdout, on any path, including the new
    `--store-from-stdin` one;
  * the Weather and Air Quality probes send the key in a header and never in a URL;
  * the two fingerprint helpers agree, so the line `--create` prints can actually
    match the dict it is pasted into;
  * `FORBIDDEN_FINGERPRINTS` is still empty AND its placeholder slot exists - the
    key does not exist yet, so no hex value may be invented;
  * the KMS statement is decrypt-only and bounded to Secrets Manager.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_KEY_SCRIPT = ROOT / "scripts/provision_maps_server_key.py"
ENVIRONMENT_SCRIPT = ROOT / "scripts/provision_vayulok_environment.py"
BUNDLE_GATE_SCRIPT = ROOT / "scripts/verify_public_bundle_secrets.py"

# Synthetic, and deliberately key-SHAPED so the --store-from-stdin shape check passes.
# Not a credential: it is a literal in a committed test file and authorizes nothing.
FAKE_KEY = "AIza" + "0" * 35


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server_key():
    name = "provision_maps_server_key_under_test"
    yield _load(SERVER_KEY_SCRIPT, name)
    sys.modules.pop(name, None)


@pytest.fixture
def environment():
    name = "provision_vayulok_environment_under_test"
    yield _load(ENVIRONMENT_SCRIPT, name)
    sys.modules.pop(name, None)


@pytest.fixture
def bundle_gate():
    name = "verify_public_bundle_secrets_under_test"
    yield _load(BUNDLE_GATE_SCRIPT, name)
    sys.modules.pop(name, None)


# --------------------------------------------------------------------------- #
# MEDIUM-3: the gcloud project is pinned, centrally.
# --------------------------------------------------------------------------- #


def test_every_gcloud_call_pins_the_project(server_key):
    proc = MagicMock(returncode=0, stdout="[]", stderr="")
    with patch.object(server_key.subprocess, "run", return_value=proc) as run, patch.object(
        server_key, "gcloud_path", return_value="/usr/bin/gcloud"
    ):
        server_key.run_gcloud(["services", "api-keys", "list"])

    argv = run.call_args[0][0]
    assert f"--project={server_key.PROJECT}" in argv
    assert server_key.PROJECT == "wecaredigitalbw"
    # Central injection means a new call site cannot forget it.
    assert "--project" in SERVER_KEY_SCRIPT.read_text(encoding="utf-8")


def test_no_key_value_reaches_the_gcloud_argv(server_key):
    proc = MagicMock(returncode=0, stdout="[]", stderr="")
    with patch.object(server_key.subprocess, "run", return_value=proc) as run, patch.object(
        server_key, "gcloud_path", return_value="/usr/bin/gcloud"
    ):
        server_key.run_gcloud(["services", "api-keys", "list"])

    assert FAKE_KEY not in " ".join(run.call_args[0][0])
    # capture_output, so gcloud's stdout - which carries keyString - is not inherited.
    assert run.call_args.kwargs.get("capture_output") is True


# --------------------------------------------------------------------------- #
# MEDIUM-2: --store-from-stdin exists, and prints no value.
# --------------------------------------------------------------------------- #


def test_store_from_stdin_is_a_real_flag_the_parser_accepts(server_key):
    """provision() tells the operator to use this flag; it has to exist.

    The message fires in the exact situation where someone is holding a live key with
    nowhere safe to put it, which is how a value ends up pasted somewhere it must not go.
    """
    with patch.object(server_key.sys, "argv",
                      ["provision_maps_server_key.py", "--store-from-stdin"]), \
         patch.object(server_key, "store_from_stdin", return_value=0) as entry:
        assert server_key.main() == 0
    entry.assert_called_once_with()

    # And provision()'s recovery message still names it.
    assert "--store-from-stdin" in SERVER_KEY_SCRIPT.read_text(encoding="utf-8")


def test_store_from_stdin_stores_without_printing_the_value(server_key, capsys):
    with patch.object(server_key, "store", return_value="new version") as store, patch.object(
        server_key.getpass, "getpass", return_value=FAKE_KEY
    ), patch.object(server_key.sys.stdin, "isatty", return_value=True), patch.object(
        server_key, "run_probes", return_value=True
    ):
        rc = server_key.store_from_stdin()

    assert rc == 0
    store.assert_called_once_with(FAKE_KEY)
    out = capsys.readouterr().out
    assert FAKE_KEY not in out
    # Metadata only: the outcome and the one-way fingerprint.
    assert "new version" in out
    assert server_key.fp(FAKE_KEY) in out


def test_store_from_stdin_refuses_an_empty_value_without_storing(server_key):
    with patch.object(server_key, "store") as store, patch.object(
        server_key.getpass, "getpass", return_value="   "
    ), patch.object(server_key.sys.stdin, "isatty", return_value=True):
        with pytest.raises(SystemExit):
            server_key.store_from_stdin()
    store.assert_not_called()


def test_store_from_stdin_refuses_a_non_key_shape_without_echoing_it(server_key, capsys):
    junk = "not-a-google-api-key-at-all-but-long-enough"
    with patch.object(server_key, "store") as store, patch.object(
        server_key.getpass, "getpass", return_value=junk
    ), patch.object(server_key.sys.stdin, "isatty", return_value=True):
        with pytest.raises(SystemExit) as exit_info:
            server_key.store_from_stdin()
    store.assert_not_called()
    assert junk not in str(exit_info.value)
    assert junk not in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# MEDIUM-4: Weather and Air Quality are probed, header-authenticated.
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


@pytest.mark.parametrize(
    "probe_name,payload,expected_method",
    [
        ("probe_weather", {"temperature": {"degrees": 31}}, "GET"),
        ("probe_air_quality", {"indexes": [{"aqi": 142}]}, "POST"),
    ],
)
def test_the_new_probes_send_the_key_in_a_header_only(
    server_key, probe_name, payload, expected_method
):
    captured = {}

    def open_stub(request, timeout=None):
        captured["request"] = request
        return _Response(payload)

    with patch.object(server_key.urllib.request, "urlopen", side_effect=open_stub):
        ok, detail = getattr(server_key, probe_name)(FAKE_KEY)

    assert ok, detail
    req = captured["request"]
    assert "key=" not in req.full_url.lower()
    assert FAKE_KEY not in req.full_url
    assert req.get_header("X-goog-api-key") == FAKE_KEY
    assert req.get_method() == expected_method


def test_the_new_probes_bound_themselves_to_one_india_coordinate(server_key):
    # New Delhi, inside the handler's own INDIA_BOUNDS box.
    assert 6.4 <= server_key.PROBE_LAT <= 37.6
    assert 68.1 <= server_key.PROBE_LNG <= 97.4


def test_a_probe_failure_never_leaks_the_request(server_key):
    def boom(request, timeout=None):
        raise OSError(f"connection to {request.full_url} with {FAKE_KEY} failed")

    with patch.object(server_key.urllib.request, "urlopen", side_effect=boom):
        ok, detail = server_key.probe_weather(FAKE_KEY)

    assert not ok
    # Type name only, because an exception's text could echo the request.
    assert detail == "OSError"
    assert FAKE_KEY not in detail


def test_an_http_refusal_reports_the_google_reason_not_the_key(server_key):
    body = b'{"error":{"message":"API has not been used in project","details":' \
           b'[{"reason":"SERVICE_DISABLED"}]}}'

    def refuse(request, timeout=None):
        import io

        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(body))

    with patch.object(server_key.urllib.request, "urlopen", side_effect=refuse):
        ok, detail = server_key.probe_air_quality(FAKE_KEY)

    assert not ok
    assert "SERVICE_DISABLED" in detail
    assert FAKE_KEY not in detail


def test_run_probes_is_the_and_of_all_three(server_key, capsys):
    with patch.object(server_key, "probe_places_new", return_value=(True, "ok")), patch.object(
        server_key, "probe_weather", return_value=(True, "ok")
    ), patch.object(server_key, "probe_air_quality", return_value=(False, "HTTP 403")):
        assert server_key.run_probes(FAKE_KEY) is False

    out = capsys.readouterr().out
    assert "Air Quality API" in out
    assert "Weather API" in out
    # A refusal must offer the "API not enabled" reading, not just "bad key".
    assert "NOT ENABLED" in out


# --------------------------------------------------------------------------- #
# HIGH-1: the fingerprint handoff, and the slot it pastes into.
# --------------------------------------------------------------------------- #


def test_the_two_fingerprint_helpers_agree(server_key, bundle_gate):
    """Otherwise the pasted entry is a key that can never match.

    fp() prefixes `sha256:`; the gate's fingerprint() does not, and compares dict KEYS
    against the bare digest. They must be the same twelve characters.
    """
    sample = "not-a-credential-just-a-string"
    assert server_key.fp(sample) == "sha256:" + bundle_gate.fingerprint(sample)


def _emitted_dict_entry(out: str, digest: str) -> str:
    """Carve the dict entry out of the handoff output, the way an operator would.

    The entry starts at the line opening the digest key and ends at the closing `),`.
    """
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(f'"{digest}":'))
    end = next(i for i, line in enumerate(lines[start:], start) if line.strip() == "),")
    return "\n".join(lines[start:end + 1])


def test_the_handoff_prints_the_bare_digest_in_a_pasteable_line(server_key, capsys):
    server_key.print_fingerprint_handoff(FAKE_KEY)
    out = capsys.readouterr().out
    digest = server_key.fp(FAKE_KEY).split(":", 1)[1]
    assert f'"{digest}":' in out
    assert server_key.BUNDLE_GATE in out
    assert FAKE_KEY not in out

    # "Pasteable" has to mean it parses. An entry whose description string is left
    # unterminated across two printed lines makes the gate script unimportable, and
    # it would do so at the worst possible moment: immediately after --create has
    # minted an unrestricted key. Assert the property, not the presence of a line.
    entry = _emitted_dict_entry(out, digest)
    parsed = ast.parse("D = {\n" + entry + "\n}")
    value = ast.literal_eval(parsed.body[0].value)
    assert list(value) == [digest]
    assert "WECARE Server Google API Key" in value[digest]
    # Implicit concatenation must not have swallowed the space between the halves.
    assert "is usable by anyone" in value[digest]


def test_the_emitted_entry_is_accepted_by_the_gate_it_pastes_into(
    server_key, bundle_gate, capsys
):
    """The pasted entry must key on what fingerprint() actually produces.

    Round-trip it: parse the emitted entry, then look the gate's own fingerprint of
    the same value up in it. A prefixed or reformatted digest would miss here.
    """
    server_key.print_fingerprint_handoff(FAKE_KEY)
    out = capsys.readouterr().out
    digest = server_key.fp(FAKE_KEY).split(":", 1)[1]
    entry = _emitted_dict_entry(out, digest)
    value = ast.literal_eval(ast.parse("D = {\n" + entry + "\n}").body[0].value)
    assert bundle_gate.fingerprint(FAKE_KEY) in value


def test_the_bundle_gate_has_a_prepared_slot_and_no_invented_value(bundle_gate):
    # Still empty: the server key does not exist yet, so its fingerprint is unknowable
    # and a made-up hex string would be a gate that can never match anything.
    assert bundle_gate.FORBIDDEN_FINGERPRINTS == {}
    source = BUNDLE_GATE_SCRIPT.read_text(encoding="utf-8")
    assert "PLACEHOLDER SLOT" in source
    assert "WECARE Server Google API Key" in source
    assert "provision_maps_server_key.py --create" in source


# --------------------------------------------------------------------------- #
# HIGH-3: the KMS statement.
# --------------------------------------------------------------------------- #

VIA_SERVICE = "secretsmanager.us-east-1.amazonaws.com"


def test_kms_statement_scopes_to_a_full_arn_when_given_one(environment):
    arn = "arn:aws:kms:us-east-1:775261844268:key/abcd-1234"
    statement = environment._kms_statement(arn)
    assert statement["Resource"] == arn
    assert statement["Action"] == "kms:Decrypt"
    assert statement["Condition"]["StringEquals"]["kms:ViaService"] == VIA_SERVICE


@pytest.mark.parametrize("value", [None, "", "alias/aws/secretsmanager", "abcd-1234"])
def test_kms_statement_falls_back_to_the_account_key_shape(environment, value):
    statement = environment._kms_statement(value)
    assert statement["Resource"] == "arn:aws:kms:us-east-1:775261844268:key/*"
    assert statement["Action"] == "kms:Decrypt"
    assert statement["Condition"]["StringEquals"]["kms:ViaService"] == VIA_SERVICE


def test_kms_statement_is_decrypt_only(environment):
    """GenerateDataKey is the write side. A reader must not hold it."""
    statement = environment._kms_statement(None)
    rendered = json.dumps(statement)
    assert "GenerateDataKey" not in rendered
    assert "kms:*" not in rendered
    assert statement["Effect"] == "Allow"


def test_the_kms_lookup_never_fails_provisioning(environment):
    """DescribeSecret is metadata only, and a lookup miss must degrade, not raise."""
    client = MagicMock()
    client.describe_secret.side_effect = environment.ClientError(
        {"Error": {"Code": "AccessDeniedException"}}, "DescribeSecret"
    )
    with patch.object(environment.boto3, "client", return_value=client):
        assert environment._resolve_secret_kms_key() is None


def test_the_kms_lookup_reads_metadata_not_a_value(environment):
    client = MagicMock()
    client.describe_secret.return_value = {"KmsKeyId": "arn:aws:kms:us-east-1:1:key/x"}
    with patch.object(environment.boto3, "client", return_value=client):
        assert environment._resolve_secret_kms_key() == "arn:aws:kms:us-east-1:1:key/x"
    client.get_secret_value.assert_not_called()


# --------------------------------------------------------------------------- #
# MEDIUM-5: the operator-facing docstring names the live secret.
# --------------------------------------------------------------------------- #


def test_the_environment_script_points_operators_at_the_canonical_secret(environment):
    assert environment.GOOGLE_SECRET_NAME == "wecare/google/cloud"
    doc = environment.__doc__ or ""
    assert "wecare/google/cloud at runtime" in doc
    # The retired id may appear only inside the dated correction that explains it.
    for line in doc.splitlines():
        if "google-maps-server" in line:
            assert "previously named" in line


# --------------------------------------------------------------------------- #
# LOW-2 / LOW-3: store()'s read-merge-write is observable, and warns.
# --------------------------------------------------------------------------- #


def _secrets_stub(secret_string: str):
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": secret_string}

    class _NotFound(Exception):
        pass

    client.exceptions.ResourceNotFoundException = _NotFound
    return client


def test_store_prints_the_preserved_field_names_and_no_values(server_key, capsys):
    existing = json.dumps({
        "api_key": "old-key-value",
        "project_id": "wecaredigitalbw",
        "project_number": "123456789012",
    })
    client = _secrets_stub(existing)
    with patch.object(server_key, "secrets_client", return_value=client):
        outcome = server_key.store(FAKE_KEY)

    assert outcome == "new version"
    out = capsys.readouterr().out
    # Names, which are not secrets, so the merge is checkable without a read-back.
    assert "project_id" in out
    assert "project_number" in out
    # No value, old or new.
    assert "wecaredigitalbw" not in out
    assert "123456789012" not in out
    assert "old-key-value" not in out
    assert FAKE_KEY not in out

    # And the siblings genuinely survived into the written payload.
    written = json.loads(client.put_secret_value.call_args.kwargs["SecretString"])
    assert written["project_id"] == "wecaredigitalbw"
    assert written["project_number"] == "123456789012"
    assert written["api_key"] == FAKE_KEY
    assert written["unified_google_api_key"] == FAKE_KEY


def test_store_warns_rather_than_silently_discarding_a_non_json_body(server_key, capsys):
    client = _secrets_stub("AIzaSomethingThatIsNotAJsonObject")
    with patch.object(server_key, "secrets_client", return_value=client):
        server_key.store(FAKE_KEY)

    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "AWSPREVIOUS" in out
    # No part of the body is echoed.
    assert "AIzaSomethingThatIsNotAJsonObject" not in out
