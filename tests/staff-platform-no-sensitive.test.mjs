// Staff platform pages hold no account ids, physical resource names, secret names or risk
// lists (audit WEB-4).
//
// Every staff chunk is a static file anyone can download, signed in or not, so the Project
// Control Center and its sibling pages describe the system in logical terms only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

import { readSource } from './helpers/loadTsx.mjs';

const ROOT = path.resolve( new URL( '..', import.meta.url ).pathname );
const PLATFORM_DIR = 'src/components/workspace/platform';
const FILES = [
  ...fs.readdirSync( path.join( ROOT, PLATFORM_DIR ) ).filter( f => f.endsWith( '.tsx' ) ).map( f => `${ PLATFORM_DIR }/${ f }` ),
  'src/components/workspace/whatsapp/calling.tsx',
];

const FORBIDDEN = [
  // Phone numbers are also 12 digits, so the two known account ids are named.
  [ /\b(775261844268|991322955408)\b/, 'an AWS account id' ],
  [ /arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}/, 'an ARN with an account id' ],
  [ /'wecare\/[a-z0-9-]+'/, 'a Secrets Manager secret name' ],
  [ /stack-wecare-digital-[A-Za-z]/, 'a physical table or queue name' ],
  [ /us-east-1_[A-Za-z0-9]{9}\b/, 'a Cognito user pool id' ],
  [ /us-east-1:[0-9a-f]{8}-/, 'a Cognito identity pool id' ],
  [ /\bE2GP22R4BIFGQ3\b/, 'the CloudFront distribution id' ],
  [ /\bacc_[A-Za-z0-9]{10,}\b/, 'the Razorpay merchant id' ],
  [ /const (RISKS|IMPROVEMENTS)\b/, 'the internal risk register' ],
];

test( 'staff platform pages carry no sensitive identifiers or risk register', () => {
  assert.ok( FILES.some( f => f.endsWith( 'SystemArchitecture.tsx' ) ), 'SystemArchitecture.tsx scanned' );
  for ( const file of FILES ) {
    const source = readSource( file );
    for ( const [ pattern, what ] of FORBIDDEN ) {
      const match = pattern.exec( source );
      assert.equal( match, null, `${ file } contains ${ what }: ${ match?.[ 0 ] }` );
    }
  }
} );
