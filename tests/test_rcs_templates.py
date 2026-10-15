"""RCS template export, normalization and cross-platform validation.

Offline. Operates on the committed export in `rcs/templates/`, so it runs in CI without
AWS and without touching Sinch.

What the export found, 2026-09-22
---------------------------------
11 approved templates on the Sinch India platform, of which **exactly one** (`rcsmenu`)
has a code path that sends it. Two more (`rcsorder`, `waalert`) are named in docstrings
but lost their senders on 2026-09-19. The remaining eight are unreferenced, and four of
those are plainly test leftovers sitting in production: `test16`, `test17`,
`wecare_test_create`, `wecare_v2_test`.

The validator encodes rendering consequences, not style preferences. An approved
template is not edited because it is untidy - each rule has to name what the customer
would actually see.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "rcs" / "templates" / "manifest.json"
SOURCE = ROOT / "rcs" / "templates" / "source"
NORMALIZED = ROOT / "rcs" / "templates" / "normalized"


def _load_sync():
    spec = importlib.util.spec_from_file_location(
        "rcs_template_sync_under_test", ROOT / "scripts" / "rcs_template_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_sync()


@pytest.fixture(scope="module")
def manifest():
    assert MANIFEST.exists(), "run scripts/rcs_template_sync.py first"
    return json.loads(MANIFEST.read_text())


# ══════════════════════════════════════════════════════════════════════════════
# The export itself.
# ══════════════════════════════════════════════════════════════════════════════

class TestExportIntegrity:
    def test_every_template_has_a_source_and_a_normalized_file(self, manifest):
        """The original remote representation is preserved separately from the
        normalized one, so a provider-side change is diffable without the
        normalization getting in the way."""
        names = {t["name"] for t in manifest["templates"]}
        assert names, "no templates exported"
        for name in names:
            safe = "".join(c for c in name if c.isalnum() or c in "-_")
            assert (SOURCE / f"{safe}.json").exists(), name
            assert (NORMALIZED / f"{safe}.json").exists(), name

    def test_source_files_are_untouched_provider_shape(self, manifest):
        """`source/` must keep the provider's own keys. If normalization leaked into
        it we would lose the ability to tell what Sinch actually returned."""
        for entry in SOURCE.glob("*.json"):
            raw = json.loads(entry.read_text())
            assert set(raw) <= {"name", "type", "status", "component"}, entry.name
            assert "fingerprint" not in raw, "normalized field leaked into source"

    def test_the_manifest_count_matches_the_files(self, manifest):
        assert manifest["counts"]["total"] == len(list(SOURCE.glob("*.json")))
        assert manifest["counts"]["total"] == len(list(NORMALIZED.glob("*.json")))

    def test_no_credential_material_in_the_export(self):
        """The template API returns bodies, but assert it rather than assume it - this
        directory is committed."""
        forbidden = ("password", "key_secret", "keySecret", "authToken", "bearer",
                     "client_secret", "Authorization")
        for entry in list(SOURCE.glob("*.json")) + list(NORMALIZED.glob("*.json")) + [MANIFEST]:
            text = entry.read_text()
            for token in forbidden:
                assert token not in text, f"{entry.name} contains {token!r}"

    def test_fingerprints_are_stable_and_distinct(self, manifest):
        prints = [t["fingerprint"] for t in manifest["templates"]]
        assert len(prints) == len(set(prints)), "two templates share a fingerprint"
        assert all(len(p) == 16 for p in prints)


# ══════════════════════════════════════════════════════════════════════════════
# Normalization.
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalization:
    def test_a_text_template_normalizes(self):
        row = sync.normalize({
            "name": "t", "type": "text_message", "status": "approved",
            "component": {"text": "Order {{order_id}} is {{status}}"}})
        assert row["isRichCard"] is False
        assert row["variables"] == ["order_id", "status"]
        assert row["variableSyntax"] == "curly"
        assert row["suggestionCount"] == 0

    def test_a_rich_card_normalizes_including_its_action(self):
        row = sync.normalize({
            "name": "c", "type": "rich_card", "status": "approved",
            "component": {"richCard": {"standaloneCard": {
                "cardOrientation": "VERTICAL",
                "cardContent": {
                    "title": "Hello", "description": "World",
                    "media": {"height": "MEDIUM", "contentInfo": {
                        "fileUrl": "https://x/y.mp4", "thumbnailUrl": "https://x/t.png"}},
                    "suggestions": [{"action": {
                        "text": "Go", "postbackData": "go",
                        "openUrlAction": {"url": "https://x", "application": "BROWSER"}}}],
                }}}}})
        assert row["isRichCard"] is True
        assert row["mediaExtension"] == "mp4"
        assert row["mediaHeight"] == "MEDIUM"
        assert row["actions"][0]["actionTypes"] == ["openUrlAction"]
        assert row["actions"][0]["url"] == "https://x"

    def test_bracket_and_curly_syntaxes_are_told_apart(self):
        assert sync._variable_syntax("Hi {{name}}") == "curly"
        assert sync._variable_syntax("Hi [custom_param1b]") == "bracket"
        assert sync._variable_syntax("Hi {{a}} and [b]") == "MIXED"
        assert sync._variable_syntax("no vars") == "none"

    def test_quick_replies_are_distinguished_from_actions(self):
        row = sync.normalize({
            "name": "r", "type": "rich_card", "status": "approved",
            "component": {"richCard": {"standaloneCard": {"cardContent": {
                "suggestions": [{"reply": {"text": "Yes", "postbackData": "y"}}]}}}}})
        assert row["actions"][0]["kind"] == "reply"


# ══════════════════════════════════════════════════════════════════════════════
# Validation rules, each tied to a rendering consequence.
# ══════════════════════════════════════════════════════════════════════════════

class TestValidationRules:
    def _finding(self, row, fragment):
        return [f for f in sync.validate([row]) if fragment in f["finding"]]

    def test_horizontal_with_tall_media_is_high_when_reachable(self):
        """Google's RBM standalone card does not offer TALL media on a HORIZONTAL card.
        A client that rejects the combination drops the media, leaving a card whose whole
        purpose was the video showing nothing.

        Severity became reachability-derived on 2026-09-28: HIGH when a code path can
        send the template, MEDIUM when none can. Both directions are asserted here,
        because the relaxation is only defensible if the escalation is real — see
        `tests/test_rcs_finding_severity.py` for why the flat-HIGH version left
        `--check` permanently red and therefore wired into nothing.
        """
        def _row(name):
            return sync.normalize({
                "name": name, "type": "rich_card", "status": "approved",
                "component": {"richCard": {"standaloneCard": {
                    "cardOrientation": "HORIZONTAL",
                    "cardContent": {"media": {"height": "TALL", "contentInfo": {
                        "fileUrl": "https://x/y.mp4"}}}}}}})

        # "rcsmenu" is the one name in sync.REFERENCED, so normalize() marks it reachable.
        reachable = self._finding(_row("rcsmenu"), "HORIZONTAL")
        assert reachable and reachable[0]["severity"] == "HIGH"
        assert reachable[0]["needsProviderReadback"] is True

        unreachable = self._finding(_row("x"), "HORIZONTAL")
        assert unreachable, "the defect must still be reported on an unsent template"
        assert unreachable[0]["severity"] == "MEDIUM"
        assert unreachable[0]["needsProviderReadback"] is True

    def test_vertical_with_tall_media_is_fine(self):
        row = sync.normalize({
            "name": "x", "type": "rich_card", "status": "approved",
            "component": {"richCard": {"standaloneCard": {
                "cardOrientation": "VERTICAL",
                "cardContent": {"media": {"height": "TALL", "contentInfo": {
                    "fileUrl": "https://x/y.png"}}}}}}})
        assert self._finding(row, "HORIZONTAL") == []

    def test_trailing_backticks_are_flagged_but_not_auto_fixed(self):
        """The approved body really does contain six backticks. The action must be a
        versioned successor, never an in-place edit of an approved template."""
        row = sync.normalize({
            "name": "x", "type": "text_message", "status": "approved",
            "component": {"text": "Hello\n``````\nWECARE"}})
        found = self._finding(row, "backticks")
        assert found and found[0]["severity"] == "MEDIUM"
        assert "do NOT edit the approved template in place" in found[0]["action"]

    def test_mixed_placeholder_syntax_is_high_when_reachable(self):
        """Same reachability rule as the orientation defect, asserted both ways."""
        text = "Hi {{name}}, order [custom_param1b]"

        reachable = self._finding(sync.normalize({
            "name": "rcsmenu", "type": "text_message", "status": "approved",
            "component": {"text": text}}), "placeholder")
        assert reachable and reachable[0]["severity"] == "HIGH"

        unreachable = self._finding(sync.normalize({
            "name": "x", "type": "text_message", "status": "approved",
            "component": {"text": text}}), "placeholder")
        assert unreachable and unreachable[0]["severity"] == "MEDIUM"

    def test_a_single_syntax_is_not_flagged(self):
        for text in ("Hi {{name}}", "Hi [custom_param1b]", "no vars at all"):
            row = sync.normalize({"name": "x", "type": "text_message",
                                  "status": "approved", "component": {"text": text}})
            assert self._finding(row, "placeholder") == []

    def test_a_suggestion_with_no_action_type_is_flagged(self):
        row = sync.normalize({
            "name": "x", "type": "rich_card", "status": "approved",
            "component": {"richCard": {"standaloneCard": {"cardContent": {
                "suggestions": [{"action": {"text": "Dead", "postbackData": "d"}}]}}}}})
        found = self._finding(row, "no action type")
        assert found and found[0]["severity"] == "MEDIUM"

    def test_video_media_is_informational_not_an_error(self):
        """Video in a card is legitimate. It is recorded because inline playback differs
        between clients, so the thumbnail has to carry the message on its own."""
        row = sync.normalize({
            "name": "x", "type": "rich_card", "status": "approved",
            "component": {"richCard": {"standaloneCard": {"cardContent": {
                "media": {"height": "MEDIUM",
                          "contentInfo": {"fileUrl": "https://x/y.mp4"}}}}}}})
        found = self._finding(row, "video media")
        assert found and found[0]["severity"] == "INFORMATIONAL"

    def test_an_image_card_raises_no_video_finding(self):
        row = sync.normalize({
            "name": "x", "type": "rich_card", "status": "approved",
            "component": {"richCard": {"standaloneCard": {"cardContent": {
                "media": {"height": "MEDIUM",
                          "contentInfo": {"fileUrl": "https://x/y.png"}}}}}}})
        assert self._finding(row, "video media") == []

    def test_unreferenced_templates_are_reported_once_in_aggregate(self):
        rows = [sync.normalize({"name": n, "type": "text_message",
                                "status": "approved", "component": {"text": "x"}})
                for n in ("rcsmenu", "test16", "test17")]
        found = [f for f in sync.validate(rows) if "no code path sends" in f["finding"]]
        assert len(found) == 1, "should aggregate, not one finding per template"
        assert "test16" in found[0]["template"] and "rcsmenu" not in found[0]["template"]

    def test_every_finding_states_a_consequence_and_an_action(self, manifest):
        """A finding without a consequence is an opinion, and an approved template is not
        changed on an opinion."""
        for f in sync.validate(manifest["templates"]):
            assert f["consequence"].strip(), f
            assert f["action"].strip(), f
            assert f["severity"] in ("HIGH", "MEDIUM", "INFORMATIONAL")


# ══════════════════════════════════════════════════════════════════════════════
# The live inventory, pinned so a provider-side change is noticed.
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveInventory:
    def test_the_template_our_code_sends_exists_and_is_approved(self, manifest):
        """`rcsmenu` is the only template with a sender. If it disappeared or fell out of
        approval, every RCS notification would fail at the provider."""
        rows = {t["name"]: t for t in manifest["templates"]}
        assert "rcsmenu" in rows, "the only referenced template is missing remotely"
        assert rows["rcsmenu"]["status"] == "approved"
        assert rows["rcsmenu"]["isRichCard"] is True

    def test_the_two_documented_only_templates_still_exist(self, manifest):
        """Their senders were deleted as dead code. They remain approved remotely, which
        is why they are documented-only rather than missing."""
        names = {t["name"] for t in manifest["templates"]}
        assert {"rcsorder", "waalert"} <= names

    def test_no_carousel_template_exists_yet(self, manifest):
        """`rcs-send` can send a carousel from a request body, but no approved carousel
        template exists - so carousel is an untested capability, not a working feature."""
        assert manifest["counts"]["carousel"] == 0

    def test_code_docstrings_overstate_the_media_height(self, manifest):
        """Both handlers document all templates as MEDIUM height. The export shows TALL
        and SHORT as well, so the comments are wrong and cannot be trusted for QA."""
        heights = {t["name"]: t["mediaHeight"] for t in manifest["templates"]
                   if t["isRichCard"]}
        assert set(heights.values()) != {"MEDIUM"}, (
            "if this passes, the docstrings may now be accurate - re-check them")
        assert heights.get("get_started") == "TALL"
        assert heights.get("wecaremenu") == "SHORT"

    def test_all_rich_cards_are_standalone_not_carousel(self, manifest):
        for t in manifest["templates"]:
            if t["isRichCard"]:
                assert t["isCarousel"] is False, t["name"]

    def test_the_high_finding_count_is_known(self, manifest):
        """Pinned deliberately. A new HIGH finding should fail this test and force a
        decision rather than sliding into the manifest unnoticed.

        The pinned count went 1 -> 0 on 2026-09-28, and the defect did not go away. The
        single HIGH was `get_started`'s HORIZONTAL/TALL combination, on a template no code
        path sends; severity is now derived from reachability, so it is reported at MEDIUM
        with its consequence and remediation intact. `--check` gating on HIGH is what made
        this matter: at 1 it could never pass, so it ran in no workflow. At 0 it is now a
        blocking step in `provider-allowlist.yml`, and it will fail the moment a defect
        lands on a template something actually sends.

        Zero is therefore the correct pin, and it is a stronger position than 1: the
        assertion below no longer tolerates a reachable defect at all.
        """
        findings = sync.validate(manifest["templates"])
        high = [f for f in findings if f["severity"] == "HIGH"]
        assert high == [], [f["finding"] for f in high]

        # The de-escalated finding must still be present, or this became a silencer.
        orientation = [f for f in findings if "HORIZONTAL" in f["finding"]]
        assert orientation, "the get_started orientation defect must still be reported"
        assert orientation[0]["template"] == "get_started"
        assert orientation[0]["severity"] == "MEDIUM"
