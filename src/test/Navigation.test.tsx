/**
 * The restructure's one hard invariant: NOTHING became unreachable.
 *
 * The sidebar went from 88 destinations to a short list, with the rest behind a
 * gear. That is only safe because `getAllNavItems()` walks BOTH trees and the
 * command palette is built from it. 21 of the original 88 paths have no link
 * anywhere else in the app, so if the palette ever stopped seeing the settings
 * tree, those pages would be reachable only by typing a URL from memory.
 *
 * These tests are the guard on that. They are deliberately about reachability and
 * about paths resolving to real files - not about which group a page sits in, which
 * is a judgement the owner can move around freely.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import {
  navigationConfig,
  settingsConfig,
  getAllNavItems,
  getSettingsItems,
  isNavItemActive,
  isSubItemActive,
} from '../config/navigation';

const PAGES = path.resolve( __dirname, '../pages' );
const COMPONENTS = path.resolve( __dirname, '../components' );

/** Does a nav path resolve to a real page file? Query strings are stripped. */
function pageExists ( navPath: string ): boolean {
  const clean = navPath.split( '?' )[ 0 ].replace( /^\//, '' );
  if ( clean === '' ) return fs.existsSync( path.join( PAGES, 'index.tsx' ) );
  return fs.existsSync( path.join( PAGES, `${clean}.tsx` ) )
    || fs.existsSync( path.join( PAGES, clean, 'index.tsx' ) );
}

/** The page file behind a path, or null. Query string and trailing slash are stripped. */
function pageFile ( navPath: string ): string | null {
  const clean = navPath.split( '?' )[ 0 ].replace( /^\//, '' ).replace( /\/$/, '' );
  for ( const f of [ path.join( PAGES, `${clean}.tsx` ), path.join( PAGES, clean, 'index.tsx' ) ] )
  {
    if ( fs.existsSync( f ) ) return f;
  }
  return null;
}

/**
 * Where a path's page forwards to, if the page is a router.replace signpost; else null.
 *
 * The workspace retires URLs with small client-side stubs (admin/, service/, forms/,
 * docs/, engage/whatsapp/) rather than server redirects, and access/ is the sign-in
 * landing, which sends a signed-in user straight to the dashboard. Each is a fine
 * bookmark-catcher and a poor destination: a row or tile pointing at one is a second
 * door with a redirect behind it.
 */
function signpostTarget ( navPath: string ): string | null {
  const file = pageFile( navPath );
  if ( !file ) return null;
  const m = fs.readFileSync( file, 'utf8' ).match( /router\.replace\(\s*'([^']+)'/ );
  return m ? m[ 1 ] : null;
}

describe( 'the sidebar is short and holds only daily streams', () => {
  it( 'has far fewer top-level entries than the 11 it had', () => {
    // The bound moved 8 -> 9 on 2026-10-07 to carry the Content section, which puts the
    // blog-production queue (source review, QA, publish) in the sidebar — queue-shaped
    // daily work, and five pages that reached neither the nav nor the command palette
    // before. The test's claim is untouched: 9 is still far fewer than 11, and it is a
    // CEILING rather than a target. A tenth section needs its own argument, made here.
    expect( navigationConfig.length ).toBeLessThanOrEqual( 9 );
  } );

  it( 'leads with canonical Workspace Home', () => {
    expect( navigationConfig[ 0 ].path ).toBe( '/workspace' );
    expect( navigationConfig[ 1 ].path ).toBe( '/workspace/communications' );
  } );

  it( 'no longer carries the 30-item WhatsApp branch', () => {
    const waInSidebar = getAllNavItemsFrom( navigationConfig )
      .filter( ( p ) => p.startsWith( '/workspace/engage/whatsapp' ) );
    expect( waInSidebar ).toHaveLength( 0 );
  } );

  it( 'keeps only Inbox and Manage as Communications navigation modes', () => {
    const communications = navigationConfig.find( ( i ) => i.path === '/workspace/communications' );
    expect( communications?.children?.map( ( c ) => c.label ) )
      .toEqual( [ 'Inbox', 'Manage communications' ] );
    expect( communications?.children?.map( ( c ) => c.path ) )
      .toEqual( [
        '/workspace/communications?view=inbox',
        '/workspace/communications?view=manage',
      ] );
    // The already-retired standalone Calls route must stay gone.
    expect( fs.existsSync( path.join( PAGES, 'workspace/engage/calls/index.tsx' ) ) ).toBe( false );
  } );
} );

function getAllNavItemsFrom ( items: any[] ): string[] {
  const out: string[] = [];
  const walk = ( arr: any[] ) => {
    for ( const i of arr )
    {
      out.push( i.path );
      if ( i.children ) walk( i.children );
    }
  };
  walk( items );
  return out;
}

describe( 'nothing became unreachable', () => {
  it( 'getAllNavItems covers the settings tree, not just the sidebar', () => {
    const all = getAllNavItems().map( ( i ) => i.path );
    for ( const s of getSettingsItems() )
    {
      expect( all ).toContain( s.path );
    }
  } );

  it( 'keeps a searchable capability registry larger than the primary workspace list', () => {
    // Consolidation deliberately retires duplicate destinations. Reachability is guarded by
    // the concrete path-existence, settings-tree and orphan-capability assertions below, so
    // pinning the count to the retired 88-row menu would punish the product for removing pages.
    const unique = new Set( getAllNavItems().map( ( i ) => i.path ) );
    expect( unique.size ).toBeGreaterThan( navigationConfig.length );
    expect( unique ).toContain( '/workspace' );
    expect( unique ).toContain( '/workspace/communications?view=manage' );
    expect( unique ).toContain( '/workspace/commerce?view=orders' );
    expect( unique ).toContain( '/workspace/payments?view=invoices' );
    expect( unique ).toContain( '/workspace/service?view=requests' );
  } );

  it( 'keeps the pages that have no link anywhere else', () => {
    // A sample of the 21 orphans, including the MFA page the owner asked to keep
    // and which cannot be reached any other way.
    const all = getAllNavItems().map( ( i ) => i.path );
    // FEAT-005/006: these orphans are now reached as `hub?tab=` deep-links (their dense
    // sections folded into tabbed hubs and their bodies moved under
    // src/components/workspace/**). Still the one sample of the orphans with no link anywhere
    // else — only their canonical paths moved. (FEAT-003 relocated the MFA page out of this set
    // into the gear panel; its reachability is proven by the SettingsGear render test, not
    // getAllNavItems, so it is no longer sampled here.)
    for ( const p of [ '/workspace/communications?view=manage&section=sms',
      '/workspace/communications?view=manage&section=search',
      '/workspace/communications?view=manage&section=whatsapp&tool=catalog-builder', '/workspace/communications?view=manage&section=whatsapp&tool=embedded-signup',
      '/workspace/settings/platform?tab=design-reference',
      '/workspace/communications?view=manage&section=ai', '/workspace/service?view=requests&action=faq' ] )
    {
      expect( all ).toContain( p );
    }
  } );

  it( 'picked up routes that were orphaned before the restructure', () => {
    const all = getAllNavItems().map( ( i ) => i.path );
    // '/workspace/forms/create' was in this list until 2026-09-25. It was deleted as a ComingSoon
    // stub, so asserting the nav still reaches it would now assert the opposite of what
    // this file is for. FeatureFlags.test.tsx carries the inverse check for it.
    // FEAT-005/006: same destinations, now reached as hub?tab= deep-links — CORS under the
    // Platform hub, the two WhatsApp tools under the WhatsApp hub, Form responses under the
    // Service hub.
    for ( const p of [ '/workspace/settings/platform?tab=cors-settings', '/workspace/communications?view=manage&section=whatsapp&tool=ai-agent',
      '/workspace/communications?view=manage&section=whatsapp&tool=scripts', '/workspace/service?view=requests' ] )
    {
      expect( all ).toContain( p );
    }
  } );
} );

describe( 'every nav path resolves to a real page', () => {
  it( 'no sidebar entry points at a missing file', () => {
    const missing = getAllNavItemsFrom( navigationConfig ).filter( ( p ) => !pageExists( p ) );
    expect( missing ).toEqual( [] );
  } );

  it( 'no settings entry points at a missing file', () => {
    const missing = getSettingsItems()
      .map( ( i ) => i.path )
      .filter( ( p ) => !pageExists( p ) );
    expect( missing ).toEqual( [] );
  } );

  it( 'no retired page is still referenced', () => {
    const all = getAllNavItems().map( ( i ) => i.path.split( '?' )[ 0 ] );
    for ( const dead of [ '/workspace/engage/calls', '/workspace/engage/rcs/inbox', '/workspace/engage/ses/inbox',
      '/workspace/engage/rcs/logs', '/workspace/engage/ses/logs', '/workspace/engage/whatsapp/logs',
      '/workspace/engage/rcs/campaign', '/workspace/engage/ses/campaign', '/workspace/forms/logs', '/workspace/link/logs' ] )
    {
      expect( all ).not.toContain( dead );
    }
  } );
} );

describe( 'no entry point lands on a redirect signpost', () => {
  // Kept on purpose, so a bookmark still lands somewhere. Removing one of these files is a
  // decision about bookmarks, not about navigation, and should fail here first.
  // FEAT-003 folds hub pages, but keeps the client router.replace signpost FILES so legacy
  // bookmarks still forward in-repo (there is no editable server-side UI redirect table for
  // workspace paths; provision_legacy_redirects.py refuses workspace entries). admin, docs and
  // dashboard/waba-usernames are restored as tiny signposts (v1 review response) so the three
  // old URLs resolve instead of 404ing through the static-export catch-all. Each forwards to a
  // destination a nav row reaches (verified below).
  const SIGNPOSTS = [ '/workspace/admin', '/workspace/forms', '/workspace/docs',
    '/workspace/access', '/workspace/contacts', '/workspace/engage/whatsapp',
    '/workspace/engage/service-ops', '/workspace/dashboard/waba-usernames' ];

  it( 'keeps every signpost, and each forwards to a destination the nav reaches', () => {
    const all = getAllNavItems().map( ( i ) => i.path );
    for ( const s of SIGNPOSTS )
    {
      const target = signpostTarget( s );
      expect( target, `${s} is no longer a router.replace signpost` ).not.toBeNull();
      const targetBase = target!.split( '?' )[ 0 ];
      const reachable = all.some( ( candidate ) =>
        candidate === target || candidate.split( '?' )[ 0 ] === targetBase
      );
      expect(
        reachable,
        `${s} forwards to ${target}, whose canonical page is not reachable from navigation/search`
      ).toBe( true );
    }
  } );

  it( 'no gear row and no sidebar leaf points at a signpost', () => {
    const sidebarLeaves = getAllNavItemsFrom(
      navigationConfig.flatMap( ( i ) => i.children ?? [ i ] ) );
    const rows = [ ...sidebarLeaves, ...getSettingsItems().map( ( i ) => i.path ) ];
    expect( rows.filter( ( p ) => signpostTarget( p ) !== null ) ).toEqual( [] );
  } );

  it( 'a sidebar section is a signpost only into one of its own children', () => {
    // A section's path doubles as its active-state prefix (isNavItemActive), which is why
    // Forms keeps /workspace/forms rather than naming one child: the signpost forwards to
    // Forms -> Form responses, so a collapsed-sidebar click or the "Forms" Ctrl+K row
    // still lands inside the section it names.
    for ( const item of navigationConfig )
    {
      const target = signpostTarget( item.path );
      if ( target === null ) continue;
      expect( item.children?.map( ( c ) => c.path ) ).toContain( target );
    }
  } );

  it( 'no Workspace Home destination points at a signpost or missing page', () => {
    const hub = fs.readFileSync( path.join( PAGES, 'workspace/index.tsx' ), 'utf8' );
    const destinations = [ ...hub.matchAll( /href: '([^']+)'/g ) ].map( ( m ) => m[ 1 ] );
    // Home is intentionally small now: it exposes operational jobs, not every implementation page.
    expect( new Set( destinations ).size ).toBeGreaterThanOrEqual( 5 );
    expect( destinations.filter( ( p ) => pageFile( p ) === null ) ).toEqual( [] );
    expect( destinations.filter( ( p ) => signpostTarget( p ) !== null ) ).toEqual( [] );
  } );
} );

describe( 'active-state matching survives the query strings', () => {
  // Inbox and Manage are query-string modes of one canonical Communications page.
  it( 'marks Communications active on its canonical page', () => {
    const communications = navigationConfig.find( ( i ) => i.path === '/workspace/communications' )!;
    expect( isNavItemActive( communications, '/workspace/communications' ) ).toBe( true );
  } );

  it( 'marks a query-string child active on its base route', () => {
    const child = { path: '/workspace/communications?view=manage', label: 'Manage communications' };
    expect( isSubItemActive( child, '/workspace/communications' ) ).toBe( true );
  } );

  it( 'does not mark an unrelated route active', () => {
    const customers = navigationConfig.find( ( i ) => i.path === '/workspace/customers' )!;
    expect( isNavItemActive( customers, '/workspace/communications' ) ).toBe( false );
  } );
} );

describe( 'the settings tree is navigable', () => {
  it( 'every group has a label, a hint and at least one item', () => {
    for ( const g of settingsConfig )
    {
      expect( g.label.length ).toBeGreaterThan( 0 );
      expect( g.hint.length ).toBeGreaterThan( 0 );
      expect( g.items.length ).toBeGreaterThan( 0 );
    }
  } );

  it( 'leads the account group with the Sign-in & MFA in-panel surface, since it cannot be reached otherwise', () => {
    // FEAT-003: Sign-in & MFA moved OUT of the routes tree into the gear panel. It is no longer
    // an items[] route (it was '/workspace/access/security'); it is declared on the account
    // group's `mfaPanel`, which SettingsGear renders FIRST and opens inline (TotpSetup needs the
    // signed-in user's own token, so it mounts in the gear rather than at a URL). Reachability is
    // proven by the SettingsGear render test below; here we pin that the gear still leads with it.
    const account = settingsConfig.find( ( g ) => g.id === 'account' );
    expect( account?.mfaPanel?.label ).toBe( 'Sign-in & MFA' );
    // And it is NOT a route any more: no account items path points at the retired security page.
    expect( account?.items.map( ( i ) => i.path ) ).not.toContain( '/workspace/access/security' );
  } );

  it( 'has no duplicate destination across the whole tree', () => {
    const paths = getSettingsItems().map( ( i ) => i.path );
    expect( new Set( paths ).size ).toBe( paths.length );
  } );

  it( 'reaches Sign-in & MFA through the gear panel, which mounts TotpSetup inline', () => {
    // FEAT-003 relocation: the MFA page left the routes tree, so reachability is proven HERE
    // instead of via getAllNavItems. The gear is the one surface that can mount TotpSetup with
    // the signed-in user's own token. SettingsGear renders the account group's `mfaPanel` and
    // opens the real TotpSetup component inline — asserted against its source, the same way
    // SearchModal.test pins the palette's source.
    const gear = fs.readFileSync( path.join( COMPONENTS, 'SettingsGear.tsx' ), 'utf8' );
    expect( gear ).toContain( "import( './security/TotpSetup' )" );
    expect( gear ).toContain( 'g.mfaPanel' );
    expect( gear ).toContain( '<TotpSetup />' );
    // The component that does the enrolling must still exist and still be the TOTP surface.
    const totp = fs.readFileSync( path.join( COMPONENTS, 'security', 'TotpSetup.tsx' ), 'utf8' );
    expect( totp ).toContain( 'setUpTOTP' );
    expect( totp ).toContain( 'verifyTOTPSetup' );
    // And no page file was left behind at the retired route.
    expect( fs.existsSync( path.join( PAGES, 'workspace/access/security.tsx' ) ) ).toBe( false );
  } );
} );
