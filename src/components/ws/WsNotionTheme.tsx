/**
 * Shared visual system for every authenticated /ws page and its Cognito login.
 * All selectors are rooted in .ws-shell.ws-notion or .wsauth-shell.ws-notion-auth.
 * No business logic, payment pricing, global public styles, or auth state changes.
 */
import React from 'react';

const WsNotionTheme: React.FC = () => (
  <style jsx global>{`

  /* Scope every rule to /ws only. No public page or /workspace regression. */
  .ws-shell.ws-notion,
  .wsauth-shell.ws-notion-auth {
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

  /* Full homepage-inspired login design, isolated to the /ws Cognito gate.
     Lime is the action + hero fill. Dark green is legible type and focus,
     not the primary button fill. Public pages and /workspace are unaffected. */
  .wsauth-shell.ws-notion-auth {
    --ws-login-lime:var(--public-brand-lime,#d1f470);
    --ws-login-lime-hover:var(--lime-hover,#c5e866);
    --ws-login-deep:var(--public-brand-green,#1a3a2a);
    --ws-login-ink:#1a1a1a;
    --ws-login-muted:#646861;
    --ws-login-field:#f4f5f2;
    min-height:100vh;
    min-height:100dvh;
    width:100%;
    color:var(--ws-login-ink);
    background:#fff;
    font-family:var(--font-sans,Inter,system-ui,sans-serif);
  }
  .wsauth-shell.ws-notion-auth * {box-sizing:border-box}
  .wsauth-shell.ws-notion-auth .wsauth-symbol {
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
    font-variation-settings:'FILL' 0,'wght' 500,'GRAD' 0,'opsz' 24;
  }
  .wsauth-shell.ws-notion-auth .wsauth-layout {
    display:grid;
    grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr);
    width:100%;
    min-height:100vh;
    min-height:100dvh;
  }
  .wsauth-shell.ws-notion-auth .wsauth-story {
    min-width:0;
    display:flex;
    background:var(--ws-login-lime);
    padding:clamp(26px,4.5vw,72px);
    overflow:hidden;
  }
  .wsauth-shell.ws-notion-auth .wsauth-story-inner {
    min-height:100%;
    max-width:670px;
    margin:0 auto;
    display:flex;
    flex:1;
    flex-direction:column;
    justify-content:space-between;
    gap:32px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-public-home {
    display:inline-flex;
    width:max-content;
    max-width:100%;
    align-items:center;
    border-radius:12px;
    text-decoration:none;
  }
  .wsauth-shell.ws-notion-auth .wsauth-public-home:focus-visible,
  .wsauth-shell.ws-notion-auth :is(.wsauth-form-footer a,.wsauth-backsite):focus-visible {
    outline:3px solid var(--ws-login-deep);
    outline-offset:4px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-story-main {
    display:grid;
    align-content:center;
    justify-items:start;
    gap:21px;
    padding-block:12px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-story-kicker {
    display:inline-block;
    font-size:12px;
    font-weight:800;
    letter-spacing:.12em;
    color:var(--ws-login-deep);
  }
  .wsauth-shell.ws-notion-auth .wsauth-story-main h1 {
    font-size:clamp(45px,5.1vw,76px);
    line-height:1.02;
    font-weight:700;
    letter-spacing:-.065em;
    color:var(--ws-login-ink);
    margin:0;
  }
  .wsauth-shell.ws-notion-auth .wsauth-story-main h1 em {
    font-style:normal;
    color:var(--ws-login-deep);
  }
  .wsauth-shell.ws-notion-auth .wsauth-story-main > p {
    font-size:clamp(16px,1.5vw,19px);
    font-weight:400;
    line-height:1.55;
    margin:0;
    max-width:495px;
    color:#2b3327;
  }
  .wsauth-shell.ws-notion-auth .wsauth-workbook {
    display:grid;
    gap:18px;
    max-width:520px;
    width:100%;
    margin-top:18px;
    padding:20px;
    background:rgba(255,255,255,.94);
    border-radius:22px;
    box-shadow:0 18px 54px rgba(26,58,42,.15);
    transform:rotate(-1deg);
  }
  .wsauth-shell.ws-notion-auth .wsauth-workbook-head {
    display:flex;
    align-items:center;
    gap:12px;
    color:#73776c;
    font-size:11px;
    font-weight:800;
    letter-spacing:.1em;
  }
  .wsauth-shell.ws-notion-auth .wsauth-workbook-head > .wsauth-symbol {margin-inline-start:auto;color:var(--ws-login-deep)}
  .wsauth-shell.ws-notion-auth .wsauth-workbook-window {
    display:inline-flex;
    gap:4px;
    align-items:center;
  }
  .wsauth-shell.ws-notion-auth .wsauth-workbook-window span {
    display:block;
    width:7px;
    height:7px;
    border-radius:50%;
    background:#d3d9d1;
  }
  .wsauth-shell.ws-notion-auth .wsauth-workbook-window span:first-child {background:var(--ws-login-lime)}
  .wsauth-shell.ws-notion-auth .wsauth-workbook-grid {
    display:grid;
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:10px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-module {
    display:flex;
    align-items:center;
    min-width:0;
    gap:10px;
    padding:16px 12px;
    background:var(--ws-login-field);
    border-radius:12px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-module-icon {
    display:flex;
    flex:0 0 38px;
    align-items:center;
    justify-content:center;
    width:38px;
    height:38px;
    border-radius:10px;
    background:#e4edca;
    color:var(--ws-login-deep);
  }
  .wsauth-shell.ws-notion-auth .wsauth-module-copy {
    min-width:0;
    display:flex;
    flex:1 1 auto;
    flex-direction:column;
    gap:2px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-module-copy strong {
    font-size:13px;
    color:var(--ws-login-ink);
  }
  .wsauth-shell.ws-notion-auth .wsauth-module-copy small {
    font-size:11px;
    color:var(--ws-login-muted);
    line-height:1.25;
  }
  .wsauth-shell.ws-notion-auth .wsauth-module-chevron {flex:0 0 auto;font-size:18px;color:#888f83}
  .wsauth-shell.ws-notion-auth .wsauth-story-foot {
    font-size:12px;
    font-weight:600;
    color:#42533a;
  }

  /* The sign-in panel is a deliberate whitespace-first form, not a bordered card. */
  .wsauth-shell.ws-notion-auth .wsauth-signin-side {
    min-width:0;
    min-height:100vh;
    min-height:100dvh;
    padding:clamp(32px,5vw,76px);
    display:flex;
    flex-direction:column;
    justify-content:center;
    align-items:center;
    gap:30px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-frame {
    width:100%;
    max-width:430px;
    display:grid;
    gap:27px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-header {display:grid;gap:11px}
  .wsauth-shell.ws-notion-auth .wsauth-form-kicker {
    width:max-content;
    max-width:100%;
    margin:0 0 7px;
    padding:7px 11px;
    background:#eff7d8;
    border-radius:999px;
    font-size:11px;
    font-weight:800;
    letter-spacing:.1em;
    color:var(--ws-login-deep);
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-header h2 {
    font-size:clamp(34px,3.1vw,46px);
    line-height:1.1;
    letter-spacing:-.055em;
    font-weight:700;
    color:var(--ws-login-ink);
    margin:0;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-header > p:last-child {
    font-size:15px;
    line-height:1.55;
    margin:0;
    color:var(--ws-login-muted);
  }
  .wsauth-shell.ws-notion-auth .wsauth-card {
    border:0;
    padding:0;
    margin:0;
    width:100%;
    background:transparent;
    border-radius:0;
    box-shadow:none;
    overflow:visible;
  }
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator],
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator] [data-amplify-container] {
    width:100%;
    max-width:none;
  }
  .wsauth-shell.ws-notion-auth [data-amplify-router] {
    border:0;
    background:transparent;
    box-shadow:none;
    padding:0;
    border-radius:0;
  }
  .wsauth-shell.ws-notion-auth [data-amplify-form] {padding:0}
  .wsauth-shell.ws-notion-auth .wsauth-auth-badge {
    display:inline-flex;
    align-items:center;
    gap:7px;
    margin:0 0 14px;
    font-size:11px;
    font-weight:800;
    letter-spacing:.095em;
    color:var(--ws-login-deep);
  }
  .wsauth-shell.ws-notion-auth .wsauth-auth-badge .wsauth-symbol {font-size:19px}
  .wsauth-shell.ws-notion-auth .amplify-heading {
    color:var(--ws-login-ink);
    font-size:20px;
    line-height:1.3;
    font-weight:700;
    letter-spacing:-.03em;
  }
  .wsauth-shell.ws-notion-auth .amplify-label {
    display:block;
    margin-bottom:7px;
    font-size:13px;
    font-weight:650;
    color:var(--ws-login-ink);
  }

  /* BORDERLESS means border:0 — not a pale border. On focus the accessible
     ring appears outside the field; at rest the whole input has no stroke. */
  .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select),
  .wsauth-shell.ws-notion-auth .amplify-passwordfield .amplify-input {
    width:100%;
    min-height:56px;
    border:0!important;
    border-radius:13px!important;
    box-shadow:none!important;
    background:var(--ws-login-field)!important;
    color:var(--ws-login-ink)!important;
    font-family:inherit;
    font-size:16px!important;
    padding-inline:16px;
  }
  .wsauth-shell.ws-notion-auth .amplify-field-group__control {
    border:0!important;
    box-shadow:none!important;
    border-radius:13px;
    background:var(--ws-login-field);
  }
  .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select):focus {
    outline:2px solid var(--ws-login-deep)!important;
    outline-offset:2px!important;
    border:0!important;
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
    background:var(--ws-login-field);
    border:0!important;
    border-radius:0 13px 13px 0;
    color:var(--ws-login-ink);
    min-width:46px;
  }
  .wsauth-shell.ws-notion-auth :is(.amplify-input,.amplify-select)[aria-invalid='true'] {
    outline:2px solid #b91c1c!important;
    outline-offset:1px;
  }
  .wsauth-shell.ws-notion-auth .amplify-field__error-message {color:#b91c1c;font-size:13px}

  /* ONE primary CTA visual owner. Brand lime, dark readable label, Material 3 arrow. */
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary'] {
    display:flex;
    align-items:center;
    justify-content:center;
    gap:9px;
    width:100%;
    min-height:54px;
    border:0!important;
    border-radius:13px;
    background-color:var(--ws-login-lime);
    color:var(--ws-login-deep);
    font-size:16px;
    font-weight:750;
    box-shadow:none;
    transition:background-color .16s ease,transform .16s ease;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']::after {
    content:'arrow_forward';
    font-family:'Material Symbols Rounded';
    font-size:22px;
    line-height:1;
    font-weight:400;
    letter-spacing:normal;
    text-transform:none;
    font-feature-settings:'liga';
    font-variation-settings:'FILL' 0,'wght' 500,'GRAD' 0,'opsz' 24;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:hover:not(:disabled) {
    background-color:var(--ws-login-lime-hover);
    transform:translateY(-1px);
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:focus-visible {
    outline:3px solid var(--ws-login-deep);
    outline-offset:3px;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:active:not(:disabled) {
    background-color:#b8df56;
    transform:translateY(0);
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:disabled {
    opacity:.55;
    cursor:not-allowed;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='link'] {
    color:var(--ws-login-deep);
    min-height:44px;
    font-size:13px;
    font-weight:650;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='link']:hover {
    color:var(--ws-login-ink);
    background:#f0fad5;
  }
  .wsauth-shell.ws-notion-auth [data-amplify-authenticator] :is(a,button):focus-visible {
    outline:3px solid var(--ws-login-deep);
    outline-offset:3px;
  }

  /* Preserve Cognito's real MFA controls in the new borderless design. */
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

  /* Real, reachable site policies, not invented consent text. */
  .wsauth-shell.ws-notion-auth .wsauth-form-footer {
    border-top:1px solid #e5e7eb;
    padding-top:20px;
    display:grid;
    justify-items:start;
    gap:10px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-footer > p {
    margin:0;
    color:var(--ws-login-muted);
    font-size:12px;
    line-height:1.5;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-footer nav {
    display:flex;
    align-items:center;
    flex-wrap:wrap;
    gap:10px;
    color:#8b8d87;
    font-size:13px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-footer a {
    text-decoration:underline;
    text-decoration-color:#a8c85b;
    text-underline-offset:4px;
    color:var(--ws-login-deep);
    font-weight:600;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-footer a:hover {
    text-decoration-color:var(--ws-login-deep);
  }
  .wsauth-shell.ws-notion-auth .wsauth-backsite {
    display:inline-flex;
    align-items:center;
    gap:6px;
    max-width:430px;
    width:100%;
    color:var(--ws-login-muted);
    font-size:13px;
    font-weight:600;
    text-decoration:none;
  }
  .wsauth-shell.ws-notion-auth .wsauth-backsite:hover {color:var(--ws-login-deep)}
  .wsauth-shell.ws-notion-auth .wsauth-backsite .wsauth-symbol {font-size:17px}

  @media(max-width:1060px) {
    .wsauth-shell.ws-notion-auth .wsauth-story {padding:34px}
    .wsauth-shell.ws-notion-auth .wsauth-signin-side {padding:36px}
    .wsauth-shell.ws-notion-auth .wsauth-workbook {padding:15px}
    .wsauth-shell.ws-notion-auth .wsauth-module {padding:12px 9px;gap:7px}
    .wsauth-shell.ws-notion-auth .wsauth-module-chevron {display:none}
  }
  @media(max-width:780px) {
    .wsauth-shell.ws-notion-auth .wsauth-layout {
      grid-template-columns:minmax(0,1fr);
      min-height:100vh;
      min-height:100dvh;
    }
    .wsauth-shell.ws-notion-auth .wsauth-story {
      min-height:0;
      padding:max(22px,env(safe-area-inset-top,0px)) 24px 26px;
    }
    .wsauth-shell.ws-notion-auth .wsauth-story-inner {gap:22px}
    .wsauth-shell.ws-notion-auth .wsauth-story-main {gap:10px;padding:0}
    .wsauth-shell.ws-notion-auth .wsauth-story-main h1 {
      font-size:clamp(27px,6.5vw,39px);
      letter-spacing:-.055em;
    }
    .wsauth-shell.ws-notion-auth .wsauth-story-main > p {font-size:14px;max-width:390px}
    .wsauth-shell.ws-notion-auth .wsauth-workbook,
    .wsauth-shell.ws-notion-auth .wsauth-story-foot {display:none}
    .wsauth-shell.ws-notion-auth .wsauth-signin-side {
      justify-content:start;
      min-height:0;
      padding:35px 24px max(40px,env(safe-area-inset-bottom,0px));
      gap:26px;
    }
    .wsauth-shell.ws-notion-auth .wsauth-form-frame {gap:25px}
  }
  @media(max-width:420px) {
    .wsauth-shell.ws-notion-auth .wsauth-story {padding-inline:18px}
    .wsauth-shell.ws-notion-auth .wsauth-signin-side {padding-inline:18px}
    .wsauth-shell.ws-notion-auth .wsauth-form-header h2 {font-size:34px}
  }
  @media(prefers-reduced-motion:reduce) {
    .ws-shell.ws-notion .ws-home-card {transition:none}
    .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary'] {transition:none}
    .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:hover:not(:disabled),
    .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:active:not(:disabled) {transform:none}
  }
  @media(forced-colors:active) {
    .ws-shell.ws-notion .ws-nav-link.active,
    .ws-shell.ws-notion .ws-bottom-link.active {border:1px solid Highlight}
    .wsauth-shell.ws-notion-auth .wsauth-card {border-color:CanvasText}
  }

  `}</style>
);

export default WsNotionTheme;
