/**
 * Amend Request — [retired public path]/amend-request
 * Order-centric amendment: select order → find linked requests → amend → track.
 */
import React, { useState, useEffect, useCallback } from 'react';
import MaybeLayout from '../../../components/MaybeLayout';
import SEO, { PAGE_SEO } from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import EmptyState from '../../../components/ui/EmptyState';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';

type Step = 'ORDER_SELECT' | 'REQUEST_SELECT' | 'AMEND_FORM' | 'REVIEW' | 'DONE';

const AMENDMENT_TYPES = [
  'Add Information',
  'Correct Details',
  'Change Request Type',
  'Add Attachment',
  'Update Contact Info',
  'Cancel Request',
  'Other',
];

/* Derived from the list above so the two cannot drift. The '' placeholder row stays first and
   keeps its text, because an empty amendmentType is what "not chosen yet" means here. */
const AMENDMENT_TYPE_OPTIONS: SelectOption[] = [
  { value: '', label: 'Select type...' },
  ...AMENDMENT_TYPES.map( t => ( { value: t, label: t } ) ),
];

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

function extractShortId ( orderId: string ): string {
  const parts = orderId.split( '-' );
  return parts.length >= 3 ? parts[ parts.length - 1 ] : orderId.slice( 0, 8 );
}

function formatOrderLabel ( o: api.Order ): string {
  const short = o.shortId || extractShortId( o.orderId );
  return `${short} — ${o.orderDateIST || o.orderDate || ''}`;
}

function fmtDate ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' } );
}

function statusColor ( status: string ): { bg: string; fg: string } {
  const map: Record<string, { bg: string; fg: string }> = {
    open: { bg: '#dbeafe', fg: '#1e40af' }, in_progress: { bg: '#fef3c7', fg: '#92400e' },
    resolved: { bg: '#d1f470', fg: '#1a3a2a' }, closed: { bg: '#f3f4f6', fg: '#374151' },
  };
  return map[ status ] || { bg: '#f3f4f6', fg: '#374151' };
}

function Badge ( { label }: { label: string } ) {
  const c = statusColor( label );
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 12, fontWeight: 600, background: c.bg, color: c.fg } }>{ label.replace( /_/g, ' ' ) }</span>;
}

const AmendRequestPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ step, setStep ] = useState<Step>( 'ORDER_SELECT' );
  const [ orders, setOrders ] = useState<api.Order[]>( [] );
  const [ loadingOrders, setLoadingOrders ] = useState( true );
  const [ selectedOrder, setSelectedOrder ] = useState<api.Order | null>( null );
  const [ submissions, setSubmissions ] = useState<api.FlowSubmissionItem[]>( [] );
  const [ loadingSubs, setLoadingSubs ] = useState( false );
  const [ selectedSub, setSelectedSub ] = useState<api.FlowSubmissionItem | null>( null );
  const [ form, setForm ] = useState( { amendmentType: '', description: '' } );
  const [ submitting, setSubmitting ] = useState( false );
  const [ resultId, setResultId ] = useState<string | null>( null );
  const [ orderSearch, setOrderSearch ] = useState( '' );

  useEffect( () => {
    ( async () => {
      setLoadingOrders( true );
      try
      {
        const data = await api.listOrders( { limit: 200 } );
        setOrders( data.orders || [] );
      } catch { toast.error( 'Failed to load orders' ); }
      setLoadingOrders( false );
    } )();
  }, [ toast ] );

  const selectOrder = useCallback( async ( order: api.Order ) => {
    setSelectedOrder( order );
    setLoadingSubs( true );
    try
    {
      const subs = await api.getOrderSubmissions( order.orderId );
      setSubmissions( subs );
    } catch { toast.error( 'Failed to load requests' ); }
    setLoadingSubs( false );
    setStep( 'REQUEST_SELECT' );
  }, [ toast ] );

  const handleSubmit = async () => {
    if ( !selectedOrder || !selectedSub ) return;
    setSubmitting( true );
    try
    {
      const res = await api.amendRequest( {
        submissionId: selectedSub.submissionId,
        orderId: selectedOrder.orderId,
        amendmentType: form.amendmentType,
        description: form.description,
      } );
      if ( res?.success )
      {
        setResultId( res.amendmentId || 'submitted' );
        setStep( 'DONE' );
      } else
      {
        toast.error( 'Amendment failed' );
      }
    } catch { toast.error( 'Amendment failed' ); }
    setSubmitting( false );
  };

  const filteredOrders = orders.filter( o => {
    if ( !orderSearch.trim() ) return true;
    const q = orderSearch.toLowerCase();
    return formatOrderLabel( o ).toLowerCase().includes( q ) || ( o.customerName || '' ).toLowerCase().includes( q );
  } );

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.amendRequest } />
      <div style={ { padding: '24px 32px', maxWidth: 800, margin: '0 auto' } }>
        {/* Progress */ }
        <div style={ { display: 'flex', gap: 8, marginBottom: 24 } }>
          { ( [ 'ORDER_SELECT', 'REQUEST_SELECT', 'AMEND_FORM', 'REVIEW', 'DONE' ] as Step[] ).map( ( s, i ) => (
            <div key={ s } style={ { flex: 1, height: 4, borderRadius: 2, background: i <= [ 'ORDER_SELECT', 'REQUEST_SELECT', 'AMEND_FORM', 'REVIEW', 'DONE' ].indexOf( step ) ? '#1a3a2a' : '#e5e7eb' } } />
          ) ) }
        </div>

        <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: '0 0 4px' } }>Amend Request</h1>
        <p style={ { fontSize: 14, color: '#6b7280', margin: '0 0 24px' } }>
          { step === 'ORDER_SELECT' && 'Select the order to amend' }
          { step === 'REQUEST_SELECT' && 'Select the request to amend' }
          { step === 'AMEND_FORM' && 'Describe your amendment' }
          { step === 'REVIEW' && 'Review your amendment' }
          { step === 'DONE' && 'Amendment submitted' }
        </p>

        {/* STEP 1: ORDER SELECT */ }
        { step === 'ORDER_SELECT' && (
          <div style={ cardStyle }>
            <input type="text" placeholder="Search orders..." value={ orderSearch } onChange={ e => setOrderSearch( e.target.value ) } style={ { ...inputStyle, marginBottom: 12 } } />
            <div style={ { maxHeight: 400, overflowY: 'auto' } }>
              { loadingOrders ? (
                <div style={ { textAlign: 'center', padding: 24, color: '#6b7280' } }>Loading...</div>
              ) : filteredOrders.length === 0 ? (
                <EmptyState icon="default" title="No orders" description="No orders found" />
              ) : (
                filteredOrders.map( o => (
                  <button key={ o.orderId } onClick={ () => selectOrder( o ) } style={ { display: 'block', width: '100%', padding: '10px 14px', border: '2px solid #f3f4f6', borderRadius: 10, background: '#fff', cursor: 'pointer', marginBottom: 6, textAlign: 'left' } }>
                    <div style={ { fontWeight: 600, fontSize: 13, color: '#1a3a2a' } }>{ formatOrderLabel( o ) }</div>
                    <div style={ { fontSize: 12, color: '#6b7280', marginTop: 2 } }>{ o.customerName || 'Customer' } · { o.itemsSummary || `${o.itemCount || 0} items` }</div>
                  </button>
                ) )
              ) }
            </div>
          </div>
        ) }

        {/* STEP 2: REQUEST SELECT */ }
        { step === 'REQUEST_SELECT' && selectedOrder && (
          <div style={ cardStyle }>
            <div style={ { padding: '10px 14px', background: '#f9fafb', borderRadius: 8, marginBottom: 16 } }>
              <div style={ { fontSize: 12, color: '#6b7280' } }>Order</div>
              <div style={ { fontWeight: 600, color: '#1a3a2a' } }>{ formatOrderLabel( selectedOrder ) }</div>
            </div>
            { loadingSubs ? (
              <div style={ { textAlign: 'center', padding: 24, color: '#6b7280' } }>Loading requests...</div>
            ) : submissions.length === 0 ? (
              <div>
                <EmptyState icon="default" title="No requests" description="No service requests found for this order" />
                <Button variant="secondary" onClick={ () => setStep( 'ORDER_SELECT' ) } style={ { marginTop: 12 } }>Back</Button>
              </div>
            ) : (
              <>
                { submissions.map( ( sub: any ) => (
                  <button key={ sub.submissionId } onClick={ () => { setSelectedSub( sub ); setStep( 'AMEND_FORM' ); } } style={ { display: 'block', width: '100%', padding: '12px 16px', border: '2px solid #f3f4f6', borderRadius: 10, background: '#fff', cursor: 'pointer', marginBottom: 8, textAlign: 'left' } }>
                    <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }>
                      <div style={ { fontWeight: 600, fontSize: 14, color: '#1a3a2a' } }>{ sub.subject || sub.requestType || sub.flowCode }</div>
                      <Badge label={ sub.status || 'open' } />
                    </div>
                    <div style={ { fontSize: 12, color: '#6b7280', marginTop: 4 } }>
                      Ref: { sub.submissionNumber || sub.submissionId?.slice( 0, 8 ) } · { fmtDate( sub.createdAt ) }
                    </div>
                  </button>
                ) ) }
                <Button variant="secondary" onClick={ () => setStep( 'ORDER_SELECT' ) } style={ { marginTop: 8 } }>Back</Button>
              </>
            ) }
          </div>
        ) }

        {/* STEP 3: AMEND FORM */ }
        { step === 'AMEND_FORM' && selectedSub && (
          <div style={ cardStyle }>
            <div style={ { padding: '10px 14px', background: '#f9fafb', borderRadius: 8, marginBottom: 16 } }>
              <div style={ { fontSize: 12, color: '#6b7280' } }>Amending</div>
              <div style={ { fontWeight: 600, color: '#1a3a2a' } }>{ ( selectedSub as any ).subject || ( selectedSub as any ).requestType } — { ( selectedSub as any ).submissionNumber || selectedSub.submissionId.slice( 0, 8 ) }</div>
            </div>
            { /* SHAPE (a), design 5.2 - the wrapping <label> is gone and Select owns the pair.
                 A <button> is a labelable element too, so the wrapper would have made the
                 accessible name "Amendment Type * Select type...". */ }
            <Select label="Amendment Type *" value={ form.amendmentType }
              onChange={ v => setForm( f => ( { ...f, amendmentType: v } ) ) }
              options={ AMENDMENT_TYPE_OPTIONS } />
            <label style={ labelStyle }>Description *
              <textarea value={ form.description } onChange={ e => setForm( f => ( { ...f, description: e.target.value } ) ) } placeholder="Describe what you want to change or add..." rows={ 5 } style={ { ...inputStyle, resize: 'vertical' } } maxLength={ 2000 } />
              <div style={ { fontSize: 11, color: '#9ca3af', textAlign: 'right', marginTop: 2 } }>{ form.description.length }/2000</div>
            </label>
            <div style={ { display: 'flex', gap: 8, marginTop: 16 } }>
              <Button variant="secondary" onClick={ () => setStep( 'REQUEST_SELECT' ) }>Back</Button>
              <Button variant="primary" disabled={ !form.amendmentType || !form.description.trim() } onClick={ () => setStep( 'REVIEW' ) }>Review</Button>
            </div>
          </div>
        ) }

        {/* STEP 4: REVIEW */ }
        { step === 'REVIEW' && selectedOrder && selectedSub && (
          <div style={ cardStyle }>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 } }>
              <div><span style={ metaLabel }>Order</span><div style={ { fontWeight: 600 } }>{ formatOrderLabel( selectedOrder ) }</div></div>
              <div><span style={ metaLabel }>Request</span><div>{ ( selectedSub as any ).subject || ( selectedSub as any ).requestType }</div></div>
              <div><span style={ metaLabel }>Amendment Type</span><div>{ form.amendmentType }</div></div>
              <div><span style={ metaLabel }>Current Status</span><div><Badge label={ ( selectedSub as any ).status || 'open' } /></div></div>
              <div style={ { gridColumn: '1 / -1' } }><span style={ metaLabel }>Description</span><div style={ { padding: 12, background: '#f9fafb', borderRadius: 8, fontSize: 14, whiteSpace: 'pre-wrap' } }>{ form.description }</div></div>
            </div>
            <div style={ { display: 'flex', gap: 8 } }>
              <Button variant="secondary" onClick={ () => setStep( 'AMEND_FORM' ) }>Back</Button>
              <Button variant="primary" loading={ submitting } onClick={ handleSubmit }>Submit Amendment</Button>
            </div>
          </div>
        ) }

        {/* STEP 5: DONE */ }
        { step === 'DONE' && (
          <div style={ { ...cardStyle, textAlign: 'center', padding: 40 } }>
            <div style={ { fontSize: 48, marginBottom: 12 } }>✅</div>
            <h2 style={ { fontSize: 20, fontWeight: 700, color: '#1a3a2a', margin: '0 0 8px' } }>Amendment Submitted</h2>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '0 0 24px' } }>Your amendment has been submitted and will be reviewed.</p>
            <div style={ { display: 'flex', gap: 8, justifyContent: 'center' } }>
              <Button variant="secondary" onClick={ () => { setStep( 'ORDER_SELECT' ); setSelectedOrder( null ); setSelectedSub( null ); setForm( { amendmentType: '', description: '' } ); setResultId( null ); } }>
                Amend Another
              </Button>
              <Button variant="primary" onClick={ () => window.location.href = '/workspace/service/track-request' }>Track Request</Button>
            </div>
          </div>
        ) }
      </div>
    </MaybeLayout>
  );
};

const cardStyle: React.CSSProperties = { border: '2px solid #f3f4f6', borderRadius: 13, padding: 24, background: '#fff' };
const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '10px 14px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 4, boxSizing: 'border-box' };
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 14, fontWeight: 500, color: '#374151', marginBottom: 14 };
const metaLabel: React.CSSProperties = { display: 'block', fontSize: 12, color: '#6b7280', marginBottom: 2 };

export default AmendRequestPage;
