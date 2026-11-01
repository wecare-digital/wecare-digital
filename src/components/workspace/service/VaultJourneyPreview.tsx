/**
 * Vault ledger-style, read-only review of the exact file and the approved WhatsApp
 * journey. This is not a second payment engine or a WhatsApp template editor.
 *
 * The journey order / trigger / spacing is read from the staff-only SystemConfig
 * record. Body copy below is a visual reference to approved Meta templates; only
 * the existing sender and Meta decide the actual message and dynamic payload.
 */
import React from 'react';
import Link from 'next/link';
import { getSystemConfigResult, getTemplateDetails, type SecureFile } from '../../../api/client';
import {
  rupeesFromPaise,
  type ServicePaymentTemplates,
  type ServicePriceBreakdown,
} from '../../../lib/servicePricing';
import styles from './VaultJourneyPreview.module.css';
import VaultMessageTimeline from './VaultMessageTimeline';
import PaymentTemplateMedia from '../pay/PaymentTemplateMedia';

export interface VaultRegistryStep {
  step: number;
  templateId: string;
  templateName: string;
  trigger: string;
  role: string;
  sendCount: number;
  defaultDelaySeconds: number;
  headerMode?: string;
  buttonText?: string;
  flowId?: string;
  buttonUrl?: string;
}

export interface VaultRegistryJourney {
  journeyId: string;
  configurationMode: string;
  steps: VaultRegistryStep[];
  normalMessageCountOnFullManualPath: number;
}

/** Reject malformed configuration instead of rendering misleading partial payment steps. */
export function parseVaultJourney ( value: unknown ): VaultRegistryJourney | null {
  if ( !value || typeof value !== 'object' ) return null;
  const raw = value as Record<string, unknown>;
  const legacy = raw.journeyId === 'VAULT_WA_MANUAL_OFFER_V1';
  if ( !legacy && raw.journeyId !== 'VAULT_WA_DIRECT_PAYMENT_V2' ) return null;
  const expected = legacy
    ? [ 'ready_offer', 'native_payment', 'order_status', 'receipt', 'access' ]
    : [ 'native_payment', 'order_status', 'receipt', 'access' ];
  if ( raw.schemaVersion !== 1 || !Array.isArray( raw.steps ) || raw.steps.length !== expected.length ) return null;
  const steps: VaultRegistryStep[] = [];
  for ( let index = 0; index < expected.length; index += 1 ) {
    const step = raw.steps[ index ] as Partial<VaultRegistryStep> | undefined;
    if ( !step || typeof step !== 'object'
      || step.step !== index + 1 || step.role !== expected[ index ]
      || typeof step.templateId !== 'string' || !/^[0-9]+$/.test( step.templateId )
      || typeof step.templateName !== 'string' || !step.templateName
      || typeof step.trigger !== 'string'
      || typeof step.sendCount !== 'number' || step.sendCount < 1
      || typeof step.defaultDelaySeconds !== 'number' || step.defaultDelaySeconds < 0 ) return null;
    steps.push( {
      step: step.step,
      templateId: step.templateId,
      templateName: step.templateName,
      trigger: step.trigger,
      role: step.role,
      sendCount: step.sendCount,
      defaultDelaySeconds: step.defaultDelaySeconds,
      headerMode: typeof step.headerMode === 'string' ? step.headerMode : undefined,
      buttonText: typeof step.buttonText === 'string' ? step.buttonText : undefined,
      flowId: typeof step.flowId === 'string' ? step.flowId : undefined,
      buttonUrl: typeof step.buttonUrl === 'string' ? step.buttonUrl : undefined,
    } );
  }
  return {
    journeyId: String( raw.journeyId ),
    configurationMode: typeof raw.configurationMode === 'string' ? raw.configurationMode : '',
    normalMessageCountOnFullManualPath:
      typeof raw.normalMessageCountOnFullManualPath === 'number'
        ? raw.normalMessageCountOnFullManualPath : 6,
    // Keep old send metadata for historical audit, but never render it as
    // a stage or offer an operator any new Unlock Vault action.
    steps: steps.filter( step => step.role !== 'ready_offer' ),
  };
}

