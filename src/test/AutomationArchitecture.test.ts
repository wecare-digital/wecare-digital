import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { getAllNavItems, navigationConfig, settingsConfig } from '../config/navigation';

const ROOT = path.resolve( __dirname, '..' );
const page = fs.readFileSync( path.join( ROOT, 'pages/workspace/automation/index.tsx' ), 'utf8' );
const agent = fs.readFileSync( path.join( ROOT, 'components/dashboard/tabs/InternalChatTab.tsx' ), 'utf8' );

describe( 'canonical Automation and AI workspace', () => {
  it( 'has exactly Staff agent, Rules, Schedules and Knowledge as primary modes', () => {
    const block = page.slice( page.indexOf( 'const TABS' ), page.indexOf( 'function one' ) );
    const labels = [ ...block.matchAll( /label: '([^']+)'/g ) ].map( match => match[ 1 ] );
    expect( labels ).toEqual( [ 'Staff agent', 'Rules', 'Schedules', 'Knowledge' ] );
  } );

  it( 'keeps Automation contextual and searchable instead of making it a permanent workspace', () => {
    expect( navigationConfig.find( item => item.path === '/workspace/automation' ) ).toBeUndefined();
    const paths = getAllNavItems().map( item => item.path );
    expect( paths ).toContain( '/workspace/automation' );
    expect( paths ).toContain( '/workspace/automation?view=agent' );
    expect( paths ).toContain( '/workspace/automation?view=rules' );
    expect( paths ).toContain( '/workspace/automation?view=schedules' );
    expect( paths ).toContain( '/workspace/automation?view=knowledge' );
  } );

  it( 'keeps the customer-facing Meta agent out of the staff-agent workspace', () => {
    expect( page ).toContain( "InternalChatTab" );
    expect( page ).not.toContain( "MetaAgent" );
    const communications = fs.readFileSync( path.join( ROOT, 'pages/workspace/communications/index.tsx' ), 'utf8' );
    expect( communications ).toContain( 'MetaAgentPanel' );
  } );

  it( 'keeps only true internal-agent configuration in Settings', () => {
    const account = settingsConfig.find( group => group.id === 'account' );
    const internal = account?.items.find( item => item.path === '/workspace/settings/internal-agent' );
    expect( internal?.label ).toBe( 'Internal Agent configuration' );
  } );

  it( 'uses dynamic viewport height and current product language in the staff agent', () => {
    expect( agent ).toContain( '100dvh' );
    expect( agent ).toContain( 'WECARE.DIGITAL workspace assistant' );
    expect( agent ).not.toContain( 'Stack CRM task assistant' );
  } );
} );
