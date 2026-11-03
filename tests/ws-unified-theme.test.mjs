// Layout-only regression guards for the /ws Notion-inspired visual system.
// The auth/payment flows remain outside this feature's scope.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const theme = readSource('src/components/ws/WsNotionTheme.tsx');
const shell = readSource('src/components/ws/WsShell.tsx');
const auth = readSource('src/components/ws/WsAuthShell.tsx');

test('one /ws visual system is shared by workspace pages and login only', () => {
  assert.ok(theme.includes('.ws-shell.ws-notion'), 'workspace theme root required');
  assert.ok(theme.includes('.wsauth-shell.ws-notion-auth'), 'login theme root required');
  assert.ok(!theme.includes('.ws-shell.ws-notion,\n  .wsauth-shell.ws-notion-auth {'),
    'the public header, footer and share dock must not inherit workspace-specific design tokens');
  assert.ok(!theme.includes(':root {'), 'no global token override');
  assert.ok(!theme.includes('body {'), 'no global page body override');
  assert.ok(shell.includes('<WsNotionTheme />'), 'logged-in shell mounts shared theme');
  assert.ok(auth.includes('<WsNotionTheme />'), 'login mounts shared theme');
  assert.ok(shell.includes('className="ws-shell ws-notion"'));
  assert.ok(auth.includes('className="wsauth-shell ws-notion-auth"'));
});

