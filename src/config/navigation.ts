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
export interface SettingsGroup {
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
 * FLAT SIDEBAR (workspace redesign). Eight single-level streams, in the order the
 * redesign spec fixes: Messages, Contacts, Commerce, Payments, Service, Links, Tasks,
 * SEO. The sidebar renders ONLY the top level — there is no expand/collapse tree any
 * more — so `Layout.tsx` reads `item.path`, `item.label` and `item.icon` and nothing
 * else from each row.
 *
 * WHY `children` STILL EXISTS ON SOME ROWS
 * ----------------------------------------
 * The children are NOT a sidebar tree. They are the deep-link / command-palette index:
 * `getAllNavItems()` walks them so every destination that used to be a sidebar row (and
 * has no other home) stays findable by name in Ctrl+K and keeps resolving to a real
 * page. The dense sections (Service, SEO, Commerce) collapse into one page with in-page
 * tabs, and these child entries are how the palette reaches each tab's canonical path.
 * `isNavItemActive` matches on the row's own base path, so a child never renders a
 * second visible level. BottomNav takes the first four rows (Messages, Contacts,
 * Commerce, Payments) — all thumb-reachable daily streams.
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
    // Canonical Payments workspace: Collect for money-moving initiation, Ledger for read/audit.
    path: '/workspace/payments',
    label: 'Payments',
    icon: 'payment',
    children: [
      { path: '/workspace/payments?view=collect', label: 'Collect' },
      { path: '/workspace/payments?view=invoices', label: 'Invoices' },
      { path: '/workspace/payments?view=activity', label: 'Activity' },
    ],
  },
  {
    // Service is one workspace. Requests are the operational queue; customer-facing
    // submit/track/amend steps and service tools are contextual deep-links, not primary tabs.
    path: '/workspace/service',
    label: 'Service',
    icon: 'order',
    children: [
      { path: '/workspace/service?view=requests', label: 'Requests' },
      { path: '/workspace/service?view=requests&action=submit', label: 'Submit Request' },
      { path: '/workspace/service?view=requests&action=track', label: 'Track Request' },
      { path: '/workspace/service?view=requests&action=amend', label: 'Amend Request' },
      { path: '/workspace/service?view=appointments', label: 'Appointments' },
      { path: '/workspace/service?view=appointments&action=rx-slots', label: 'RX Slots' },
      { path: '/workspace/service?view=documents', label: 'Documents' },
      { path: '/workspace/service?view=documents&action=secure-files', label: 'Secure Files' },
      { path: '/workspace/service?view=requests&action=enterprise', label: 'Enterprise Cases' },
      { path: '/workspace/service?view=requests&action=reviews', label: 'Reviews' },
      { path: '/workspace/service?view=requests&action=faq', label: 'FAQ' },
    ],
  },
  {
    // One content workspace. Blog Studio and production stage URLs remain contextual deep links
    // because those jobs carry their own record/stage parameters; they are not primary apps.
    path: '/workspace/content',
    label: 'Content',
    icon: 'search',
    children: [
      { path: '/workspace/content?view=blog', label: 'Blog' },
      { path: '/workspace/seo/blog-studio', label: 'Blog Studio' },
      { path: '/workspace/content?view=production', label: 'Production' },
      { path: '/workspace/seo/blog-production?tab=review', label: 'Source review' },
      { path: '/workspace/seo/blog-production?tab=qa', label: 'QA review' },
      { path: '/workspace/seo/blog-production?tab=publish', label: 'Publish queue' },
      { path: '/workspace/content?view=seo&area=tools', label: 'SEO Tools' },
      { path: '/workspace/content?view=seo&area=pages', label: 'SEO Pages' },
      { path: '/workspace/content?view=links', label: 'Short links' },
    ],
  },
  {
    path: '/workspace/automation',
    label: 'Automation & AI',
    icon: 'settings',
    children: [
      { path: '/workspace/automation?view=agent', label: 'Staff agent' },
      { path: '/workspace/automation?view=rules', label: 'Rules' },
      { path: '/workspace/automation?view=schedules', label: 'Schedules' },
      { path: '/workspace/automation?view=knowledge', label: 'Knowledge' },
    ],
  },
  {
    path: '/workspace/task',
    label: 'Tasks',
    icon: 'checklist',
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
    // leads with it. Navigation.test / PagesConsolidation assert exactly this relocation.
    mfaPanel: { id: 'mfa', label: 'Sign-in & MFA' },
    items: [
      // Internal Agent moved here from the Platform group: with the flat sidebar, the
      // account menu / gear is the ONE place that holds true config, and the redesign
      // spec names exactly two settings rows — Sign-in & MFA then Internal Agent. It
      // configures the operator's own admin helper (distinct from the customer-facing
      // WhatsApp AI Agent under Messaging tools).
      { path: '/workspace/settings/internal-agent', label: 'Internal Agent configuration' },
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
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=lists', label: 'Interactive Lists' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=auto-response', label: 'Auto Response' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=conversions-api', label: 'Conversions API (CTWA)' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=ctwa-ads', label: 'Ads to WhatsApp (CTWA)' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=tech-partner', label: 'Tech Partner Readiness' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=templates', label: 'WhatsApp Templates' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=template-builder', label: 'Create WhatsApp Template' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=catalog-builder', label: 'Catalog & Flow Mapping' },
      { path: '/workspace/communications?view=manage&section=flows', label: 'Flow Hub' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=flows', label: 'WhatsApp Flows' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=flow-publish', label: 'Flow Publish' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=flow-responses', label: 'Flow Responses' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=groups', label: 'Groups' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=calling', label: 'Calling' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=cost-controls', label: 'Cost Controls' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=scripts', label: 'Scripts' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=welcome', label: 'Welcome Message' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=bot-menu', label: 'Bot & Service Menu' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=ai-agent', label: 'WhatsApp AI Agent' },
    ],
  },
  {
    id: 'channels',
    label: 'Other channels',
    icon: 'message',
    hint: 'SMS, RCS, Email, Voice, Push',
    items: [
      // `/workspace/engage` is a real 160-line page (the Messages hub), not just a section
      // container. It was the old sidebar's "Messages" parent, so dropping the
      // parent would have orphaned an actual route.
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
      // FEAT-005: these automation/content/analytics tools are in-page tabs on the Messages hub
      // now; each deep-links /workspace/engage with its ?tab= id.
      { path: '/workspace/communications?view=manage&section=automation', label: 'Automation' },
      { path: '/workspace/communications?view=manage&section=templates', label: 'Content Library' },
      { path: '/workspace/communications?view=manage&section=analytics', label: 'Analytics' },
      { path: '/workspace/communications?view=manage&section=usage', label: 'Cost & Usage' },
      { path: '/workspace/communications?view=manage&section=search', label: 'Message Search' },
      { path: '/workspace/communications?view=manage&section=ai', label: 'Meta AI Agent' },
      { path: '/workspace/communications?view=manage&section=whatsapp&tool=ai-agent', label: 'AI Agent' },
      { path: '/workspace/communications?view=manage&section=docs', label: 'Docs Scraper' },
      { path: '/workspace/link', label: 'Short Links' },
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
  {
    id: 'seo',
    label: 'SEO',
    icon: 'search',
    // Seven entries left this group: Pages, Issues, Analytics, Tracking, Schema,
    // Properties and Sitemaps. They were not slow or half-finished pages — they were
    // pages that threw on arrival. All seven read through `seoFetch` in
    // src/api/seo.ts, which throws when NEXT_PUBLIC_SEO_API_URL is unset, and that
    // variable is absent from the `stack` branch environment. So each of those gear
    // links led to a thrown error instead of a screen, which is precisely the
    // menu-entry-leading-to-a-promise failure the Platform comment below set out to
    // avoid.
    //
    // The four that remain are live, on the OTHER half of that client
    // (`seoToolsFetch`): SEO Dashboard, Tools, Blog SEO and Site Pages SEO. Tools
    // also reads NEXT_PUBLIC_SEO_API_URL, but through its own fetch, and degrades
    // gracefully when it is unset rather than throwing.
    //
    // 'Blog Studio' also left this group, but it MOVED rather than went: it is a
    // child of the Content sidebar section now, beside the blog-production queue it
    // belongs with. It is deliberately not listed in both places.
    hint: 'SEO dashboard, tools and content SEO',
    items: [
      { path: '/workspace/seo', label: 'SEO Dashboard' },
      // FEAT-005: Tools / Blog SEO / Site Pages SEO are in-page tabs on the SEO hub now.
      { path: '/workspace/seo?tab=tools', label: 'Tools' },
      { path: '/workspace/seo?tab=blog', label: 'Blog SEO' },
      { path: '/workspace/seo?tab=pages', label: 'Site Pages SEO' },
    ],
  },
  {
    id: 'platform',
    label: 'Platform',
    icon: 'dashboard',
    hint: 'Infrastructure, architecture, diagnostics',
    items: [
      // 'Dashboard Overview' (/workspace/dashboard) was the first row here until the
      // Dashboard section was removed. It was an analytics page with no surviving owner;
      // the workspace landing is now /workspace/engage/inbox, so no row replaces it.
      // FEAT-006: the seven Platform infra pages folded into ONE hub
      // (/workspace/settings/platform) with in-page tabs. Their bodies moved out of the
      // routes tree into src/components/workspace/platform/**, so each row deep-links the
      // hub with its ?tab= id. pageExists strips the query and resolves all of them to the
      // one platform/index.tsx hub route. Every workspaceMCP / api/client.ts call inside
      // those bodies is unchanged.
      { path: '/workspace/settings/platform?tab=mcp-connections', label: 'MCP Connections' },
      // Labelled 'Control Center' until 2026-10-07, which promised a place you operate
      // from. It is a static snapshot of the architecture, hand-maintained, and it has
      // measurably drifted: it lists `wecare-meta-analytics` as an active function on
      // route /meta-analytics and names a MetaAnalyticsLog table, and the live account
      // has neither. The label now says what the page is, so a reader treats it as a
      // document to check rather than a console to trust.
      { path: '/workspace/settings/platform?tab=system-architecture', label: 'Architecture snapshot' },
      { path: '/workspace/settings/platform?tab=lambda-functions', label: 'Lambda Functions' },
      { path: '/workspace/settings/platform?tab=code-repo', label: 'Code Repo' },
      // 'WABA Usernames' (/workspace/dashboard/waba-usernames) was a row here until
      // 2026-10-15. It was a smaller copy of WhatsApp -> BSUID & Usernames (same
      // getBusinessUsername / claimBusinessUsername calls, same two numbers, none of the
      // suggestions or webhook fields), so the route is now a signpost to that page.
      { path: '/workspace/settings/platform?tab=wa-graph-tools', label: 'WA Graph Tools' },
      { path: '/workspace/settings/platform?tab=cors-settings', label: 'CORS Settings' },
      { path: '/workspace/settings/platform?tab=design-reference', label: 'Design Reference' },
      // Internal Agent moved up to the "Your account" group — see the note there. The
      // redesign keeps Settings as exactly two rows (Sign-in & MFA + Internal Agent); the
      // Platform group remains for infrastructure reachability via the palette.
      // '/carbon' and '/nocode' were here. Both removed 2026-09-25 with their pages:
      // each was a 15-line EmptyState reading "... coming soon" with nothing behind it
      // ("Sustainability and carbon tracking", "Visual workflow and form builder"). A
      // menu entry leading to a promise is exactly the failure mode the Growth/Commerce
      // comment above set out to avoid — a flagged-off page that explains itself is real
      // content, "coming soon" is not.
      //
      // '/workspace/docs' ("Docs") was the last row here, removed 2026-10-15. docs/index.tsx
      // is a router.replace signpost to /workspace/engage/documents, which the sidebar
      // already lists as Service Ops -> Drop Docs, so the row was a second door to one page
      // with a label that named neither it nor the Docs Scraper (/workspace/engage/docs,
      // under Messaging tools). The signpost file stays for bookmarks.
    ],
  },
];

// ---------------------------------------------------------------------------
// THE EIGHT MODULE HOMES (master prompt phase 8.1)
// ---------------------------------------------------------------------------
/**
 * The master prompt asks for eight module homes: Home, Communications, Customers,
 * Commerce, Growth, Service Operations, Platform Operations and Settings.
 *
 * RECONCILING THAT WITH THE SIDEBAR ABOVE
 * ---------------------------------------
 * These are not the same question, and conflating them is what made this look like a
 * contradiction. A **module home** is a route: the landing page for a domain, with its
 * inner pages separately routed and lazy-loaded. The **sidebar** is which of those are
 * one click away. The owner overrode the second — "just show main inbox, rest move
 * under settings" — and said nothing about the first.
 *
 * So the eight homes are declared here and every one is a real, reachable route. Six of
 * the eight were already live under different names; this registry stops that being
 * implicit, and `tests/test_module_homes.py` asserts each `path` exists as a page and
 * appears in `getAllNavItems()`.
 *
 * Settings is deliberately `null`. A `/workspace/settings` page would be one more destination to
 * navigate to *before* navigating, with its own shell, breadcrumb and a decision about
 * the page you were on — so it is a panel (`SettingsGear`) over `settingsConfig`, not a
 * route. That was a C1 decision and it stands; recording it as a home with no path is
 * more honest than inventing a route to satisfy a count.
 */
export interface ModuleHome {
  /** The master prompt's name for the module. */
  id: string;
  label: string;
  /** The live route, or null when the module is a panel rather than a page. */
  path: string | null;
  /** Where its inner pages live, for the lazy-loading requirement. */
  innerPages: string[];
  /** Why this route is the home, when the name does not match the master prompt's. */
  note?: string;
}

export const moduleHomes: ModuleHome[] = [
  {
    id: 'home', label: 'Home', path: '/workspace',
    innerPages: [],
    note: 'Workspace Home is the operator launchpad. It owns attention queues, quick actions, '
      + 'recent work and discovery of the small set of operational workspaces.',
  },
  {
    id: 'communications', label: 'Communications', path: '/workspace/communications',
    innerPages: [
      '/workspace/communications?view=inbox',
      '/workspace/communications?view=manage',
    ],
    note: 'Exactly two primary modes: Inbox for daily conversation work and Manage for channels, '
      + 'content, automation and communications operations.',
  },
  {
    id: 'customers', label: 'Customers', path: '/workspace/customers',
    innerPages: [],
    note: 'Customer 360 is the customer record itself; there is no separate Engage/Contact 360 destination.',
  },
  {
    id: 'commerce', label: 'Commerce', path: '/workspace/commerce',
    innerPages: ['/workspace/commerce?view=orders', '/workspace/commerce?view=catalog'],
    note: 'Orders and Catalog are the two Commerce modes; money collection and invoice records live in Payments.',
  },
  // The 'growth' module home was here, gated on NEXT_PUBLIC_ENABLE_GROWTH_MODULE.
  // Removed 2026-09-25 with /growth/index.tsx on owner instruction. The pages it listed
  // as innerPages are all still reachable in their own right — [retired public path], [retired public path]/pages,
  // [retired public path]/analytics, [retired public path]/tracking, [retired public path]/schema, [retired public path]/whatsapp/ctwa-ads and
  // [retired public path]/whatsapp/conversions-api each have their own nav entry — so nothing became
  // unreachable, only the grouping page went.
  {
    id: 'payments', label: 'Payments', path: '/workspace/payments',
    innerPages: [
      '/workspace/payments?view=collect',
      '/workspace/payments?view=invoices',
      '/workspace/payments?view=activity',
    ],
    note: 'Collect, Invoices and Activity are the three primary money modes; the invoice engine remains authoritative.',
  },
  {
    id: 'content', label: 'Content', path: '/workspace/content',
    innerPages: [
      '/workspace/content?view=blog',
      '/workspace/content?view=production',
      '/workspace/content?view=seo&area=tools',
      '/workspace/content?view=seo&area=pages',
      '/workspace/content?view=links',
    ],
    note: 'Blog, Production, supported AWS-native SEO and Short Links share one content workspace.',
  },
  {
    id: 'automation', label: 'Automation & AI', path: '/workspace/automation',
    innerPages: [
      '/workspace/automation?view=agent',
      '/workspace/automation?view=rules',
      '/workspace/automation?view=schedules',
      '/workspace/automation?view=knowledge',
    ],
    note: 'Staff agent operations are separate from the customer-facing Meta Business Agent; true configuration remains contextual.',
  },
  {
    id: 'service-operations', label: 'Service', path: '/workspace/service',
    innerPages: [
      '/workspace/service?view=requests',
      '/workspace/service?view=appointments',
      '/workspace/service?view=documents',
    ],
    note: 'Requests, Appointments and Documents are the three primary service modes; the remaining capabilities open contextually.',
  },
  {
    id: 'platform-operations', label: 'Platform Operations',
    // FEAT-006: the Platform infra pages folded into one hub with in-page tabs; the home
    // and its inner pages deep-link the hub with ?tab= ids.
    path: '/workspace/settings/platform?tab=system-architecture',
    innerPages: ['/workspace/settings/platform?tab=lambda-functions', '/workspace/settings/platform?tab=code-repo',
      '/workspace/settings/platform?tab=cors-settings', '/workspace/settings/platform?tab=design-reference'],
  },
  {
    id: 'settings', label: 'Settings', path: null,
    innerPages: [],
    note: 'A panel, not a route. See the block comment above.',
  },
];

/**
 * Every destination, sidebar AND settings.
 *
 * This is the one function the command palette is built from, so anything missing
 * here becomes genuinely unreachable once the sidebar is short. `getAllNavItems`
 * therefore walks both trees, and a test asserts the settings paths are present.
 */
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
  return items;
}

