"""Provider-free tests: never contact Google, CPCB, PVGIS, S3 or DynamoDB."""
import datetime as dt
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

path = Path(__file__).resolve().parents[2] / "amplify/functions/core/vayulok-environment/handler.py"
spec = importlib.util.spec_from_file_location("nano_climate_environment_handler", path)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def test_disabled_sources_do_not_read_credentials_or_providers(monkeypatch):
    monkeypatch.setattr(h, "EXTRA_SOURCES", frozenset())
    forbidden = Mock(side_effect=AssertionError("network"))
    monkeypatch.setattr(h, "_extra_read", forbidden)
    monkeypatch.setattr(h, "_google_key", forbidden)
    r = h._location_context(28.6, 77.2, "IN", {"buildingCandidate": True})
    assert set(r["sources"]) == set(h.EXTRA_LIMITS)
    assert all(x["status"] == "disabled" for x in r["sources"].values())
    forbidden.assert_not_called()


def test_two_atomic_reservations_and_fail_closed(monkeypatch):
    monkeypatch.setattr(h, "EXTRA_SOURCES", frozenset({"solar"}))
    monkeypatch.setattr(h, "EXTRA_BUDGET_TABLE", h.RATE_TABLE)
    ddb = Mock()
    monkeypatch.setattr(h, "_extra_dynamo", ddb)
    h._reserve_extra("solar")
    rows = ddb.transact_write_items.call_args.kwargs["TransactItems"]
    assert len(rows) == 2
    assert all(r["Update"]["Key"]["id"]["S"].startswith(h.BUDGET_PREFIX + "solar:") for r in rows)
    assert [r["Update"]["ExpressionAttributeValues"][":cap"]["N"] for r in rows] == ["250", "7750"]
    assert all("#count < :cap" in r["Update"]["ConditionExpression"] for r in rows)
    ddb.transact_write_items.side_effect = RuntimeError("unavailable")
    monkeypatch.setattr(h, "_google_key", lambda: "unit-test-placeholder")
    provider = Mock()
    monkeypatch.setattr(h, "_extra_json", provider)
    with pytest.raises(h.ProviderUnavailable):
        h._solar_context(28.6, 77.2)
    provider.assert_not_called()


def test_solar_exact_endpoint_and_building_guard(monkeypatch):
    monkeypatch.setattr(h, "EXTRA_SOURCES", frozenset({"solar"}))
    monkeypatch.setattr(h, "EXTRA_BUDGET_TABLE", h.RATE_TABLE)
    reserve = Mock()
    monkeypatch.setattr(h, "_reserve_extra", reserve)
    monkeypatch.setattr(h, "_google_key", lambda: "unit-test-placeholder")
    sample = {"center": {"latitude": 28.6, "longitude": 77.2},
              "solarPotential": {"panelCapacityWatts": 400, "solarPanelConfigs": [
                  {"panelsCount": 1, "yearlyEnergyDcKwh": 500},
                  {"panelsCount": 8, "yearlyEnergyDcKwh": 3900}]}}
    provider = Mock(return_value=sample)
    monkeypatch.setattr(h, "_extra_json", provider)
    r = h._location_context(28.6, 77.2, "IN", {"buildingCandidate": False})
    assert r["sources"]["solar"]["status"] == "select_building"
    reserve.assert_not_called()
    provider.assert_not_called()
    r = h._location_context(28.6, 77.2, "IN", {"buildingCandidate": True})
    assert r["sources"]["solar"]["annualEnergyDcKwh"] == 3900
    reserve.assert_called_once_with("solar")
    assert provider.call_args.args[0].startswith("https://solar.googleapis.com/v1/buildingInsights:findClosest?")
    assert "key=" not in provider.call_args.args[0]


