/**
 * Navigation — a short sidebar, and everything else behind the gear.
 *
 * THE GOVERNING RULE
 * ------------------
 *   Sidebar = streams you work in daily.  Gear = things you configure once.
 *
 * The sidebar held 11 top-level sections and 88 destinations, of which **30 were
 * WhatsApp sub-pages** — 34% of the whole navigation in one branch. Nothing was
 * broken; it was simply a settings tree wearing a sidebar's clothes, and the
 * things an operator touches hourly sat at the same level as "Flow Publish
 * Checklist".
 *
 * NOTHING IS UNREACHABLE. `getAllNavItems()` returns the sidebar AND the settings
 * tree, and that is the single function the command palette is built from. So
 * every destination that existed before is still findable by name with Ctrl+K.
 * That property is load-bearing rather than incidental: 21 of the 88 paths have no
 * link anywhere else in the app, so if the palette missed the settings tree this
 * change would strand them. There is a test on exactly that.
 *
 * TWO THINGS HAD TO LAND FIRST, and did:
 *   - The palette used to search its own hardcoded 14 entries and locked the
 *     renderer on keystroke. Fixed before this, because this change deletes the
 *     sidebar search box that was doing the job.
 *   - Fifteen routes rendered no shell at all. Wrapped before this, because
 *     without a sidebar they would have been dead ends.
 *
 * WHY Calls IS NOT HERE AS A PAGE: it is `/workspace/engage/inbox?channel=voice`. `dm/calls`
 * read the same canonical MessagesTable the inbox already reads, and the inbox
 * already renders voice with its own badge and an audio player. Call
 * *configuration* is under the gear.
 */

export interface NavSubItem {
  path: string;
  label: string;
  icon?: string;
  badge?: string;
  children?: NavSubItem[];
}

export interface NavItem {
  path: string;
  label: string;
  icon: string;
  badge?: string;
  sectionLabel?: string;
  children?: NavSubItem[];
}

/** A named group in the settings tree the gear opens. */
interface SettingsGroup {
  id: string;
  label: string;
  icon: string;
  /** One line saying what lives here, so the group is scannable. */
  hint: string;
  items: NavSubItem[];
  /**
   * An in-panel surface the gear renders inline instead of navigating to a route.
   * Used by the account group for Sign-in & MFA (FEAT-003): TotpSetup needs the
   * signed-in user's own token, so it mounts inside the gear rather than at a URL.
   * It is NOT a route and NOT part of getAllNavItems()/the command palette.
   */
  mfaPanel?: { id: string; label: string };
}

// ---------------------------------------------------------------------------
// THE SIDEBAR — daily streams only
// ---------------------------------------------------------------------------
/**
 * FLAT SIDEBAR (workspace redesign). The sidebar renders only top-level operating areas;
 * there is no expand/collapse tree. `Layout.tsx` reads `item.path`, `item.label` and
 * `item.icon` from each row.
 *
 * WHY `children` STILL EXISTS ON SOME ROWS
 * ----------------------------------------
 * Children are a deep-link / command-palette index, not a second sidebar level.
 * `getAllNavItems()` walks them so canonical sub-modes stay findable by name in Ctrl+K.
 * Commerce and other multi-mode workspaces may therefore keep children even though the
 * sidebar itself stays flat. Vault now belongs to Pay & Flow, while Service retains Contribute;
 * Flow-backed service items remain intentionally absent until they are deliberately added back. `isNavItemActive` matches on the row's own base path.
 */
export const navigationConfig: NavItem[] = [
  {
    // Workspace Home is the global launchpad and a first-class search destination.
    path: '/workspace',
    label: 'Home',
    icon: 'home',
  },
  {
    // Canonical daily communication workspace. Channels are filters/capabilities inside
    // Inbox/Manage, not separate top-level destinations.
    path: '/workspace/communications',
    label: 'Communications',
    icon: 'message',
    children: [
      { path: '/workspace/communications?view=inbox', label: 'Inbox' },
      { path: '/workspace/communications?view=manage', label: 'Manage communications' },
    ],
  },
  {
    path: '/workspace/customers',
    label: 'Customers',
    icon: 'contacts',
  },
  {
    // Commerce is one operational workspace with exactly two modes.
    path: '/workspace/commerce',
    label: 'Commerce',
    icon: 'store',
    children: [
      { path: '/workspace/commerce?view=orders', label: 'Orders' },
      { path: '/workspace/commerce?view=catalog', label: 'Catalog' },
    ],
  },
  {
    // Pay & Flow owns staff money requests and secure Vault delivery.
    path: '/workspace/payments',
    label: 'Payments',
    icon: 'payment',
    children: [
      { path: '/workspace/collect', label: 'Collect · custom invoices' },
      { path: '/workspace/vault', label: 'Vault · private files' },
      { path: '/workspace/payments?view=defaults', label: 'Invoice items (29)' },
      { path: '/workspace/payments?view=timing', label: 'Access Vault delay' },
      { path: '/workspace/payments?view=ledger', label: 'Ledger' },
    ],
  },
  {
    // Vault has moved to Pay & Flow. Keep other service capabilities in Service.
    path: '/workspace/service',
    label: 'Service',
    icon: 'order',
    children: [
      { path: '/workspace/service?view=contribute', label: 'Contribute' },
    ],
  },
  {
    path: '/workspace/platform',
    label: 'Platform',
    icon: 'dashboard',
    children: [
      { path: '/workspace/platform?view=system-architecture', label: 'Architecture snapshot' },
      { path: '/workspace/platform?view=lambda-functions', label: 'Lambda inventory' },
      { path: '/workspace/platform?view=code-repo', label: 'Code Repo' },
      { path: '/workspace/platform?view=wa-graph-tools', label: 'WA Graph Tools' },
      { path: '/workspace/platform?view=cors-settings', label: 'CORS Settings' },
      { path: '/workspace/platform?view=design-reference', label: 'Design Reference' },
    ],
  },
];

