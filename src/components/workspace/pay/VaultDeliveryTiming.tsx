/**
 * Operator-editable delay only between the paid invoice and Access Vault.
 * Processing -> Completed has a fixed 1s gap for Vault. All other steps before the paid receipt have no added wait.
 * Payment capture and exact-file entitlement remain mandatory event gates.
 */
import React from 'react';
import Link from 'next/link';
import * as api from '../../../api/client';
import { useConfirm } from '../../../contexts/ConfirmContext';
import { fetchServicePrices, type ServicePaymentTemplates } from '../../../lib/servicePricing';
import { parseVaultJourney, type VaultRegistryJourney } from './VaultJourneyPreview';
import PaymentTemplateMedia from './PaymentTemplateMedia';

const CONFIG_KEY = 'vault_delivery_timing_v1';
const DEFAULTS = { postReceiptAccessGapSeconds: 4 } as const;
type Timing = { postReceiptAccessGapSeconds: number };

export const validVaultDelay = ( value: unknown ): value is number =>
  typeof value === 'number' && Number.isInteger( value ) && value >= 0 && value <= 5;

export function readVaultTiming( raw: unknown ): Timing | null {
  if ( !raw || typeof raw !== 'object' ) return null;
  const value = raw as Record<string, unknown>;
  // Older records may also contain orderStatusGapSeconds. Ignore that
  // retired setting; every new write contains only the access delay.
  if ( !validVaultDelay( value.postReceiptAccessGapSeconds ) ) return null;
  return { postReceiptAccessGapSeconds: value.postReceiptAccessGapSeconds };
}