type Mode = 'upload' | 'existing';
interface Props {
  mode: Mode;
  customerName: string;
  customerPhone: string;
  draftFile: File | null;
  selectedFile: SecureFile | null;
  pricePaise: number | null;
  paymentItemDescription: string;
  onPaymentItemDescriptionChange: ( value: string ) => void;
  breakdown: ServicePriceBreakdown | null;
  templates: ServicePaymentTemplates | null;
  priceLoading: boolean;
  journey: VaultRegistryJourney | null;
  journeyError: string;
  onCopyFileId: () => void;
  onStaffDownload: () => void;
}

const stages = [
  { step: 2, name: 'Review & Pay', trigger: 'Staff or customer requests native payment', fallback: 'wecare_whatapp_native_pay_template' },
  { step: 3, name: 'Order updates', trigger: 'Captured payment', fallback: 'wecare_order_status_v3' },
  { step: 4, name: 'Paid invoice', trigger: 'Invoice is ready', fallback: 'wecare_default_invoice_image_template' },
  { step: 5, name: 'Access Vault', trigger: 'Paid entitlement granted', fallback: 'wecare_default_download' },
] as const;

const currency = ( value: number | undefined | null ): string =>
  typeof value === 'number' ? '₹' + rupeesFromPaise( value ) : '—';

function fileSize ( bytes: number | undefined ): string {
  if ( !bytes || bytes < 0 ) return '—';
  if ( bytes < 1024 ) return String( bytes ) + ' B';
  if ( bytes < 1024 * 1024 ) return ( bytes / 1024 ).toFixed( 1 ) + ' KB';
  return ( bytes / 1048576 ).toFixed( 1 ) + ' MB';
}

type MetaTemplateCopy = { body: string; footer: string; buttons: string[]; status: string };

/** Only render actual text if the staff Meta template read supplied its BODY.
 * Never present a hand-authored illustration as approved live copy. */
export function parseMetaTemplateCopy ( raw: unknown ): MetaTemplateCopy | null {
  if ( !raw || typeof raw !== 'object' ) return null;
  const row = raw as Record<string, unknown>;
  if ( !Array.isArray( row.components ) ) return null;
  let body = '';
  let footer = '';
  const buttons: string[] = [];
  for ( const value of row.components ) {
    if ( !value || typeof value !== 'object' ) continue;
    const part = value as Record<string, unknown>;
    const kind = String( part.type || '' ).toUpperCase();
    if ( kind === 'BODY' && typeof part.text === 'string' ) body = part.text;
    if ( kind === 'FOOTER' && typeof part.text === 'string' ) footer = part.text;
    if ( kind === 'BUTTONS' && Array.isArray( part.buttons ) ) {
      for ( const entry of part.buttons ) {
        if ( entry && typeof entry === 'object'
          && typeof ( entry as Record<string, unknown> ).text === 'string' )
          buttons.push( String( ( entry as Record<string, unknown> ).text ) );
      }
    }
  }
  return body ? { body, footer, buttons, status: String( row.status || 'UNKNOWN' ).toUpperCase() } : null;
}

function stageBody ( step: number ): string {
  switch ( step ) {
    case 2: return '💳 Your order is ready for payment. Tap Review and Pay to complete it securely.';
    case 3: return '📦 Your order status has been updated.';
    case 4: return '✅ Payment received. Your transaction has been confirmed.';
    default: return '📄 Your requested document is ready. Tap below to access it.';
  }
}

