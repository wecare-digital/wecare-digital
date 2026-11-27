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
