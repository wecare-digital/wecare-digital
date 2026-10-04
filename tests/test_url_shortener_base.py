"""The short-link base: what we MINT, and what we must keep HONOURING.

Short links moved from the `r.wecare.digital` subdomain to the `wecare.digital/r`
path on 2026-09-26. The move is only safe because those two questions have
different answers, and this file pins both.

What we mint changed. What we honour did not, and must not: the factory-reset guard
in `operations/system-cleanup` protects ShortLinksTable on the stated grounds that
short links are "printed on materials, embedded in messages, and shared externally".
A link on a printed card cannot be edited, an RCS card already on a handset cannot
be recalled, and the click table held 719 rows when this was written. So the old
host stays mapped, and `SHORT_LINK_BASE` governs generation only.

Resolution is deliberately not asserted here because it is not a property of this
module: the handler accepts `/r/{code}` and a bare `/{code}`, API Gateway maps both
hosts to the same API, and Amplify proxies `/r/<*>`. Those are live-infrastructure
facts, and a unit test claiming to cover them would be asserting its own fixture.
`scripts/check_short_link_hosts.py` probes them for real.
"""
import importlib.util
import os

import pytest

_HANDLER = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'core',
    'url-shortener', 'handler.py'))


def _load(monkeypatch, env):
    """Import the handler fresh under a given environment.

    The base is computed at import time, so it cannot be re-read by setting an
    env var on an already-imported module - hence a reload per case.
    """
    for k in ('SHORT_LINK_BASE', 'SHORT_DOMAIN'):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location('url_shortener_base_under_test', _HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_base_is_the_apex_path(monkeypatch):
    """With nothing configured, new links mint on the apex path, not the subdomain."""
    mod = _load(monkeypatch, {})
    assert mod.SHORT_LINK_BASE == 'wecare.digital/r'


def test_short_link_base_env_wins(monkeypatch):
    mod = _load(monkeypatch, {'SHORT_LINK_BASE': 'wecare.digital/r'})
    assert mod.SHORT_LINK_BASE == 'wecare.digital/r'


def test_legacy_short_domain_is_still_honoured_as_a_fallback(monkeypatch):
    """An environment not yet migrated keeps minting its old form rather than
    silently switching. Changing what a deployed function emits should be a
    deliberate env change, not a side effect of shipping code.

    Note the sting in this since 2026-09-28: `r.wecare.digital` is now NXDOMAIN, so an
    environment still relying on this fallback would mint links that resolve nowhere.
    The precedence test below is what matters in practice — `SHORT_LINK_BASE` wins — and
    the live value is `wecare.digital/r`, verified in
    config/lambda-env-manifest.json. The fallback is kept because removing it would
    make an un-migrated environment mint on a bare default instead, which is no better
    and harder to diagnose.
    """
    mod = _load(monkeypatch, {'SHORT_DOMAIN': 'r.wecare.digital'})
    assert mod.SHORT_LINK_BASE == 'r.wecare.digital'


def test_short_link_base_takes_precedence_over_legacy(monkeypatch):
    mod = _load(monkeypatch, {'SHORT_LINK_BASE': 'wecare.digital/r',
                              'SHORT_DOMAIN': 'r.wecare.digital'})
    assert mod.SHORT_LINK_BASE == 'wecare.digital/r'


@pytest.mark.parametrize('raw', ['wecare.digital/r/', ' wecare.digital/r ', '/wecare.digital/r/'])
def test_stray_slashes_and_space_are_normalised(monkeypatch, raw):
    """The built URL is f"https://{base}/{code}". An unnormalised value produces
    `https://wecare.digital/r//abc`, which is a different path from
    `/r/abc` to a static host and would not match the Amplify `/r/<*>` rule."""
    mod = _load(monkeypatch, {'SHORT_LINK_BASE': raw})
    assert mod.SHORT_LINK_BASE == 'wecare.digital/r'
    assert f"https://{mod.SHORT_LINK_BASE}/abc" == 'https://wecare.digital/r/abc'


def test_the_old_host_is_registered_as_retired(monkeypatch):
    """Inverted on 2026-09-28, deliberately, and worth reading before changing back.

    This test used to assert the opposite — that `check_retired_origins.py` must NEVER
    list `r.wecare.digital` — guarding against someone copying the
    the retired legacy frontend host retirement pattern onto a host that still resolved live
    short codes. That was correct while the host resolved.

    The owner then retired it: the Route 53 record was deleted under
    `YES R53-DELETE-001` and the host is NXDOMAIN, so it now resolves nothing at all
    and the distinction the old assertion protected no longer exists. Registering it
    is what keeps the two retired-host guards agreeing with each other —
    `check_short_link_hosts.py` asserts the host does not resolve, and this registry is
    what refuses an allow-list entry offering it.

    The links already issued on that host are dead. That is a consequence of the
    retirement recorded in docs/media-bucket-merge.md, not something either guard can
    fix, and not a reason to un-register the host here.
    """
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
    spec = importlib.util.spec_from_file_location(
        'retired_origins_under_test',
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts',
                                     'check_retired_origins.py')))
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    assert 'r.wecare.digital' in gate.RETIRED_HOSTS
    # A reason must accompany it. The registry's value is the explanation, not the key:
    # a bare entry tells the next reader nothing about whether it can be removed.
    assert 'NXDOMAIN' in gate.RETIRED_HOSTS['r.wecare.digital']
    # The originally dead host stays listed, so this cannot pass by the registry
    # having been emptied.
    legacy_stack_host = 'stack.' + 'wecare.digital'\n    assert legacy_stack_host in gate.RETIRED_HOSTS
