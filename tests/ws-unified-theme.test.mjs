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
  assert.ok(theme.includes("content:'arrow_forward'"),
    'the submit button should display its Material 3 arrow');
  assert.ok(theme.includes(".amplify-button[data-variation='primary']:focus-visible"),
    'the lime button still needs a strong keyboard focus state');
  assert.ok(theme.includes(".amplify-button[data-variation='primary']:disabled"),
    'a disabled submit button needs an intentional state');
  assert.ok(theme.includes('@media(prefers-reduced-motion:reduce)'),
    'respect visitors who ask to reduce animation');
  assert.ok(theme.includes(".amplify-button[data-variation='primary']:active:not(:disabled) {transform:none}"),
    'the login CTA must not translate when reduced motion is enabled');
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
});

test('login has a real split design, homepage logo, Material 3 glyphs and real policy routes', () => {
  const icons = readSource('src/config/materialSymbols.ts');
  for (const name of [
    'arrow_forward',
    'group',
    'inbox',
    'lock',
    'receipt_long',
    'shopping_bag',
  ]) {
    assert.ok(icons.includes("'" + name + "'"), 'Material 3 font subset must contain ' + name);
    assert.ok(auth.includes("symbol('" + name + "')"), 'login must use typed Material 3 icon ' + name);
  }
  assert.ok(auth.includes("https://wecare.digital/get/o/stream/media/m/wecare-digital.svg"),
    'login logo must use the actual verified WECARE SVG hosted in the canonical S3 media prefix');
  assert.ok(!auth.includes('<BrandLockup compact />'),
    'the PNG homepage logo must not override the requested S3 SVG');
  assert.ok(auth.includes('<span className="wsauth-svg-frame" aria-hidden="true">'),
    'SVG icon is decorative next to the visible WECARE.DIGITAL name');
  assert.ok(auth.includes('<strong>WECARE<span className="wsauth-wordmark-dot">.</span></strong>'),
    'retain public two-line WECARE.DIGITAL brand treatment');
  assert.ok(auth.includes('wsauth-form-kicker">WECARE.DIGITAL</p>'),
    'keep the requested WECARE.DIGITAL login section label');
  assert.ok(theme.includes('.wsauth-shell.ws-notion-auth .wsauth-svg-frame img'),
    'the original SVG viewBox whitespace must be cropped without changing its artwork');
  assert.ok(auth.includes('className="wsauth-layout"'), 'a real responsive layout is required');
  assert.ok(auth.includes('className="wsauth-workbook"'), 'the split-panel workspace preview is required');
  assert.ok(theme.includes('grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr)'),
    'desktop must render the two-column login');
  assert.ok(theme.includes('@media(max-width:780px)'),
    'mobile must have a deliberate compact layout');
  assert.ok(auth.includes('href="/terms/"'), 'link to the real terms page');
  assert.ok(auth.includes('href="/privacy/"'), 'link to the real privacy page');
  assert.ok(auth.includes('Access is restricted to authorized staff.'),
    'the staff-only access notice should remain visible');
  assert.ok(!auth.includes('By signing in you agree'),
    'do not invent terms acceptance from simply signing in');
});
