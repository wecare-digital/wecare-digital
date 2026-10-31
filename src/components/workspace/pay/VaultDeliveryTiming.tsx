/**
 * Operator-editable, bounded Vault WhatsApp spacing (not a delivery-order guarantee).
 * Payment capture, paid invoice issuance and the private-file entitlement are
 * event/ownership gated by the backend; these intervals cannot change that.
 */
import React from 'react';
import * as api from '../../../api/client';
import { useConfirm } from '../../../contexts/ConfirmContext';
import { fetchServicePrices, type ServicePaymentTemplates } from '../../../lib/servicePricing';
import PaymentTemplateMedia from './PaymentTemplateMedia';

const CONFIG_KEY = 'vault_delivery_timing_v1';
const DEFAULTS = { orderStatusGapSeconds: 2, postReceiptAccessGapSeconds: 4 } as const;
type Timing = { orderStatusGapSeconds: number; postReceiptAccessGapSeconds: number };

export const validVaultDelay = ( value: unknown ): value is number =>
  typeof value === 'number' && Number.isInteger( value ) && value >= 0 && value <= 5;

export function readVaultTiming( raw: unknown ): Timing | null {
  if ( !raw || typeof raw !== 'object' ) return null;
  const value = raw as Record<string, unknown>;
  if ( !validVaultDelay( value.orderStatusGapSeconds )
    || !validVaultDelay( value.postReceiptAccessGapSeconds ) ) return null;
  return {
    orderStatusGapSeconds: value.orderStatusGapSeconds,
    postReceiptAccessGapSeconds: value.postReceiptAccessGapSeconds,
  };
}

const VaultDeliveryTiming: React.FC = () => {
  const confirm = useConfirm();
  const [ value, setValue ] = React.useState<Timing>( { ...DEFAULTS } );
  const [ loading, setLoading ] = React.useState( true );
  const [ saving, setSaving ] = React.useState( false );
  const [ message, setMessage ] = React.useState( '' );
  const [ error, setError ] = React.useState( '' );
  const [ canSave, setCanSave ] = React.useState( true );
  const [ templates, setTemplates ] = React.useState<ServicePaymentTemplates | null>( null );

  React.useEffect( () => {
    let current = true;
    void api.getSystemConfigResult( CONFIG_KEY ).then( result => {
      if ( !current ) return;
      if ( !result.ok ) {
        setError( 'Timing settings could not be read; saving is disabled until they load.' );
        setCanSave( false );
        return;
      }
      const configured = readVaultTiming( result.data.config );
      if ( result.data.config !== null && !configured ) {
        setError( 'Saved timing settings are invalid. Ask an administrator to reconcile them.' );
        setCanSave( false );
      } else {
        setValue( configured || { ...DEFAULTS } );
        setCanSave( true );
        setError( '' );
      }
    } ).catch( () => {
      if ( current ) {
        setCanSave( false );
        setError( 'Timing settings could not be read.' );
      }
    } ).finally( () => { if ( current ) setLoading( false ); } );
    void fetchServicePrices().then( prices => {
      if ( current ) setTemplates( prices.vault?.available ? prices.vault.templates || null : null );
    } ).catch( () => { /* Keep the image preview safely unavailable. */ } );
    return () => { current = false; };
  }, [] );

  const update = ( key: keyof Timing, raw: string ) => {
    setMessage( '' );
    setError( '' );
    const parsed = Number( raw );
    setValue( current => ({ ...current, [key]: raw.trim() === '' ? -1 : parsed }) );
  };

  const save = async () => {
    setMessage( '' );
    if ( loading || saving || !canSave ) return;
    if ( !validVaultDelay( value.orderStatusGapSeconds )
      || !validVaultDelay( value.postReceiptAccessGapSeconds ) ) {
      setError( 'Each delay must be a whole number from 0 to 5 seconds.' );
      return;
    }
    const approved = await confirm( {
      title: 'Save Vault WhatsApp timing?',
      message: 'Changes affect later payment messages only. Payment capture, invoice and access gates remain mandatory. WhatsApp delivery order is not guaranteed.',
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
      setMessage( 'Saved for later Vault payment journeys. Existing messages are unchanged.' );
    } catch {
      setError( 'Save status is unknown. Refresh the settings before trying again.' );
    } finally {
      setSaving( false );
    }
  };

  return (
    <section style={ { display: 'grid', gap: 18, maxWidth: 980, padding: '12px 0 32px' } } aria-label="Vault delivery timing and media">
      <div>
        <h2 style={ { margin: '0 0 8px' } }>Vault WhatsApp delivery timing</h2>
        <p style={ { margin: 0 } }>Only operators can save. These short delays space accepted WhatsApp sends; they do not replace payment confirmation or delivered/read webhooks.</p>
      </div>
      <div style={ { display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))' } }>
        <label style={ { display: 'grid', gap: 6 } }>
          <strong>Between payment updates and receipt (seconds)</strong>
          <input aria-label="Order status and receipt gap in seconds" type="number" min="0" max="5" step="1"
            value={ value.orderStatusGapSeconds }
            disabled={ loading || saving || !canSave }
            onChange={ event => update( 'orderStatusGapSeconds', event.target.value ) } />
          <small>Applied after processing and after completed, before the paid invoice send.</small>
        </label>
        <label style={ { display: 'grid', gap: 6 } }>
          <strong>Between accepted invoice and Access Vault (seconds)</strong>
          <input aria-label="Invoice to access gap in seconds" type="number" min="0" max="5" step="1"
            value={ value.postReceiptAccessGapSeconds }
            disabled={ loading || saving || !canSave }
            onChange={ event => update( 'postReceiptAccessGapSeconds', event.target.value ) } />
          <small>Access remains owner-bound and requires a verified paid entitlement.</small>
        </label>
      </div>
      { error && <p role="alert" style={ { color: '#b91c1c' } }>{ error }</p> }
      { message && <p role="status">{ message }</p> }
      <div><button type="button" disabled={ loading || saving || !canSave } onClick={ () => { void save(); } }>
        { saving ? 'Saving…' : 'Save delivery timing' }
      </button></div>
      <PaymentTemplateMedia serviceLabel="Vault" templates={ templates } signedPreview />
      <p style={ { fontSize: 13, color: 'var(--text-muted)' } }>
        The header and item images are approved S3 assets. The signed preview is short-lived and
        for staff inspection only. The payment sender uses its separately validated approved media;
        staff cannot replace either image or the catalogue price here.
      </p>
    </section>
  );
};
export default VaultDeliveryTiming;
