import React from 'react';
import type { Message } from '../api/client';

export function flowResponseTitle ( message: Pick<Message, 'flowType' | 'flowCode'> ): string {
  const key = ( message.flowType || message.flowCode || '' ).toLowerCase();
  if ( [ 'customer_idea', 'wd-f002-leave-review', 'wd_idea', 'feedback', 'wd_rev', 'leave_review' ].includes( key ) ) return 'Leave Review';
  return key.replace( /^wd_/, '' ).replace( /_v\d+$/, '' ).replace( /_/g, ' ' ).replace( /\b\w/g, letter => letter.toUpperCase() ) || 'Submitted Form';
}

/** One readable response table and the files belonging to that submission. */
export default function FlowResponseDetails ( { flowAnswers = [], flowAttachments = [] }: Pick<Message, 'flowAnswers' | 'flowAttachments'> ) {
  return <>
    { flowAnswers.length === 0 && <p>Response details were not included in this message.</p> }
    { flowAnswers.length > 0 && <table aria-label="Flow response answers" style={ { width: '100%', tableLayout: 'fixed', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' } }>
      <thead><tr><th scope="col" style={ { width: '38%', textAlign: 'left', padding: 8 } }>Question</th><th scope="col" style={ { textAlign: 'left', padding: 8 } }>Answer</th></tr></thead>
      <tbody>{ flowAnswers.map( ( row, index ) => <tr key={ index }>
        <th scope="row" style={ { textAlign: 'left', verticalAlign: 'top', padding: 8, borderTop: '1px solid var(--border)', overflowWrap: 'anywhere' } }>{ row.question }</th>
        <td style={ { verticalAlign: 'top', padding: 8, borderTop: '1px solid var(--border)', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }>{ row.answer }</td>
      </tr> ) }</tbody>
    </table> }
    { flowAttachments.length > 0 && <section aria-label="Flow attachments" style={ { marginTop: 12 } }>
      <strong>Attachments</strong>
      <ul style={ { listStyle: 'none', padding: 0, margin: '8px 0', display: 'flex', flexWrap: 'wrap', gap: 8 } }>
        { flowAttachments.map( ( attachment, index ) => {
          const url = ( attachment.url || '' ).startsWith( 'https://' ) ? attachment.url : '';
          const name = attachment.filename || `Attachment ${ index + 1 }`;
          const image = ( attachment.type || '' ).startsWith( 'image/' ) || /\.(png|jpe?g|gif|webp)(\?|$)/i.test( url || '' );
          return <li key={ index } style={ { maxWidth: '100%', overflowWrap: 'anywhere' } }>
            { url ? <a href={ url } target="_blank" rel="noopener noreferrer" style={ { display: 'flex', flexDirection: 'column', gap: 4 } }>
              { image && <img src={ url } alt={ name } style={ { width: 84, height: 84, objectFit: 'cover', borderRadius: 7 } } /> }
              <span>{ name }</span>
            </a> : <span>{ name } · Download unavailable</span> }
          </li>;
        } ) }
      </ul>
    </section> }
  </>;
}