const VaultDeliveryTiming: React.FC = () => {
  const confirm = useConfirm();
  const [ value, setValue ] = React.useState<Timing>( { ...DEFAULTS } );
  const [ loading, setLoading ] = React.useState( true );
  const [ saving, setSaving ] = React.useState( false );
  const [ message, setMessage ] = React.useState( '' );
  const [ error, setError ] = React.useState( '' );
  const [ canSave, setCanSave ] = React.useState( false );
  const [ settingSource, setSettingSource ] = React.useState<'saved' | 'default' | 'unavailable'>( 'unavailable' );
  const [ templates, setTemplates ] = React.useState<ServicePaymentTemplates | null>( null );
  const [ registry, setRegistry ] = React.useState<VaultRegistryJourney | null>( null );
  const [ retryRead, setRetryRead ] = React.useState( 0 );

  React.useEffect( () => {
    let current = true;
    setLoading( true );
    setCanSave( false );
    setSettingSource( 'unavailable' );
    void api.getSystemConfigResult( CONFIG_KEY ).then( result => {
      if ( !current ) return;
      if ( !result.ok ) {
        const status = result.failure.status;
        setError( status === 400
          ? 'The live settings API does not recognize Vault access timing yet (HTTP 400). Update wecare-ai-config-management before saving.'
          : status === 401 || status === 403
            ? 'Staff authorization is required to read and save Vault access timing. Check your session and permissions.'
            : 'Vault timing read failed' + ( status ? ' (HTTP ' + status + ')' : '' )
              + '. Saving is disabled until the server confirms the current value.' );
        return;
      }
      const configured = readVaultTiming( result.data.config );
      if ( result.data.config !== null && !configured ) {
        setError( 'The saved access delay is invalid. Ask an administrator to reconcile it before editing.' );
      } else {
        setValue( configured || { ...DEFAULTS } );
        setSettingSource( configured ? 'saved' : 'default' );
        setCanSave( true );
        setError( '' );
      }
    } ).catch( () => {
      if ( current ) setError( 'Unable to reach the settings API. Saving remains disabled.' );
    } ).finally( () => { if ( current ) setLoading( false ); } );
    return () => { current = false; };
  }, [ retryRead ] );

  React.useEffect( () => {
    let current = true;
    void fetchServicePrices().then( prices => {
      if ( current ) setTemplates( prices.vault?.available ? prices.vault.templates || null : null );
    } ).catch( () => { /* Do not invent a catalogue price or template. */ } );
    // v71 can read this historical WABA1 registry even when service-prices
    // omits templateIds. Use IDs only when they match the named template.
    void api.getSystemConfigResult( 'vault_whatsapp_template_journey_v1' ).then( result => {
      if ( current && result.ok ) setRegistry( parseVaultJourney( result.data.config ) );
    } ).catch( () => { /* No unverified ID fallback on a failed read. */ } );
    return () => { current = false; };
  }, [] );

  const templateIdFor = ( role: string, expectedName: string, liveId?: string ) => {
    if ( liveId && /^[0-9]{10,25}$/.test( liveId ) )
      return { id: liveId, source: 'Service-pricing registry' };
    const recorded = registry?.steps.find( step => step.role === role );
    if ( recorded?.templateName === expectedName && /^[0-9]{10,25}$/.test( recorded.templateId ) )
      return { id: recorded.templateId, source: 'Saved journey reference · verify with Meta' };
    return { id: '', source: 'Template ID unavailable' };
  };
  const paymentName = templates?.nativePay || 'wecare_whatapp_native_pay_template';
  const statusName = templates?.orderStatus || 'wecare_order_status_v3';
  const invoiceName = templates?.receipt || 'wecare_default_invoice_image_template';
  const accessName = templates?.delivery || 'wecare_default_download';
  const paymentId = templateIdFor( 'native_payment', paymentName, templates?.templateIds?.nativePay );
  const statusId = templateIdFor( 'order_status', statusName, templates?.templateIds?.orderStatus );
  const invoiceId = templateIdFor( 'receipt', invoiceName, templates?.templateIds?.receipt );
  const accessId = templateIdFor( 'access', accessName, templates?.templateIds?.delivery );

  const update = ( raw: string ) => {
    setMessage( '' );
    setError( '' );
    const parsed = Number( raw );
    setValue( { postReceiptAccessGapSeconds: raw.trim() === '' ? -1 : parsed } );
  };

  const save = async () => {
    setMessage( '' );
    if ( loading || saving || !canSave ) return;
    if ( !validVaultDelay( value.postReceiptAccessGapSeconds ) ) {
      setError( 'The Access Vault delay must be a whole number from 0 to 5 seconds.' );
      return;
    }
    const approved = await confirm( {
      title: 'Save Access Vault delivery delay?',
      message: 'This changes only the pause after the paid invoice is accepted and before Access Vault. Processing, completed and receipt have no added wait. Payment capture and owner-bound access remain mandatory.',
      confirmText: 'Save timing',
    } );
    if ( !approved ) return;
    setSaving( true );
    try {
      const ok = await api.updateSystemConfig( CONFIG_KEY, value );
      if ( !ok ) {
        setError( 'Save could not be confirmed. Refresh before trying again.' );
        return;
      }
      setSettingSource( 'saved' );
      setMessage( 'Saved for later Vault payment journeys. Existing messages are unchanged.' );
    } catch {
      setError( 'Save status is unknown. Refresh the settings before trying again.' );
    } finally {
      setSaving( false );
    }
  };

  return (
    <section className="vdt-shell" aria-label="Vault delivery timing and approved message templates">
      <header className="vdt-header">
        <div>
          <p className="vdt-eyebrow">PAY &amp; FLOW / VAULT</p>
          <h2>Access Vault delivery timing</h2>
          <p>One editable delay, after verified payment and the accepted paid invoice.
            This changes neither payment approval nor the fixed message order.</p>
        </div>
        <Link href="/workspace/payments?view=vault" className="vdt-back">Back to Vault workbench</Link>
      </header>
      <div className="vdt-summary" aria-label="Payment message timing summary">
        <div><small>Processing → Completed</small><strong>1 second · fixed</strong></div>
        <div><small>Completed → GST invoice</small><strong>0 seconds added</strong></div>
        <div><small>Invoice accepted → Access Vault</small>
          <strong>{ value.postReceiptAccessGapSeconds >= 0 ? value.postReceiptAccessGapSeconds : '—' } seconds</strong>
          <span>{ settingSource === 'saved' ? 'Saved setting' : settingSource === 'default'
            ? 'Server default' : 'Saved value not verified' }</span>
        </div>
      </div>
      <div className="vdt-editor">
        <label htmlFor="vdt-access-seconds">Invoice → Access Vault delay (0–5 seconds)</label>
        <div className="vdt-input-row">
          <input id="vdt-access-seconds" aria-label="Paid invoice to Access Vault delay in seconds"
            aria-describedby="vdt-access-hint" type="number" inputMode="numeric"
            min="0" max="5" step="1"
            value={ value.postReceiptAccessGapSeconds }
            disabled={ loading || saving || !canSave }
            onChange={ event => update( event.target.value ) } />
          <span>seconds</span>
        </div>
        <p id="vdt-access-hint">
          Default is 4 seconds. Only whole numbers from 0 to 5 are allowed.
          The send still waits for verified payment, the invoice and delivery gates.
          This is not a timer for payment collection.
        </p>
        { error && (
          <div className="vdt-read-error" role="alert">
            <p className="vdt-error">{ error }</p>
            <button type="button" className="vdt-retry" disabled={ loading || saving }
              onClick={ () => { setError( '' ); setRetryRead( n => n + 1 ); } }>
              Retry settings read
            </button>
          </div>
        ) }
        { message && <p className="vdt-success" role="status">{ message }</p> }
        <button className="vdt-save" type="button" disabled={ loading || saving || !canSave }
          onClick={ () => { void save(); } }>
          { loading ? 'Loading setting…' : saving ? 'Saving…' : 'Save delivery timing' }
        </button>
      </div>
      <section className="vdt-template-section" aria-label="Read-only Vault WhatsApp send sequence">
        <div className="vdt-template-head">
          <h3>WhatsApp message sequence · read only</h3>
          <p>Service-pricing IDs are preferred. When unavailable, a read-only saved WABA1
            journey reference is shown and clearly marked for verification with Meta.
            Open the Vault workbench for actual template bodies and per-file delivery evidence.</p>
        </div>
        <div className="vdt-template-grid">
          { [
            { step: '1', title: 'Review & Pay', name: paymentName, ...paymentId,
              when: 'Native ORDER_DETAILS · customer approval' },
            { step: '2', title: 'Processing', name: statusName, ...statusId,
              when: 'After verified capture · no added wait' },
            { step: '3', title: 'Completed', name: statusName, ...statusId,
              when: 'Fixed 1 second after accepted Processing' },
            { step: '4', title: 'Paid GST invoice', name: invoiceName, ...invoiceId,
              when: 'When issued · no added wait · Leave Review Flow button' },
            { step: '5', title: 'Access Vault', name: accessName, ...accessId,
              when: value.postReceiptAccessGapSeconds >= 0
                ? value.postReceiptAccessGapSeconds + 's after accepted invoice' : 'Set a valid access delay' },
          ].map( item => (
            <article className="vdt-template-card" key={ item.step }>
              <header><span>{ item.step }</span><strong>{ item.title }</strong></header>
              <code>{ item.name || 'Registry unavailable' }</code>
              <small>Meta ID: { item.id || 'Not verified' }</small>
              <small className="vdt-source">{ item.source }</small>
              <p>{ item.when }</p>
            </article>
          ) ) }
        </div>
        <p className="vdt-template-note">
          The download button uses <code>{ 'https://wecare.digital/vault/?file={{1}}' }</code>,
          with an owner-bound file ID inserted server-side. No raw S3 link or new price is entered here.
        </p>
      </section>
      <details className="vdt-media">
        <summary>View approved WhatsApp header and item images</summary>
        <PaymentTemplateMedia serviceLabel="Vault" templates={ templates } signedPreview />
        <p>The approved S3 media is read only. The production sender checks the live images separately.</p>
      </details>
      <style jsx>{`
        .vdt-shell{min-width:0;display:grid;gap:16px;max-width:1050px;padding:16px 0 36px}
        .vdt-header{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap}
        .vdt-eyebrow{margin:0 0 5px;font-size:11px;font-weight:800;letter-spacing:.08em;color:#62816c}
        .vdt-header h2{margin:0 0 7px;font-size:clamp(21px,3vw,27px);color:var(--text)}
        .vdt-header p:not(.vdt-eyebrow){max-width:640px;margin:0;font-size:13px;line-height:1.55;color:var(--text-muted)}
        .vdt-back{min-height:44px;display:inline-flex;align-items:center;padding:8px 14px;border:1px solid #b9d5b1;border-radius:10px;background:#f3faef;color:#245134;font-size:12px;font-weight:750;text-decoration:none}
        .vdt-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
        .vdt-summary>div{display:grid;align-content:start;gap:5px;min-width:0;padding:15px;border:1px solid #dce9d7;border-radius:13px;background:#fff}
        .vdt-summary small{color:#536d5c;font-size:11px;line-height:1.45}
        .vdt-summary strong{color:#22502d;font-size:15px;overflow-wrap:anywhere}
        .vdt-summary span{color:#65786a;font-size:11px}
        .vdt-editor{display:grid;justify-items:start;gap:10px;padding:20px;border:1px solid #c4dbbc;border-radius:15px;background:#f7fcf3}
        .vdt-editor label{font-size:14px;font-weight:800;color:#1c4529}
        .vdt-input-row{display:flex;align-items:center;gap:12px}
        .vdt-input-row input{box-sizing:border-box;width:110px;min-height:48px;padding:8px 12px;border:2px solid #adcda4;border-radius:10px;background:#fff;color:#193f27;font:700 18px var(--font-sans)}
        .vdt-input-row span{font-size:12px;color:#4b6652}
        .vdt-editor p{margin:0;max-width:700px;font-size:12px;line-height:1.55;color:#506957}
        .vdt-editor .vdt-error{color:#9c3327;font-weight:700}
        .vdt-read-error{display:grid;gap:9px;justify-items:start}
        .vdt-retry{min-height:44px;padding:8px 14px;border:1px solid #bcad8d;border-radius:9px;background:#fff;color:#7d5024;font:700 12px var(--font-sans);cursor:pointer}
        .vdt-editor .vdt-success{color:#256036;font-weight:700}
        .vdt-save{min-height:48px;border:1px solid #a9d17d;border-radius:10px;background:var(--lime,#d2f476);color:#21452b;font:750 13px var(--font-sans);padding:10px 20px;cursor:pointer}
        .vdt-save:disabled{opacity:.55;cursor:default}
        .vdt-template-section{min-width:0;display:grid;gap:13px;padding:18px;border:1px solid #dce7d8;border-radius:14px;background:#fff}
        .vdt-template-head h3{margin:0 0 5px;font-size:17px;color:#1c4228}
        .vdt-template-head p{margin:0;font-size:12px;line-height:1.5;color:#66776b}
        .vdt-template-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
        .vdt-template-card{display:grid;align-content:start;gap:7px;min-width:0;border:1px solid #dbe7d7;border-radius:11px;padding:13px;background:#fbfdf9}
        .vdt-template-card header{display:flex;align-items:center;gap:9px}
        .vdt-template-card header span{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;background:#dff2bd;color:#22522f;font-size:12px;font-weight:800}
        .vdt-template-card header strong{font-size:13px;color:#244c30}
        .vdt-template-card code{font-size:11px;line-height:1.45;overflow-wrap:anywhere}
        .vdt-template-card small{font-size:11px;color:#607968;overflow-wrap:anywhere}
        .vdt-template-card .vdt-source{font-weight:700;color:#456d4c}
        .vdt-template-card p{margin:0;font-size:12px;line-height:1.5;color:#3d5a44}
        .vdt-template-note{font-size:12px;line-height:1.6;color:#526c5a;overflow-wrap:anywhere;margin:0}
        .vdt-template-note code{overflow-wrap:anywhere}
        .vdt-media{border:1px solid #dbe8d5;border-radius:12px;background:#fff;padding:13px}
        .vdt-media summary{display:flex;align-items:center;min-height:44px;font-size:13px;font-weight:750;color:#31563a;cursor:pointer}
        .vdt-media p{font-size:12px;color:#5c7460;line-height:1.5}
        .vdt-back:focus-visible,.vdt-save:focus-visible,.vdt-retry:focus-visible,.vdt-media summary:focus-visible{outline:3px solid #2d6b36;outline-offset:2px}
        .vdt-input-row input:focus-visible{outline:3px solid #2d6b36;outline-offset:2px}
        @media(max-width:660px){
          .vdt-shell{padding:12px 0 24px;gap:13px}
          .vdt-back{width:100%;box-sizing:border-box;justify-content:center}
          .vdt-summary,.vdt-template-grid{grid-template-columns:1fr}
          .vdt-editor,.vdt-template-section{padding:13px}
          .vdt-save,.vdt-retry{width:100%}
          .vdt-input-row input{font-size:18px}
        }
      `}</style>
    </section>
  );
};
export default VaultDeliveryTiming;
