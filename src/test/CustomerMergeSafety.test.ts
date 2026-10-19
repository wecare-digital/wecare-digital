import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const source = fs.readFileSync(
  path.join( root, 'amplify/functions/core/contacts/handler.py' ),
  'utf8',
);

describe( 'audited customer merge saga', () => {
  it( 'uses the existing authenticated contacts route with an Admin merge gate', () => {
    expect( source ).toContain( "merge_command = str(preauth_body.get('_action')" );
    expect( source ).toContain( "or merge_command" );
    expect( source ).toContain( "required_role='Admin'" );
    expect( source ).toContain( "return _merge_contacts(body, event.get('_auth') or {}, request_id, origin)" );
  } );

  it( 'requires exact unambiguous identity evidence', () => {
    const block = source.slice(
      source.indexOf( 'def _merge_identity_evidence' ),
      source.indexOf( 'def _merge_contacts' ),
    );
    expect( block ).toContain( "shared.append('phone')" );
    expect( block ).toContain( "shared.append('email')" );
    expect( block ).toContain( 'CUSTOMER_MERGE_EXACT_IDENTITY_REQUIRED' );
    expect( block ).toContain( 'CUSTOMER_MERGE_IDENTITY_CONFLICT' );
  } );

  it( 'claims before aliasing and finalizes a retained source alias only after aliases are durable', () => {
    const block = source.slice(
      source.indexOf( 'def _merge_contacts' ),
      source.indexOf( '# ─── CREATE' ),
    );
    const claim = block.indexOf( "#merge_state = :claimed" );
    const alias = block.indexOf( 'mergedContactIds = list_append' );
    const finalize = block.indexOf( "mergeState = :merged" );
    expect( claim ).toBeGreaterThan( -1 );
    expect( alias ).toBeGreaterThan( claim );
    expect( finalize ).toBeGreaterThan( alias );
    expect( block ).not.toContain( 'deletedAt = :now' );
    expect( block ).toContain( 'REMOVE phone, email, bsuid' );
    expect( block ).toContain( 'CUSTOMER_MERGE_FINALIZE_RETRY' );
  } );

  it( 'never rewrites or deletes orders invoices payments or consent evidence', () => {
    const block = source.slice(
      source.indexOf( 'def _merge_contacts' ),
      source.indexOf( '# ─── CREATE' ),
    );
    expect( block ).not.toContain( 'ORDERS_TABLE' );
    expect( block ).not.toContain( 'INVOICES_TABLE' );
    expect( block ).not.toContain( 'PAYMENTS_TABLE' );
    expect( block ).not.toContain( 'delete_item' );
    expect( block ).not.toContain( 'optInWhatsApp' );
    expect( block ).not.toContain( 'allowlistWhatsApp' );
    expect( block ).toContain( "'preservedFinancialHistory': True" );
  } );

  it( 'keeps old contact links readable through the canonical target', () => {
    const read = source.slice(
      source.indexOf( 'def _read_one' ),
      source.indexOf( '# ─── COUNT' ),
    );
    expect( read ).toContain( "merged_target = str(item.get('mergedIntoContactId')" );
    expect( read ).toContain( "resolved['resolvedFromMergedContactId'] = contact_id" );
    expect( read ).toContain( "contact_read_merged_alias" );
  } );

  it( 'derives merge actor from auth and records reason on the source row', () => {
    const block = source.slice(
      source.indexOf( 'def _merge_contacts' ),
      source.indexOf( '# ─── CREATE' ),
    );
    expect( block ).toContain( "(auth or {}).get('username')" );
    expect( block ).not.toContain( "body.get('actor')" );
    expect( block ).toContain( "mergeReason = :reason" );
    expect( block ).toContain( "record_audit(" );
    expect( block ).toContain( "action='customer.merge'" );
  } );
} );