def test_cpcb_nearest_fresh_station_and_missing_units():
    now = dt.datetime(2026, 11, 27, 9, 30, tzinfo=dt.timezone.utc)
    base = {"country": "India", "city": "Delhi", "pollutant_id": "PM2.5",
            "last_update": "27-11-2026 14:00:00", "pollutant_avg": "0"}
    rows = [
        dict(base, station="Near", latitude="28.60", longitude="77.20"),
        dict(base, station="Far", latitude="28.70", longitude="77.20", pollutant_avg="45"),
        dict(base, station="Near", latitude="28.60", longitude="77.20", pollutant_avg="NA"),
        dict(base, station="Old", latitude="28.60", longitude="77.20", last_update="01-01-2020 00:00:00"),
    ]
    data = h._cpcb_context(28.6, 77.2, rows, now)
    assert data["station"] == "Near"
    assert data["readings"][0]["average"] == 0
    assert data["readings"][0]["unit"] is None
    assert data["readings"][0]["observedAt"].endswith("+05:30")
    assert h._cpcb_context(20, 80, rows, now)["status"] == "no_data"


def test_cpcb_reads_only_fixed_secure_parameter(monkeypatch):
    monkeypatch.setattr(h, "CPCB_PARAMETER", h.CPCB_PARAMETER_NAME)
    fake = Mock()
    fake.get_parameter.return_value = {"Parameter": {
        "Name": h.CPCB_PARAMETER_NAME, "Type": "SecureString", "Value": "unit-test-placeholder"
    }}
    monkeypatch.setattr(h, "_cpcb_ssm", fake)
    assert h._cpcb_key() == "unit-test-placeholder"
    fake.get_parameter.assert_called_once_with(Name="/wecare/nano-climate/cpcb", WithDecryption=True)
    fake.reset_mock()
    monkeypatch.setattr(h, "CPCB_PARAMETER", "/wecare/other")
    with pytest.raises(h.ProviderUnavailable, match="not configured"):
        h._cpcb_key()
    fake.get_parameter.assert_not_called()


@pytest.mark.parametrize("name,kind,value", [
    ("/wecare/nano-climate/cpcb", "String", "unit-test-placeholder"),
    ("/wecare/other", "SecureString", "unit-test-placeholder"),
    ("/wecare/nano-climate/cpcb", "SecureString", ""),
    ("/wecare/nano-climate/cpcb", "SecureString", "not a valid credential"),
])
def test_cpcb_rejects_invalid_parameter(monkeypatch, name, kind, value):
    monkeypatch.setattr(h, "CPCB_PARAMETER", h.CPCB_PARAMETER_NAME)
    fake = Mock()
    fake.get_parameter.return_value = {"Parameter": {"Name": name, "Type": kind, "Value": value}}
    monkeypatch.setattr(h, "_cpcb_ssm", fake)
    with pytest.raises(h.ProviderUnavailable, match="CPCB API key unavailable"):
        h._cpcb_key()


def test_cpcb_budget_reserves_before_any_decrypt_or_provider_request(monkeypatch):
    monkeypatch.setattr(h, "_extra_cache", {})
    reserve = Mock(side_effect=h.ExtraBudgetExhausted("limit"))
    key = Mock(side_effect=AssertionError("must not decrypt"))
    provider = Mock(side_effect=AssertionError("must not contact upstream"))
    monkeypatch.setattr(h, "_reserve_extra", reserve)
    monkeypatch.setattr(h, "_cpcb_key", key)
    monkeypatch.setattr(h, "_extra_json", provider)
    with pytest.raises(h.ExtraBudgetExhausted):
        h._cpcb_snapshot()
    reserve.assert_called_once_with("cpcb")
    key.assert_not_called()
    provider.assert_not_called()
    reserve.side_effect = None
    key.side_effect = h.ProviderUnavailable("CPCB API key unavailable")
    with pytest.raises(h.ProviderUnavailable):
        h._cpcb_snapshot()
    assert reserve.call_count == 2
    provider.assert_not_called()


def test_cpcb_snapshot_cache_skips_decrypt_and_reservation(monkeypatch):
    monkeypatch.setattr(h, "_extra_cache", {})
    h._extra_store("cpcb:national", [{"station": "Test"}])
    forbidden = Mock(side_effect=AssertionError("cache hit must not call AWS or provider"))
    monkeypatch.setattr(h, "_reserve_extra", forbidden)
    monkeypatch.setattr(h, "_cpcb_key", forbidden)
    monkeypatch.setattr(h, "_extra_json", forbidden)
    assert h._cpcb_snapshot() == [{"station": "Test"}]
    forbidden.assert_not_called()


