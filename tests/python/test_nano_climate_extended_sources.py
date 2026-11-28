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
    monkeypatch.setattr(h, "_cpcb_key_cache", {})
    monkeypatch.setattr(h, "CPCB_PARAMETER", h.CPCB_PARAMETER_NAME)
    fake = Mock()
    fake.get_parameter.return_value = {"Parameter": {
        "Name": h.CPCB_PARAMETER_NAME, "Type": "SecureString", "Value": "unit-test-placeholder"
    }}
    monkeypatch.setattr(h, "_cpcb_ssm", fake)
    assert h._cpcb_key() == "unit-test-placeholder"
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
    monkeypatch.setattr(h, "_cpcb_key_cache", {})
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


def test_cpcb_reads_live_avg_value_field():
    # Live data.gov.in schema (2026-11-28): avg_value, with "NA" for missing.
    now = dt.datetime(2026, 11, 28, 4, 0, tzinfo=dt.timezone.utc)
    base = {"country": "India", "state": "Delhi", "city": "Delhi", "station": "Shadipur, Delhi - CPCB",
            "last_update": "28-11-2026 09:00:00", "latitude": "28.6514781", "longitude": "77.1473105",
            "min_value": "117", "max_value": "448"}
    rows = [dict(base, pollutant_id="PM10", avg_value="300"),
            dict(base, pollutant_id="PM2.5", avg_value="NA")]
    data = h._cpcb_context(28.6139, 77.209, rows, now)
    assert data["status"] == "ok"
    assert data["station"] == "Shadipur, Delhi - CPCB"
    assert [(r["pollutant"], r["average"]) for r in data["readings"]] == [("PM10", 300)]


def test_cpcb_request_sends_named_user_agent(monkeypatch):
    monkeypatch.setattr(h, "_extra_cache", {})
    monkeypatch.setattr(h, "_reserve_extra", lambda source: None)
    monkeypatch.setattr(h, "_cpcb_key", lambda: "unit-test-placeholder")
    seen = {}
    def fake(url, headers=None):
        seen["headers"] = headers
        return {"records": [], "total": 0}
    monkeypatch.setattr(h, "_extra_json", fake)
    assert h._cpcb_snapshot() == []
    assert seen["headers"]["User-Agent"].startswith("wecare-nano-climate/")


def test_cpcb_rejects_incomplete_snapshot(monkeypatch):
    monkeypatch.setattr(h, "_extra_cache", {})
    monkeypatch.setattr(h, "_cpcb_key", lambda: "unit-test-placeholder")
    monkeypatch.setattr(h, "_reserve_extra", Mock())
    monkeypatch.setattr(h, "_extra_json", lambda *_, **__: {"total": "2", "records": [{}]})
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

def test_cpcb_diagnostics_never_log_url_key_or_provider_message(monkeypatch, caplog):
    import urllib.error
    url = h.CPCB_URL + "?api-key=unit-test-placeholder&format=json"
    fake = Mock()
    fake.open.side_effect = urllib.error.HTTPError(url, 403, "unit-test-placeholder", {}, None)
    monkeypatch.setattr(h.urllib.request, "build_opener", lambda *_: fake)
    with pytest.raises(h.ProviderFailure):
        h._extra_read(url)
    assert "nano_climate_cpcb_upstream_http status=403" in caplog.text
    assert "unit-test-placeholder" not in caplog.text
    assert h.CPCB_URL not in caplog.text
    fake.open.side_effect = urllib.error.URLError("unit-test-placeholder")
    with pytest.raises(h.ProviderFailure):
        h._extra_read(url)
    assert "nano_climate_cpcb_transport type=URLError reason_type=str" in caplog.text
    assert "unit-test-placeholder" not in caplog.text


def test_cpcb_complete_single_snapshot_and_provider_error_fail_closed(monkeypatch):
    monkeypatch.setattr(h, "_extra_cache", {})
    reserve = Mock()
    monkeypatch.setattr(h, "_reserve_extra", reserve)
    monkeypatch.setattr(h, "_cpcb_key", Mock(return_value="unit-test-placeholder"))
    provider = Mock(return_value={"status": "error", "total": 0, "records": []})
    monkeypatch.setattr(h, "_extra_json", provider)
    with pytest.raises(h.ProviderFailure):
        h._cpcb_snapshot()
    assert h._extra_cached("cpcb:national", 3600) is None
    provider.return_value = {"status": "ok", "total": 2, "records": [{"station": "A"}, {"station": "B"}]}
    assert len(h._cpcb_snapshot()) == 2
    assert reserve.call_count == 2
    assert provider.call_count == 2
    assert "limit=10000" in provider.call_args.args[0]
    assert len(h._cpcb_snapshot()) == 2
    assert provider.call_count == 2
