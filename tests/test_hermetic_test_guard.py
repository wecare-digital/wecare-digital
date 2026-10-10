"""The test session cannot reach production, and cannot be run with real credentials.

What was measured, on commit f87ea643
-------------------------------------
A probe that wrapped `socket.socket.connect`, refused every non-loopback address and
recorded it found **thirteen test files making real outbound TLS connections** during a
normal `pytest` run: AWS us-east-1 service endpoints from all thirteen, and from
`tests/test_inbound_whatsapp.py` also `57.144.142.141` —
`edge-star-shv-02-ccu2.facebook.com`, i.e. a live Meta Graph POST. The ambient AWS
credential on a developer machine here is ROOT, so those were production reads and writes
performed by the test suite.

The root `conftest.py` at that commit was a Python-version check and nothing else: no
credential forcing, no network guard. `pytest.ini` had no `markers` section.

Two measurements that made the guard safe to add rather than risky
-----------------------------------------------------------------
* Blocking every non-loopback connect changed the suite result **not at all** —
  `1 failed, 10648 passed, 6 skipped, 3 xfailed`, identical to the unguarded baseline with
  the same single pre-existing failure. Every one of those calls sat inside a
  swallowed-exception path, so no assertion ever depended on one succeeding.
* It is faster: 53s guarded against 111s unguarded. The network round trips were half the
  suite's wall clock.

These tests pin the guard itself. They are the reason a future contributor cannot quietly
delete it and leave the suite looking fine.
"""

from __future__ import annotations

import os
import socket
import urllib.error
import urllib.request

import pytest

# Reach the guard through the function that is ACTUALLY installed on the socket, not via
# `import conftest`. Under `--import-mode=importlib` a plain import yields a SECOND copy of
# the module, whose `OutboundNetworkBlocked` is a different class object — so
# `pytest.raises` would not match the exception the live guard raises, and these tests
# would fail while the guard worked perfectly. Taking the names out of the installed
# function's own globals is exact by construction.
_GUARD = socket.socket.connect.__globals__
OutboundNetworkBlocked = _GUARD['OutboundNetworkBlocked']
_is_loopback = _GUARD['_is_loopback']


# ──────────────────────────────────────────────────────────────────────────
# credentials
# ──────────────────────────────────────────────────────────────────────────
def test_the_credentials_are_dummies():
    """Not the ambient ones, whatever the contributor's shell had in it."""
    assert os.environ['AWS_ACCESS_KEY_ID'] == 'testing'
    assert os.environ['AWS_SECRET_ACCESS_KEY'] == 'testing'
    assert os.environ['AWS_SESSION_TOKEN'] == 'testing'
    assert os.environ['AWS_DEFAULT_REGION'] == 'us-east-1'


def test_aws_profile_is_absent_rather_than_empty():
    """THE TRAP, asserted.

    `AWS_PROFILE=''` is not the same as unset: botocore reads the empty string as a
    profile *named* `""` and raises `ProfileNotFound: The config profile () could not be
    found` while importing test modules — 187 collection errors and zero tests run. The
    documented shell prefix therefore needs `env -u AWS_PROFILE`, and `conftest.py` has to
    `pop` rather than blank. Both halves of that are easy to get subtly wrong, so this
    test fixes the behaviour in place.
    """
    assert 'AWS_PROFILE' not in os.environ


def test_the_credential_files_point_at_devnull():
    """So a profile on disk cannot supply a real key even if something re-sets AWS_PROFILE."""
    assert os.environ['AWS_CONFIG_FILE'] == os.devnull
    assert os.environ['AWS_SHARED_CREDENTIALS_FILE'] == os.devnull


# ──────────────────────────────────────────────────────────────────────────
# the network block
# ──────────────────────────────────────────────────────────────────────────
def test_a_real_boto3_call_is_blocked():
    """The AWS case: all thirteen offenders looked like this.

    botocore re-wraps the refusal as `HTTPClientError: An HTTP Client raised an unhandled
    exception: ...`, carrying our text inside it. Asserted on the text rather than the
    type, because the type is botocore's to choose — and the fact that it does NOT
    classify it as a retryable connection error is the point of
    `test_the_refusal_is_not_a_type_botocore_retries`.
    """
    boto3 = pytest.importorskip('boto3')
    client = boto3.client('dynamodb', region_name='us-east-1',
                          endpoint_url='https://dynamodb.us-east-1.amazonaws.com')
    with pytest.raises(Exception) as exc:
        client.list_tables()
    assert 'Tests run offline' in str(exc.value)
    assert 'test_a_real_boto3_call_is_blocked' in str(exc.value)


