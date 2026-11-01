"""Regression: Workspace Vault upload controls must not be clipped above the footer.

Legacy Layout.css gives .main-content a fixed 100vh scroll box. The no-sidebar
workspace needs natural document scrolling so both the Vault file picker and
the Upload to Vault action remain reachable before Stay connected/footer.

Run: python -m unittest discover -s tests -p 'test_workspace_vault_page_scroll_20261101.py'
"""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL_CSS = ROOT / "src/styles/workspace-shell.css"
SHELL_JSX = ROOT / "src/components/WorkspaceShell.tsx"
VAULT_UI = ROOT / "src/components/workspace/service/SecureFiles.tsx"
PAYMENTS_PAGE = ROOT / "src/pages/workspace/payments/index.tsx"


class VaultPageScrollTests(unittest.TestCase):
    def test_canonical_workspace_main_is_content_height_not_viewport_limited(self):
        css = SHELL_CSS.read_text(encoding="utf-8")
        match = re.search(
            r"\.workspace-shell\s+\.main-content\.workspace-main\s*\{([^}]+)\}",
            css,
            re.S,
        )
        self.assertIsNotNone(match, "Missing scoped override of legacy .main-content")
        declarations = re.sub(r"\s+", "", match.group(1))
        self.assertIn("height:auto;", declarations)
        self.assertIn("overflow-y:visible;", declarations)
        self.assertIn("display:block;", declarations)
        self.assertNotIn("height:100vh", declarations)
        self.assertNotIn("overflow-y:auto", declarations)

    def test_shared_workspace_footer_follows_unconstrained_main(self):
        jsx = SHELL_JSX.read_text(encoding="utf-8")
        self.assertIn('className="main-content workspace-main"', jsx)
        self.assertLess(jsx.index('<main id="main-content"'),
                        jsx.index('<div className="workspace-public-share">'))
        self.assertLess(jsx.index('<div className="workspace-public-share">'),
                        jsx.index('<Footer />'))

    def test_vault_file_picker_and_save_only_action_exist(self):
        ui = VAULT_UI.read_text(encoding="utf-8")
        payments = PAYMENTS_PAGE.read_text(encoding="utf-8")
        self.assertIn('id="sf-file"', ui)
        self.assertIn("type=\"file\"", ui)
        self.assertIn("Upload to Vault", ui)
        self.assertIn("handleUpload()", ui)
        self.assertIn("Save only — no WhatsApp message, charge or payment request.", ui)
        self.assertIn('<VaultWorkbench signOut={ signOut } user={ user } embedded />', payments)


if __name__ == "__main__":
    unittest.main()
