import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = process.cwd();
const read = ( file: string ) => fs.readFileSync( path.join( root, file ), 'utf8' );

describe( 'Workspace mobile hardening', () => {
  it( 'keeps shared modal and pagination controls touch-safe', () => {
    const modal = read( 'src/components/ui/Modal.tsx' );
    const pagination = read( 'src/components/ui/Pagination.tsx' );

    expect( modal ).toContain( "maxHeight: '90dvh'" );
    expect( modal ).toContain( 'safe-area-inset-bottom' );
    expect( modal ).toContain( "width: '44px'" );
    expect( modal ).toContain( 'className="ui-modal-panel"' );

    expect( pagination ).toContain( "width: '44px'" );
    expect( pagination ).toContain( "height: '44px'" );
    expect( pagination ).toContain( 'aria-label="Previous page"' );
    expect( pagination ).toContain( 'flexWrap' );
  } );

  it( 'recomposes the topbar for the ~280px foldable harness', () => {
    const layout = read( 'src/components/Layout.tsx' );
    expect( layout ).toContain( 'workspace-action workspace-tasks' );
    expect( layout ).toContain( '.workspace-search,.workspace-tasks{display:none}' );
    expect( layout ).toContain( '.workspace-brand{max-width:112px}' );
    expect( layout ).toContain( 'safe-area-inset-left' );
    expect( layout ).toContain( 'safe-area-inset-right' );
  } );

  it( 'turns Customers detail and forms into phone-safe overlays', () => {
    const customers = read( 'src/pages/workspace/customers/index.tsx' );
    expect( customers ).toContain( 'className="customer-detail-panel"' );
    expect( customers ).toContain( 'className="customer-modal-panel"' );
    expect( customers ).toContain( 'calc(100dvh - 16px' );
    expect( customers ).toContain( 'className="customer-page-btn"' );
    expect( customers ).toContain( 'min-width:44px !important' );
  } );

  it( 'uses cards instead of wide operational tables on phones', () => {
    const tasks = read( 'src/pages/workspace/task/index.tsx' );
    const orders = read( 'src/components/workspace/commerce/Orders.tsx' );
    const service = read( 'src/components/service/ResponsesQueue.tsx' );

    expect( tasks ).toContain( 'className="tk-mobile-list"' );
    expect( tasks ).toContain( '.tk-table-wrap{display:none}' );

    expect( orders ).toContain( 'className="orders-mobile-list"' );
    expect( orders ).toContain( '.orders-desktop-table{display:none}' );
    expect( orders ).toContain( '.orders-filters > input' );

    expect( service ).toContain( 'className="service-responses-mobile"' );
    expect( service ).toContain( '.service-responses-table{display:none}' );
    expect( service ).toContain( 'label="Set status"' );
  } );

  it( 'uses dynamic viewport units and safe-area spacing in the Inbox master/detail flow', () => {
    const inbox = read( 'src/pages/workspace/engage/inbox/index.tsx' );
    expect( inbox ).not.toContain( 'height: calc(100vh - 56px)' );
    expect( inbox ).not.toContain( 'height: calc(100vh - 120px)' );
    expect( inbox ).toContain( 'height: calc(100dvh - 56px' );
    expect( inbox ).toContain( 'safe-area-inset-bottom' );
    expect( inbox ).toContain( 'width: 44px; height: 44px' );
    expect( inbox ).toContain( '.ui-msg-bubble{overflow-wrap:anywhere' );
  } );


  it( 'keeps shared Workspace content contained and controls at the 44px floor', () => {
    const css = read( 'src/styles/workspace.css' );
    expect( css ).toContain( '.workspace-shell .ps-content > *' );
    expect( css ).toContain( 'overscroll-behavior-inline: contain' );
    expect( css ).toContain( '.workspace-shell .workspace-main .btn' );
    expect( css ).toContain( 'min-height: var(--tap-min) !important' );
  } );
} );
