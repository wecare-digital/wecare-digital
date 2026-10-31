/**
 * Operator-editable delay only between the paid invoice and Access Vault.
 * Native Review & Pay, processing, completed and receipt have no added wait.
 * Payment capture and exact-file entitlement remain mandatory event gates.
 */
import React from 'react';
import * as api from '../../../api/client';
import { useConfirm } from '../../../contexts/ConfirmContext';
import { fetchServicePrices, type ServicePaymentTemplates } from '../../../lib/servicePricing';
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
        <h2 style={ { margin: '0 0 8px' } }>Access Vault delivery delay</h2>
        <p style={ { margin: 0 } }>The only adjustable WhatsApp delay is after the paid receipt. Native Review &amp; Pay, processing, completed and invoice have no artificial wait. The customer still authorizes payment, and a paid entitlement is required to send access.</p>
      </div>
      <div style={ { display: 'grid', gap: 14, maxWidth: 530 } }>
        <label style={ { display: 'grid', gap: 6 } }>
          <strong>Accepted paid invoice → Access Vault (seconds)</strong>
          <input aria-label="Paid invoice to Access Vault delay in seconds" type="number" min="0" max="5" step="1"
            value={ value.postReceiptAccessGapSeconds }
            disabled={ loading || saving || !canSave }
            onChange={ event => update( event.target.value ) } />
          <small>Default 4 seconds; editable 0–5 seconds. This is not a delivered/read acknowledgment or a second payment.</small>
        </label>
      </div>
      <p style={ { margin: 0, fontSize: 13 } }>
        <strong>Other steps:</strong> Review &amp; Pay → customer approval → processing → completed → paid invoice: event-gated and sent without an added timer.
      </p>
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
