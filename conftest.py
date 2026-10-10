"""Root pytest configuration: refuse to run on an interpreter this suite does not support.

WHY THIS FILE EXISTS, and it is a real hour lost rather than a hypothetical one.

Run on Python 3.9, this suite reports:

    5 failed, 3529 passed, 1 skipped, 110 errors

and every one of those 115 problems is the interpreter, not the code. On 3.12 the same tree is
`3715 passed`. The failures look exactly like a broken repository:

  * the 5 failures are `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` -
    PEP 604 annotations (`str | None`) evaluated at runtime in modules that do not import
    `from __future__ import annotations`. Valid since 3.10, a TypeError before it.
  * the 110 errors are collection failures for optional dependencies that are not installed
    because `requirements-dev.txt` was never installed for that interpreter.

requirements-dev.txt already says what to use, at the top of the file:

    python3.12 -m venv .venv
    .venv/bin/python -m pip install -r requirements-dev.txt

and all fourteen CI workflows pin `python-version: '3.12'`. So the instruction was there and the
enforcement was not, which is the gap this closes. The cost of leaving it open is not a broken
build - CI is pinned and always was - it is a reader, or an agent, taking a bare `python3` from
`$PATH`, believing the 115 problems, and reporting a baseline that does not exist. That happened.

A UsageError rather than an assert or a raise in module scope: pytest prints it as a single ERROR
line with no traceback, which is the whole point - one sentence naming the version you have, the
version you need and the command to get there, instead of 115 tracebacks about `|`.

This does NOT pin a patch version and there is deliberately no `.python-version` file alongside
it. pyenv does not prefix-match, so a `.python-version` of `3.12` fails outright on a machine
whose 3.12 is registered as `3.12.13`, and pinning the patch means every contributor whose
interpreter moved on gets a hard stop for no reason. A floor is the correct constraint: the suite
needs 3.10+ syntax and CI proves 3.12, so 3.12 is what it asks for.
"""

import os
import socket
import sys

import pytest

# The version every workflow pins. Kept as a tuple so the comparison is version-aware rather
# than a string compare that would read "3.9" as newer than "3.12".
REQUIRED = ( 3, 12 )

# ─────────────────────────────────────────────────────────────────────────────
# THE SECOND REASON THIS FILE EXISTS: tests were reaching PRODUCTION AWS.
#
# Measured on commit f87ea643 with a probe that wrapped `socket.socket.connect`, refused
# every non-loopback address and recorded it, then ran the whole suite. THIRTEEN test
# files attempted real outbound TLS:
#
#   tests/test_live_smoke_lockdown.py        AWS us-east-1 (11 distinct endpoint IPs)
#   tests/test_inbound_whatsapp.py           AWS us-east-1 AND 57.144.142.141 =
#                                            edge-star-shv-02-ccu2.facebook.com — a real
#                                            Meta Graph POST
#   tests/test_notifications_worker.py       AWS us-east-1 (13 IPs)
#   tests/test_graft_money_correctness.py    AWS us-east-1 (6 IPs)
#   tests/test_paid_submit_request.py        AWS us-east-1 (8 IPs)
#   plus test_agent_approval_route, test_business_api, test_calling, test_comms_sms,
#   test_plivo_routes, test_review_attribution, test_sms_aws_dlt, test_task12_seo
#
# Every AWS IP reverse-resolves to `*.compute-1.amazonaws.com`, i.e. live service
# endpoints. The ambient credential on a developer machine here is ROOT, so those were
# production reads and writes from a test run.
#
# Two measurements that make this guard safe rather than brave:
#
#   * Blocking every non-loopback connect changes the suite result NOT AT ALL:
#     `1 failed, 10648 passed, 6 skipped, 3 xfailed`, byte-identical to the unguarded
#     baseline and the same single pre-existing failure. All of the production access sat
#     inside swallowed-exception paths — it was never load-bearing for an assertion.
#   * It is FASTER. 53s guarded against 110.89s unguarded: the network round trips were
#     half the suite's wall clock.
#
# Loopback stays open, so moto, local HTTP fixtures and anything on 127.0.0.1 / ::1 keep
# working. Unix sockets are untouched. Only `socket` and `os` are used — no new
# dependency, which is why this is not `pytest-socket`.
# ─────────────────────────────────────────────────────────────────────────────

#: Credentials every test session runs with. Deliberately not real, and not empty: an
#: empty string is a credential botocore will try to sign with and then fail obscurely.
DUMMY_AWS_ENV = {
    'AWS_ACCESS_KEY_ID': 'testing',
    'AWS_SECRET_ACCESS_KEY': 'testing',
    'AWS_SESSION_TOKEN': 'testing',
    'AWS_DEFAULT_REGION': 'us-east-1',
}

#: Hosts a test may still reach. Loopback only.
_LOOPBACK_HOSTS = frozenset( { '127.0.0.1', '::1', 'localhost', 'localhost.localdomain',
                               '0.0.0.0', '', None } )

