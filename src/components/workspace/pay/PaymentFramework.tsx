import React from 'react';
import Link from 'next/link';
import OutgoingMessageContent from './OutgoingMessageContent';
import * as api from '../../../api/client';
import {FRAMEWORK_TEMPLATES, FRAMEWORK_INPUTS, FRAMEWORK_GAPS, frameworkStages,
  frameworkCounts, type FrameworkSection, type TemplateRole} from '../../../lib/paymentFramework';

type Lookup = {status: string; verified: boolean; components?: unknown[]};
const LABELS: Record<FrameworkSection, string> = {collect: 'Collect', vault: 'Vault', contribute: 'Contribute'};

/** Inspection only: no send, upload, config-write, payment or grant endpoint is used. */
const PaymentFramework: React.FC<{section: FrameworkSection}> = ({section}) => {
  const stages = frameworkStages(section);
  const counts = frameworkCounts(section);
  const roles = Array.from(new Set(stages.flatMap(stage => stage.role ? [stage.role] : [])));
  const [lookups, setLookups] = React.useState<Partial<Record<TemplateRole, Lookup>>>({});
  const [timing, setTiming] = React.useState('Saved timing not checked');
  const [loading, setLoading] = React.useState(true);
  const [refresh, setRefresh] = React.useState(0);
  const [checkedAt, setCheckedAt] = React.useState('');

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    setLookups({});
    setCheckedAt('');
    setTiming('Reading saved access timing…');
    const selectedRoles: TemplateRole[] = section === 'vault'
      ? ['payment', 'status', 'invoice', 'access'] : ['payment', 'status', 'invoice'];
    const templateReads = Promise.all(selectedRoles.map(async role => {
      const expected = FRAMEWORK_TEMPLATES[role];
      try {
        const row = await api.getTemplateDetails(expected.id);
        const exact = row?.name === expected.name && (!row.id || String(row.id) === expected.id);
        return [role, {status: exact ? String(row?.status || 'UNKNOWN').toUpperCase() : 'IDENTITY NOT VERIFIED',
          verified: exact && String(row?.status || '').toUpperCase() === 'APPROVED',
          components: exact && Array.isArray(row?.components) ? row.components : undefined}] as const;
      } catch {
        return [role, {status: 'LOOKUP UNAVAILABLE', verified: false}] as const;
      }
    }));
    const timingRead = section === 'vault' ? api.getSystemConfigResult('vault_delivery_timing_v1')
      .then(result => {
        if (!result.ok) return 'Saved timing unavailable · server fallback is 4 seconds';
        if (result.data.config === null) return 'No saved setting · server fallback is 4 seconds';
        const raw = result.data.config as Record<string, unknown>;
        const value = raw?.postReceiptAccessGapSeconds;
        return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 5
          ? `Saved spacing: ${value} seconds after paid invoice acceptance`
          : 'Saved timing invalid · server fallback is 4 seconds';
      }).catch(() => 'Saved timing unavailable · server fallback is 4 seconds')
      : Promise.resolve('No editable message delay for this section');
    void Promise.all([templateReads, timingRead]).then(([templates, savedTiming]) => {
      if (!active) return;
      setLookups(Object.fromEntries(templates));
      setTiming(savedTiming);
      setCheckedAt(new Date().toLocaleString('en-IN', {timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short'}));
      setLoading(false);
    });
    return () => { active = false; };
  }, [section, refresh]);

  return (
    <section className="pf" aria-labelledby="pf-title" aria-busy={loading}>
      <header className="pf-head">
        <div>
          <p className="pf-kicker">{LABELS[section]} / FRAMEWORK</p>
          <h2 id="pf-title">Message and payment framework</h2>
          <p>Standard native-payment journey: <strong>{counts.templates} distinct templates</strong>,{' '}
            <strong>{counts.messages} planned outgoing template messages</strong>.
            Processing and Completed reuse one template. Failures and optional resends can change actual counts.</p>
        </div>
        <button type="button" onClick={() => setRefresh(current => current + 1)} disabled={loading}>
          {loading ? 'Checking references…' : 'Refresh template and timing checks'}
        </button>
      </header>
      <p className="pf-status" role="status">Source-defined framework · {checkedAt ? `lookups checked ${checkedAt} IST` : 'live lookups pending'}.
        {' '}Template approval lookup does not prove a customer send, delivery or payment.</p>

      <section aria-labelledby="pf-templates">
        <h3 id="pf-templates">1. Templates and variable parameters</h3>
        <div className="pf-table-wrap">
          <table>
            <thead><tr><th>Template / source registry ID</th><th>Outgoing shape</th><th>Variable parameters</th><th>Current lookup</th></tr></thead>
            <tbody>{roles.map(role => {
              const template = FRAMEWORK_TEMPLATES[role];
              return <tr key={role}>
                <td><code>{template.name}</code><small>{template.id} · source reference</small></td>
                <td>{template.shape}</td><td>{template.variables}</td>
                <td>{loading ? 'Checking…' : lookups[role]?.status || 'Not verified'}
                  {lookups[role]?.verified && <small>Registry approval only; sender validates components/readiness.</small>}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
      </section>

      <OutgoingMessageContent section={section} definitions={Object.fromEntries(
        Object.entries(lookups).map(([role, value]) => [role, value.components]))} />

      <section aria-labelledby="pf-sequence">
        <h3 id="pf-sequence">2. Order, timing and response at each step</h3>
        <p>{timing}. All timings below describe deliberate spacing or event gates; no actual delivery lag is measured here.</p>
        <ol className="pf-stages">{stages.map(stage => (
          <li key={stage.name}>
            <div className="pf-stage-head"><h4>{stage.name}</h4><span>{stage.direction} · {stage.type}</span></div>
            {stage.role && <code>{FRAMEWORK_TEMPLATES[stage.role].name}</code>}
            <dl><div><dt>Gate</dt><dd>{stage.gate}</dd></div>
              <div><dt>Time lag</dt><dd>{stage.timing}</dd></div>
              <div><dt>Response / evidence</dt><dd>{stage.response}</dd></div></dl>
          </li>
        ))}</ol>
        {section === 'vault' && <Link href="/workspace/payments?view=timing">Open existing Access Vault delay settings</Link>}
      </section>

      <section aria-labelledby="pf-inputs">
        <h3 id="pf-inputs">3. Variable input section</h3>
        <div className="pf-table-wrap"><table>
          <thead><tr><th>Input</th><th>Where it comes from</th><th>Who controls it</th></tr></thead>
          <tbody>{FRAMEWORK_INPUTS[section].map(input => <tr key={input.field}>
            <td>{input.field}</td><td>{input.source}</td><td>{input.control}</td>
          </tr>)}</tbody>
        </table></div>
        <p>This is an input inventory. Edit values only in the owning Create form or settings screen; this framework cannot send or change a payment.</p>
      </section>

      <section aria-labelledby="pf-response-types">
        <h3 id="pf-response-types">4. Interactive messages, incoming replies and events</h3>
        <div className="pf-table-wrap"><table>
          <thead><tr><th>Direction / type</th><th>Meaning and handling</th><th>Money or access effect</th></tr></thead>
          <tbody>
            <tr><td>Outgoing template · ORDER_DETAILS</td><td>Approved native Review &amp; Pay button opens checkout.</td><td>Requests payment; does not capture money.</td></tr>
            <tr><td>Outgoing template · ORDER_STATUS</td><td>Processing / Completed use the approved status template. Approved status template only.</td><td>Reflects an already verified money event; not proof of shipment fulfilment.</td></tr>
            <tr><td>Outgoing template · FLOW button</td><td>Paid invoice contains the review Flow. A Flow button inside a template is still a template send.</td><td>Optional feedback; does not authorize another payment.</td></tr>
            <tr><td>Incoming interactive.nfm_reply</td><td>Review/Flow completion is checked server-side. Address submissions use name=address_message and route separately when a cart needs an address.</td><td>A form reply is not payment evidence.</td></tr>
            <tr><td>Incoming interactive.button_reply / list_reply / button</td><td>Recorded as incoming inbox evidence. No standalone button/list navigation sender or automatic menu reply is provided.</td><td>No payment/access authority from a tap alone. Retired Unlock Vault offers must not be reissued.</td></tr>
            <tr><td>Incoming text / media / order</td><td>Inbox handles conversation/media. A catalog order uses the separate native-cart path; it is not the staff Contribute sender.</td><td>Must pass its own identity, pricing and payment gates.</td></tr>
            <tr><td>Incoming provider status event</td><td>Sent, delivered, read or failed status updates correlate through message IDs. This is transport evidence, not a customer form response.</td><td>No payment capture or private-file entitlement.</td></tr>
            <tr><td>Incoming verified payment webhook</td><td>Backend reconciles provider capture, immutable reference, amount and currency.</td><td>Updates money state and triggers eligible post-payment work.</td></tr>
            {section === 'vault' && <tr><td>Outgoing URL → incoming website/API request</td><td>Access Vault opens the owner-bound website; customer signs in and requests the exact file.</td><td>Verified first download starts the single 24-hour paid window. WhatsApp read/URL click does not start it.</td></tr>}
          </tbody>
        </table></div>
      </section>

      <section aria-labelledby="pf-gaps">
        <h3 id="pf-gaps">5. Missing evidence, recovery and gaps</h3>
        <div className="pf-gaps">{FRAMEWORK_GAPS.map(gap => <details key={gap.title}>
          <summary>{gap.title}</summary><p>{gap.detail}</p>
        </details>)}</div>
        <p>Also reconcile cancellation/refund outcomes, expired access, template rejection, recipient mismatch, unknown sends and paid-but-undelivered files through their existing records. None should be treated as a new payable journey automatically.</p>
      </section>
      <footer>Source references: shared whatsapp_templates registry · invoice-engine · Razorpay webhook · paid_vault delivery · inbound WhatsApp handlers · workspace forms. This map covers Collect, Vault and Contribute.</footer>
      <style jsx>{`
        .pf{display:grid;grid-template-columns:minmax(0,1fr);gap:26px;max-width:1340px;min-width:0;padding:8px 0 32px;color:var(--text-primary)}
        .pf>section,.pf-head,.pf-head>div{min-width:0}
        .pf-head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap}
        .pf-kicker{font-size:11px;font-weight:800;letter-spacing:.08em;margin:0 0 6px;color:var(--text-muted)}
        h2{font-size:clamp(23px,3vw,31px);margin:0 0 9px}h3{font-size:18px;margin:0 0 12px}h4{font-size:15px;margin:0}
        p,footer{font-size:13px;line-height:1.65;color:var(--text-muted);margin:8px 0;max-width:1000px}
        .pf-head p{max-width:830px}.pf-status{margin:0}
        button,.pf :global(a){min-height:44px;padding:10px 14px;border:1px solid var(--border);border-radius:10px;font:inherit;font-size:12px;font-weight:750;color:var(--text-primary);background:var(--surface);cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}
        button:disabled{opacity:.6;cursor:default}button:focus-visible,.pf :global(a:focus-visible),summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
        .pf-table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
        table{width:100%;border-collapse:collapse;text-align:left;table-layout:fixed}th,td{padding:13px;vertical-align:top;border-bottom:1px solid var(--border);font-size:12px;line-height:1.6;overflow-wrap:anywhere}th{color:var(--text-muted);background:var(--bg-secondary);font-weight:750}tr:last-child td{border-bottom:0}
        code{font-size:11px;overflow-wrap:anywhere}small{display:block;margin-top:5px;color:var(--text-muted);font-size:11px}
        .pf-stages{padding-left:26px;margin:14px 0;display:grid;gap:12px}.pf-stages li{padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
        .pf-stage-head{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:8px}.pf-stage-head span{font-size:11px;color:var(--text-muted)}
        dl{display:grid;gap:7px;margin:10px 0 0}dl>div{display:grid;grid-template-columns:140px 1fr;gap:12px}dt,dd{font-size:12px;line-height:1.6}dt{color:var(--text-muted)}dd{margin:0}
        .pf-gaps{display:grid;gap:8px}details{border-bottom:1px solid var(--border);padding-bottom:8px}summary{min-height:44px;padding:10px 0;font-size:13px;font-weight:750;cursor:pointer}details p{margin:0 0 10px}
        footer{border-top:1px solid var(--border);padding-top:16px;margin:0}
        @media(max-width:700px){table{min-width:650px}.pf-head{display:grid;grid-template-columns:minmax(0,1fr)}.pf-head button{justify-content:center}.pf-stages{padding-left:20px}.pf-stages li{padding:12px}dl>div{grid-template-columns:1fr;gap:2px}.pf{gap:22px}}
      `}</style>
    </section>
  );
};
export default PaymentFramework;
