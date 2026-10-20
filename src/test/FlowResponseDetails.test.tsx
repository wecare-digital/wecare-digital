import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import FlowResponseDetails from '../components/FlowResponseDetails';

describe( 'Flow response details in the inbox', () => {
  it( 'renders answers in a semantic table with complete response text and document links', () => {
    render( <FlowResponseDetails flowAnswers={ [{ question: 'Rating', answer: '5' }, { question: 'Feedback', answer: 'The whole response remains readable.' }] }
      flowAttachments={ [{ filename: 'Invoice.pdf', type: 'application/pdf', url: 'https://wecare.digital/private/signed-file' }] } /> );
    expect( screen.getByRole( 'table', { name: 'Flow response answers' } ) ).toBeTruthy();
    expect( screen.getByRole( 'rowheader', { name: 'Rating' } ) ).toBeTruthy();
    expect( screen.getByText( 'The whole response remains readable.' ) ).toBeTruthy();
    expect( screen.getByRole( 'link', { name: 'Invoice.pdf' } ).getAttribute( 'href' ) ).toContain( 'signed-file' );
  } );
  it( 'shows image attachments and avoids broken links for files without a signed URL', () => {
    render( <FlowResponseDetails flowAttachments={ [{ filename: 'Photo.png', type: 'image/png', url: 'https://wecare.digital/photo.png' }, { filename: 'Pending.pdf', key: 'secure/file.pdf' }] } /> );
    expect( screen.getByRole( 'img', { name: 'Photo.png' } ) ).toBeTruthy();
    expect( screen.getByText( 'Pending.pdf · Download unavailable' ) ).toBeTruthy();
    expect( screen.queryByRole( 'link', { name: /Pending/ } ) ).toBeNull();
  } );
  it( 'renders unsafe link schemes as unavailable rather than clickable', () => {
    render( <FlowResponseDetails flowAttachments={ [{ filename: 'Unsafe', url: 'javascript:alert(1)' }] } /> );
    expect( screen.queryByRole( 'link' ) ).toBeNull();
  } );
} );
