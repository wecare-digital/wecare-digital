/**
 * Shared WhatsApp contact-card bubble.
 *
 * Renders the name, numbers, emails and organisation a customer shared, with a
 * `tel:` link and a copy button on every number. The copy button is the point of
 * this component rather than a flourish: before it existed the handler discarded
 * the payload entirely and an agent had to ask the customer to retype the number.
 *
 * Used by BOTH inboxes. They render messages through two unrelated local paths
 * (`renderMessageContent` in the WhatsApp inbox, inline JSX in the unified one),
 * so a shared component is what stops the two views drifting apart — which is the
 * failure this whole change is repairing one layer down.
 *
 * Styles are inline on purpose. styled-jsx does not scope composite components,
 * so a class name declared by either parent would arrive here unstyled.
 */
import React, { useCallback, useState } from 'react';
import type { WaContactCard } from '../api/client';
import { colors } from '../lib/design-tokens';

interface ContactCardBubbleProps {
  contacts?: WaContactCard[] | null;
  /** Shown when a contact carries no name and no number at all. */
  fallbackLabel?: string;
}

const displayName = ( c: WaContactCard, fallbackLabel: string ): string => {
  const n = c.name || {};
  const joined = [ n.first_name, n.last_name ].filter( Boolean ).join( ' ' ).trim();
  return ( n.formatted_name || '' ).trim() || joined
    || ( c.phones || [] ).map( p => p.phone ).filter( Boolean )[ 0 ] || fallbackLabel;
};

const ContactCardBubble: React.FC<ContactCardBubbleProps> = ( { contacts, fallbackLabel = 'Contact card' } ) => {
  const [ copied, setCopied ] = useState<string | null>( null );

  const copy = useCallback( async ( phone: string ) => {
    // navigator.clipboard is undefined in an insecure context and in jsdom, so the
    // button has to survive its absence rather than throw on click.
    try
    {
      if ( typeof navigator === 'undefined' || !navigator.clipboard ) return;
      await navigator.clipboard.writeText( phone );
      setCopied( phone );
      setTimeout( () => setCopied( null ), 2000 );
    } catch
    {
      // A rejected write is a denied permission. The number is still selectable
      // in the bubble, so there is nothing to recover and nothing to report.
    }
  }, [] );

  // Returning null lets each caller fall back to its own plain label — which is
  // what the one already-stored row with no payload keeps using.
  if ( !Array.isArray( contacts ) || contacts.length === 0 ) return null;

  return (
    <div style={ { display: 'flex', flexDirection: 'column', gap: 8 } }>
      { contacts.map( ( c, i ) => (
        <div
          key={ i }
          style={ {
            border: `1px solid ${colors.border}`,
            borderRadius: 10,
            padding: '8px 10px',
            background: colors.bgSecondary,
            minWidth: 180,
          } }
        >
          <div style={ { fontSize: 14, fontWeight: 600, color: colors.text, wordBreak: 'break-word' } }>
            { displayName( c, fallbackLabel ) }
          </div>

          { ( c.org?.title || c.org?.company ) && (
            <div style={ { fontSize: 12, color: colors.textMuted, marginTop: 2 } }>
              { [ c.org?.title, c.org?.company ].filter( Boolean ).join( ' · ' ) }
            </div>
          ) }

          { ( c.phones || [] ).filter( p => p && p.phone ).map( ( p, j ) => (
            <div key={ j } style={ { display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 } }>
              <a
                href={ `tel:${p.phone}` }
                style={ { fontSize: 13, color: colors.primary, textDecoration: 'none', fontWeight: 600 } }
              >
                { p.phone }
              </a>
              { p.type && <span style={ { fontSize: 11, color: colors.textMuted } }>{ p.type }</span> }
              <button
                type="button"
                onClick={ () => copy( p.phone as string ) }
                title={ `Copy ${p.phone}` }
                aria-label={ `Copy phone number ${p.phone}` }
                style={ {
                  fontSize: 11,
                  padding: '2px 7px',
                  border: `1px solid ${colors.border}`,
                  borderRadius: 6,
                  background: '#fff',
                  color: colors.textMuted,
                  cursor: 'pointer',
                } }
              >
                { copied === p.phone ? 'Copied' : 'Copy' }
              </button>
            </div>
          ) ) }

          { ( c.emails || [] ).filter( e => e && e.email ).map( ( e, j ) => (
            <div key={ j } style={ { marginTop: 4 } }>
              <a
                href={ `mailto:${e.email}` }
                style={ { fontSize: 13, color: colors.primary, textDecoration: 'none' } }
              >
                { e.email }
              </a>
            </div>
          ) ) }
        </div>
      ) ) }
    </div>
  );
};

export default ContactCardBubble;