def test_cpcb_rejects_incomplete_snapshot(monkeypatch):
    monkeypatch.setattr(h, "_extra_cache", {})
    monkeypatch.setattr(h, "_cpcb_key", lambda: "unit-test-placeholder")
    monkeypatch.setattr(h, "_reserve_extra", Mock())
    monkeypatch.setattr(h, "_extra_json", lambda *_: {"total": "2", "records": [{}]})
    with pytest.raises(h.ProviderFailure):
        h._cpcb_snapshot()


def test_pvgis_requires_actual_annual_fields():
    source = {"outputs": {"totals": {"fixed": {"E_y": 4500, "H(i)_y": 1800}},
                          "monthly": {"fixed": [{"month": 1, "E_m": 400}]}}}
    data = h._pvgis_summary(source, 28.61, 77.21)
    assert data["annualEnergyKwh"] == 4500
    assert data["annualIrradianceKwhM2"] == 1800
    assert data["monthly"] == []
    with pytest.raises(h.ProviderFailure):
        h._pvgis_summary({"outputs": {}}, 28.61, 77.21)


def test_spartan_latest_unflagged_filter_observation():
    sample = (
        "# File Updated: 2026-10-13\n"
        "Site_Code,Start_Year_local,Start_Month_local,Start_Day_local,End_Year_local,End_Month_local,End_Day_local,Hours_sampled,Parameter_Code,Value,Units,Flag\n"
        "INDH,2024,3,5,2024,3,6,12,28101,41.52,Micrograms per cubic meter (ug/m3),\n"
        "INDH,2024,3,7,2024,3,8,12,28101,999,Micrograms per cubic meter (ug/m3),bad\n"
        "INDH,2024,3,8,2024,3,9,12,28401,99,Micrograms per cubic meter (ug/m3),\n"
    )
    data = h._spartan_summary(sample, h.SPARTAN_SITES[0], 3.2)
    assert data["pm25UgM3"] == 41.52
    assert data["endDate"] == "2024-03-06"
    assert data["method"] == "filter"


def test_invalid_building_flag_does_not_call_upstream():
    with pytest.raises(ValueError):
        h._location_context(28.6, 77.2, "IN", {"buildingCandidate": "true"})


def _spartan_csv(code, value, parameter="28101"):
    return (
        "Site_Code,Start_Year_local,Start_Month_local,Start_Day_local,End_Year_local,End_Month_local,End_Day_local,Hours_sampled,Parameter_Code,Value,Units,Flag\n"
        f"{code},2024,3,5,2024,3,6,12,{parameter},{value},Micrograms per cubic meter (ug/m3),\n"
    )


@pytest.mark.parametrize("lat,lng,site,value", [
    (28.6139, 77.2090, "Delhi", 41.5),
    (26.9124, 75.7873, "Jaipur", 22.2),
    (26.4499, 80.3319, "Kanpur", 63.3),
])
def test_spartan_and_pvgis_follow_the_selected_place_not_a_previous_one(monkeypatch, lat, lng, site, value):
    """Regression for the reported stale-card case: Delhi data after moving to Jaipur or Kanpur."""
    h._extra_cache.clear()
    monkeypatch.setattr(h, "EXTRA_SOURCES", frozenset({"pvgis", "spartan"}))
    monkeypatch.setattr(h, "EXTRA_BUDGET_TABLE", h.RATE_TABLE)
    monkeypatch.setattr(h, "_reserve_extra", lambda source: None)
    files = {s[4]: _spartan_csv(s[0], v, "28101" if s[5] == "filter" else "28108")
             for s, v in zip(h.SPARTAN_SITES, (41.5, 22.2, 63.3))}
    monkeypatch.setattr(h, "_extra_read", lambda url, headers=None, limit=0: files[url.replace(h.SPARTAN_BASE, "")].encode())
    calls = []

    def fake_json(url):
        calls.append(url)
        return {"outputs": {"totals": {"fixed": {"E_y": 4000 + len(calls), "H(i)_y": 1900}}, "monthly": {"fixed": []}}}

    monkeypatch.setattr(h, "_extra_json", fake_json)
    # Select Delhi first so any process-level cache from it would leak into the next place.
    h._location_context(28.6139, 77.2090, "IN", {"buildingCandidate": False})
    result = h._location_context(lat, lng, "IN", {"buildingCandidate": False})
    assert result["latitude"] == lat and result["longitude"] == lng
    spartan = result["sources"]["spartan"]
    pvgis = result["sources"]["pvgis"]
    if site == "Kanpur":
        # Kanpur uses a daily estimate product with another parameter code, so the Delhi
        # filter value must never appear in its place.
        assert spartan.get("site") in (None, "Kanpur")
    else:
        assert spartan["site"] == site and spartan["pm25UgM3"] == value
    assert pvgis["gridLat"] == round(lat, 2) and pvgis["gridLng"] == round(lng, 2)
    assert any(f"lat={round(lat, 2)}" in c for c in calls)

