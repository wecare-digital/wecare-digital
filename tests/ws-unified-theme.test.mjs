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
  assert.ok(app.includes("router.pathname.startsWith( '/ws' ) ? WsAuthShell : AuthShell"),
    'legacy /workspace authentication remains separate');
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
