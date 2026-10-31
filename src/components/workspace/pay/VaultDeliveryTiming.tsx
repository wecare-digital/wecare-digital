/**
 * Operator-editable delay only between the paid invoice and Access Vault.
 * Processing -> Completed has a fixed 1s gap for Vault. All other steps before the paid receipt have no added wait.
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
        <p style={ { margin: 0 } }>Only Access Vault timing is editable. Native Review &amp; Pay and payment-to-Processing have no wait; Processing → Completed has a fixed 1-second gap; Completed → paid invoice has a 0-second gap. The customer must approve payment and retain a paid entitlement.</p>
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
        <strong>Other steps:</strong> Review &amp; Pay → customer approval → Processing (no wait) → Completed (fixed 1 second) → paid invoice (0 seconds).
        All transitions still require their payment and provider-status gates.
      </p>
      { error && <p role="alert" style={ { color: '#b91c1c' } }>{ error }</p> }
      { message && <p role="status">{ message }</p> }
      <div><button type="button" disabled={ loading || saving || !canSave } onClick={ () => { void save(); } }>
        { saving ? 'Saving…' : 'Save delivery timing' }
      </button></div>
      <section aria-label="Approved Vault WhatsApp template IDs" style={ { display: 'grid', gap: 10, maxWidth: 960 } }>
        <h3 style={ { margin: 0, fontSize: 16 } }>Approved template IDs · read-only live catalogue</h3>
        <p style={ { margin: 0, fontSize: 12 } }>
          Names and Meta IDs below come from the server&apos;s service-pricing contract, not from a staff text field.
          If unavailable, verify the template registry before sending.
        </p>
        <div style={ { overflowX: 'auto' } }>
          <table style={ { width: '100%', minWidth: 620, borderCollapse: 'collapse', fontSize: 12 } }>
            <thead><tr style={ { textAlign: 'left', borderBottom: '1px solid var(--border)' } }>
              <th scope="col">Send</th><th scope="col">Meta template</th><th scope="col">Template ID</th><th scope="col">Timing</th>
            </tr></thead>
            <tbody>
              { [
                { step: 'Review & Pay', name: templates?.nativePay, id: templates?.templateIds?.nativePay, when: 'Customer approval; no added delay' },
                { step: 'Processing', name: templates?.orderStatus, id: templates?.templateIds?.orderStatus, when: 'After verified capture; no added delay' },
                { step: 'Completed', name: templates?.orderStatus, id: templates?.templateIds?.orderStatus, when: 'Fixed 1s after accepted Processing' },
                { step: 'Paid invoice image', name: templates?.receipt, id: templates?.templateIds?.receipt, when: '0s after Completed, once issued' },
                { step: 'Access Vault link', name: templates?.delivery, id: templates?.templateIds?.delivery, when: `${ value.postReceiptAccessGapSeconds }s after invoice acceptance` },
              ].map( item => (
                <tr key={ item.step } style={ { borderBottom: '1px solid var(--border-light, var(--border))' } }>
                  <td style={ { padding: '10px 6px' } }>{ item.step }</td>
                  <td style={ { padding: '10px 6px' } }><code>{ item.name || 'Server quote unavailable' }</code></td>
                  <td style={ { padding: '10px 6px' } }><code>{ item.id || 'ID verification pending' }</code></td>
                  <td style={ { padding: '10px 6px' } }>{ item.when }</td>
                </tr>
              ) ) }
            </tbody>
          </table>
        </div>
        <p style={ { margin: 0, fontSize: 12 } }>
          The approved download button points to <code>{ 'https://wecare.digital/vault/?file={{1}}' }</code>.
          WhatsApp replaces <code>{ '{{1}}' }</code> with the server-bound file ID.
          This customer-facing Vault page is not a presigned S3 document URL.
        </p>
      </section>
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
