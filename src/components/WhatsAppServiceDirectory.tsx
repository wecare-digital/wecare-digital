import React from 'react';
import { WHATSAPP_SERVICE_ENTRIES, whatsappKeywordLink } from '../config/whatsappServiceEntries';

const WhatsAppServiceDirectory: React.FC = () => (
  <section aria-label="Customer service keywords">
    <h3>Customer service keywords</h3>
    <p>Orders and Customer ID require a verified customer WhatsApp account. Chat links prefill a keyword; the customer sends it to start.</p>
    <div style={ { overflowX: 'auto' } }>
      <table style={ { width: '100%', textAlign: 'left', borderCollapse: 'collapse' } }>
        <thead><tr><th>Service</th><th>Keyword</th><th>Flow and status</th><th>Open</th></tr></thead>
        <tbody>{ WHATSAPP_SERVICE_ENTRIES.map( entry => (
          <tr key={ entry.slug }>
            <td>{ entry.label }</td><td>{ entry.keyword }</td>
            <td>{ entry.state }{ entry.flowId && <div>{ entry.flowId }</div> }</td>
            <td><a href={ whatsappKeywordLink( entry.keyword ) } target="_blank" rel="noopener noreferrer">WhatsApp</a></td>
          </tr>
        ) ) }</tbody>
      </table>
    </div>
  </section>
);

export default WhatsAppServiceDirectory;
