"""Static regression checks for brand-lime toasts and non-modal feedback.

These checks verify source contracts without AWS credentials or outbound messages.
They do not replace a browser accessibility / visual test.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_orders_whatsapp_feedback_is_inline_lime_and_transient():
    source = (ROOT / "src/components/orders/OrdersPage.tsx").read_text()
    style = source.split(".ord-profile-toast{", 1)[1].split(".ord-profile-toast-icon{", 1)[0]
    assert "position:static;" in style
    assert "position:fixed;" not in style
    assert "background:var(--public-brand-lime);color:var(--public-brand-green)" in style
    assert ".ord-profile-toast-error{background:var(--public-brand-lime);color:var(--public-brand-green)}" in source
    assert "window.setTimeout( () => setProfileAction( 'idle' ), 4000 )" in source
    assert "profileAction === 'failed' ? 'alert' : 'status'" in source


def test_workspace_toasts_use_lime_and_quiet_fade():
    source = (ROOT / "src/styles/inner-ux.css").read_text()
    section = source.split(".toast-container {", 1)[1].split("/* ========================================\n   RESPONSIVE - MOBILE", 1)[0]
    assert "background: var(--public-brand-lime);" in section
    assert "color: var(--public-brand-green);" in section
    assert "pointer-events: none;" in section  # The outer rail does not swallow page taps.
    assert "pointer-events: auto;" in section  # Each toast remains dismissible.
    assert "transform: translateX(" not in section
    assert "box-shadow: none;" in section
    assert "animation: toast-exit 0.2s ease forwards;" in section


def test_shared_toasts_announce_severity_and_remain_dismissible():
    component = (ROOT / "src/components/Toast.tsx").read_text()
    assert "role={toast.type === 'error' || toast.type === 'warning' ? 'alert' : 'status'}" in component
    assert 'aria-atomic="true"' in component
    assert "onAnimationEnd={handleAnimationEnd}" in component
    assert "aria-label=\"Dismiss notification\"" in component
