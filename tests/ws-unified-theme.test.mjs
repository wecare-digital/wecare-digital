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


test('public /auth button treatment owns /ws CTA, without conflicting Amplify variation CSS', () => {
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
  assert.ok(blockMatch[1].includes('background-color:var(--public-lime-tint,var(--ws-login-field))'),
    'Sign in must use the customer /auth tinted rest surface, not an unrelated solid button');
  assert.ok(blockMatch[1].includes('color:var(--public-brand-green,var(--ws-login-deep))'),
    'use the common public-brand-green ink on the button');
  assert.ok(blockMatch[1].includes('border:0!important'),
    'the CTA must not reintroduce the legacy outlined button');
  assert.ok(theme.includes("content:'login'"),
    'sign-in uses the Material Symbols Rounded login icon instead of Next');
  assert.ok(theme.includes(".wsauth-shell.ws-notion-auth[data-wsauth-signin='true'] .amplify-button[data-variation='primary']::before"),
    'the sign-in icon must never leak to MFA, verification or password reset primary buttons');
  assert.ok(auth.includes("data-wsauth-signin={ route === 'signIn' ? 'true' : undefined }"),
    'actual Cognito signIn route, not button text guessing, scopes compact layout and glyph');
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
  assert.ok(!theme.includes('border-radius:999px'),
    'only the shared BrandBadge is pill-shaped; fields and buttons are now 13px');
  assert.ok(theme.includes('border-radius:13px'),
    'login actions have 13px corners');
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
  assert.ok(theme.includes('box-shadow:inset 0 -2px 0 var(--ws-login-deep)!important'),
    'focused fields use the subtle /auth-style underline, not a thick dark-green box ring');
  assert.ok(theme.includes('outline:0!important'),
    'input focus removes heavy outside outlines, while preserving a visible underline');
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

test('login reuses the public transparent SVG BrandBadge with homepage typography', () => {
  const badge = readSource('src/components/BrandBadge.tsx');
  const mark = readSource('src/components/BrandMark.tsx');
  assert.ok(auth.includes('<Header />'), 'retain shared public header branding');
  assert.ok(auth.includes("import BrandBadge from '../BrandBadge'"),
    'use the same reusable branded pill rather than a new icon or logo renderer');
  assert.ok(auth.includes('<BrandBadge label="WECARE.DIGITAL" />'),
    'render official mark LEFT and WECARE.DIGITAL text RIGHT in one shared component');
  assert.ok(badge.includes('<BrandMark />'), 'use the validated inline vector');
  assert.match(badge, /<BrandMark\s*\/>\s*\{\s*label\s*\}/,
    'the rendered vector must immediately precede the rendered text, ignoring component props');
  assert.ok(mark.includes('viewBox="1816 1604 1451 1718"'),
    'SVG is cropped in its own vector coordinate system, not by CSS magnification');
  assert.ok(mark.includes('fill="currentColor"'),
    'SVG must inherit the dark green ink on lime with transparent backing');
  assert.ok(!mark.includes('<rect'), 'do not reintroduce a baked-in opaque SVG background');
  assert.ok(!auth.includes('<img '), 'no network-loaded white square or CSS crop in the auth form');
  assert.ok(!auth.includes('WECARE_SVG_URL'), 'no duplicate remote icon asset');
  assert.ok(theme.includes('.wsauth-shell.ws-notion-auth .wsauth-eyebrow'),
    'position the common badge within the login only');
  assert.ok(!theme.includes('wsauth-eyebrow-icon'),
    'do not duplicate the BrandBadge icon geometry in Auth CSS');
  assert.ok(badge.includes('background:#d1f470'),
    'the branded pill uses the public design system lime');
  assert.ok(badge.includes('font-size:14px;font-weight:600;letter-spacing:-.125px'),
    'badge typography must exactly match the public site');
  assert.ok(theme.includes('background:#fff;'), 'the login main page remains white');
});

test('login fields and form fonts use public homepage tokens, not system gray', () => {
  const tokens = readSource('src/styles/tokens.css');
  assert.ok(tokens.includes('--public-lime-tint: var(--lime-tint)'),
    'the public theme provides the existing soft lime input surface');
  assert.ok(theme.includes('--ws-login-field:var(--public-lime-tint,rgba(209,244,112,.22))'),
    'credentials and password eye must use public lime tint instead of gray');
  assert.ok(!theme.includes('--ws-login-field:#f4f5f2'),
    'retired neutral gray input surface must not return');
  assert.ok(theme.includes('font-size:var(--public-card-size,22px)'),
    'form heading follows Home card size');
  assert.ok(theme.includes('font-size:var(--public-supporting-size,16px)'),
    'labels follow the Home supporting text scale');
  assert.ok(theme.includes('font-size:var(--public-supporting-size,16px)!important'),
    'mobile inputs remain at least 16px for iOS zoom safety');
  assert.ok(theme.includes('font-size:var(--public-cta-font-size,17px)'),
    'the Sign in CTA follows the public button scale');
  assert.ok(theme.includes('font-weight:700'),
    'the Sign in CTA uses the /auth action emphasis and underline');
  assert.ok(theme.includes("font-family:var(--font-sans,Inter,system-ui,sans-serif)"),
    'use the existing Inter typography instead of native font defaults');
  assert.ok(theme.includes('.amplify-input:-webkit-autofill'),
    'autofill must not introduce system yellow on themed inputs');
  assert.ok(theme.includes('-webkit-box-shadow:0 0 0 1000px #f5fde0 inset!important'),
    'autofill overlay must use opaque resolved homepage lime tint, not translucent fill');
  assert.ok(theme.includes('border:0!important'),
    'inputs stay actually borderless');
  assert.match(theme,
    /\.wsauth-shell\.ws-notion-auth :is\(\.amplify-input,\.amplify-select\):focus\s*\{[^}]*box-shadow:inset 0 -2px 0 var\(--ws-login-deep\)!important;/,
    'username and password focus must show the 2px /auth-style underline, not the old dark box outline');
  const passwordFocus = theme.match(
    /\.wsauth-shell\.ws-notion-auth \.amplify-passwordfield \.amplify-input:focus\s*\{([^{}]*)\}/,
  );
  assert.ok(passwordFocus && !passwordFocus[1].includes('box-shadow:none'),
    'password input must retain its own focus indicator if :focus-within is not painted');
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
  assert.ok(theme.includes('border-radius:13px'),
    'buttons and fields use 13px corners, while shared brand badge stays a pill');
  assert.ok(theme.includes('box-shadow:inset 0 -2px 0 var(--ws-login-deep)!important'),
    'focused credentials retain a clear but non-box-shaped keyboard focus indicator');
  assert.ok(theme.includes('[data-amplify-authenticator-select-mfa-type]'),
    'MFA flow is still styled and usable');
});

test('Option C borrows /auth compact card treatment without changing Cognito or hero copy', () => {
  // /auth is the design reference, but keep these regression checks scoped
  // to the /ws styles rather than coupling CI to an unrelated customer page.
  assert.ok(theme.includes('border-top:4px solid var(--ws-login-lime)'),
    '/ws card should echo the public auth page lime accent');
  assert.ok(theme.includes('box-shadow:0 14px 38px rgba(26,58,42,.08)'),
    'the login card adopts the subtle /auth shadow');
  assert.ok(theme.includes('.wsauth-shell.ws-notion-auth .wsauth-form'),
    'the visual card wraps the existing Cognito form');
  assert.ok(theme.includes('max-width:520px'),
    'card stays contained like the /auth page');
  assert.ok(theme.includes('border-radius:13px'),
    'form card and input boxes have the requested 13px corners');
  assert.ok(auth.includes("ctx.authStatus, ctx.route"),
    'route state stays inside the existing Amplify authenticator context');
  assert.ok(!auth.includes('RotatingHero'),
    'do not add public marketing headlines to the minimal staff login');
  assert.ok(auth.includes('<BrandBadge label="WECARE.DIGITAL" />'),
    'the transparent official icon + brand eyebrow stays a pill');
});

test('only Sign in uses right-aligned 200x46 CTA with 13px corners', () => {
  const block = theme.match(
    /\.wsauth-shell\.ws-notion-auth\[data-wsauth-signin='true'\] \.amplify-button\[data-variation='primary'\]\s*\{([^{}]*)\}/,
  );
  assert.ok(block, 'the compact CTA needs an explicit Cognito-route-scoped selector');
  for (const declaration of ['width:200px', 'max-width:100%', 'min-height:46px', 'margin-inline-start:auto', 'align-self:flex-end', 'border-radius:13px']) {
    assert.ok(block[1].includes(declaration), 'missing compact CTA declaration: ' + declaration);
  }
  assert.ok(!block[1].includes('background-color:'),
    'sign-in layout override must not conflict with the single public-lime CTA fill owner');
  const fields = theme.match(/\.wsauth-shell\.ws-notion-auth :is\(\.amplify-input,\.amplify-select\),[\s\S]*?padding-inline:17px;\s*\}/);
  assert.ok(fields && fields[0].includes('border-radius:13px!important'),
    'credential fields should use the same 13px corner scale');
  assert.ok(theme.includes("  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='link']"),
    'keep forgot-password separate from the primary action');
  assert.ok(theme.includes('background:var(--public-lime-tint,var(--ws-login-field))'),
    'keep the secondary action on the same /auth lime-tint surface');
});

test('public /auth buttons and staff /ws buttons share one visual interaction language', () => {
  const primary = theme.match(
    /\.wsauth-shell\.ws-notion-auth \.amplify-button\[data-variation='primary'\]\s*\{([^{}]*)\}/,
  );
  const secondary = theme.match(
    /\.wsauth-shell\.ws-notion-auth \.amplify-button\[data-variation='link'\]\s*\{([^{}]*)\}/,
  );
  assert.ok(primary && secondary, 'both Cognito action classes require visual styling');
  for (const [name, block] of [['primary', primary[1]], ['secondary', secondary[1]]]) {
    for (const fragment of [
      'border-radius:13px', 'font-weight:700', 'line-height:1.35',
      'text-decoration:underline', 'text-decoration-thickness:1.5px',
      'text-underline-offset:4px', 'touch-action:manipulation',
      '-webkit-tap-highlight-color:transparent', 'transition:background-color .18s ease',
    ]) {
      assert.ok(block.includes(fragment), name + ' button must share /auth design contract: ' + fragment);
    }
  }
  assert.ok(primary[1].includes('background-color:var(--public-lime-tint,var(--ws-login-field))'),
    'primary resting fill comes from the same public lime-tint token as customer auth');
  assert.ok(secondary[1].includes('background:var(--public-lime-tint,var(--ws-login-field))'),
    'secondary resting fill uses the same tint, not a gray system fill');
  for (const fragment of [
    'background-color:var(--public-brand-lime,var(--ws-login-lime))',
    'background:var(--public-brand-lime,var(--ws-login-lime))',
    'transform:translateY(-1px)',
    'box-shadow:var(--public-lift-shadow',
    'text-decoration-color:transparent',
  ]) {
    assert.ok(theme.includes(fragment), 'hover must match /auth interaction style: ' + fragment);
  }
  assert.ok(theme.includes(".amplify-button[data-variation='link'] {transition:none}"),
    'reduced-motion users must not get secondary button transitions');
  assert.ok(theme.includes('):hover:not(:disabled) {transform:none}'),
    'reduced-motion users must not get hover lift animation');
  assert.ok(theme.includes(".amplify-button[data-variation='link']:disabled"),
    'secondary buttons must have intentional disabled states');
  for (const kind of ['primary', 'link']) {
    const disabledRule = theme.match(new RegExp(
      String.raw`\\.wsauth-shell\\.ws-notion-auth \\.amplify-button\\[data-variation='${kind}'\\]:disabled\\s*\\{([^{}]*)\\}`,
    ));
    assert.ok(disabledRule && disabledRule[1].includes('cursor:not-allowed'),
      kind + ' disabled action must use not-allowed, never a misleading loading cursor');
    assert.ok(!disabledRule[1].includes('cursor:wait'),
      kind + ' disabled action must not imply a network request is processing');
  }
  assert.ok(theme.includes('outline:3px solid var(--public-brand-green,var(--ws-login-deep))'),
    'public auth palette is used for keyboard focus indicators');
  assert.ok(auth.includes("data-wsauth-signin={ route === 'signIn' ? 'true' : undefined }"),
    '200x46 right-aligned layout still applies only on actual Cognito signIn route');
});
