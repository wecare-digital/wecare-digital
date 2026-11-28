// The /ws customer dialogs use the shared accessible dialog (audit WEB-11).
//
// ui/Modal moves focus into the dialog, traps Tab, closes on Escape and restores focus on
// close. ErasureScopeReview and CustomerActionsSheet used hand-built overlays that did none of
// that. This pins them to ui/Modal and pins the Modal behaviours they rely on.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { readSource } from './helpers/loadTsx.mjs';

test( 'ErasureScopeReview and CustomerActionsSheet render through ui/Modal', () => {
  for ( const file of [ 'src/components/ws/customers/ErasureScopeReview.tsx', 'src/components/ws/customers/CustomerActionsSheet.tsx' ] ) {
    const source = readSource( file );
    assert.ok( source.includes( "import Modal from '../../ui/Modal';" ), `${ file } imports ui/Modal` );
    assert.match( source, /<Modal isOpen onClose=\{ ?onClose ?\}/, `${ file } renders <Modal>` );
    assert.ok( !source.includes( 'aria-modal' ), `${ file } builds no dialog of its own` );
  }
} );

test( 'ui/Modal keeps disabled controls out of the focus trap and leaves stacked dialogs their Escape', () => {
  const modal = readSource( 'src/components/ui/Modal.tsx' );
  assert.match( modal, /button:not\(\[disabled\]\)/ );
  assert.match( modal, /closest\('\[aria-modal="true"\]'\)/ );
  assert.match( modal, /previousFocusRef\.current\?\.focus\(\)/, 'focus is restored on close' );
} );

test( '/ws raises ui/Modal above its bottom navigation and the support widget', () => {
  const theme = readSource( 'src/components/ws/WsNotionTheme.tsx' );
  assert.match( theme, /\.ws-shell\.ws-notion \.ui-modal-overlay \{z-index:1400!important\}/ );
} );
