/**
 * Shared visual system for every authenticated /ws page and its Cognito login.
 * All selectors are rooted in .ws-shell.ws-notion or .wsauth-shell.ws-notion-auth.
 * No business logic, payment pricing, global public styles, or auth state changes.
 */
import React from 'react';

const WsNotionTheme: React.FC = () => (
  <style jsx global>{`

  /* Workspace document tokens must NOT leak into the shared public header, share dock or footer on the /ws login. */
  .ws-shell.ws-notion {
    --ws-canvas:#fbfbfa;
    --ws-paper:#ffffff;
    --ws-sidebar:#f7f7f5;
    --ws-ink:#262626;
    --ws-muted:#787774;
    --ws-hairline:#e8e8e5;
    --ws-hover:#f0f0ee;
    --ws-green:#24533b;
    --ws-selected:#eaf0e7;
    --bg:var(--ws-paper);
    --bg-secondary:var(--ws-sidebar);
    --bg-hover:var(--ws-hover);
    --surface:var(--ws-paper);
    --text:var(--ws-ink);
    --text-muted:var(--ws-muted);
    --text-secondary:#666663;
    --border:var(--ws-hairline);
    --border-light:#f0f0ed;
    --border-dark:#d7d7d2;
    --accent:var(--ws-green);
    --accent-hover:#193d2c;
    --lime-tint:var(--ws-selected);
    --shadow-sm:0 1px 2px rgba(35,35,35,.035);
    --shadow-md:0 2px 9px rgba(35,35,35,.045);
    --shadow-lg:0 4px 15px rgba(35,35,35,.06);
    --shadow-xl:0 12px 36px rgba(35,35,35,.07);
    --radius-lg:10px;
    --radius-xl:11px;
    --radius-2xl:12px;
    color:var(--ws-ink);
    font-family:var(--font-sans,Inter,system-ui,sans-serif);
  }

  /* Persistent document-like workspace shell: one muted sidebar, one reading surface. */
  .ws-shell.ws-notion .ws-sidebar {
    background:var(--ws-sidebar);
    border-color:var(--ws-hairline);
  }
  .ws-shell.ws-notion .ws-brand-side {
    border-bottom:1px solid var(--ws-hairline);
    padding-bottom:17px;
    margin-bottom:13px;
  }
  .ws-shell.ws-notion .ws-brand-mark {
    background:#e7eee6;
    border-radius:8px;
  }
  .ws-shell.ws-notion .ws-brand-name {
    font-weight:750;
    letter-spacing:-.045em;
  }
  .ws-shell.ws-notion .ws-nav-link {
    color:#5e5d5a;
    font-size:13px;
    font-weight:550;
    border-radius:7px;
  }
  .ws-shell.ws-notion .ws-nav-link:hover {
    background:var(--ws-hover);
  }
  .ws-shell.ws-notion .ws-nav-link.active {
    background:#eaeae7;
    color:var(--ws-ink);
    font-weight:680;
  }
  .ws-shell.ws-notion .ws-nav-link.active .ws-nav-icon {
    color:var(--ws-green);
  }
  .ws-shell.ws-notion .ws-main {
    background:var(--ws-paper);
  }
  .ws-shell.ws-notion .ws-header {
    background:rgba(255,255,255,.97);
    border-bottom-color:var(--ws-hairline);
  }
  .ws-shell.ws-notion .ws-header-in {
    min-height:58px;
  }
  .ws-shell.ws-notion .ws-footer {
    border-color:var(--ws-hairline);
    background:var(--ws-paper);
  }
  .ws-shell.ws-notion .ws-bottomnav {
    background:var(--ws-paper);
    border-color:var(--ws-hairline);
  }
  .ws-shell.ws-notion .ws-bottom-link.active {
    color:var(--ws-green);
    background:#f5f7f3;
  }
  .ws-shell.ws-notion .ws-content {
    width:100%;
    max-width:1250px;
    margin:0 auto;
    padding-top:28px;
  }

  /* Same quiet title, eyebrow and supporting-copy scale on every /ws page. */
  .ws-shell.ws-notion :is(
    .ws-home-title,.ib-title,.cl-title,.wsc-title,.wsx-title,.ws-page-title
  ) {
    color:var(--ws-ink);
    font-size:clamp(26px,2.8vw,34px);
    font-weight:740;
    line-height:1.16;
    letter-spacing:-.045em;
  }
  .ws-shell.ws-notion :is(
    .ws-home-eyebrow,.wsc-eyebrow,.wsx-eyebrow,.ws-page-eyebrow,.ib-eyebrow,.cl-eyebrow
  ) {
    color:var(--ws-muted);
    font-size:11px;
    letter-spacing:.04em;
    font-weight:650;
    text-transform:none;
  }
  .ws-shell.ws-notion :is(.ws-home-sub,.wsc-sub,.wsx-sub,.ws-page-note) {
    color:var(--ws-muted);
    font-size:13px;
    line-height:1.65;
  }

  /* The home launchpad should read like a Notion page index, not marketing tiles. */
  .ws-shell.ws-notion .ws-home-grid {
    gap:10px;
  }
  .ws-shell.ws-notion .ws-home-card {
    background:var(--ws-paper);
    border-color:var(--ws-hairline);
    border-radius:9px;
    box-shadow:none;
    min-height:92px;
  }
  .ws-shell.ws-notion .ws-home-card:hover {
    background:#fafbf9;
    border-color:#d2d9d1;
    box-shadow:var(--shadow-sm);
  }
  .ws-shell.ws-notion .ws-home-card-icon {
    background:#edf1eb;
    color:var(--ws-green);
    border-radius:8px;
  }

  /* Consistent hairline cards for Collect, Vault, Settings, Commerce and dialogs. */
  .ws-shell.ws-notion :is(
    .wsc-preview,.cc-card,.vc-card,.vl-card,.ws-settings-card,
    .ws-settings-push,.pc-table,.pc-detail
  ) {
    background:var(--ws-paper);
    border-color:var(--ws-hairline);
    border-radius:10px;
    box-shadow:none;
  }
  .ws-shell.ws-notion :is(.ib-row,.cl-row,.vc-file,.vl-file) {
    border-color:var(--ws-hairline);
    border-radius:8px;
    box-shadow:none;
  }
  .ws-shell.ws-notion :is(.ib-row.active,.cl-row.sel,.vc-file.sel,.vl-file.sel) {
    background:var(--ws-selected);
    border-color:#cbd8c8;
  }
  .ws-shell.ws-notion :is(.ib-avatar,.cl-avatar) {
    background:#e9eee8;
    color:var(--ws-green);
  }
  .ws-shell.ws-notion :is(.ib-search,.cl-search) {
    border-color:var(--ws-hairline);
    border-radius:8px;
  }
  .ws-shell.ws-notion :is(.wsc-tabs,.wsx-tabs,.vt-switch) {
    background:var(--ws-sidebar);
    border-color:var(--ws-hairline);
    border-radius:9px;
  }
  .ws-shell.ws-notion :is(.wsc-tab.on,.vt-switch button.on) {
    background:var(--ws-paper);
    color:var(--ws-ink);
    border-radius:6px;
    box-shadow:var(--shadow-sm);
  }
  .ws-shell.ws-notion .wsx-tabs .wsx-tab.on {
    color:var(--ws-ink);
  }
  .ws-shell.ws-notion :is(.cc-btn,.vc-btn,.vl-btn,.cl-ghost,.ib-ghost,.ws-settings-signout) {
    border-radius:8px;
  }
  .ws-shell.ws-notion :is(
    .cc-field input,.vc-field input,.pc-toolbar input
  ) {
    border-radius:8px;
  }

  /* Keyboard and payment safety: do not override disabled/primary/destructive actions. */
  .ws-shell.ws-notion :is(a,button,input,textarea,select):focus-visible {
    outline:2px solid var(--ws-green);
    outline-offset:2px;
  }
  .ws-shell.ws-notion :is(input,textarea,select):not([type='checkbox']):not([type='radio']):focus-visible {
    border-color:var(--ws-green);
  }

  /* /ws login reproduces the supplied minimal form and reuses the exact
     homepage Header, PublicShare and Footer components. Everything below is
     scoped to the unauthenticated gate; the workspace pages remain unchanged. */
  .wsauth-shell.ws-notion-auth {
    --ws-login-lime:var(--public-brand-lime,#d1f470);
    --ws-login-lime-hover:var(--lime-hover,#c5e866);
    --ws-login-deep:var(--public-brand-green,#1a3a2a);
    --ws-login-ink:var(--public-body,#1a1a1a);
    --ws-login-field:var(--public-lime-tint,rgba(209,244,112,.22));
    --ws-login-muted:var(--public-muted,rgba(0,0,0,.54));
    width:100%;
    min-height:100vh;
    min-height:100dvh;
    background:#fff;
    color:var(--ws-login-ink);
    font-family:var(--font-sans,Inter,system-ui,sans-serif);
  }
  .wsauth-shell.ws-notion-auth * {box-sizing:border-box}
  /* The homepage header is fixed: 108px desktop, 96px on phones. */
  .wsauth-shell.ws-notion-auth .wsauth-site {
    display:flex;
    flex-direction:column;
    min-height:100vh;
    min-height:100dvh;
    padding-top:108px;
    background:#fff;
  }
  .wsauth-shell.ws-notion-auth .wsauth-login-main {
    width:100%;
    background:#fff;
    flex:1;
    min-height:calc(100vh - 108px);
    min-height:calc(100dvh - 108px);
    display:flex;
    align-items:center;
    justify-content:center;
    padding:64px 24px 76px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form {
    width:100%;
    max-width:440px;
    min-width:0;
  }
  .wsauth-shell.ws-notion-auth .wsauth-public-share {
    width:100%;
    max-width:var(--public-content-max,1300px);
    min-width:0;
    margin-inline:auto;
    padding:0 var(--public-page-gutter,24px) 48px;
    overflow-x:hidden;
    overflow-x:clip;
  }
  [dir='rtl'] [data-amplify-theme='ws-homepage-lime-auth'] {
    direction:rtl;
    unicode-bidi:isolate;
  }

  /* Reuse the homepage BrandBadge component as-is: its BrandMark is a
     transparent inline SVG and its Inter 14px/600 type is the public badge
     contract. Only position the badge here: no second icon/pill CSS owner. */
  .wsauth-shell.ws-notion-auth .wsauth-eyebrow {
    display:flex;
    align-items:center;
    justify-content:flex-start;
    width:100%;
    margin:0 0 26px;
  }

  /* Remove the previous card/marketing treatment, not just its outline. */
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator],
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator] [data-amplify-container] {
    max-width:none;
    width:100%;
  }
  .wsauth-shell.ws-notion-auth [data-amplify-router] {
    width:100%;
    background:transparent;
    border:0;
    border-radius:0;
    padding:0;
    box-shadow:none;
    overflow:visible;
  }
  .wsauth-shell.ws-notion-auth [data-amplify-form] {padding:0}
  /* Typography uses Home's canonical Inter ladder, rather than Amplify
     defaults: 22px card heading, 16px supporting labels and 17px CTA. */
  .wsauth-shell.ws-notion-auth .amplify-heading {
    color:var(--public-heading,var(--ws-login-ink));
    font-family:var(--font-sans,Inter,system-ui,sans-serif);
    font-size:var(--public-card-size,22px);
    font-weight:var(--public-card-weight,700);
    line-height:var(--public-card-leading,1.27);
    letter-spacing:var(--public-card-tracking,-.25px);
  }
  .wsauth-shell.ws-notion-auth .amplify-label {
    display:block;
    margin-bottom:9px;
    font-family:var(--font-sans,Inter,system-ui,sans-serif);
    font-size:var(--public-supporting-size,16px);
    font-weight:600;
    letter-spacing:var(--public-body-tracking,-.125px);
    color:var(--public-body,var(--ws-login-ink));
  }
  /* Truly borderless homepage-lime-tint fields, including password visibility.
     The ring exists only on focus, to preserve keyboard accessibility. */
  .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select),
  .wsauth-shell.ws-notion-auth .amplify-passwordfield .amplify-input {
    width:100%;
    min-height:56px;
    border:0!important;
    border-radius:14px!important;
    background:var(--ws-login-field)!important;
    box-shadow:none!important;
    color:var(--ws-login-ink)!important;
    font-family:var(--font-sans,Inter,system-ui,sans-serif)!important;
    font-size:var(--public-supporting-size,16px)!important;
    font-weight:var(--public-body-weight,400);
    letter-spacing:var(--public-body-tracking,-.125px);
    padding-inline:17px;
  }
  .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select)::placeholder {
    color:var(--public-muted,rgba(0,0,0,.54));
    opacity:1;
  }
  /* Chrome/Android autofill must not recolor the lime-tint field yellow.
     The inset fill is not a visible border; focus outline remains separate. */
  .wsauth-shell.ws-notion-auth .amplify-input:-webkit-autofill {
    -webkit-text-fill-color:var(--ws-login-ink)!important;
    -webkit-box-shadow:0 0 0 1000px var(--ws-login-field) inset!important;
  }
  .wsauth-shell.ws-notion-auth .amplify-field-group__control {
    background:var(--ws-login-field);
    border:0!important;
    border-radius:14px;
    box-shadow:none!important;
  }
  /* No hover border, border-color or shadow on username, password or the eye.
     Preserve focus outlines for keyboard input and validation errors. */
  .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select):hover,
  .wsauth-shell.ws-notion-auth .amplify-field-group__control:hover,
  .wsauth-shell.ws-notion-auth .amplify-passwordfield:hover .amplify-field-group__control,
  .wsauth-shell.ws-notion-auth .amplify-field-group__outer-end .amplify-button:hover:not(:disabled) {
    border:0!important;
    border-color:transparent!important;
    box-shadow:none!important;
    background:var(--ws-login-field)!important;
  }
  .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select):focus {
    border:0!important;
    outline:2px solid var(--ws-login-deep)!important;
    outline-offset:2px!important;
    box-shadow:none!important;
  }
  .wsauth-shell.ws-notion-auth .amplify-passwordfield .amplify-input:focus {
    outline:0!important;
  }
  .wsauth-shell.ws-notion-auth .amplify-passwordfield .amplify-field-group__control:focus-within {
    outline:2px solid var(--ws-login-deep);
    outline-offset:2px;
  }
  .wsauth-shell.ws-notion-auth .amplify-field-group__outer-end .amplify-button {
    display:inline-flex;
    align-items:center;
    justify-content:center;
    min-width:48px;
    min-height:56px;
    border:0!important;
    border-radius:0 14px 14px 0;
    color:var(--ws-login-ink);
    background:var(--ws-login-field);
  }
  .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select)[aria-invalid='true'] {
    outline:2px solid #b91c1c!important;
    outline-offset:2px!important;
  }
  .wsauth-shell.ws-notion-auth .amplify-field__error-message {
    color:#b91c1c;
    font-size:13px;
  }

  /* Lime sign-in CTA: Google's Material 3 login glyph, never a Next arrow. */
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary'] {
    gap:10px;
    width:100%;
    min-height:54px;
    display:flex;
    align-items:center;
    justify-content:center;
    border:0!important;
    border-radius:999px;
    background-color:var(--ws-login-lime);
    color:var(--ws-login-deep);
    box-shadow:none;
    font-family:var(--font-sans,Inter,system-ui,sans-serif);
    font-size:var(--public-cta-font-size,17px);
    font-weight:var(--public-cta-font-weight,600);
    letter-spacing:var(--public-body-tracking,-.125px);
    transition:background-color .16s ease;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']::before {
    content:'login';
    display:inline-block;
    font-family:'Material Symbols Rounded';
    font-size:23px;
    line-height:1;
    font-weight:400;
    font-style:normal;
    white-space:nowrap;
    letter-spacing:normal;
    text-transform:none;
    font-feature-settings:'liga';
    -webkit-font-feature-settings:'liga';
    font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:hover:not(:disabled) {
    background-color:var(--ws-login-lime-hover);
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:focus-visible {
    outline:3px solid var(--ws-login-deep);
    outline-offset:3px;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:active:not(:disabled) {
    background-color:#b8df56;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:disabled {
    opacity:.55;
    cursor:not-allowed;
  }
  /* Screenshot: the Forgot password action is a centered gray pill. */
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='link'] {
    display:inline-flex;
    width:max-content;
    max-width:100%;
    margin-inline:auto;
    min-height:44px;
    padding-inline:20px;
    border:0;
    border-radius:999px;
    background:var(--ws-login-field);
    color:var(--ws-login-deep);
    font-family:var(--font-sans,Inter,system-ui,sans-serif);
    font-size:var(--public-meta-size,14px);
    font-weight:600;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='link']:hover {
    background:var(--ws-login-field);
    text-decoration:underline;
    text-underline-offset:3px;
  }
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator] :is(a,button):focus-visible {
    outline:3px solid var(--ws-login-deep);
    outline-offset:3px;
  }

  /* MFA/radio choices must remain interactive in the same borderless form. */
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator-select-mfa-type] .amplify-radio {
    min-height:50px;
    display:flex;
    align-items:center;
    gap:12px;
    padding:12px 14px;
    border:0;
    border-radius:12px;
    background:var(--ws-login-field);
  }
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator-select-mfa-type] .amplify-radio:focus-within {
    outline:2px solid var(--ws-login-deep);
    outline-offset:2px;
  }
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator-select-mfa-type] .amplify-radio__button {
    --amplify-components-radio-button-color:var(--ws-login-deep);
    --amplify-components-radio-button-border-color:#74786f;
  }
  @media(max-width:767px) {
    .wsauth-shell.ws-notion-auth .wsauth-site {padding-top:96px}
    .wsauth-shell.ws-notion-auth .wsauth-login-main {
      min-height:calc(100vh - 96px);
      min-height:calc(100dvh - 96px);
      padding:38px 18px 54px;
    }
    .wsauth-shell.ws-notion-auth .wsauth-public-share {
      padding-inline:16px;
      padding-bottom:40px;
    }
  }
  @media(prefers-reduced-motion:reduce) {
    .ws-shell.ws-notion .ws-home-card {transition:none}
    .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary'] {transition:none}
  }
  @media(forced-colors:active) {
    .ws-shell.ws-notion .ws-nav-link.active,
    .ws-shell.ws-notion .ws-bottom-link.active {border:1px solid Highlight}
    .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select) {outline:1px solid CanvasText!important}
    .wsauth-shell.ws-notion-auth .wsauth-eyebrow {border:1px solid CanvasText}
    .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary'] {border:2px solid ButtonText!important}
  }

  `}</style>
);

export default WsNotionTheme;
