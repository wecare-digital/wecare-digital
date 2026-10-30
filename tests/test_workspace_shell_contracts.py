from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOTS = (
    ROOT / "src" / "pages" / "workspace",
    ROOT / "src" / "components" / "workspace",
)
LAYOUT = ROOT / "src" / "components" / "Layout.tsx"
APP = ROOT / "src" / "pages" / "_app.tsx"
PAYMENTS = ROOT / "src" / "pages" / "workspace" / "payments" / "index.tsx"

SHARED_IMPORT = re.compile(
    r"from\s+['\"][^'\"]*components/(Header|Footer|PublicShare|SupportWidget)['\"]"
)


def workspace_sources():
    for root in WORKSPACE_ROOTS:
        yield from root.rglob("*.tsx")


def test_layout_is_the_one_workspace_chrome_owner():
    source = LAYOUT.read_text(encoding="utf-8")
    for component in ("Header", "PublicShare", "Footer"):
        assert f"import {component} from './{component}'" in source
        assert f"<{component} />" in source
    assert "BottomNav" not in source
    assert 'data-wc-no-translate="true"' in source
    assert "WorkspaceShellContext" in source
    assert "return nested ? <>{ props.children }</> : <WorkspaceShell { ...props } />;" in source


def test_workspace_routes_and_nested_components_do_not_import_shared_chrome():
    offenders = []
    for path in workspace_sources():
        source = path.read_text(encoding="utf-8")
        if SHARED_IMPORT.search(source):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], (
        "Workspace code must receive Header/Footer/PublicShare/SupportWidget from Layout/_app, "
        f"not mount shared chrome directly: {offenders}"
    )


def test_payments_uses_canonical_layout_not_a_private_wrapper():
    source = PAYMENTS.read_text(encoding="utf-8")
    assert "import Layout from '../../../components/Layout'" in source
    assert 'shellClassName="payments-public-layout"' in source
    for component in ("Header", "Footer", "PublicShare", "SupportWidget"):
        assert f"components/{component}" not in source


def test_authenticated_support_widget_and_agent_stay_global_and_separate():
    source = APP.read_text(encoding="utf-8")
    authenticated = source[source.index("<AuthShell>"):]
    assert authenticated.count("<SupportWidget />") == 1
    assert authenticated.count("<FloatingAgent />") == 1
    assert authenticated.index("<FloatingAgent />") < authenticated.index("<SupportWidget />")