// ---------------------------------------------------------------------------
// THE GEAR — everything configured rather than worked in
// ---------------------------------------------------------------------------
export const settingsConfig: SettingsGroup[] = [
  {
    id: 'account',
    label: 'Your account',
    icon: 'access',
    hint: 'Sign-in and second factors',
    // FEAT-003: Sign-in & MFA moved OUT of the routes tree. It was /workspace/access/security,
    // a standalone route and the first row of this group; the TotpSetup surface now renders
    // INSIDE the gear panel (SettingsGear) as an in-panel view, because the gear is the one
    // surface that can mount TotpSetup with the SIGNED-IN user's own access token (Cognito's
    // AssociateSoftwareToken does not evaluate IAM, so there is no admin path). It is declared
    // on `mfaPanel` below rather than as a `items[]` route, so getAllNavItems() / the command
    // palette (which index real URLs only) never point at a missing file, while the gear still
    // leads with it.
    mfaPanel: { id: 'mfa', label: 'Sign-in & MFA' },
    items: [
      // '/workspace/access' ("Access") was a second row here. It is the sign-in landing,
      // and for a signed-in user - the only person who can open this gear - it does
      // nothing but router.replace to /workspace/engage/inbox (access/index.tsx), which is
      // the workspace landing. A row labelled Access that lands on the inbox is a promise
      // the page does not keep. The PAGE stays: it is where "Sign in" links go.
    ],
  },
  {
    id: 'whatsapp',
    label: 'WhatsApp',
    icon: 'whatsapp',
    hint: 'Business identity, messaging, Flows and operations',
    items: [
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=waba', label: 'WABA Dashboard' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=embedded-signup', label: 'Connect WABA' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=connected-accounts', label: 'Connected Accounts' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=my-account', label: 'My WhatsApp Account' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=profile', label: 'Business Profile' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=webhooks', label: 'Webhooks' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=bsuid', label: 'BSUID & Usernames' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=migration', label: 'WABA Migration' },
      { path: '/workspace/communications?view=manage&section=whatsapp', label: 'WhatsApp Management' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=send-test', label: 'Send Test' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=campaign', label: 'WhatsApp Campaign' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=auto-response', label: 'Auto Response' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=conversions-api', label: 'Conversions API (CTWA)' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=ctwa-ads', label: 'Ads to WhatsApp (CTWA)' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=templates', label: 'WhatsApp Templates' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=template-builder', label: 'Create WhatsApp Template' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=catalog-builder', label: 'Catalog & Flow Mapping' },
      { path: '/workspace/communications?view=manage&section=flows', label: 'Flow Hub' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=flows', label: 'WhatsApp Flows' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=flow-publish', label: 'Flow Publish' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=groups', label: 'Groups' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=calling', label: 'Calling' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=cost-controls', label: 'Cost Controls' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=scripts', label: 'Scripts' },
    ],
  },
  {
    id: 'channels',
    label: 'Other channels',
    icon: 'message',
    hint: 'SMS, RCS, Email, Voice, Push',
    items: [
      // The old /workspace/engage parent was a redirect-only alias and has been
      // removed. Communications and active channel pages own these controls.
      { path: '/workspace/communications?view=manage&section=sms', label: 'SMS' },
      { path: '/workspace/communications?view=manage&section=rcs', label: 'RCS' },
      { path: '/workspace/communications?view=manage&section=email', label: 'Email' },
      { path: '/workspace/communications?view=manage&section=push', label: 'Push' },
      { path: '/workspace/communications?view=manage&section=voice', label: 'Voice (outbound)' },
      { path: '/workspace/engage/channels?tab=voice-in', label: 'Call History' },
    ],
  },
  {
    id: 'messaging-tools',
    label: 'Messaging tools',
    icon: 'settings',
    hint: 'Automation, content, analytics, cost',
    items: [
      // Automation, content and analytics are tabs under the canonical
      // Communications Manage page, not standalone legacy Engage pages.
      { path: '/workspace/communications?view=manage&section=automation', label: 'Automation' },
      { path: '/workspace/communications?view=manage&section=templates', label: 'Content Library' },
      { path: '/workspace/communications?view=manage&section=analytics', label: 'Analytics' },
      { path: '/workspace/communications?view=manage&section=usage', label: 'Cost & Usage' },
      { path: '/workspace/communications?view=manage&section=search', label: 'Message Search' },
      { path: '/workspace/communications?view=manage&section=docs', label: 'Docs Scraper' },
      // Short Links is inside Communications > Manage. The retired /workspace/link
      // alias no longer exists and must not reappear in menu entries.
      { path: '/workspace/communications?view=manage&section=links', label: 'Short Links' },
    ],
  },
  {
    id: 'modules',
    label: 'Modules',
    icon: 'dashboard',
    hint: 'Growth and Commerce — read-only, behind flags',
    items: [
      // Flag-gated and currently OFF. Listed anyway: the whole point of
      // `getAllNavItems()` is that nothing is unreachable, and a flagged-off page that
      // explains WHY it is off is more use than a 404.
      //
      // '/growth' sat beside Commerce until 2026-09-25 and was removed with its page on
      // owner instruction. Commerce is the same shape and stays.
      { path: '/workspace/commerce', label: 'Commerce' },
    ],
  },
  // #956 (Rebuild Content as one publishing workspace) retired standalone SEO from
  // navigation: the gear 'seo' group's rows all pointed at /workspace/seo and
  // /workspace/seo?tab=tools|blog|pages. These obsolete redirect-only routes
  // have been deleted. SEO now lives in the Content workspace
  // (/workspace/content?view=seo&area=tools|pages), which the primary Content sidebar
  // section already exposes and which the command palette (getAllNavItems) already
  // indexes, so the gear group is removed rather than repointed.
  // #957 (make Platform a canonical workspace) added a first-class primary Platform
  // sidebar section and re-pointed every Platform deep-link to the identical
  // /workspace/platform?view=... paths. The gear 'platform' settings group's six rows
  // (Architecture snapshot, Lambda Functions, Code Repo, WA Graph
  // Tools, CORS Settings, Design Reference) therefore became exact duplicates of the
  // primary section, which surfaced as two 'CORS Settings' entries in getAllNavItems()
  // and the command palette. Its "infrastructure reachability via the palette" purpose
  // is now served by the first-class primary Platform sidebar section (and the palette
  // built from it), so the gear group is removed to de-duplicate those destinations.
];