def test_a_real_http_call_is_blocked():
    """The Meta Graph case, which is how a test POSTed to facebook.com."""
    with pytest.raises(Exception) as exc:
        urllib.request.urlopen('https://graph.facebook.com/v23.0/me', timeout=5)
    assert not isinstance(exc.value, urllib.error.HTTPError), (
        'the request reached Meta and came back with a status')


def test_the_refusal_names_the_test_that_caused_it():
    """A guard that says "something somewhere" costs more than it saves."""
    sock = socket.socket()
    try:
        with pytest.raises(OutboundNetworkBlocked) as exc:
            sock.connect(('93.184.216.34', 443))
    finally:
        sock.close()
    assert 'test_the_refusal_names_the_test_that_caused_it' in str(exc.value)
    assert '93.184.216.34' in str(exc.value)


def test_connect_ex_is_blocked_too():
    """Blocking only `connect` would leave the other half of the socket API open."""
    sock = socket.socket()
    try:
        with pytest.raises(OutboundNetworkBlocked):
            sock.connect_ex(('93.184.216.34', 443))
    finally:
        sock.close()


def test_the_refusal_is_not_a_type_botocore_retries():
    """Deliberately not a ConnectionError.

    Raising one made the two worst offenders take 349s between them, because botocore
    retried every refused connect through its full backoff budget. Failing with a type
    nothing retries is what keeps the guarded suite faster than the unguarded one.
    """
    assert issubclass(OutboundNetworkBlocked, RuntimeError)
    assert not issubclass(OutboundNetworkBlocked, OSError)


# ──────────────────────────────────────────────────────────────────────────
# what must STILL work
# ──────────────────────────────────────────────────────────────────────────
def test_loopback_is_not_blocked():
    """THE MOTO / LOCAL-FIXTURE GUARANTEE.

    moto and the local HTTP fixtures talk to 127.0.0.1. A guard that blocked loopback
    would break them, and the first person to hit that would delete the guard rather than
    narrow it. Asserted by connecting to a real listening socket on 127.0.0.1 — a refusal
    would raise `OutboundNetworkBlocked`, and this connecting at all proves it does not.
    """
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = socket.socket()
    try:
        client.connect(('127.0.0.1', port))  # must not raise
    finally:
        client.close()
        listener.close()


def test_the_whole_127_block_is_allowed_not_just_127_0_0_1():
    """Some fixtures bind 127.0.0.2. Allowing one address and not the loopback range is
    the kind of near-miss that looks like a flaky test."""
    assert _is_loopback(('127.0.0.2', 8000))
    assert _is_loopback(('127.0.0.1', 8000))
    assert _is_loopback(('::1', 8000))
    assert _is_loopback(('localhost', 8000))
    assert not _is_loopback(('10.0.0.1', 443))
    assert not _is_loopback(('graph.facebook.com', 443))


def test_a_unix_socket_address_is_allowed():
    """A filesystem path cannot leave the machine, so it is not the guard's business."""
    assert _is_loopback('/tmp/some.sock')


# ──────────────────────────────────────────────────────────────────────────
# the escape hatch
# ──────────────────────────────────────────────────────────────────────────
def test_the_live_marker_is_registered(pytestconfig):
    """Registered in pytest.ini, so `@pytest.mark.live` is not a silent typo under
    `--strict-markers` and `pytest --markers` documents it."""
    markers = pytestconfig.getini('markers')
    assert any(m.startswith('live:') for m in markers), markers


def test_the_live_bypass_exists_without_exercising_it():
    """Asserts the hook and the real functions the bypass restores.

    Deliberately does NOT make a live outbound call to prove the bypass: a test that
    reaches the network to check that it can reach the network is the exact behaviour this
    file exists to stop, and it would fail on a machine with no route out.
    """
    assert 'pytest_runtest_protocol' in _GUARD
    assert _GUARD['_real_connect'] is not _GUARD['_guarded_connect']
    assert _GUARD['_real_connect_ex'] is not _GUARD['_guarded_connect_ex']


def test_nothing_in_ci_uses_the_live_marker():
    """The marker is for a local probe. A CI job that reaches a live provider fails for
    reasons unrelated to the commit, and this is cheaper than discovering that later."""
    import pathlib
    workflows = pathlib.Path(__file__).resolve().parents[1] / '.github' / 'workflows'
    offenders = [p.name for p in workflows.glob('*.yml')
                 if 'mark.live' in p.read_text() or '-m live' in p.read_text()]
    assert offenders == [], offenders
