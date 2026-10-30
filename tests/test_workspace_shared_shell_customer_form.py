"""Source contracts for the shared Workspace shell and F001 customer form."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_authenticated_app_mounts_one_workspace_shell():
    app = (ROOT / 'src/pages/_app.tsx').read_text()
    assert "const WorkspaceLayout = dynamic" in app
    protected = app[app.index('// Protected pages'):]
    assert '<WorkspaceLayout' in protected
    assert 'showBreadcrumbs={ false }' in protected
    assert protected.count('<SupportWidget />') == 1

def test_workspace_layout_uses_one_shared_public_shell():
    source = (ROOT / 'src/components/Layout.tsx').read_text()
    assert "import Header from './Header'" in source
    assert "import PublicShare from './PublicShare'" in source
    assert "import Footer from './Footer'" in source
    assert source.count('<Header />') == 1
    assert source.count('<PublicShare />') == 1
    assert source.count('<Footer />') == 1
    assert 'WorkspaceShellContext' in source
    assert 'data-wc-no-translate="true"' in source
    assert 'BottomNav' not in source

def test_payments_uses_canonical_layout_not_a_copied_shell():
    source = (ROOT / 'src/pages/workspace/payments/index.tsx').read_text()
    assert "import Layout from '../../../components/Layout'" in source
    assert '<Layout user={ user } onSignOut={ signOut }' in source
    assert "import Header from" not in source
    assert '<PublicShare />' not in source
    assert '<Footer />' not in source

def test_customer_modal_matches_subscribe_profile_and_resolves_duplicates():
    source = (ROOT / 'src/pages/workspace/customers/index.tsx').read_text()
    form = source[source.index('const renderContactForm'):source.index('\n\n  return (', source.index('const renderContactForm'))]
    for label in ('Full name *','Linked WhatsApp number *','WhatsApp username','Organization','Job title','Your address'):
        assert label in form
    assert 'contact-email' not in form
    assert 'Contact &amp; system identity' not in form
    assert "checkDuplicate(formPhone, '')" in source
    assert 'addressComplete(formAddress)' in source
    assert 'Open existing customer' in source
    assert 'Use for payment' in source
    assert 'HTTP 409' not in source
