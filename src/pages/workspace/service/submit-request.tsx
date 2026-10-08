/**
 * Submit Request — [retired public path]/submit-request
 * Order-centric service request submission with draft support.
 * Flow: ORDER_SELECT → SUBMIT_FORM → TERMS → REVIEW → THANK_YOU
 */
import React, { useState, useEffect, useCallback } from 'react';
import MaybeLayout from '../../../components/MaybeLayout';
import SEO, { PAGE_SEO } from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import EmptyState from '../../../components/ui/EmptyState';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';

type Step = 'ORDER_SELECT' | 'SUBMIT_FORM' | 'TERMS' | 'REVIEW' | 'THANK_YOU';

const REQUEST_TYPES = [
  'Return / Refund',
  'Exchange',
  'Damaged / Defective',
  'Missing Item',
  'Wrong Item Received',
  'Delivery Issue',
  'Payment Issue',
  'General Inquiry',
  'Other',
];

/* Derived from the list above so the two cannot drift. The '' placeholder row stays first and
   keeps its text, because an empty requestType is what "not chosen yet" means here. */
const REQUEST_TYPE_OPTIONS: SelectOption[] = [
  { value: '', label: 'Select type...' },
  ...REQUEST_TYPES.map( t => ( { value: t, label: t } ) ),
];

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

function extractShortId ( orderId: string ): string {
  const parts = orderId.split( '-' );
  return parts.length >= 3 ? parts[ parts.length - 1 ] : orderId.slice( 0, 8 );
}

function formatOrderLabel ( o: api.Order ): string {
  const short = o.shortId || extractShortId( o.orderId );
  const date = o.orderDateIST || o.orderDate || '';
  return `${short} — ${date}`;
}

const SubmitRequestPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const userPhone = user?.signInDetails?.loginId || user?.username || 'web-user';
  const [ step, setStep ] = useState<Step>( 'ORDER_SELECT' );
  const [ orders, setOrders ] = useState<api.Order[]>( [] );
  const [ loadingOrders, setLoadingOrders ] = useState( true );
  const [ selectedOrder, setSelectedOrder ] = useState<api.Order | null>( null );
  const [ form, setForm ] = useState( { requestType: '', subject: '', description: '' } );
  const [ termsAccepted, setTermsAccepted ] = useState( false );
  const [ submitting, setSubmitting ] = useState( false );
  const [ result, setResult ] = useState<{ submissionId: string; submissionNumber: string } | null>( null );
  const [ draftLoaded, setDraftLoaded ] = useState( false );
  const [ orderSearch, setOrderSearch ] = useState( '' );

  // Load orders
  useEffect( () => {
    ( async () => {
      setLoadingOrders( true );
      try
      {
        const data = await api.listOrders( { status: 'active', limit: 200 } );
        setOrders( data.orders || [] );
      } catch { toast.error( 'Failed to load orders' ); }
      setLoadingOrders( false );
    } )();
  }, [ toast ] );

  // Load draft on mount
  useEffect( () => {
    ( async () => {
      try
      {
        const draft = await api.getDraft( 'SUBMIT_REQUEST' );
        if ( draft?.formData )
        {
          const parsed = JSON.parse( draft.formData );
          if ( parsed.orderId && parsed.requestType )
          {
            setForm( { requestType: parsed.requestType || '', subject: parsed.subject || '', description: parsed.description || '' } );
            setDraftLoaded( true );
            toast.success( 'Draft restored' );
          }
        }
      } catch { /* no draft */ }
    } )();
  }, [ toast ] );

  // Auto-save draft
  const saveDraft = useCallback( async () => {
    if ( !selectedOrder || !form.requestType ) return;
    try
    {
      await api.saveDraft( {
        phone: userPhone,
        flowCode: 'SUBMIT_REQUEST',
        screen: step,
        formData: JSON.stringify( { orderId: selectedOrder.orderId, ...form } ),
      } );
    } catch { /* silent */ }
  }, [ selectedOrder, form, step, userPhone ] );

  useEffect( () => {
    const timer = setTimeout( saveDraft, 2000 );
    return () => clearTimeout( timer );
  }, [ saveDraft ] );

  const handleSubmit = async () => {
    if ( !selectedOrder ) return;
    setSubmitting( true );
    try
    {
      const res = await api.submitRequest( {
        orderId: selectedOrder.orderId,
        requestType: form.requestType,
        subject: form.subject,
        description: form.description,
      } );
      if ( res )
      {
        setResult( res );
        setStep( 'THANK_YOU' );
        await api.deleteDraft( 'SUBMIT_REQUEST' );
      } else
      {
        toast.error( 'Submission failed. Please try again.' );
      }
    } catch { toast.error( 'Submission failed' ); }
    setSubmitting( false );
  };

  const filteredOrders = orders.filter( o => {
    if ( !orderSearch.trim() ) return true;
    const q = orderSearch.toLowerCase();
    const label = formatOrderLabel( o ).toLowerCase();
    const name = ( o.customerName || '' ).toLowerCase();
    return label.includes( q ) || name.includes( q ) || o.orderId.toLowerCase().includes( q );
  } );

  const canProceedForm = form.requestType && form.subject.trim() && form.description.trim();

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.submitRequest } />
      <div style={ { padding: '24px 32px', maxWidth: 800, margin: '0 auto' } }>
        {/* Progress */ }
        <div style={ { display: 'flex', gap: 8, marginBottom: 24 } }>
          { ( [ 'ORDER_SELECT', 'SUBMIT_FORM', 'TERMS', 'REVIEW', 'THANK_YOU' ] as Step[] ).map( ( s, i ) => (
            <div key={ s } style={ { flex: 1, height: 4, borderRadius: 2, background: i <= [ 'ORDER_SELECT', 'SUBMIT_FORM', 'TERMS', 'REVIEW', 'THANK_YOU' ].indexOf( step ) ? '#1a3a2a' : '#e5e7eb' } } />
          ) ) }
        </div>

        <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: '0 0 4px' } }>Submit Request</h1>
        <p style={ { fontSize: 14, color: '#6b7280', margin: '0 0 24px' } }>
          { step === 'ORDER_SELECT' && 'Select the order you need help with' }
          { step === 'SUBMIT_FORM' && 'Describe your request' }
          { step === 'TERMS' && 'Review terms and conditions' }
          { step === 'REVIEW' && 'Review your submission before sending' }
          { step === 'THANK_YOU' && 'Your request has been submitted' }
        </p>

        {/* STEP 1: ORDER SELECT */ }
        { step === 'ORDER_SELECT' && (
          <div style={ cardStyle }>
            <input
              type="text"
              placeholder="Search orders by ID, date, or customer..."
              value={ orderSearch }
              onChange={ e => setOrderSearch( e.target.value ) }
              style={ { ...inputStyle, marginBottom: 12 } }
            />
            { loadingOrders ? (
              <div style={ { textAlign: 'center', padding: 32, color: '#6b7280' } }>Loading orders...</div>
            ) : filteredOrders.length === 0 ? (
              <EmptyState icon="default" title="No orders found" description="No matching orders available" />
            ) : (
              <div style={ { maxHeight: 400, overflowY: 'auto' } }>
                { filteredOrders.map( o => (
                  <button
                    key={ o.orderId }
                    onClick={ () => { setSelectedOrder( o ); setStep( 'SUBMIT_FORM' ); } }
                    style={ {
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      width: '100%', padding: '12px 16px', border: '2px solid #f3f4f6', borderRadius: 10,
                      background: selectedOrder?.orderId === o.orderId ? '#f0fdf4' : '#fff',
                      cursor: 'pointer', marginBottom: 8, textAlign: 'left', transition: 'border-color 0.15s',
                    } }
                    onMouseEnter={ e => ( e.currentTarget.style.borderColor = '#d1f470' ) }
                    onMouseLeave={ e => ( e.currentTarget.style.borderColor = '#f3f4f6' ) }
                  >
                    <div>
                      <div style={ { fontWeight: 600, fontSize: 14, color: '#1a3a2a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 400 } }>
                        { formatOrderLabel( o ) }
                      </div>
                      <div style={ { fontSize: 12, color: '#6b7280', marginTop: 2 } }>
                        { o.customerName || 'Customer' } · { o.itemsSummary || `${o.itemCount || 0} items` }
                      </div>
                    </div>
                    <div style={ { textAlign: 'right', flexShrink: 0 } }>
                      <span style={ { ...pillStyle, background: o.paymentStatus === 'paid' ? '#d1fae5' : '#fef3c7', color: o.paymentStatus === 'paid' ? '#065f46' : '#92400e' } }>
                        { o.paymentStatus }
                      </span>
                    </div>
                  </button>
                ) ) }
              </div>
            ) }
          </div>
        ) }

        {/* STEP 2: SUBMIT FORM */ }
        { step === 'SUBMIT_FORM' && selectedOrder && (
          <div style={ cardStyle }>
            <div style={ { padding: '12px 16px', background: '#f9fafb', borderRadius: 8, marginBottom: 16 } }>
              <div style={ { fontSize: 12, color: '#6b7280' } }>Selected Order</div>
              <div style={ { fontWeight: 600, color: '#1a3a2a' } }>{ formatOrderLabel( selectedOrder ) }</div>
            </div>
            { /* SHAPE (a), design 5.2 - the wrapping <label> is gone and Select owns the pair. */ }
            <Select label="Request Type *" value={ form.requestType }
              onChange={ v => setForm( f => ( { ...f, requestType: v } ) ) }
              options={ REQUEST_TYPE_OPTIONS } />
            <label style={ labelStyle }>Subject *
              <input type="text" value={ form.subject } onChange={ e => setForm( f => ( { ...f, subject: e.target.value } ) ) } placeholder="Brief summary of your request" style={ inputStyle } maxLength={ 200 } />
            </label>
            <label style={ labelStyle }>Description *
              <textarea value={ form.description } onChange={ e => setForm( f => ( { ...f, description: e.target.value } ) ) } placeholder="Provide details about your request..." rows={ 5 } style={ { ...inputStyle, resize: 'vertical' } } maxLength={ 2000 } />
              <div style={ { fontSize: 11, color: '#9ca3af', textAlign: 'right', marginTop: 2 } }>{ form.description.length }/2000</div>
            </label>
            <div style={ { display: 'flex', gap: 8, marginTop: 16 } }>
              <Button variant="secondary" onClick={ () => setStep( 'ORDER_SELECT' ) }>Back</Button>
              <Button variant="primary" disabled={ !canProceedForm } onClick={ () => setStep( 'TERMS' ) }>Continue</Button>
            </div>
          </div>
        ) }

        {/* STEP 3: TERMS */ }
        { step === 'TERMS' && (
          <div style={ cardStyle }>
            <div style={ { padding: 16, background: '#f9fafb', borderRadius: 8, marginBottom: 16, fontSize: 14, lineHeight: 1.6, maxHeight: 300, overflowY: 'auto' } }>
              <p style={ { fontWeight: 600, marginBottom: 8 } }>Terms & Conditions</p>
              <p>By submitting this service request, you agree to the following:</p>
              <ul style={ { paddingLeft: 20, margin: '8px 0' } }>
                <li>All information provided is accurate and complete.</li>
                <li>Processing times may vary based on request type and complexity.</li>
                <li>A service fee of ₹49 may apply for certain request types.</li>
                <li>You will be notified of status updates via WhatsApp.</li>
                <li>Refunds, if applicable, will be processed to the original payment method.</li>
              </ul>
            </div>
            <label style={ { display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' } }>
              <input type="checkbox" checked={ termsAccepted } onChange={ e => setTermsAccepted( e.target.checked ) } style={ { accentColor: '#1a3a2a', width: 18, height: 18 } } />
              I agree to the terms and conditions
            </label>
            <div style={ { display: 'flex', gap: 8, marginTop: 16 } }>
              <Button variant="secondary" onClick={ () => setStep( 'SUBMIT_FORM' ) }>Back</Button>
              <Button variant="primary" disabled={ !termsAccepted } onClick={ () => setStep( 'REVIEW' ) }>Continue</Button>
            </div>
          </div>
        ) }

        {/* STEP 4: REVIEW */ }
        { step === 'REVIEW' && selectedOrder && (
          <div style={ cardStyle }>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 } }>
              <div><span style={ metaLabel }>Order</span><div style={ { fontWeight: 600 } }>{ formatOrderLabel( selectedOrder ) }</div></div>
              <div><span style={ metaLabel }>Request Type</span><div>{ form.requestType }</div></div>
              <div style={ { gridColumn: '1 / -1' } }><span style={ metaLabel }>Subject</span><div>{ form.subject }</div></div>
              <div style={ { gridColumn: '1 / -1' } }><span style={ metaLabel }>Description</span><div style={ { padding: 12, background: '#f9fafb', borderRadius: 8, fontSize: 14, whiteSpace: 'pre-wrap' } }>{ form.description }</div></div>
            </div>
            <div style={ { display: 'flex', gap: 8 } }>
              <Button variant="secondary" onClick={ () => setStep( 'TERMS' ) }>Back</Button>
              <Button variant="primary" loading={ submitting } onClick={ handleSubmit }>Submit Request</Button>
            </div>
          </div>
        ) }

        {/* STEP 5: THANK YOU */ }
        { step === 'THANK_YOU' && result && (
          <div style={ { ...cardStyle, textAlign: 'center', padding: 40 } }>
            <div style={ { fontSize: 48, marginBottom: 12 } }>✅</div>
            <h2 style={ { fontSize: 20, fontWeight: 700, color: '#1a3a2a', margin: '0 0 8px' } }>Request Submitted</h2>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '0 0 16px' } }>
              Your request <strong>{ result.submissionNumber }</strong> has been submitted successfully.
            </p>
            <p style={ { fontSize: 13, color: '#9ca3af', margin: '0 0 24px' } }>
              You will receive status updates via WhatsApp. You can also track your request from the Track Request page.
            </p>
            <div style={ { display: 'flex', gap: 8, justifyContent: 'center' } }>
              <Button variant="secondary" onClick={ () => { setStep( 'ORDER_SELECT' ); setSelectedOrder( null ); setForm( { requestType: '', subject: '', description: '' } ); setTermsAccepted( false ); setResult( null ); } }>
                Submit Another
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
const pillStyle: React.CSSProperties = { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 11, fontWeight: 600 };

export default SubmitRequestPage;
