"""CA-3: per-IP throttles see the client behind a trusted proxy, and only then."""
import pytest

from lambda_utils import client_ip, otp_throttle, rate_limit

PROXY = "3.80.1.10"


def event(source="203.0.113.7", xff=None, header="x-forwarded-for", rest=False):
    rc = {"identity": {"sourceIp": source}} if rest else {"http": {"sourceIp": source}}
    headers = {} if xff is None else {header: xff}
    return {"requestContext": rc, "headers": headers}


@pytest.fixture
def proxied(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", f"{PROXY}/32, 2600:1f18::/32 10.0.0.0/8")


def test_default_is_unchanged_and_ignores_forwarded_headers(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    assert client_ip.client_ip(event(PROXY, "198.51.100.1")) == PROXY
    assert client_ip.client_ip(event("203.0.113.7", rest=True)) == "203.0.113.7"
    assert client_ip.client_ip({}) == ""


def test_trusted_proxy_uses_the_right_most_untrusted_entry(proxied):
    assert client_ip.client_ip(event(PROXY, "198.51.100.1")) == "198.51.100.1"
    # Left-most entries are client-written and never used.
    spoofed = "1.1.1.1, 8.8.8.8, 198.51.100.1"
    assert client_ip.client_ip(event(PROXY, spoofed)) == "198.51.100.1"
    # Trusted hops between the client and the peer are skipped.
    assert client_ip.client_ip(event(PROXY, f"9.9.9.9, 198.51.100.1, 10.2.3.4, {PROXY}")) \
        == "198.51.100.1"
    assert client_ip.client_ip(event(PROXY, "198.51.100.1", header="X-Forwarded-For")) \
        == "198.51.100.1"


def test_untrusted_peer_cannot_choose_its_address_with_a_header(proxied):
    assert client_ip.client_ip(event("203.0.113.7", "198.51.100.1")) == "203.0.113.7"
    assert client_ip.client_ip(event("203.0.113.7", f"198.51.100.1, {PROXY}")) == "203.0.113.7"


@pytest.mark.parametrize("xff", [
    None, "", "garbage", "198.51.100.1, garbage", "198.51.100.1, 999.1.1.1",
    "198.51.100.1,", "198.51.100.1, 1.2.3.4:abc", "198.51.100.1, [2001:db8::1",
    "198.51.100.1, \uff11.\uff12.\uff13.\uff14", f"10.1.1.1, {PROXY}",
])
def test_malformed_or_missing_hops_fall_back_to_the_peer(proxied, xff):
    assert client_ip.client_ip(event(PROXY, xff)) == PROXY


@pytest.mark.parametrize("raw,expected", [
    ("198.51.100.1", "198.51.100.1"),
    (" 198.51.100.1:443 ", "198.51.100.1"),
    ("2001:db8::1", "2001:db8::1"),
    ("[2001:db8::1]:443", "2001:db8::1"),
    ("[2001:db8::1]", "2001:db8::1"),
    ("::ffff:198.51.100.1", "198.51.100.1"),
])
def test_parse_ip_accepts_address_forms(raw, expected):
    assert str(client_ip.parse_ip(raw)) == expected


@pytest.mark.parametrize("raw", [
    "", None, "unknown", "999.1.1.1", "1.2.3.4:", "1.2.3.4:abc", "1.2.3.4:123456",
    "[2001:db8::1", "[2001:db8::1]x", "[2001:db8::1]:", "\u0661.2.3.4", "1" * 80,
])
def test_parse_ip_rejects_malformed_values(raw):
    assert client_ip.parse_ip(raw) is None


def test_ipv6_and_mapped_peers_match_their_ranges(proxied):
    assert client_ip.client_ip(event("2600:1f18::5", "198.51.100.1")) == "198.51.100.1"
    assert client_ip.client_ip(event(f"::ffff:{PROXY}", "198.51.100.1")) == "198.51.100.1"


def test_cidr_list_parsing_drops_bad_entries():
    networks = client_ip.trusted_proxies("10.0.0.0/8,  nonsense 192.0.2.1 ,, 2001:db8::/32")
    assert [str(n) for n in networks] == ["10.0.0.0/8", "192.0.2.1/32", "2001:db8::/32"]
    assert client_ip.trusted_proxies("") == ()


def test_rest_multi_value_headers_are_read(proxied):
    rest = {"requestContext": {"identity": {"sourceIp": PROXY}},
            "multiValueHeaders": {"X-Forwarded-For": ["1.1.1.1", "198.51.100.1"]}}
    assert client_ip.client_ip(rest) == "198.51.100.1"


class CounterTable:
    def __init__(self):
        self.keys = []

    def update_item(self, *, Key, **kwargs):
        self.keys.append(Key["grantId"])
        return {"Attributes": {"attempts": 1, "windowStartedAt": 1000}}


def test_otp_throttle_counts_the_resolved_client(proxied):
    assert otp_throttle.source_ip(event(PROXY, "198.51.100.1")) == "198.51.100.1"
    table = CounterTable()
    otp_throttle.check_and_consume(table, phone_e164="+919000000001",
                                   event=event(PROXY, "1.1.1.1, 198.51.100.1"), now=1000)
    assert table.keys[1] == otp_throttle.IP_PREFIX + otp_throttle._hashed("198.51.100.1")


def test_rate_limit_helper_keys_on_the_resolved_client(proxied, monkeypatch):
    seen = []
    monkeypatch.setattr(rate_limit, "check_rate_limit",
                        lambda channel, resource, **kwargs: seen.append((channel, resource)) or True)
    assert rate_limit.check_client_rate_limit("partner", event(PROXY, "198.51.100.1")) is True
    assert rate_limit.check_client_rate_limit("partner", {}) is True
    assert seen == [("partner", "198.51.100.1"), ("partner", "unknown")]
