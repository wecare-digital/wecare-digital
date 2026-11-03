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


test('login buttons have exactly one visual owner and accessible interaction states', () => {
  const selector = ".wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary'] {";
  assert.equal(theme.split(selector).length - 1, 1,
    'shared /ws visual system owns the base primary button style once');

  // The old lime selector and redundant Amplify component token caused three
  // competing values in the cascade; neither can be reintroduced.
  assert.ok(!auth.includes("data-variation='primary'"),
    'WsAuthShell must never style the primary button directly');
  assert.ok(!/\bbutton:\s*\{\s*primary:/.test(auth),
    'Amplify button variations must not introduce a competing primary palette');
  // Match the full, flat CSS declaration block. The [^{}]* guard makes the
  // assertion fail if a nested rule or stray brace is introduced later.
  const blockMatch = theme.match(/\.wsauth-shell\.ws-notion-auth \.amplify-button\[data-variation='primary'\]\s*\{([^{}]*)\}/);
  assert.ok(blockMatch, 'primary button rule must be present and well-formed');
  const buttonRule = blockMatch[1];
  assert.ok(buttonRule.includes('background-color:var(--ws-green)'),
    'primary button should use the same green as /ws');
  assert.ok(buttonRule.includes('color:#fff'),
    'primary button should have readable white text');
  assert.ok(theme.includes(".amplify-button[data-variation='primary']:is(:hover,:focus-visible)"),
    'hover and keyboard focus must share an intentional green state');
  assert.ok(theme.includes(".amplify-button[data-variation='primary']:active"),
    'pressed state must be explicit');
  assert.ok(theme.includes(".amplify-button[data-variation='primary']:disabled"),
    'disabled state must remain visually clear');

  assert.ok(theme.includes(':is(.amplify-input,.amplify-select):focus'),
    'input focus should match the green action palette');
  assert.ok(!auth.includes('rgba(209,244,112,0.35)'),
    'obsolete lime form focus ring should not return');
  assert.ok(!auth.includes('#d1f470') && !auth.includes('var(--lime,'),
    'auth brand tile and Amplify fallback palette must not restore lime');
  assert.ok(auth.includes('background:#e9eee8;'),
    'brand tile fallback should match the neutral shared theme');
});
