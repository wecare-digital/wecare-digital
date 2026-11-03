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

  /* Login matches the workspace without changing the Cognito Authenticator. */
  .wsauth-shell.ws-notion-auth {
    background:var(--ws-canvas);
  }
  .wsauth-shell.ws-notion-auth .wsauth-centre {
    display:grid;
    grid-template-columns:minmax(0,1fr) minmax(330px,420px);
    gap:clamp(32px,6vw,104px);
    align-items:center;
    width:100%;
    max-width:1030px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-intro {
    display:grid;
    justify-items:start;
    gap:17px;
    min-width:0;
  }
  .wsauth-shell.ws-notion-auth .wsauth-intro-kicker {
    font-size:12px;
    letter-spacing:.08em;
    font-weight:750;
    color:var(--ws-green);
    margin:0;
  }
  .wsauth-shell.ws-notion-auth .wsauth-intro h1 {
    font-size:clamp(38px,5vw,57px);
    line-height:1.12;
    letter-spacing:-.06em;
    font-weight:740;
    margin:0;
    max-width:520px;
    color:var(--ws-ink);
  }
  .wsauth-shell.ws-notion-auth .wsauth-intro-description {
    max-width:420px;
    font-size:16px;
    line-height:1.75;
    color:var(--ws-muted);
    margin:0;
  }
  .wsauth-shell.ws-notion-auth .wsauth-intro-line {
    width:46px;
    height:4px;
    background:var(--ws-green);
    border-radius:4px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-form-column {
    width:100%;
    display:grid;
    gap:13px;
    min-width:0;
  }
  .wsauth-shell.ws-notion-auth .wsauth-card {
    background:var(--ws-paper);
    border:1px solid var(--ws-hairline);
    border-radius:12px;
    box-shadow:0 12px 44px rgba(35,35,35,.055);
    padding:30px 28px 32px;
    overflow:hidden;
  }
  .wsauth-shell.ws-notion-auth .wsauth-brand-tile {
    background:#e9eee8;
    color:var(--ws-green);
    border-radius:8px;
  }
  .wsauth-shell.ws-notion-auth .wsauth-brand-name,
  .wsauth-shell.ws-notion-auth .amplify-heading {
    color:var(--ws-ink);
    letter-spacing:-.04em;
  }
  .wsauth-shell.ws-notion-auth .amplify-input,
  .wsauth-shell.ws-notion-auth .amplify-select {
    border-radius:8px;
    border-color:var(--ws-hairline);
    background:var(--ws-paper);
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary'] {
    background:var(--ws-green);
    color:#fff;
    border-radius:8px;
    min-height:46px;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='primary']:hover {
    background:#193e2b;
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='link'] {
    color:var(--ws-green);
  }
  .wsauth-shell.ws-notion-auth .amplify-button[data-variation='link']:hover {
    background:var(--ws-selected);
  }
  .wsauth-shell.ws-notion-auth .wsauth-note {
    font-size:12px;
    color:var(--ws-muted);
    line-height:1.55;
  }
  @media(max-width:780px) {
    .wsauth-shell.ws-notion-auth .wsauth-centre {
      grid-template-columns:minmax(0,1fr);
      max-width:430px;
      gap:0;
    }
    .wsauth-shell.ws-notion-auth .wsauth-intro {
      display:none;
    }
  }
  @media(max-width:480px) {
    .wsauth-shell.ws-notion-auth .wsauth-card {padding:22px 18px 25px}
    .ws-shell.ws-notion .ws-content {padding-top:22px}
  }
  @media(prefers-reduced-motion:reduce) {
    .ws-shell.ws-notion .ws-home-card {transition:none}
  }
  @media(forced-colors:active) {
    .ws-shell.ws-notion .ws-nav-link.active,
    .ws-shell.ws-notion .ws-bottom-link.active {border:1px solid Highlight}
    .wsauth-shell.ws-notion-auth .wsauth-card {border-color:CanvasText}
  }

  `}</style>
);

export default WsNotionTheme;