def test_configure_cpcb_requires_standard_encrypted_parameter(monkeypatch):
    import sys
    script = path.parents[4] / "scripts/configure_nano_climate_sources.py"
    spec = importlib.util.spec_from_file_location("configure_nano_climate_test", script)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    clients = {name: Mock() for name in ("sts", "lambda", "iam", "dynamodb", "ssm", "kms")}
    monkeypatch.setattr(cfg.boto3, "client", lambda name, **kwargs: clients[name])
    clients["sts"].get_caller_identity.return_value = {"Account": cfg.ACCOUNT}
    table_arn = f"arn:aws:dynamodb:{cfg.REGION}:{cfg.ACCOUNT}:table/{cfg.TABLE}"
    clients["dynamodb"].describe_table.return_value = {"Table": {
        "TableStatus": "ACTIVE", "TableArn": table_arn,
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    }}
    role = f"arn:aws:iam::{cfg.ACCOUNT}:role/{cfg.ROLE}"
    old = {"Role": role, "RevisionId": "revision", "Environment": {"Variables": {
        "VAYULOK_EXTENDED_SOURCES": "pvgis,spartan", "UNRELATED": "preserve"
    }}}
    clients["lambda"].get_function_configuration.return_value = old
    monkeypatch.setattr(sys, "argv", ["configure", "--sources", "pvgis", "spartan", "cpcb", "--apply"])
    metadata = {"Name": cfg.CPCB, "Tier": "Standard", "Type": "String", "KeyId": "alias/aws/ssm"}
    clients["ssm"].describe_parameters.return_value = {"Parameters": [metadata]}
    with pytest.raises(SystemExit, match="Standard SecureString"):
        cfg.main()
    clients["iam"].put_role_policy.assert_not_called()
    clients["lambda"].update_function_configuration.assert_not_called()
    metadata["Type"] = "SecureString"
    key_arn = f"arn:aws:kms:{cfg.REGION}:{cfg.ACCOUNT}:key/unit-test"
    clients["kms"].describe_key.return_value = {"KeyMetadata": {
        "Arn": key_arn, "KeyManager": "AWS", "KeyState": "Enabled"
    }}
    clients["lambda"].get_function_configuration.side_effect = [old, {
        "Environment": {"Variables": {
            "VAYULOK_EXTENDED_SOURCES": "cpcb,pvgis,spartan",
            "VAYULOK_EXTENDED_BUDGET_TABLE": cfg.TABLE, "VAYULOK_CPCB_PARAMETER": cfg.CPCB,
            "UNRELATED": "preserve",
        }}
    }]
    cfg.main()
    import json
    statements = json.loads(clients["iam"].put_role_policy.call_args.kwargs["PolicyDocument"])["Statement"]
    parameter_arn = f"arn:aws:ssm:{cfg.REGION}:{cfg.ACCOUNT}:parameter{cfg.CPCB}"
    assert statements[1] == {"Effect": "Allow", "Action": "ssm:GetParameter", "Resource": parameter_arn}
    assert statements[2]["Resource"] == key_arn
    assert statements[2]["Condition"]["StringEquals"] == {
        "kms:ViaService": f"ssm.{cfg.REGION}.amazonaws.com",
        "kms:EncryptionContext:PARAMETER_ARN": parameter_arn,
    }
    assert statements[0]["Resource"] == table_arn
    variables = clients["lambda"].update_function_configuration.call_args.kwargs["Environment"]["Variables"]
    assert variables["UNRELATED"] == "preserve"
    assert variables["VAYULOK_CPCB_PARAMETER"] == cfg.CPCB
    assert variables["VAYULOK_EXTENDED_SOURCES"] == "cpcb,pvgis,spartan"
    clients["ssm"].get_parameter.assert_not_called()

