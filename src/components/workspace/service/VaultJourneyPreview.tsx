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
  if ( raw.journeyId !== 'VAULT_WA_MANUAL_OFFER_V1'
    || raw.schemaVersion !== 1 || !Array.isArray( raw.steps ) || raw.steps.length !== 5 ) return null;

  const expected = [ 'ready_offer', 'native_payment', 'order_status', 'receipt', 'access' ];
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
    steps,
  };
}

type Mode = 'upload' | 'existing';
interface Props {
  mode: Mode;
  customerName: string;
  customerPhone: string;
  draftFile: File | null;
  selectedFile: SecureFile | null;
  /** Staff typed {{1}} in the approved Vault-ready offer; unrelated to file identity. */
  offerBodyText: string;
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
  { step: 1, name: 'Vault ready', trigger: 'Staff sends offer', fallback: 'wecare_vault_request_ready' },
  { step: 2, name: 'Review & Pay', trigger: 'Customer taps Unlock Vault', fallback: 'wecare_whatapp_native_pay_template' },
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

function stageBody ( step: number, offerBodyText: string ): string {
  switch ( step ) {
    case 1: return '📄 Your requested *' + ( offerBodyText || '{{1}}' ) + '* is available in your Vault. Amount due for this request: *₹49*.';
    case 2: return '💳 Your order is ready for payment. Tap Review and Pay to complete it securely.';
    case 3: return '📦 Your order status has been updated.';
    case 4: return '✅ Payment received. Your transaction has been confirmed.';
    default: return '📄 Your requested document is ready. Tap below to access it.';
  }
}

export default function VaultJourneyPreview ( props: Props ) {
  const [ activeStage, setActiveStage ] = React.useState( 1 );
  const currentFile = props.mode === 'existing' ? props.selectedFile : null;
  const draftFile = props.mode === 'upload' ? props.draftFile : null;
  const extension = draftFile?.name.match( /\.[a-zA-Z0-9]{1,10}$/ )?.[ 0 ]?.toLowerCase() || '';
  // The backend assigns the UUID when upload begins; never preview original upload names.
  const fileName = currentFile?.displayName
    || ( draftFile ? 'wecare-digital-<uuid>' + extension : 'Choose a document' );
  const offerBodyText = props.offerBodyText.trim();
  const fileType = currentFile?.contentType || draftFile?.type || 'Type confirmed after upload';
  const isPdf = fileType === 'application/pdf';
  const fileBytes = currentFile?.sizeBytes || draftFile?.size;
  const fileId = currentFile?.fileId || '';
  const owner = currentFile?.ownerName || props.customerName || 'Choose a customer';
  const mobile = currentFile?.ownerPhoneMasked || props.customerPhone || '—';
  const link = fileId
    ? 'https://wecare.digital/vault/?file=' + encodeURIComponent( fileId )
    : 'https://wecare.digital/vault/?file={{1}}';
  const stage = stages.find( item => item.step === activeStage ) || stages[ 0 ];
  const registryStep = props.journey?.steps.find( item => item.step === activeStage );
  const fallbackTemplates: Record<number, string | undefined> = {
    1: stage.fallback,
    2: props.templates?.nativePay,
    3: props.templates?.orderStatus,
    4: props.templates?.receipt,
    5: props.templates?.delivery,
  };
  const templateName = registryStep?.templateName || fallbackTemplates[ activeStage ] || stage.fallback;
  const priceMismatch = props.pricePaise !== null && props.pricePaise !== 4900;

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
          <h3>Approved WhatsApp templates</h3>
          <span>WABA1 · no message sent by preview</span>
        </div>
        <div className={ styles.steps } role="group" aria-label="Choose a WhatsApp message step">
          { stages.map( item => (
            <button key={ item.step } type="button"
              className={ styles.stepButton + ( activeStage === item.step ? ' ' + styles.activeStep : '' ) }
              aria-pressed={ activeStage === item.step }
              onClick={ () => setActiveStage( item.step ) }>
              <span>{ item.step }</span>{ item.name }
            </button>
          ) ) }
        </div>
        <div className={ styles.messageMeta }>
          <span>{ stage.trigger }</span>
          <span>{ registryStep ? ( registryStep.sendCount + ' send' + ( registryStep.sendCount > 1 ? 's' : '' ) ) : 'Preview' }</span>
        </div>
        <div className={ styles.bubble }>
          <small>{ templateName }</small>
          <p>{ stageBody( activeStage, offerBodyText ) }</p>
          { activeStage === 1 && <span className={ styles.bubbleButton }>Unlock Vault</span> }
          { activeStage === 2 && <span className={ styles.bubbleButton }>Review and Pay · ORDER_DETAILS</span> }
          { activeStage === 3 && <span className={ styles.smallNote }>Two separate updates: processing → completed</span> }
          { activeStage === 4 && <span className={ styles.bubbleButton }>Leave Review · existing Flow</span> }
          { activeStage === 5 && <span className={ styles.bubbleButton }>Access Vault · URL</span> }
        </div>

        { activeStage === 2 && (
          <PaymentTemplateMedia serviceLabel="Vault" templates={ props.templates } />
        ) }

        <details className={ styles.technical }>
          <summary className={ styles.disclosureTitle }>Template variables and technical send gates</summary>
        <dl className={ styles.variables }>
          <div><dt>Meta template</dt><dd>{ registryStep?.templateId || 'Registry read pending' }</dd></div>
          <div><dt>Send gate</dt><dd>{ registryStep?.trigger || 'See approved server workflow' }</dd></div>
          <div><dt>Spacing</dt><dd>{ registryStep ? String( registryStep.defaultDelaySeconds ) + 's (not delivery ordering)' : '—' }</dd></div>
          { activeStage === 1 && (
            <>
              <div><dt>Body {'{{1}}'}</dt><dd>{ offerBodyText || 'Enter free text in the left-side WhatsApp field' }</dd></div>
              <div><dt>Quick reply</dt><dd>Server-generated signed offer token; not editable</dd></div>
              <div><dt>Header</dt><dd>Fixed WhatsApp header image</dd></div>
            </>
          ) }
          { activeStage === 2 && (
            <>
              <div><dt>Payment item</dt><dd>Vault · quantity 1 · { currency( props.pricePaise ) } base</dd></div>
              <div><dt>Native payload</dt><dd>Server-priced ORDER_DETAILS; original-icon item thumbnail</dd></div>
              <div><dt>Customer action</dt><dd>Unlock Vault must be tapped first</dd></div>
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
        <p className={ styles.hint }>The approved template wording is fixed. Only its {'{{1}}'} body value is editable in the customer card. The S3 filename, invoice, token and URL remain server-generated.</p>
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
        { priceMismatch && <p className={ styles.warning }>Approved offer copy still says ₹49; catalogue base price differs. Align the approved template before sending.</p> }
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
          <div><dt>Media variants</dt><dd>{ isPdf
            ? 'PDF: Vault link plus an optional WhatsApp document when a delivery copy exists and the customer messaged within 24 hours. Attachment filename: ' + fileName
            : 'Images, office files and other supported types: the approved secure Vault link.' }</dd></div>
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
            ? 'Journey order loaded from the saved DynamoDB registry. No Meta Flow is created by this preview.'
            : ( props.journeyError || 'Loading saved Vault journey mapping…' ) }
        </p>
      </details>

    </aside>
  );
}
