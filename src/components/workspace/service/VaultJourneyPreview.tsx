/**
 * Vault ledger-style, read-only review of the exact file and the approved WhatsApp
 * journey. This is not a second payment engine or a WhatsApp template editor.
 *
 * The journey order / trigger / spacing is read from the staff-only SystemConfig
 * record. Body copy below is a visual reference to approved Meta templates; only
 * the existing sender and Meta decide the actual message and dynamic payload.
 */
import React from 'react';
import type { SecureFile } from '../../../api/client';
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
              </dd>
            </div>
          ) ) }
        </dl>
        <p className={ styles.templateNote }>Read-only IDs from the backend template registry; live Meta approval is rechecked by the sender. Payment status uses one approved template twice (processing → completed).</p>
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
          <p>{ stageBody( activeStage ) }</p>
          { activeStage === 2 && <span className={ styles.bubbleButton }>Review and Pay · ORDER_DETAILS</span> }
          { activeStage === 3 && <span className={ styles.smallNote }>Two separate updates: processing → completed</span> }
          { activeStage === 4 && <span className={ styles.bubbleButton }>Leave Review · existing Flow</span> }
          { activeStage === 5 && <span className={ styles.bubbleButton }>Access Vault · URL</span> }
        </div>

        { mappingMismatch && <p className={ styles.warning } role="status">Backend template ID differs from the saved journey registry. Verify the WABA mapping before sending; the preview cannot change the live sender.</p> }

        { activeStage === 2 && (
          <PaymentTemplateMedia serviceLabel="Vault" templates={ props.templates } signedPreview />
        ) }

        <details className={ styles.technical }>
          <summary className={ styles.disclosureTitle }>Template variables and technical send gates</summary>
        <dl className={ styles.variables }>
          <div><dt>Meta template ID</dt><dd>{ templateId || 'Registry read pending' }</dd></div>
          <div><dt>Send gate</dt><dd>{ registryStep?.trigger || 'See approved server workflow' }</dd></div>
          <div><dt>Spacing</dt><dd>{ registryStep ? String( registryStep.defaultDelaySeconds ) + 's (not delivery ordering)' : '—' }</dd></div>
          { activeStage === 2 && (
            <>
              <div><dt>Payment item</dt><dd>Vault · quantity 1 · { currency( props.pricePaise ) } base</dd></div>
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
        <p className={ styles.hint }>Staff may select a verified file but cannot edit the Vault catalogue price, approved payment media, invoice or access URL. The issued receipt follows verified capture.</p>
      </section>

      <VaultMessageTimeline file={ currentFile } journey={ props.journey } />

      <details className={ styles.invoice } aria-label="Invoice breakdown preview">
        <summary className={ styles.disclosureTitle }>
          <span>Estimated invoice &amp; pricing</span>
          <strong>{ currency( props.breakdown?.totalPayablePaise ) }</strong>
        </summary>
        <div className={ styles.invoiceTop }>
          <strong>WECARE.DIGITAL</strong>
          <span>PREVIEW · NOT ISSUED</span>
        </div>
        <h3>Vault access invoice</h3>
        <p className={ styles.customer }>{ owner } · { mobile }</p>
        <div className={ styles.billRow }><span>Vault · one file / one access window</span><strong>{ currency( props.pricePaise ) }</strong></div>
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
            <button type="button" onClick={ props.onStaffDownload } disabled={ !currentFile.sourceDocumentId }>Staff download</button>
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
