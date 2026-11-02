import React from 'react';
import snapshot from '../../../content/paymentTemplateSnapshot.json';
import {FRAMEWORK_TEMPLATES, type FrameworkSection, type TemplateRole} from '../../../lib/paymentFramework';

const HEADER = 'https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png';
const THUMBNAIL = 'https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png';
interface Component {
  type?: string; format?: string; text?: string;
  example?: {header_handle?: string[]};
  buttons?: {type?: string; text?: string; url?: string; flow_id?: string | number; flow_action?: string; icon?: string}[];
}
interface Props {section: FrameworkSection; definitions?: Partial<Record<TemplateRole, unknown[]>>;}

/** Actual registered copy and source-defined media. This component has no send capability. */
export default function OutgoingMessageContent({section, definitions = {}}: Props) {
  const roles: TemplateRole[] = section === 'vault' ? ['payment', 'status', 'invoice', 'access'] : ['payment', 'status', 'invoice'];
  return <section className="omc" aria-labelledby="omc-title">
    <h3 id="omc-title">Full outgoing content and complete image links</h3>
    <p>Exact Meta definition snapshot read on 2 November 2026 at 09:50 IST. A fresh matching registry read replaces that snapshot below when available. This describes the message contract; a particular customer&apos;s sent payload needs its invoice/file and message ID.</p>
    <div className="omc-media">
      {[{name: 'Payment and Access Vault header', url: HEADER}, {name: 'Ordinary payment-item thumbnail', url: THUMBNAIL}].map(media => <figure key={media.url}>
        <img src={media.url} alt={media.name} loading="lazy" />
        <figcaption>{media.name}</figcaption>
        <a href={media.url} target="_blank" rel="noopener noreferrer">{media.url}</a>
      </figure>)}
    </div>
    <div className="omc-messages">{roles.map(role => {
      const expected = FRAMEWORK_TEMPLATES[role];
      const stored = snapshot.templates.find(row => row.name === expected.name);
      const components = (definitions[role] || stored?.components || []) as Component[];
      const body = components.find(part => part.type?.toUpperCase() === 'BODY');
      const footer = components.find(part => part.type?.toUpperCase() === 'FOOTER');
      const header = components.find(part => part.type?.toUpperCase() === 'HEADER');
      const buttons = components.find(part => part.type?.toUpperCase() === 'BUTTONS')?.buttons || [];
      return <article key={role}>
        <h4>{role === 'status' ? 'Processing and Completed · sent twice' : role === 'payment' ? 'Review and Pay' : role === 'invoice' ? 'Paid invoice' : 'Access Vault'}</h4>
        <code>{expected.name}</code>
        <small>{definitions[role] ? 'Current matching registry definition' : 'Verified Meta snapshot · 2 November 2026, 09:50 IST'}</small>
        <dl>
          <div><dt>Wire message type</dt><dd><code>template</code> · language <code>en</code></dd></div>
          <div><dt>Header</dt><dd>{role === 'status' ? 'No header component.' : role === 'invoice'
            ? 'Customer-specific paid invoice PNG. The backend uploads the private invoice asset to WhatsApp and sends an image media ID. There is no single permanent public URL.'
            : <a href={HEADER} target="_blank" rel="noopener noreferrer">{HEADER}</a>}</dd></div>
          <div><dt>Exact body text</dt><dd className="omc-copy">{body?.text || 'Body not available from the definition.'}</dd></div>
          <div><dt>Exact footer</dt><dd>{footer?.text || 'No footer component.'}</dd></div>
          <div><dt>Body variables</dt><dd>0 · the body copy is fixed.</dd></div>
          <div><dt>Button components</dt><dd>{buttons.length ? buttons.map((button, index) => <div className="omc-button" key={index}>
            <strong>{button.text}</strong> · <code>{button.type}</code> · index {index}
            {button.url && <div>Registered destination: <code>{button.url}</code></div>}
            {button.flow_id && <div>Flow ID: <code>{String(button.flow_id)}</code> · action <code>{button.flow_action}</code></div>}
          </div>) : 'No button component in the registered definition.'}</dd></div>
          {role === 'payment' && <div><dt>What varies per send</dt><dd>Recipient; reserved payment reference; item names, quantity and amounts; GST/Delight/Express/convenience breakdown; payment configuration; required delivery address. The Review and Pay button opens native checkout, not a browser payment URL. Ordinary items use the thumbnail above; the Convenience fee item has no image.</dd></div>}
          {role === 'status' && <div><dt>Dynamic status content</dt><dd><code>reference_id</code> identifies the original payment. Processing: <code>processing</code>, description <q>Payment received.</q> Completed: <code>completed</code>, description <q>Payment complete.</q> These are ORDER_STATUS fields, not body-text replacements.</dd></div>}
          {role === 'invoice' && <div><dt>What varies per send</dt><dd>Paid invoice image with saved customer, invoice, line-item, tax, fee and payment facts; an opaque order-bound review token on the Leave Review button. No free-form caption is added. The review token is generated for the send and is not displayed here.</dd></div>}
          {role === 'access' && <div><dt>What varies per send</dt><dd>URL button suffix <code>{'{{1}}'}</code> is the owner-bound file ID: <code>https://wecare.digital/vault/?file=&lt;FILE_ID&gt;</code>. The registered <code>doc.pdf</code> value is only an approval example. Customer sign-in and paid access checks still apply; no raw private S3 link or document attachment is sent.</dd></div>}
        </dl>
        {header?.example?.header_handle?.length ? <details>
          <summary>Complete Meta registration-example image URLs · not send-time images</summary>
          {header.example.header_handle.map(url => <a className="omc-example" key={url} href={url} target="_blank" rel="noopener noreferrer">{url}</a>)}
        </details> : null}
        <details><summary>Full registered components</summary><pre>{JSON.stringify(components, null, 2)}</pre></details>
      </article>;
    })}</div>
    <style jsx>{`
      .omc{min-width:0;display:grid;grid-template-columns:minmax(0,1fr);gap:16px}h3{font-size:18px;margin:0}h4{font-size:16px;margin:0 0 7px}p{margin:0;font-size:13px;line-height:1.65;color:var(--text-muted)}
      .omc-media{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:0;min-width:0;border:1px solid var(--border);border-radius:12px;background:var(--surface);padding:14px;display:grid;gap:10px}img{display:block;max-width:100%;width:auto;height:130px;object-fit:contain;justify-self:start}figcaption{font-size:13px;font-weight:750}
      a,code{overflow-wrap:anywhere;word-break:break-word}a{font-size:12px;line-height:1.65;color:var(--accent)}a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}code,pre{font-size:11px}
      .omc-messages{display:grid;gap:14px}article{min-width:0;padding:17px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}small{display:block;font-size:11px;color:var(--text-muted);margin-top:7px}dl{margin:16px 0 0;display:grid;gap:10px}dl>div{display:grid;grid-template-columns:160px minmax(0,1fr);gap:12px}dt,dd{font-size:12px;line-height:1.65}dt{color:var(--text-muted)}dd{margin:0;min-width:0}.omc-copy{white-space:pre-wrap}.omc-button{margin-bottom:8px}summary{min-height:44px;padding:11px 0;cursor:pointer;font-size:12px;font-weight:750}.omc-example{display:block;margin:8px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;line-height:1.6;margin:0;padding:12px;background:var(--bg-secondary);border-radius:8px}
      @media(max-width:700px){.omc-media{grid-template-columns:1fr}dl>div{grid-template-columns:1fr;gap:3px}article{padding:13px}}
    `}</style>
  </section>;
}
