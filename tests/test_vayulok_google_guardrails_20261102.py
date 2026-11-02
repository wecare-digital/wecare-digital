"""Source-contract tests for VayuLok's main India map and Google quota safeguards.

No external APIs are called; manual visual QA remains mandatory.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = (ROOT / "src/components/VayuLokLive.tsx").read_text(encoding="utf-8")
GLOBE = (ROOT / "src/components/VayuLokApprovedGlobe.tsx").read_text(encoding="utf-8")


class VayuLokGoogleGuardrails(unittest.TestCase):
    def test_main_map_starts_with_india_overview(self):
        self.assertIn("const INDIA_OVERVIEW_BOUNDS = {", LIVE)
        for bound in ("north: 37.5", "south: 6.0", "east: 98.0", "west: 67.5"):
            self.assertIn(bound, LIVE)
        self.assertIn("fitBounds?.( INDIA_OVERVIEW_BOUNDS, 24 )", LIVE)
        self.assertIn("useRef<PlaceState | null>( DEFAULT_PLACE )", LIVE)
        self.assertIn("name: 'New Delhi'", LIVE)
        self.assertIn("regionCode: 'IN'", LIVE)

    def test_main_map_loads_only_near_viewport(self):
        self.assertIn("ref={ mapRegionRef }", LIVE)
        self.assertIn("rootMargin: '480px 0px'", LIVE)
        self.assertIn("const [ mapViewRequested, setMapViewRequested ]", LIVE)
        self.assertIn("if ( !MAPS_KEY || !mapViewRequested || typeof window === 'undefined' ) return;", LIVE)
        self.assertIn("[ mapInitNonce, mapViewRequested ]", LIVE)

    def test_core_weather_air_google_only_and_failures_not_cached(self):
        self.assertIn("weather.googleapis.com/v1/currentConditions:lookup", LIVE)
        self.assertIn("airquality.googleapis.com/v1/currentConditions:lookup", LIVE)
        self.assertIn("if ( store.air || store.weather ) cache.current[ cacheKey ]", LIVE)
        self.assertNotIn("api.open-meteo.com", LIVE)
        self.assertNotIn("api.openweathermap.org", LIVE)

    def test_google_maps_attribution_not_hidden(self):
        self.assertNotIn(".vl-live :global(.gm-style-cc),", LIVE)
        self.assertNotIn('img[alt="Google"]){display:none', LIVE)
        self.assertIn("Always preserve Google's visible logo", LIVE)

    def test_indian_time_zone_does_not_call_google_endpoint(self):
        self.assertIn("( place.regionCode || '' ).toUpperCase() === 'IN'", LIVE)
        self.assertIn("setLocationTime( DEFAULT_LOCATION_TIME );", LIVE)

    def test_search_requests_debounced_and_race_safe(self):
        self.assertIn("const SEARCH_DEBOUNCE_MS = 300;", LIVE)
        self.assertIn("const WORLD_SEARCH_DEBOUNCE_MS = 300;", LIVE)
        self.assertIn("requestSeq !== searchRequestSeqRef.current", LIVE)

    def test_bigquery_history_requires_per_place_click(self):
        self.assertIn("insightsRequestedFor === ", LIVE)
        self.assertIn("Load long-term history", LIVE)
        self.assertNotIn("weathernext_3_0_0_0p1deg", LIVE)
        self.assertNotIn("weathernext_3_0_0_0p05deg", LIVE)

    def test_globe_was_not_modified_for_main_map(self):
        self.assertIn("const MAPS_KEY =", GLOBE)
        self.assertNotIn("INDIA_OVERVIEW_BOUNDS", GLOBE)


if __name__ == "__main__":
    unittest.main()