test('auth still runs through the same Cognito Authenticator, MFA and render contract', () => {
  assert.ok(auth.includes("import '../../lib/amplifyConfig'"), 'Cognito configuration retained');
  assert.ok(auth.includes('<Authenticator.Provider>'), 'auth provider retained');
  assert.ok(auth.includes('<Authenticator hideSignUp={ true } components={ { Header: WsBrandHeader } }>'));
  assert.ok(auth.includes('children( { signOut, user } )'), 'authenticated render and signOut retained');
  assert.ok(auth.includes("authStatus === 'authenticated'"), 'successful sign-in still renders the workspace');
  const app = readSource('src/pages/_app.tsx');
  // Confirm semantics without binding the test to arbitrary spacing or quote style
  // in _app.tsx. The /ws and /workspace guards must remain distinct.
  assert.match(app,
    /router\.pathname\.startsWith\(\s*['"]\/ws['"]\s*\)\s*\?\s*WsAuthShell\s*:\s*AuthShell/,
    '/ws must use its own auth shell; /workspace retains the legacy one');
});

test('each /ws route retains its original business panel and shared theme', () => {
  for (const file of [
    'src/pages/ws/index.tsx',
    'src/pages/ws/inbox/index.tsx',
    'src/pages/ws/collect/index.tsx',
    'src/pages/ws/customers/index.tsx',
    'src/pages/ws/commerce/index.tsx',
    'src/pages/ws/settings/index.tsx',
  ]) {
    assert.ok(readSource(file).includes('<WsShell'), file + ' must keep the shared shell');
  }
  assert.ok(readSource('src/pages/ws/index.tsx').includes('<WsShell active="home"'),
    'home should not highlight Inbox');
  assert.ok(readSource('src/pages/ws/collect/index.tsx').includes('<CollectCreatePanel'),
    'invoice create/payment review flow must remain intact');
  assert.ok(readSource('src/pages/ws/commerce/index.tsx').includes('<PriceCatalog'),
    'text-only pricing catalog must remain intact');
  assert.ok(readSource('src/pages/ws/commerce/index.tsx').includes('<Orders'),
    'orders view must remain intact');
});


test('homepage lime owns the sign-in CTA, without conflicting Amplify variation CSS', () => {
  // The base paint rule is singular. A reduced-motion media query may repeat
  // the selector only to suppress animation, without redefining the button fill.
  const primaryBlocks = [ ...theme.matchAll(
    /\.wsauth-shell\.ws-notion-auth \.amplify-button\[data-variation='primary'\]\s*\{([^{}]*)\}/g,
  ) ];
  assert.equal(primaryBlocks.filter( match => match[1].includes('background-color:') ).length, 1,
    'the scoped /ws theme must define the primary button fill exactly once');
  assert.ok(!auth.includes("data-variation='primary'"),
    'the auth component must not add a competing button selector');
  assert.ok(!/\bbutton:\s*\{\s*primary:/.test(auth),
    'Amplify theme tokens must not add a competing button variation');

  const blockMatch = theme.match(/\.wsauth-shell\.ws-notion-auth \.amplify-button\[data-variation='primary'\]\s*\{([^{}]*)\}/);
  assert.ok(blockMatch, 'the CTA rule must be a flat, well-formed CSS declaration');
  assert.ok(blockMatch[1].includes('background-color:var(--ws-login-lime)'),
    'the CTA fill must be homepage lime, not solid dark green');
  assert.ok(blockMatch[1].includes('color:var(--ws-login-deep)'),
    'dark ink on lime must keep the button label readable');
  assert.ok(blockMatch[1].includes('border:0!important'),
    'the CTA must not reintroduce the legacy outlined button');
  assert.ok(theme.includes("content:'login'"),
    'sign-in uses the Material Symbols Rounded login icon instead of Next');
  assert.ok(!theme.includes("content:'arrow_forward'"),
    'do not add a forward/Next arrow to the sign-in button');
  assert.ok(readSource('src/config/materialSymbols.ts').includes("'login'"),
    'the icon must be included in the Google Material 3 subset font');
  assert.ok(theme.includes("font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24"),
    'Material 3 icon weight must match its explicit font-weight to avoid browser fallback');
  assert.ok(theme.includes("-webkit-font-feature-settings:'liga'"),
    'enable ligature rendering in browsers using WebKit font-feature settings');
  assert.ok(theme.includes(".amplify-button[data-variation='primary']:focus-visible"),
    'the lime button still needs a strong keyboard focus state');
  assert.ok(theme.includes(".amplify-button[data-variation='primary']:disabled"),
    'a disabled submit button needs an intentional state');
  assert.ok(theme.includes('@media(prefers-reduced-motion:reduce)'),
    'respect visitors who ask to reduce animation');
  assert.ok(theme.includes(".amplify-button[data-variation='primary'] {transition:none}"),
    'the simple login CTA must respect reduced-motion preferences');
  assert.ok(theme.includes('border-radius:999px'),
    'the button and forgot-password affordance must be oval as pictured');
});

test('credential inputs are truly borderless at rest with an accessible focus ring', () => {
  const fields = theme.match(
    /\.wsauth-shell\.ws-notion-auth :is\(\.amplify-input,\.amplify-select\),\s*\.wsauth-shell\.ws-notion-auth \.amplify-passwordfield \.amplify-input\s*\{([^{}]*)\}/,
  );
  assert.ok(fields, 'the input and password field rule must exist');
  assert.match(fields[1], /border:0!important;/, 'input borders must be ZERO, not a lighter stroke');
  assert.match(fields[1], /background:var\(--ws-login-field\)!important;/,
    'borderless fields use a soft surface to distinguish input areas');
  assert.ok(theme.includes('.amplify-passwordfield .amplify-field-group__control:focus-within'),
    'password visibility controls must preserve a visible focus ring');
  assert.ok(theme.includes('outline:2px solid var(--ws-login-deep)'),
    'keyboard focus must remain visible even though field borders are removed');
  assert.ok(theme.includes('.amplify-field-group__control:hover'),
    'password control hover must not reintroduce an Amplify default border');
  assert.ok(theme.includes('border-color:transparent!important'),
    'input, group and eye-button hover borders must stay transparent');
});

test('login has exactly the minimal form and real homepage header, share block, footer', () => {
  assert.ok(auth.includes("import Header from '../Header'"), 'reuse real site header');
  assert.ok(auth.includes("import Footer from '../Footer'"), 'reuse real site footer');
  assert.ok(auth.includes("import PublicShare from '../PublicShare'"), 'reuse real homepage share actions');
  assert.ok(auth.includes("import PublicToastProvider from '../public/PublicToastProvider'"),
    'share actions retain the public feedback provider');
  assert.ok(auth.includes('<PublicToastProvider>'), 'public chrome gets its feedback context');
  assert.ok(auth.includes('<Header />'), 'public header appears above login');
  assert.ok(auth.includes('<Footer />'), 'public footer appears after share block');
  assert.ok(auth.includes('<PublicShare url="https://wecare.digital/" title="WECARE.DIGITAL" />'),
    'share the public homepage rather than the password-protected route');
  assert.ok(auth.includes('className="wsauth-login-main"'), 'form occupies its own main area');
  assert.ok(auth.includes('className="wsauth-form"'), 'keep one centered form');
  assert.ok(theme.includes('padding-top:108px'), 'desktop form clears the fixed public header');
  assert.ok(theme.includes('@media(max-width:767px)'), 'mobile header and spacing are covered');
  assert.ok(theme.includes('padding-top:96px'), 'phone form clears the fixed mobile header');
  for (const obsolete of ['wsauth-workbook', 'wsauth-story', 'wsauth-module', 'Welcome back.', 'STAFF WORKSPACE', 'SECURE SIGN IN']) {
    assert.ok(!auth.includes(obsolete), 'do not bring back the previous promo UI: ' + obsolete);
  }
  assert.ok(!auth.includes('Back to wecare.digital'), 'the shared header already navigates home');
  assert.ok(!auth.includes('Site policies'), 'avoid duplicating the public menu navigation');
  assert.ok(auth.indexOf("authStatus === 'authenticated'") < auth.indexOf('<PublicToastProvider>'),
    'public chrome must unmount after sign-in, not wrap the private workspace');
});

test('only the WECARE.DIGITAL eyebrow appears above form, without duplicate logo', () => {
  assert.ok(auth.includes('<Header />'), 'public Header remains the only page logo owner');
  assert.ok(auth.includes('const WsBrandHeader = (): React.JSX.Element => ('),
    'text eyebrow belongs in the actual Cognito header slot');
  assert.ok(auth.includes('<div className="wsauth-eyebrow" data-wc-no-translate="true">WECARE.DIGITAL</div>'),
    'the complete eyebrow label must be exactly WECARE.DIGITAL');
  assert.ok(theme.includes('.wsauth-shell.ws-notion-auth .wsauth-eyebrow'),
    'eyebrow pill is styled and scoped to /ws');
  assert.ok(!auth.includes('<img '), 'the login must not render a duplicate logo image');
  assert.ok(!auth.includes('WECARE_SVG_URL'), 'the S3 logo is already handled by shared Header');
  assert.ok(!theme.includes('wsauth-svg-frame'), 'remove unused duplicated-logo styling');
  assert.ok(theme.includes('background:#fff;'), 'login is on a white page, not lime-tinted');
  assert.ok(theme.includes('.wsauth-shell.ws-notion-auth .wsauth-login-main'),
    'centered form remains separate from public chrome');
});

test('the screenshot input and password affordances stay intact', () => {
  assert.ok(theme.includes('.wsauth-shell.ws-notion-auth .amplify-label'),
    'username and password labels remain readable');
  assert.ok(theme.includes('.wsauth-shell.ws-notion-auth .amplify-field-group__outer-end .amplify-button'),
    'the existing show-password eye is retained');
  assert.ok(theme.includes(".wsauth-shell.ws-notion-auth .amplify-button[data-variation='link']"),
    'the password recovery button remains available');
  assert.ok(theme.includes('background:var(--ws-login-field)'),
    'forgot password has the pale gray pill surface');
  assert.ok(theme.includes('border-radius:999px'), 'form actions are fully rounded as requested');
  assert.ok(theme.includes('outline:2px solid var(--ws-login-deep)'),
    'focused password and username fields remain accessible');
  assert.ok(theme.includes('[data-amplify-authenticator-select-mfa-type]'),
    'MFA flow is still styled and usable');
});