#: Set by `pytest_runtest_protocol` so a refusal can name the test that caused it.
_current_test = '<module import or fixture>'

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class OutboundNetworkBlocked( RuntimeError ):
    """A test tried to reach a non-loopback host.

    A plain RuntimeError subclass on purpose: botocore retries `ConnectionError` and its
    own transport exceptions, so raising one of those would burn the full retry budget on
    every blocked call. The probe run measured exactly that — the two worst offenders took
    349s between them under naive blocking. This type is not retried, so a stray call fails
    fast and names itself.
    """


def _is_loopback( address ) -> bool:
    """Whether `address` is loopback, and therefore allowed.

    Unix-domain sockets arrive as a path string rather than a `(host, port)` tuple and are
    always allowed: they cannot leave the machine.
    """
    if not isinstance( address, tuple ):
        return True
    host = address[ 0 ] if address else None
    if host in _LOOPBACK_HOSTS:
        return True
    host_text = str( host or '' )
    # 127.0.0.0/8 in full, not just 127.0.0.1 — some fixtures bind 127.0.0.2.
    return host_text.startswith( '127.' ) or host_text == '::ffff:127.0.0.1'


def _guarded_connect( self, address ):
    if _is_loopback( address ):
        return _real_connect( self, address )
    raise OutboundNetworkBlocked(
        f'{_current_test} tried to open a network connection to {address!r}. '
        f'Tests run offline: 13 test files were reaching live AWS us-east-1 and the Meta '
        f'Graph API with the ambient (root) credential. Patch the boundary your code '
        f'actually uses — see tests/test_inbound_whatsapp.py for the lazy-client case — '
        f'or mark the test `@pytest.mark.live` if it genuinely must reach the network. '
        f'Nothing in CI uses that marker.'
    )


def _guarded_connect_ex( self, address ):
    if _is_loopback( address ):
        return _real_connect_ex( self, address )
    raise OutboundNetworkBlocked(
        f'{_current_test} tried to open a network connection to {address!r} '
        f'(connect_ex). See the message on connect for what to do.'
    )


def pytest_configure( config ):
    if sys.version_info < REQUIRED:
        have = '.'.join( str( part ) for part in sys.version_info[ :3 ] )
        want = '.'.join( str( part ) for part in REQUIRED )
        raise pytest.UsageError(
            f'This suite needs Python {want} or newer and is running on {have} '
            f'({sys.executable}). On an older interpreter it reports around 115 failures that are '
            f'all the interpreter and none of them the code - PEP 604 annotations raise TypeError '
            f'before 3.10, and the optional dependencies are absent. Every CI workflow pins '
            f'{want}. Set up the environment the way requirements-dev.txt describes:\n'
            f'    python{want} -m venv .venv\n'
            f'    .venv/bin/python -m pip install -r requirements-dev.txt\n'
            f'    .venv/bin/python -m pytest'
        )

    # Force dummy credentials for the whole session. This is belt AND braces: the
    # documented way to run the suite is with the dummy-credential env prefix, and this
    # protects the contributor who forgets it. It cannot protect the interpreter before
    # this file is imported, which is why the prefix stays mandatory.
    for name, value in DUMMY_AWS_ENV.items():
        os.environ[ name ] = value
    os.environ[ 'AWS_CONFIG_FILE' ] = os.devnull
    os.environ[ 'AWS_SHARED_CREDENTIALS_FILE' ] = os.devnull

    # POPPED, not set to '': `AWS_PROFILE=` makes botocore look for a profile *named* the
    # empty string and raise `ProfileNotFound: The config profile () could not be found`
    # at import time — 187 collection errors, no tests run. The ambient value on this
    # machine is a real production profile, so leaving it in place is the other failure.
    # Popping is the only correct option and it is why the shell prefix needs
    # `env -u AWS_PROFILE` rather than `AWS_PROFILE=`.
    os.environ.pop( 'AWS_PROFILE', None )

    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex


def pytest_unconfigure( config ):
    socket.socket.connect = _real_connect
    socket.socket.connect_ex = _real_connect_ex


@pytest.hookimpl( hookwrapper = True )
def pytest_runtest_protocol( item, nextitem ):
    """Record the current test id so a refusal names it, and lift the block for `live`.

    A hookwrapper rather than a plain hook: the test runs inside the `yield`. A plain hook
    returning None would hand control back to pytest BEFORE the test executed, so any
    restore in a `finally` would undo the bypass before it was needed.
    """
    global _current_test
    _current_test = item.nodeid
    live = item.get_closest_marker( 'live' ) is not None
    if live:
        socket.socket.connect = _real_connect
        socket.socket.connect_ex = _real_connect_ex
    try:
        yield
    finally:
        if live:
            socket.socket.connect = _guarded_connect
            socket.socket.connect_ex = _guarded_connect_ex
