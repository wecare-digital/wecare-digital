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
}

// ---------------------------------------------------------------------------
// THE SIDEBAR — daily streams only
// ---------------------------------------------------------------------------
export const navigationConfig: NavItem[] = [
  {
    // The channel children are filters on ONE page, not separate pages. They exist
    // because jumping straight to "just the RCS threads" is a daily move, and the
    // in-page selector is one extra click away from the sidebar.
    path: '/workspace/engage/inbox',
    label: 'Inbox',
    icon: 'message',
    children: [
      { path: '/workspace/engage/inbox', label: 'All channels' },
      { path: '/workspace/engage/inbox?channel=whatsapp', label: 'WhatsApp' },
      { path: '/workspace/engage/inbox?channel=sms', label: 'SMS' },
      { path: '/workspace/engage/inbox?channel=rcs', label: 'RCS' },
      { path: '/workspace/engage/inbox?channel=email', label: 'Email' },
      { path: '/workspace/engage/inbox?channel=voice', label: 'Calls' },
    ],
  },
  {
    path: '/workspace/contacts',
    label: 'Contacts',
    icon: 'contacts',
    children: [
      { path: '/workspace/contacts', label: 'All contacts' },
      { path: '/workspace/engage/contact-360', label: 'Contact 360' },
    ],
  },
  {
    path: '/workspace/engage/broadcast',
    label: 'Broadcast',
    icon: 'message',
    children: [
      { path: '/workspace/engage/broadcast', label: 'Send a broadcast' },
      { path: '/workspace/engage/scheduled', label: 'Scheduled' },
      { path: '/workspace/engage/logs', label: 'Message logs' },
    ],
  },
  {
    path: '/workspace/pay',
    label: 'Payments',
    icon: 'payment',
    children: [
      { path: '/workspace/pay', label: 'Overview' },
      // The ledger: what was billed, paid and delivered. Read-only on purpose -
      // cancel, delete and resend all move money or message a customer.
      { path: '/workspace/pay/records', label: 'Invoice records' },
      { path: '/workspace/pay/flow', label: 'Pay Flow' },
      // 'Pay Link' (/workspace/pay/link) was a fourth child here. The ENTRY went, the PAGE
      // stays: pay/index.tsx:11 imports it as PayLinkPage and renders it at :28 as the
      // Pay hub's second tab, so this drops a duplicate route into the same screen,
      // not a destination.
    ],
  },
  {
    // Owner leaned sidebar: ten child routes, and they are order-linked daily work
    // rather than configuration.
    path: '/workspace/engage/service-ops',
    label: 'Service Ops',
    icon: 'order',
    children: [
      { path: '/workspace/engage/service-ops', label: 'Orders' },
      { path: '/workspace/service/submit-request', label: 'Submit Request' },
      { path: '/workspace/service/track-request', label: 'Track Request' },
      { path: '/workspace/service/amend-request', label: 'Amend Request' },
      { path: '/workspace/engage/appointments', label: 'Appointments' },
      { path: '/workspace/engage/rx-slots', label: 'RX Slots' },
      { path: '/workspace/engage/documents', label: 'Drop Docs' },
      // Beside Drop Docs because the two are the same errand in opposite directions:
      // Drop Docs collects a file from a customer, Secure Files delivers one to them.
      // NOT under Platform, where its [retired public path]/ path would suggest it belongs - it
      // charges a customer ₹49 per download and creates their Cognito login, which is
      // order work, not infrastructure. Until now nothing linked it at all: 535 lines
      // and the only four callers of initSecureUpload/confirmSecureUpload/
      // listSecureFiles/revokeSecureFile, reachable only by typing the URL.
      { path: '/workspace/dashboard/secure-files', label: 'Secure Files' },
      { path: '/workspace/engage/enterprise', label: 'Enterprise' },
      { path: '/workspace/engage/reviews', label: 'Reviews' },
      { path: '/workspace/engage/faq', label: 'FAQ' },
    ],
  },
  {
    // '/store' until it moved: it is a staff page, and at that path its prerendered HTML
    // was the sign-in wall on a public-looking URL. See the note atop the page file.
    path: '/workspace/commerce/catalog',
    label: 'Store',
    icon: 'store',
    children: [
      { path: '/workspace/commerce/catalog', label: 'Catalog' },
      { path: '/workspace/engage/commerce', label: 'Commerce' },
    ],
  },
  {
    path: '/workspace/forms',
    label: 'Forms',
    icon: 'form',
    children: [
      // Responses first: a submitted request nobody actioned is a customer who paid
      // and heard nothing, so the queue matters more than a builder would.
      { path: '/workspace/forms/responses', label: 'Responses' },
      // '/workspace/forms/create' ("Forms Builder") was here. Removed 2026-09-25 with the page: it
      // was a ComingSoon stub listing six features with no backend behind any of them,
      // and [retired public path]/index.tsx redirected straight to it, so the whole [retired public path] landing was a
      // redirect into a list of promises. [retired public path] now goes to Responses.
      { path: '/workspace/forms/' + 'self' + 'service', label: 'Customer Service Hub' },
    ],
  },
  {
    // No longer 'Soon'. It was a ComingSoon stub promising six features with no
    // backend at all; it is now the conversation-meta work queue, which is real
    // data the inbox already writes.
    path: '/workspace/task',
    label: 'Tasks',
    icon: 'checklist',
  },
  {
    // Queue-shaped daily work, which is what the governing rule at the top of this
    // file puts in the sidebar: a source waiting on review, an article waiting on QA,
    // an approved article waiting to publish.
    //
    // These five pages were absent from navigationConfig, settingsConfig AND
    // moduleHomes, so they were absent from getAllNavItems() and therefore from the
    // command palette. A 1,790-line production pipeline was reachable only by clicking
    // a tile on /workspace/seo, or by typing the URL.
    //
    // NINTH ON PURPOSE: BottomNav renders navigationConfig.slice( 0, 4 ), so position
    // nine keeps this off the phone bottom bar, where it does not belong — reviewing a
    // source is desk work.
    //
    // blog-production/batch deliberately gets NO entry: it needs ?id=<batchId> and
    // renders "No wave was named" without one, which is the menu-entry-leading-to-a-
    // promise failure this file exists to avoid. It is reached from the wave list at
    // blog-production/index.tsx:78,178,204, which is where a batch id exists to pass.
    path: '/workspace/seo/blog-production',
    label: 'Content',
    icon: 'document',
    children: [
      { path: '/workspace/seo/blog-production', label: 'Production waves' },
      { path: '/workspace/seo/blog-production/review', label: 'Source review' },
      { path: '/workspace/seo/blog-production/qa', label: 'QA review' },
      { path: '/workspace/seo/blog-production/publish', label: 'Publish queue' },
      // Moved here from the gear's SEO group rather than duplicated — see the note there.
      { path: '/workspace/seo/blog-studio', label: 'Blog Studio' },
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
    items: [
      // Kept deliberately prominent. TOTP enrolment cannot be done from the admin
      // side — Cognito's AssociateSoftwareToken takes the user's own access token
      // and does not evaluate IAM — so the signed-in person must be able to reach
      // this. Burying it would work against the admin-MFA target.
      { path: '/workspace/access/security', label: 'Sign-in & MFA' },
      { path: '/workspace/access', label: 'Access' },
    ],
  },
  {
    id: 'whatsapp',
    label: 'WhatsApp',
    icon: 'whatsapp',
    hint: 'WABA setup, templates, flows, calling',
    items: [
      { path: '/workspace/engage/whatsapp', label: 'WhatsApp Inbox' },
      { path: '/workspace/engage/whatsapp/waba-dashboard', label: 'WABA Dashboard' },
      { path: '/workspace/engage/whatsapp/embedded-signup', label: 'Connect WABA' },
      { path: '/workspace/engage/whatsapp/connected-accounts', label: 'Connected Accounts' },
      { path: '/workspace/engage/whatsapp/my-account', label: 'My WhatsApp Account' },
      { path: '/workspace/engage/whatsapp/business-profile', label: 'Business Profile' },
      { path: '/workspace/engage/whatsapp/webhooks', label: 'Webhooks' },
      { path: '/workspace/engage/whatsapp/bsuid', label: 'BSUID & Usernames' },
      { path: '/workspace/engage/whatsapp/migration', label: 'WABA Migration' },
      { path: '/workspace/engage/whatsapp/settings', label: 'WhatsApp Settings' },
      { path: '/workspace/engage/whatsapp/send-test', label: 'Send Test' },
      { path: '/workspace/engage/whatsapp/campaign', label: 'WhatsApp Campaign' },
      { path: '/workspace/engage/whatsapp/interactive-lists', label: 'Interactive Lists' },
      { path: '/workspace/engage/whatsapp/auto-response', label: 'Auto Response' },
      { path: '/workspace/engage/whatsapp/conversions-api', label: 'Conversions API (CTWA)' },
      { path: '/workspace/engage/whatsapp/ctwa-ads', label: 'Ads to WhatsApp (CTWA)' },
      { path: '/workspace/engage/whatsapp/tech-partner', label: 'Tech Partner Readiness' },
      { path: '/workspace/engage/whatsapp/templates', label: 'Templates' },
      { path: '/workspace/engage/whatsapp/template-builder', label: 'Template Builder' },
      { path: '/workspace/engage/whatsapp/catalog-builder', label: 'Catalog & Flow Builder' },
      { path: '/workspace/engage/whatsapp/flow-hub', label: 'Flow Hub' },
      { path: '/workspace/engage/whatsapp/flows', label: 'Flows' },
      { path: '/workspace/engage/whatsapp/flow-publish', label: 'Flow Publish Checklist' },
      { path: '/workspace/engage/whatsapp/flow-responses', label: 'Flow Responses' },
      { path: '/workspace/engage/whatsapp/groups', label: 'Groups' },
      { path: '/workspace/engage/whatsapp/calling', label: 'Calling' },
      { path: '/workspace/engage/whatsapp/cost-controls', label: 'Cost Controls' },
      { path: '/workspace/engage/whatsapp/scripts', label: 'Scripts' },
      { path: '/workspace/engage/whatsapp/welcome', label: 'Welcome Message' },
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
      { path: '/workspace/engage', label: 'Messages hub' },
      { path: '/workspace/engage/channels', label: 'All channels' },
      { path: '/workspace/engage/settings', label: 'Channel Settings' },
      { path: '/workspace/engage/sms', label: 'SMS' },
      { path: '/workspace/engage/rcs', label: 'RCS' },
      { path: '/workspace/engage/ses', label: 'Email' },
      { path: '/workspace/engage/push', label: 'Push' },
      // Call CONFIGURATION. The call RECORDS are [retired public path]/inbox?channel=voice.
      { path: '/workspace/engage/voice', label: 'Voice (outbound)' },
      { path: '/workspace/engage/voice-in', label: 'Voice In (IVR)' },
    ],
  },
  {
    id: 'messaging-tools',
    label: 'Messaging tools',
    icon: 'settings',
    hint: 'Automation, content, analytics, cost',
    items: [
      { path: '/workspace/engage/automation', label: 'Automation' },
      { path: '/workspace/engage/content', label: 'Content Library' },
      { path: '/workspace/engage/analytics', label: 'Analytics' },
      { path: '/workspace/engage/cost', label: 'Cost & Usage' },
      { path: '/workspace/engage/search', label: 'Message Search' },
      { path: '/workspace/engage/meta-agent', label: 'Meta AI Agent' },
      { path: '/workspace/engage/whatsapp/ai-agent', label: 'AI Agent' },
      { path: '/workspace/engage/docs', label: 'Docs Scraper' },
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
      { path: '/workspace/seo/tools', label: 'Tools' },
      { path: '/workspace/seo/blog-manager', label: 'Blog SEO' },
      { path: '/workspace/seo/pages-manager', label: 'Site Pages SEO' },
    ],
  },
  {
    id: 'platform',
    label: 'Platform',
    icon: 'dashboard',
    hint: 'Infrastructure, architecture, diagnostics',
    items: [
      { path: '/workspace/dashboard', label: 'Dashboard Overview' },
      { path: '/workspace/dashboard/mcp-connections', label: 'MCP Connections' },
      // Labelled 'Control Center' until 2026-10-07, which promised a place you operate
      // from. It is a static snapshot of the architecture, hand-maintained, and it has
      // measurably drifted: it lists `wecare-meta-analytics` as an active function on
      // route /meta-analytics and names a MetaAnalyticsLog table, and the live account
      // has neither. The label now says what the page is, so a reader treats it as a
      // document to check rather than a console to trust.
      { path: '/workspace/dashboard/system-architecture', label: 'Architecture snapshot' },
      { path: '/workspace/dashboard/lambda-functions', label: 'Lambda Functions' },
      { path: '/workspace/dashboard/code-repo', label: 'Code Repo' },
      { path: '/workspace/dashboard/waba-usernames', label: 'WABA Usernames' },
      { path: '/workspace/dashboard/wa-graph-tools', label: 'WA Graph Tools' },
      { path: '/workspace/dashboard/cors-settings', label: 'CORS Settings' },
      { path: '/workspace/dashboard/design-reference', label: 'Design Reference' },
      // The operator's own assistant, and deliberately NOT next to "AI Agent" under
      // Messaging tools: that one answers customers on WhatsApp, this one configures the
      // admin helper, and two rows reading "agent" in one settings screen would invite
      // changing the wrong model's prompt. Its own docblock recorded that nothing in the
      // repo linked it; the /workspace tile grid was the only route, and nothing links
      // /workspace either, so the page was reachable only by typing two URLs in a row.
      { path: '/workspace/settings/internal-agent', label: 'Internal Agent' },
      // '/carbon' and '/nocode' were here. Both removed 2026-09-25 with their pages:
      // each was a 15-line EmptyState reading "... coming soon" with nothing behind it
      // ("Sustainability and carbon tracking", "Visual workflow and form builder"). A
      // menu entry leading to a promise is exactly the failure mode the Growth/Commerce
      // comment above set out to avoid — a flagged-off page that explains itself is real
      // content, "coming soon" is not.
      { path: '/workspace/docs', label: 'Docs' },
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
    id: 'home', label: 'Home', path: '/workspace/dashboard',
    innerPages: ['/workspace/dashboard/system-architecture', '/workspace/dashboard/lambda-functions',
      '/workspace/dashboard/code-repo', '/workspace/dashboard/cors-settings'],
    note: 'Tab bodies are lazy via next/dynamic; OverviewTab stays eager because it is '
      + 'the default tab and lazy-loading it would only add a round trip.',
  },
  {
    id: 'communications', label: 'Communications', path: '/workspace/engage',
    // The master prompt is explicit: Communications exposes EXACTLY these three.
    innerPages: ['/workspace/engage/inbox', '/workspace/engage/whatsapp', '/workspace/engage/voice'],
    note: 'Common Inbox, WhatsApp Business and Business Calling — exactly three, as '
      + 'specified. The other channels (SMS, RCS, Email, Push) are filters on the '
      + 'common inbox plus configuration under the gear, not peers of these three.',
  },
  {
    id: 'customers', label: 'Customers', path: '/workspace/contacts',
    innerPages: ['/workspace/engage/contact-360'],
  },
  {
    id: 'commerce', label: 'Commerce', path: '/workspace/commerce',
    innerPages: ['/workspace/commerce/catalog', '/workspace/engage/commerce', '/workspace/pay', '/workspace/pay/records'],
    note: 'Behind NEXT_PUBLIC_ENABLE_COMMERCE_MODULE, and OFF — not because it is '
      + 'unfinished but because the storefront is live, so a new surface over a '
      + 'production store opens deliberately. With the flag off it links to the working '
      + 'pages rather than shadowing them.',
  },
  // The 'growth' module home was here, gated on NEXT_PUBLIC_ENABLE_GROWTH_MODULE.
  // Removed 2026-09-25 with /growth/index.tsx on owner instruction. The pages it listed
  // as innerPages are all still reachable in their own right — [retired public path], [retired public path]/pages,
  // [retired public path]/analytics, [retired public path]/tracking, [retired public path]/schema, [retired public path]/whatsapp/ctwa-ads and
  // [retired public path]/whatsapp/conversions-api each have their own nav entry — so nothing became
  // unreachable, only the grouping page went.
  {
    id: 'service-operations', label: 'Service Operations', path: '/workspace/engage/service-ops',
    innerPages: ['/workspace/service/submit-request', '/workspace/service/track-request',
      '/workspace/service/amend-request', '/workspace/engage/appointments', '/workspace/engage/rx-slots',
      '/workspace/engage/documents', '/workspace/engage/enterprise', '/workspace/engage/reviews', '/workspace/engage/faq'],
  },
  {
    id: 'platform-operations', label: 'Platform Operations',
    path: '/workspace/dashboard/system-architecture',
    innerPages: ['/workspace/dashboard/lambda-functions', '/workspace/dashboard/code-repo',
      '/workspace/dashboard/cors-settings', '/workspace/dashboard/design-reference'],
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