export default function VaultJourneyPreview ( props: Props ) {
  const [ activeStage, setActiveStage ] = React.useState( 2 );
  const currentFile = props.mode === 'existing' ? props.selectedFile : null;
  const draftFile = props.mode === 'upload' ? props.draftFile : null;
  const extension = draftFile?.name.match( /\.[a-zA-Z0-9]{1,10}$/ )?.[ 0 ]?.toLowerCase() || '';
  // The backend assigns the UUID when upload begins; never preview original upload names.
  const fileName = currentFile?.displayName
    || ( draftFile ? 'wecare-digital-<uuid>' + extension : 'Choose a document' );
  const fileType = currentFile?.contentType || draftFile?.type || 'Type confirmed after upload';
  const fileBytes = currentFile?.sizeBytes || draftFile?.size;
  const fileId = currentFile?.fileId || '';
  const editable49Item = props.pricePaise === 4900;
  const invoiceItemLabel = editable49Item ? props.paymentItemDescription : 'Vault access';
  const owner = currentFile?.ownerName || props.customerName || 'Choose a customer';
  const mobile = currentFile?.ownerPhoneMasked || props.customerPhone || '—';
  const link = fileId
    ? 'https://wecare.digital/vault/?file=' + encodeURIComponent( fileId )
    : 'https://wecare.digital/vault/?file={{1}}';
  const stage = stages.find( item => item.step === activeStage ) || stages[ 0 ];
  const registryStep = props.journey?.steps.find( item =>
    item.role === ( { 2: 'native_payment', 3: 'order_status', 4: 'receipt', 5: 'access' } as Record<number, string> )[ activeStage ] );
  const fallbackTemplates: Record<number, string | undefined> = {
    2: props.templates?.nativePay,
    3: props.templates?.orderStatus,
    4: props.templates?.receipt,
    5: props.templates?.delivery,
  };
  // Prefer the server's live service-price template registry for paid steps.
  // The staff-only SystemConfig journal remains a read-only audit fallback.
  // Neither source is used to choose a WhatsApp template or initiate a send.
  const templateName = fallbackTemplates[ activeStage ] || registryStep?.templateName || stage.fallback;
  const metaIds = props.templates?.templateIds;
  const paidIdByStage: Record<number, string | undefined> = {
    2: metaIds?.nativePay,
    3: metaIds?.orderStatus,
    4: metaIds?.receipt,
    5: metaIds?.delivery,
  };
  const templateId = paidIdByStage[ activeStage ] || registryStep?.templateId || '';
  const mappingMismatch = Boolean(
    paidIdByStage[ activeStage ] && registryStep?.templateId
    && paidIdByStage[ activeStage ] !== registryStep.templateId
  );
  const paidTemplateRows = [
    { stage: 2, label: 'Review & Pay', name: props.templates?.nativePay || stages[ 0 ].fallback,
      metaId: metaIds?.nativePay || props.journey?.steps.find( s => s.role === 'native_payment' )?.templateId || '' },
    { stage: 3, label: 'Payment status ×2', name: props.templates?.orderStatus || stages[ 1 ].fallback,
      metaId: metaIds?.orderStatus || props.journey?.steps.find( s => s.role === 'order_status' )?.templateId || '' },
    { stage: 4, label: 'GST invoice', name: props.templates?.receipt || stages[ 2 ].fallback,
      metaId: metaIds?.receipt || props.journey?.steps.find( s => s.role === 'receipt' )?.templateId || '' },
    { stage: 5, label: 'Access Vault', name: props.templates?.delivery || stages[ 3 ].fallback,
      metaId: metaIds?.delivery || props.journey?.steps.find( s => s.role === 'access' )?.templateId || '' },
  ];

  const [ copies, setCopies ] = React.useState<Record<string, MetaTemplateCopy>>( {} );
  const [ copyLoading, setCopyLoading ] = React.useState( false );
  const [ accessDelay, setAccessDelay ] = React.useState<{ seconds: number; source: string }>(
    { seconds: 4, source: 'unverified' } );

  // Read the CURRENT Meta template BODY by the backend-provided ID. This API is
  // staff-only and read-only; nothing here creates a message or alters a template.
  React.useEffect( () => {
    const requested = [
      { id: metaIds?.nativePay, name: props.templates?.nativePay || stages[ 0 ].fallback },
      { id: metaIds?.orderStatus, name: props.templates?.orderStatus || stages[ 1 ].fallback },
      { id: metaIds?.receipt, name: props.templates?.receipt || stages[ 2 ].fallback },
      { id: metaIds?.delivery, name: props.templates?.delivery || stages[ 3 ].fallback },
    ].filter( ( item ): item is { id: string; name: string } =>
      typeof item.id === 'string' && /^[0-9]+$/.test( item.id ) && Boolean( item.name ) );
    if ( requested.length === 0 ) {
      setCopies( {} );
      setCopyLoading( false );
      return;
    }
    let active = true;
    setCopies( {} ); // Do not show an old approval while checking a changed mapping.
    setCopyLoading( true );
    void Promise.all( requested.map( async item => {
      try {
        // Read by exact Meta ID from the production messaging account.
        // A different name, language or category is not a verified Vault step.
        const data = await getTemplateDetails( item.id, '2094615664435155' );
        const copy = data?.name === item.name && data.language === 'en'
          && data.category === 'UTILITY' ? parseMetaTemplateCopy( data ) : null;
        return { id: item.id, copy };
      } catch {
        return { id: item.id, copy: null };
      }
    } ) ).then( results => {
      if ( !active ) return;
      const next: Record<string, MetaTemplateCopy> = {};
      results.forEach( item => { if ( item.copy ) next[ item.id ] = item.copy; } );
      setCopies( next );
      setCopyLoading( false );
    } );
    return () => { active = false; };
  }, [ metaIds?.nativePay, metaIds?.orderStatus, metaIds?.receipt, metaIds?.delivery,
    props.templates?.nativePay, props.templates?.orderStatus,
    props.templates?.receipt, props.templates?.delivery ] );

  React.useEffect( () => {
    let active = true;
    void getSystemConfigResult( 'vault_delivery_timing_v1' ).then( result => {
      if ( !active ) return;
      if ( !result.ok ) return;
      const raw = result.data.config;
      if ( raw === null ) { setAccessDelay( { seconds: 4, source: 'default' } ); return; }
      const seconds = ( raw as Record<string, unknown> ).postReceiptAccessGapSeconds;
      if ( typeof seconds === 'number' && Number.isInteger( seconds ) && seconds >= 0 && seconds <= 5 )
        setAccessDelay( { seconds, source: 'saved' } );
    } ).catch( () => { /* Never pretend an unreadable setting is confirmed. */ } );
    return () => { active = false; };
  }, [] );

  const liveCopy = templateId ? copies[ templateId ] : undefined;

  return (
    <aside className={ styles.preview } id="sf-journey-preview" aria-label="Vault invoice and WhatsApp preview">
      <header className={ styles.header }>
        <div>
          <p className={ styles.kicker }>LIVE CUSTOMER PREVIEW</p>
          <h2>WhatsApp + Vault</h2>
        </div>
        <span className={ styles.tag }>Preview only</span>
      </header>

      <div className={ styles.document }>
        <span className={ styles.documentIcon } aria-hidden="true">📄</span>
        <div className={ styles.documentCopy }>
          <strong>{ fileName }</strong>
          <small>{ fileSize( fileBytes ) } · { fileType }</small>
          <small>{ fileId ? 'Private file · published' : 'UUID assigned securely after saving' }</small>
        </div>
      </div>

      <section className={ styles.quickFlow } aria-label="Vault message timing settings">
        <div><small>After payment capture</small><strong>Processing → Completed: 1s fixed</strong></div>
        <div><small>After Completed</small><strong>Paid invoice: 0s added</strong></div>
        <div>
          <small>Invoice accepted → Access link</small>
          <strong>{ accessDelay.seconds }s { accessDelay.source === 'saved'
            ? 'saved' : accessDelay.source === 'default' ? 'default' : 'default · unverified' }</strong>
        </div>
        <Link href="/workspace/payments?view=timing">View / edit Access delay</Link>
      </section>

      <section className={ styles.messages } aria-label="WhatsApp journey preview">
        <div className={ styles.sectionTitle }>
          <h3>Vault WhatsApp templates &amp; Meta IDs</h3>
          <span>WABA1 · no message sent by preview</span>
        </div>
        <dl className={ styles.templateCatalog } aria-label="Payment and Vault template IDs">
          { paidTemplateRows.map( item => (
            <div key={ item.stage } className={ styles.templateCatalogRow }>
              <dt>{ item.label }</dt>
              <dd>
                <code>{ item.name }</code>
                <small>Meta Template ID: { item.metaId || 'Not available from backend' }</small>
                { item.metaId && <small>Meta approval: { copyLoading ? 'Checking live Meta…'
                  : copies[ item.metaId ]?.status || 'Not confirmed' }</small> }
              </dd>
            </div>
          ) ) }
        </dl>
        <p className={ styles.templateNote }>These are the internal template names and IDs selected by the live pricing registry. Select a stage to read its Meta message body. The sender rechecks approval and eligibility before any customer send.</p>
        <div className={ styles.steps } role="group" aria-label="Choose a WhatsApp message step">
          { stages.map( item => (
            <button key={ item.step } type="button"
              className={ styles.stepButton + ( activeStage === item.step ? ' ' + styles.activeStep : '' ) }
              aria-pressed={ activeStage === item.step }
              onClick={ () => setActiveStage( item.step ) }>
              <span>{ item.step - 1 }</span>{ item.name }
            </button>
          ) ) }
        </div>
        <div className={ styles.messageMeta }>
          <span>{ stage.trigger }</span>
          <span>{ registryStep ? ( registryStep.sendCount + ' send' + ( registryStep.sendCount > 1 ? 's' : '' ) ) : 'Preview' }</span>
        </div>
        <div className={ styles.bubble }>
          <small>{ templateName }</small>
          <small>Meta Template ID: { templateId || 'Awaiting backend registry' }</small>
          <strong className={ styles.copySource }>{
            liveCopy?.status === 'APPROVED' ? 'Live approved Meta message body · read-only'
              : liveCopy ? `Meta text · status ${ liveCopy.status } (approval not confirmed)`
                : copyLoading ? 'Loading Meta message text…'
                  : 'Illustrative text only · live Meta body unavailable'
          }</strong>
          <p>{ liveCopy?.body || stageBody( activeStage ) }</p>
          { liveCopy?.footer && <small className={ styles.metaFooter }>Footer: { liveCopy.footer }</small> }
          { liveCopy?.buttons.length ? (
            <div className={ styles.metaButtons } aria-label="Meta template button labels">
              { liveCopy.buttons.map( ( label, index ) =>
                <span className={ styles.bubbleButton } key={ index }>{ label }</span> ) }
            </div>
          ) : (
            <>
              { activeStage === 2 && <span className={ styles.bubbleButton }>Review and Pay · ORDER_DETAILS</span> }
              { activeStage === 3 && <span className={ styles.smallNote }>Two separate status updates: processing → completed</span> }
              { activeStage === 4 && <span className={ styles.bubbleButton }>Leave Review · existing Flow</span> }
              { activeStage === 5 && <span className={ styles.bubbleButton }>Access Vault · URL</span> }
            </>
          ) }
          <small className={ styles.metaFooter }>Variables such as {'{{1}}'} are filled by the sender at delivery.
            This preview never sends messages or issues invoices.</small>
        </div>

        { mappingMismatch && <p className={ styles.warning } role="status">Backend template ID differs from the saved journey registry. Verify the WABA mapping before sending; the preview cannot change the live sender.</p> }

        { activeStage === 2 && (
          <details className={ styles.mediaDetails }>
            <summary className={ styles.disclosureTitle }>Approved payment header and item images</summary>
            <PaymentTemplateMedia serviceLabel="Vault" templates={ props.templates } signedPreview />
          </details>
        ) }

        <details className={ styles.technical }>
          <summary className={ styles.disclosureTitle }>Template variables and technical send gates</summary>
        <dl className={ styles.variables }>
          <div><dt>Meta template ID</dt><dd>{ templateId || 'Registry read pending' }</dd></div>
          <div><dt>Send gate</dt><dd>{ registryStep?.trigger || 'See approved server workflow' }</dd></div>
          <div><dt>Timing</dt><dd>{ activeStage === 5
            ? 'Only Access Vault has an editable wait (0–5s, default 4s) in Pay & Flow → Access delay'
            : activeStage === 3
              ? 'Fixed 1s after accepted Processing → Completed (Vault only); 0s before paid invoice'
              : 'No artificial wait; next action starts after its required event/acknowledgment' }</dd></div>
          { activeStage === 2 && (
            <>
              <div><dt>Payment item</dt><dd>{ invoiceItemLabel } · quantity 1 · { currency( props.pricePaise ) } base</dd></div>
              <div><dt>Native payload</dt><dd>Server-priced ORDER_DETAILS; original-icon item thumbnail</dd></div>
              <div><dt>Customer action</dt><dd>Customer confirms the server-priced native Review &amp; Pay request</dd></div>
            </>
          ) }
          { activeStage === 3 && (
            <div><dt>Provider IDs</dt><dd>Separate WhatsApp message ID per update; capture required</dd></div>
          ) }
          { activeStage === 4 && (
            <>
              <div><dt>Image header</dt><dd>Generated paid invoice PNG · unavailable before capture</dd></div>
              <div><dt>Review Flow ID</dt><dd>{ registryStep?.flowId || 'Existing Leave Review Flow' }</dd></div>
            </>
          ) }
          { activeStage === 5 && (
            <>
              <div><dt>URL {'{{1}}'}</dt><dd>{ fileId || 'Server-created file ID after publish' }</dd></div>
              <div><dt>Button link</dt><dd>{ link }</dd></div>
              <div><dt>Download transport</dt><dd>Customer login → paid entitlement → short-lived private URL</dd></div>
            </>
          ) }
        </dl>
        </details>
        <p className={ styles.hint }>Only the description of the ₹49 single Vault item is editable. Quantity 1, catalogue amount, GST, fees, approved template assets and access URL remain locked. The issued receipt follows verified capture.</p>
      </section>

      <details open className={ styles.invoice } aria-label="Vault item name and locked invoice totals">
        <summary className={ styles.disclosureTitle }>
          <span>Estimated invoice &amp; pricing</span>
          <strong>{ currency( props.breakdown?.totalPayablePaise ) }</strong>
        </summary>
        <div className={ styles.invoiceTop }>
          <strong>WECARE.DIGITAL</strong>
          <span>PREVIEW · NOT ISSUED</span>
        </div>
        <h3>Vault access invoice · fixed amount</h3>
        <p className={ styles.hint }>Same canonical invoice/payment backend as Pay &amp; Flow. Only the ₹49 Vault item's one-line description is editable; the file, quantity 1, catalogue amount and all pricing remain locked. The receipt image and tax invoice are generated only after verified payment.</p>
        <p className={ styles.customer }>{ owner } · { mobile }</p>
        { editable49Item && (
          <div className={ styles.itemNamePreview }>
            <small>₹49 WhatsApp and GST invoice item · read-only mirror</small>
            <strong>{ invoiceItemLabel }</strong>
            { currentFile ? (
              <a href="#sf-vault-item-description">Edit in the Send panel above · 12–60 characters</a>
            ) : (
              <small>Choose a published file to edit the payment item above Send.</small>
            ) }
          </div>
        ) }
        <div className={ styles.billRow }><span>{ invoiceItemLabel }</span><strong>{ currency( props.pricePaise ) }</strong></div>
        <div className={ styles.billRow }><span>GST on supply</span><strong>{ currency( props.breakdown?.supplyGstPaise ) }</strong></div>
        <div className={ styles.billRow }><span>Delight</span><strong>{ props.breakdown ? '−' + currency( props.breakdown.delightPaise ) : '—' }</strong></div>
        <div className={ styles.billRow }><span>Express</span><strong>{ currency( props.breakdown?.expressPaise ) }</strong></div>
        <div className={ styles.billRow }><span>Convenience fee</span><strong>{ currency( props.breakdown?.convenienceFeePaise ) }</strong></div>
        <div className={ styles.billRow }><span>GST on fee</span><strong>{ currency( props.breakdown?.convenienceGstPaise ) }</strong></div>
        <div className={ styles.billTotal }><span>Final payable preview</span><strong>{ currency( props.breakdown?.totalPayablePaise ) }</strong></div>
        <p className={ styles.hint }>
          { props.priceLoading
            ? 'Reading server pricing…'
            : !props.breakdown
              ? 'Live price breakdown unavailable. Do not request payment until it recovers.'
              : 'Prices are server-provided. The actual invoice image is created after verified capture.' }
        </p>
        
      </details>

      <details className={ styles.historyDetails }>
        <summary className={ styles.disclosureTitle }>Message and delivery evidence · selected file</summary>
        <VaultMessageTimeline file={ currentFile } journey={ props.journey } />
      </details>

      <details className={ styles.delivery } aria-label="File and delivery details">
        <summary className={ styles.disclosureTitle }>
          <span>File, access and technical details</span>
          <small>Expand</small>
        </summary>
        <h3>What the customer gets</h3>
        <dl className={ styles.variables }>
          <div><dt>Generated stored filename</dt><dd>{ fileName }</dd></div>
          <div><dt>Customer transport</dt><dd>Exact-file Vault link; never a raw private S3 key</dd></div>
          <div><dt>Access</dt><dd>One paid 24-hour window; renewal required after expiry</dd></div>
          <div><dt>Media variants</dt><dd>PDFs, images and other supported documents: one approved Access Vault download-link template. No additional raw WhatsApp document attachment is sent by automatic paid Vault delivery.</dd></div>
          <div><dt>Invoice header</dt><dd>Dynamic PNG generated only after payment</dd></div>
        </dl>
        { currentFile && (
          <div className={ styles.actions }>
            <button type="button" onClick={ props.onStaffDownload } disabled={ currentFile.status !== 'active' }>Staff download</button>
            <button type="button" onClick={ props.onCopyFileId }>Copy file ID</button>
          </div>
        ) }
        <p className={ styles.hint }>
          { props.journey
            ? 'Four live payment stages are shown; a legacy saved offer stage is ignored. No Meta Flow is created by this preview.'
            : ( props.journeyError || 'Loading saved Vault journey mapping…' ) }
        </p>
      </details>

    </aside>
  );
}
