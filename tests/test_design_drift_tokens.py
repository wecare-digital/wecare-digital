"""The two design-drift rules added on 2026-09-24, and the arithmetic under them.

Why these need tests when the gate itself is a test
---------------------------------------------------
`scan_token_mirror` compares a TypeScript literal against a CSS custom property, and
the two files legitimately spell the same colour differently: the contract writes body
text as `rgba(0,0,0,.898)` in one place and `#1a1a1a` in another, and those are the
same colour over white — exactly. So the comparison has to composite before it
compares.

That makes the rule only as good as `normalise_colour`. Get the arithmetic wrong in one
direction and the gate fires on two files that agree, which is the kind of noise that
gets a gate switched off. Get it wrong in the other and it passes two files that
disagree, which is the defect it exists to catch: `design-tokens.ts` said
`text: '#111827'` while `tokens.css` said `--text: #1a1a1a`, and because that file has
14 importers, primary text resolved to a retired blue-tinted grey in 14 files and to the
right colour everywhere else, decided by which system a component happened to read.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_design_drift.py"


@pytest.fixture(scope="module")
def drift():
    spec = importlib.util.spec_from_file_location("drift", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNormaliseColour:
    @pytest.mark.parametrize("value,expected", [
        # The one that matters: the contract's body colour, both spellings.
        ("rgba(0, 0, 0, 0.898)", "#1a1a1a"),
        ("#1a1a1a", "#1a1a1a"),
        ("rgba(0,0,0,.898)", "#1a1a1a"),
        # The heading rung.
        ("rgba(0, 0, 0, 0.95)", "#0d0d0d"),
        # The secondary rung, used for --text-secondary and grey600.
        ("rgba(0, 0, 0, 0.54)", "#757575"),
        # Shorthand hex expands.
        ("#fff", "#ffffff"),
        ("#000", "#000000"),
        # Fully opaque rgb needs no compositing.
        ("rgb(26, 26, 26)", "#1a1a1a"),
        ("rgba(26, 26, 26, 1)", "#1a1a1a"),
        # Already-retired values must pass through unchanged, or they could be
        # normalised into looking like something legitimate.
        ("#111827", "#111827"),
        ("#4b5563", "#4b5563"),
    ])
    def test_composites_over_white(self, drift, value, expected):
        assert drift.normalise_colour(value) == expected

    def test_whitespace_and_case_do_not_change_the_answer(self, drift):
        assert (drift.normalise_colour("  #1A1A1A  ")
                == drift.normalise_colour("#1a1a1a"))

    def test_an_unparseable_value_is_returned_rather_than_guessed(self, drift):
        # `var(--something)` and named colours are not resolvable here. Returning the
        # raw string means two identical expressions still compare equal, and two
        # different ones still differ - no invented answer either way.
        assert drift.normalise_colour("var(--text)") == "var(--text)"
        assert drift.normalise_colour("currentColor") == "currentcolor"

    def test_transparent_black_composites_to_white(self, drift):
        assert drift.normalise_colour("rgba(0, 0, 0, 0)") == "#ffffff"


class TestTheRetiredSetIsComplete:
    def test_111827_is_guarded_across_all_of_src(self, drift):
        # It used to live in a stylesheet-only rule, because 129 uses were still in
        # inline React style objects across 22 files. That job is done, so there is no
        # longer a reason for it to be checked less strictly than the other eight.
        assert "#111827" in drift.RETIRED_COLOURS

    def test_the_old_stylesheet_only_scan_is_gone(self, drift):
        # Two rules for one colour is two places to get an exemption wrong.
        assert not hasattr(drift, "scan_retired_in_styles")

    @pytest.mark.parametrize("colour", [
        "#2f6b52", "#075e54", "#f2fbf6", "#fbfff0", "#1e293b",
        "#4b5563", "#0f172a", "#94a3b8", "#1e1e1e", "#111827",
    ])
    def test_every_colour_the_contract_retires_by_name_is_listed(self, drift, colour):
        assert colour in drift.RETIRED_COLOURS


class TestTokenMirror:
    def test_the_live_files_agree(self, drift):
        # Not a tautology: this is the assertion that failed before the fix, on two of
        # the five mirrored tokens.
        assert drift.scan_token_mirror() == []

    def test_every_mirrored_key_exists_in_both_files(self, drift):
        ts = drift.DESIGN_TOKENS_TS.read_text(encoding="utf-8")
        css = drift.TOKENS_CSS.read_text(encoding="utf-8")
        for ts_key, css_var in drift.TOKEN_MIRROR.items():
            assert f"{ts_key}:" in ts, f"{ts_key} vanished from design-tokens.ts"
            assert f"{css_var}:" in css, f"{css_var} vanished from tokens.css"

    def test_a_reintroduced_mismatch_is_caught(self, drift, monkeypatch, tmp_path):
        # The exact regression: design-tokens.ts drifting back to the retired grey
        # while tokens.css keeps the right value.
        fake_ts = tmp_path / "design-tokens.ts"
        fake_ts.write_text("export const colors = {\n    text: '#111827',\n} as const;\n")
        fake_css = tmp_path / "tokens.css"
        fake_css.write_text(":root {\n  --text: #1a1a1a;\n}\n")

        monkeypatch.setattr(drift, "DESIGN_TOKENS_TS", fake_ts)
        monkeypatch.setattr(drift, "TOKENS_CSS", fake_css)
        monkeypatch.setattr(drift, "ROOT", tmp_path)
        monkeypatch.setattr(drift, "TOKEN_MIRROR", {"text": "--text"})

        found = drift.scan_token_mirror()
        assert len(found) == 1
        assert found[0]["rule"] == "token_mirror_mismatch"
        assert "#111827" in found[0]["match"]

    def test_two_spellings_of_the_same_colour_do_NOT_trip_it(self, drift,
                                                            monkeypatch, tmp_path):
        # A gate that reports agreement as drift pushes somebody to "fix" it into
        # genuine disagreement.
        fake_ts = tmp_path / "design-tokens.ts"
        fake_ts.write_text("export const colors = {\n    text: '#1a1a1a',\n} as const;\n")
        fake_css = tmp_path / "tokens.css"
        fake_css.write_text(":root {\n  --text: rgba(0, 0, 0, 0.898);\n}\n")

        monkeypatch.setattr(drift, "DESIGN_TOKENS_TS", fake_ts)
        monkeypatch.setattr(drift, "TOKENS_CSS", fake_css)
        monkeypatch.setattr(drift, "ROOT", tmp_path)
        monkeypatch.setattr(drift, "TOKEN_MIRROR", {"text": "--text"})

        assert drift.scan_token_mirror() == []

    def test_a_missing_file_reports_nothing_rather_than_crashing(self, drift,
                                                                monkeypatch, tmp_path):
        monkeypatch.setattr(drift, "DESIGN_TOKENS_TS", tmp_path / "gone.ts")
        assert drift.scan_token_mirror() == []


class TestPublicTokenContract:
    def test_the_live_public_contract_is_exact(self, drift):
        assert drift.scan_public_token_contract() == []

    def test_brand_primitives_alias_the_global_foundation(self, drift):
        assert drift.PUBLIC_TOKEN_CONTRACT["--public-bg"] == "var(--bg)"
        assert drift.PUBLIC_TOKEN_CONTRACT["--public-text"] == "var(--text)"
        assert drift.PUBLIC_TOKEN_CONTRACT["--public-brand-green"] == "var(--accent)"
        assert drift.PUBLIC_TOKEN_CONTRACT["--public-brand-lime"] == "var(--lime)"
        assert drift.PUBLIC_TOKEN_CONTRACT["--public-hairline"] == "var(--border)"

    def test_public_measure_is_separate_from_application_measure(self, drift):
        assert drift.PUBLIC_TOKEN_CONTRACT["--public-content-max"] == "1300px"
        assert drift.scan_layout_token_mirror() == []

    def test_public_token_drift_is_caught(self, drift, monkeypatch, tmp_path):
        fake_css = tmp_path / "tokens.css"
        fake_css.write_text(":root { --public-hero-size: 54px; }\n")
        monkeypatch.setattr(drift, "TOKENS_CSS", fake_css)
        monkeypatch.setattr(drift, "ROOT", tmp_path)
        monkeypatch.setattr(drift, "PUBLIC_TOKEN_CONTRACT", {"--public-hero-size": "clamp(36px, 4.3vw, 60px)"})
        found = drift.scan_public_token_contract()
        assert len(found) == 1
        assert found[0]["rule"] == "public_token_drift"


class TestTheGateStillPassesOnTheRealTree:
    def test_no_retired_colour_survives_outside_a_comment(self, drift):
        # The migration's own assertion. `strip_comments` runs first, so the three
        # stylesheet notes explaining why #111827 was retired are documentation, not
        # violations - reporting the record of a fix as the defect is a mistake this
        # repository has had to correct more than once.
        assert drift.scan_retired() == []

    def test_state_colours_are_still_distinct(self, drift):
        assert drift.scan_state_collision() == []