def _cpcb_page(rows, total, offset, revision="2026-11-28T04:00:00Z"):
    return {"status": "ok", "total": total, "offset": offset, "count": len(rows),
            "updated_date": revision, "records": rows}


def test_cpcb_complete_bounded_pages_charge_every_request(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    monkeypatch.setattr(h, "_extra_cache", {})
    reserve = Mock()
    key = Mock(return_value="unit-test-placeholder")
    monkeypatch.setattr(h, "_reserve_extra", reserve)
    monkeypatch.setattr(h, "_cpcb_key", key)
    provider = Mock(side_effect=[_cpcb_page([{"station": "A"}, {"station": "B"}], 3, 0),
                                 _cpcb_page([{"station": "C"}], 3, 2)])
    monkeypatch.setattr(h, "_extra_json", provider)
    assert h._cpcb_snapshot() == [{"station": "A"}, {"station": "B"}, {"station": "C"}]
    assert reserve.call_count == 2
    key.assert_called_once()
    urls = [x.args[0] for x in provider.call_args_list]
    assert [parse_qs(urlsplit(url).query)["offset"] for url in urls] == [["0"], ["2"]]
    assert all(parse_qs(urlsplit(url).query)["limit"] == ["1000"] for url in urls)
    assert len(h._cpcb_snapshot()) == 3
    assert reserve.call_count == 2 and provider.call_count == 2


@pytest.mark.parametrize("second", [
    _cpcb_page([{"station": "B"}], 3, 1, "changed"),
    _cpcb_page([{"station": "B"}], 2, 0),
    _cpcb_page([{"station": "A"}], 2, 1),
    _cpcb_page([{"station": "B"}], 3, 1),
])
def test_cpcb_rejects_changed_or_duplicate_page(monkeypatch, second):
    monkeypatch.setattr(h, "_extra_cache", {})
    monkeypatch.setattr(h, "_reserve_extra", Mock())
    monkeypatch.setattr(h, "_cpcb_key", Mock(return_value="unit-test-placeholder"))
    monkeypatch.setattr(h, "_extra_json", Mock(side_effect=[_cpcb_page([{"station": "A"}], 2, 0), second]))
    with pytest.raises(h.ProviderFailure):
        h._cpcb_snapshot()
    assert h._extra_cached("cpcb:national", 3600) is None


def test_cpcb_later_budget_failure_does_not_fetch_or_cache(monkeypatch):
    monkeypatch.setattr(h, "_extra_cache", {})
    reserve = Mock(side_effect=[None, h.ExtraBudgetExhausted("limit")])
    monkeypatch.setattr(h, "_reserve_extra", reserve)
    monkeypatch.setattr(h, "_cpcb_key", Mock(return_value="unit-test-placeholder"))
    provider = Mock(return_value=_cpcb_page([{"station": "A"}], 2, 0))
    monkeypatch.setattr(h, "_extra_json", provider)
    with pytest.raises(h.ExtraBudgetExhausted):
        h._cpcb_snapshot()
    provider.assert_called_once()
    assert h._extra_cached("cpcb:national", 3600) is None


def test_cpcb_accepts_explicit_average_alias_without_inventing_units():
    now = dt.datetime(2026, 11, 28, 4, 30, tzinfo=dt.timezone.utc)
    row = {"country": "India", "city": "Delhi", "station": "Near", "latitude": "28.6",
           "longitude": "77.2", "pollutant_id": "PM2.5",
           "last_update": "28-11-2026 09:00:00", "avg_value": "31"}
    result = h._cpcb_context(28.6, 77.2, [row], now)
    assert result["readings"][0]["average"] == 31
    assert result["readings"][0]["unit"] is None
    assert h._cpcb_context(28.6, 77.2, [dict(row, pollutant_avg="99")], now)["status"] == "no_data"