/** Just the settings destinations, for the gear panel and for tests. */
export function getSettingsItems (): { path: string; label: string; group: string }[] {
  return settingsConfig.flatMap( ( g ) =>
    g.items.map( ( i ) => ( { path: i.path, label: i.label, group: g.label } ) ) );
}

/**
 * Strip a query string before comparing to a route.
 *
 * The Inbox children are `/workspace/engage/inbox?channel=rcs` — one page, six entries. Without
 * this, active-state matching compares a path against a path-plus-query and never
 * matches, so the sidebar would highlight nothing on the page you are looking at.
 */
function basePath ( p: string ): string {
  const i = p.indexOf( '?' );
  return i === -1 ? p : p.slice( 0, i );
}

export function getParentPath ( pathname: string ): string | null {
  for ( const item of navigationConfig )
  {
    if ( item.children?.some( ( child ) => basePath( child.path ) === pathname ) )
      return item.path;
    if ( pathname.startsWith( basePath( item.path ) ) && item.path !== '/' )
      return item.path;
  }
  return null;
}

export function isNavItemActive ( item: NavItem, pathname: string ): boolean {
  const base = basePath( item.path );
  if ( base === '/' ) return pathname === '/';
  if ( item.children ) return pathname.startsWith( base );
  return pathname === base || pathname.startsWith( base + '/' );
}

export function isSubItemActive ( subItem: NavSubItem, pathname: string ): boolean {
  const base = basePath( subItem.path );
  if ( pathname === base ) return true;
  if ( subItem.children )
    return subItem.children.some( ( child ) => pathname === basePath( child.path ) );
  return pathname.startsWith( base + '/' );
}
