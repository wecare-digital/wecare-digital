"""Retired-host HTTP checks must not require forwarding or hide a proxy response."""

import importlib.util
from pathlib import Path
from urllib.parse import urlsplit

import pytest

spec = importlib.util.spec_from_file_location(
    "host_probe", Path(__file__).parents[1] / "scripts/probe_url_host_matrix.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def retired_row():
    return next(row for row in probe.matrix() if urlsplit(row["url"]).hostname == "store.wecare.digital")


def test_retired_hosts_expect_no_http_service_and_never_a_canonical_redirect():
    hosts = {
        "www.wecare.digital", "shop.wecare.digital", "store.wecare.digital",
        "xout.wecare.digital", "release-check-unknown.wecare.digital",
        "www.xout.wecare.digital", "a.b.wecare.digital",
    }
    rows = [row for row in probe.matrix() if urlsplit(row["url"]).hostname in hosts]
    assert {urlsplit(row["url"]).hostname for row in rows} == hosts
    assert all(row["expect_status"] == 0 for row in rows)
    assert all(row["expect_terminal_url"] is None for row in rows)
    assert all(not row["informational"] for row in rows)


@pytest.mark.parametrize(("status", "ok"), [(0, True), (503, False)])
def test_http_response_is_distinct_from_no_response(monkeypatch, status, ok):
    monkeypatch.setattr(probe, "_one_hop", lambda *_: (status, "", ""))
    result = probe.follow(retired_row())
    assert result["status"] == status
    assert result["ok"] is ok


@pytest.mark.parametrize("terminal_status", [0, 200])
def test_restored_redirect_to_apex_fails_the_retired_host_check(monkeypatch, terminal_status):
    def response(url, _method):
        return (terminal_status, "", "") if url == probe.SITE + "/" else (302, probe.SITE + "/", "")

    monkeypatch.setattr(probe, "_one_hop", response)
    result = probe.follow(retired_row())
    assert result["status"] == terminal_status
    assert result["hop_count"] == 2
    assert not result["ok"]