/**
 * Every destination, sidebar AND settings.
 *
 * This is the one function the command palette is built from, so anything missing
 * here becomes genuinely unreachable once the sidebar is short. `getAllNavItems`
 * therefore walks both trees, and a test asserts the settings paths are present.
 */
const contextualRoutes: { path: string; label: string; parent: string }[] = [
  // Search shortcuts choose a type in the same Payments workspace. They are
  // intentionally absent from visible menu children: the owner wants one dropdown.
  { path: '/workspace/collect', label: 'Collect', parent: 'Payments' },
  { path: '/workspace/vault', label: 'Vault', parent: 'Payments' },
  { path: '/workspace/payments?view=contribute', label: 'Contribute', parent: 'Payments' },
  { path: '/workspace/content', label: 'Publishing', parent: 'Contextual workflows' },
  { path: '/workspace/content?view=blog', label: 'Blog', parent: 'Publishing' },
  { path: '/workspace/content?view=seo&area=tools', label: 'SEO Tools', parent: 'Publishing' },
  { path: '/workspace/content?view=seo&area=pages', label: 'SEO Pages', parent: 'Publishing' },
  { path: '/workspace/automation', label: 'Automation & AI', parent: 'Contextual workflows' },
  { path: '/workspace/automation?view=agent', label: 'Legacy assistant retired', parent: 'Automation & AI' },
  { path: '/workspace/automation?view=rules', label: 'Rules', parent: 'Automation & AI' },
  { path: '/workspace/automation?view=schedules', label: 'Schedules', parent: 'Automation & AI' },
  { path: '/workspace/automation?view=knowledge', label: 'Knowledge', parent: 'Automation & AI' },
];

export function getAllNavItems (): { path: string; label: string; parent?: string }[] {
  const items: { path: string; label: string; parent?: string }[] = [];
  const traverse = ( navItems: ( NavItem | NavSubItem )[], parentLabel?: string ) => {
    for ( const item of navItems )
    {
      items.push( { path: item.path, label: item.label, parent: parentLabel } );
      if ( 'children' in item && item.children )
      {
        traverse( item.children, item.label );
      }
    }
  };
  traverse( navigationConfig );
  for ( const group of settingsConfig )
  {
    traverse( group.items, group.label );
  }
  for ( const item of contextualRoutes )
  {
    if ( !items.some( ( existing ) => existing.path === item.path ) ) items.push( item );
  }
  return items;
}





