from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/pages/_app.tsx"
SHELL = ROOT / "src/components/WorkspaceShell.tsx"
LAYOUT = ROOT / "src/components/Layout.tsx"
SHELL_CSS = ROOT / "src/styles/workspace-shell.css"

GLOBAL_CHROME_IMPORTS = (
    "components/Header",
    "components/Footer",
    "components/PublicShare",
    "components/SupportWidget",
    "components/BottomNav",
)


def test_every_workspace_route_is_wrapped_centrally_after_authshell():
    app = APP.read_text()
    assert "const AuthShell = dynamic" in app
    assert "router.pathname.startsWith( '/workspace' )" in app
    assert "<WorkspaceShell user={ user as any } onSignOut={ handleSignOut }>" in app
    assert "<Component { ...pageProps }" in app
    auth_branch = app[app.index("<AuthShell>"):]
    assert auth_branch.count("<FloatingAgent />") == 1
    assert auth_branch.count("<SupportWidget />") == 1


def test_workspace_shell_owns_shared_chrome_once_and_keeps_operational_data_private():
    shell = SHELL.read_text()
    for shared in ("Header", "PublicShare", "Footer"):
        assert f"import {shared} from" in shell
    assert shell.count("<Header />") == 1
    assert shell.count("<PublicShare />") == 1
    assert shell.count("<Footer />") == 1
    assert "import SupportWidget" not in shell
    assert "<SupportWidget" not in shell
    assert "import FloatingAgent" not in shell
    assert "<FloatingAgent" not in shell
    assert 'data-wc-no-translate="true"' in shell
    assert 'className="main-content workspace-main"' in shell
    assert "SearchModal" in shell
    assert "'/workspace/task'" in shell
    assert "PushOptIn" in shell
    assert "onSignOut" in shell


def test_legacy_layout_is_only_a_nesting_safe_adapter():
    layout = LAYOUT.read_text()
    assert "WorkspaceShellContext" in layout
    assert "if ( insideCanonicalShell ) return" in layout
    assert "<WorkspaceShell" in layout
    for retired in ("BottomNav", "BrandLockup", "workspace-topbar"):
        assert retired not in layout


def test_workspace_pages_and_nested_components_cannot_mount_competing_global_chrome():
    roots = (ROOT / "src/pages/workspace", ROOT / "src/components/workspace")
    offenders = []
    for base in roots:
        for path in base.rglob("*.tsx"):
            source = path.read_text()
            for token in GLOBAL_CHROME_IMPORTS:
                if token in source:
                    offenders.append(f"{path.relative_to(ROOT)} -> {token}")
    assert offenders == []


def test_workspace_shell_uses_home_public_foundation_and_mobile_containment():
    shell = SHELL.read_text()
    css = SHELL_CSS.read_text()
    for token in (
        "--public-content-max",
        "--public-page-gutter",
        "--public-section-gap",
        "--public-mobile-page-gutter",
        "--public-mobile-section-gap",
        "--public-mobile-hero-top",
    ):
        assert token in shell or token in css
    assert "padding-top:108px" in shell
    assert "padding-top:96px" in shell
    assert "100vh" in shell and "100dvh" in shell
    assert "safe-area-inset-bottom" in shell
    assert "overflow-x:clip" in shell
    assert "@media(max-width:279px)" in shell
    assert "font-size:16px!important" in css
    assert "min-height:auto!important" in css


def test_workspace_tabs_and_wide_data_are_contained_locally():
    css = SHELL_CSS.read_text()
    assert ".ps-tabs-wrapper" in css
    assert "overflow-x:auto" in css
    assert "overscroll-behavior-inline:contain" in css
    assert '[class$="-table-wrap"]' in css
    assert ".table-container" in css


def test_protected_head_keeps_viewport_fit_cover():
    app = APP.read_text()
    protected = app[app.index("// Protected pages"):]
    assert "viewport-fit=cover" in protected
