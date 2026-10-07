/**
 * Reviews Admin Page — [retired public path]/reviews
 * Moderation: approve/hide, filter by status/source/rating, detail panel
 */
import React, { useState, useEffect, useCallback } from 'react';
import MaybeLayout from '../../../../components/MaybeLayout';
import SEO, { PAGE_SEO } from '../../../../components/SEO';
import Table from '../../../../components/ui/Table';
import Modal from '../../../../components/ui/Modal';
import Button from '../../../../components/ui/Button';
import Pagination from '../../../../components/ui/Pagination';
import EmptyState from '../../../../components/ui/EmptyState';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';

const PAGE_SIZE = 20;
const STATUS_OPTIONS = [ 'pending', 'approved', 'hidden', 'flagged' ];
const SOURCE_OPTIONS = [ 'whatsapp', 'web', 'google', 'manual' ];

function formatDate ( ts?: number ): string {
  if ( !ts ) return '—';
  const d = new Date( ts < 1e12 ? ts * 1000 : ts );
  return d.toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: '2-digit' } );
}

function statusBadge ( status: string ) {
  const colors: Record<string, { bg: string; fg: string }> = {
    pending: { bg: '#fef3c7', fg: '#92400e' },
    approved: { bg: '#d1f470', fg: '#1a3a2a' },
    hidden: { bg: '#f3f4f6', fg: '#374151' },
    flagged: { bg: '#fee2e2', fg: '#991b1b' },
  };
  const c = colors[ status ] || { bg: '#f3f4f6', fg: '#374151' };
  return <span style={ { display: 'inline-block', padding: '2px 8px', borderRadius: 9999, fontSize: 12, fontWeight: 600, background: c.bg, color: c.fg } }>{ status }</span>;
}

function stars ( rating: number ) {
  return '★'.repeat( rating ) + '☆'.repeat( 5 - rating );
}

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const ReviewsPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const [ reviews, setReviews ] = useState<api.Review[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ statusFilter, setStatusFilter ] = useState( '' );
  const [ sourceFilter, setSourceFilter ] = useState( '' );
  const [ ratingFilter, setRatingFilter ] = useState( '' );
  const [ page, setPage ] = useState( 1 );
  const [ selected, setSelected ] = useState<api.Review | null>( null );

  const loadData = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listReviews( {
        status: statusFilter || undefined,
        source: sourceFilter || undefined,
        minRating: ratingFilter ? Number( ratingFilter ) : undefined,
      } );
      setReviews( data.reviews || [] );
    } catch { toast.error( 'Failed to load reviews' ); }
    setLoading( false );
  }, [ statusFilter, sourceFilter, ratingFilter, toast ] );

  useEffect( () => { loadData(); }, [ loadData ] );

  const handleAction = async ( review: api.Review, status: string ) => {
    const ok = await api.updateReview( review.reviewId, { status } );
    if ( ok )
    {
      toast.success( `Review ${status}` );
      loadData();
      if ( selected?.reviewId === review.reviewId ) setSelected( { ...review, status } );
    } else toast.error( 'Update failed' );
  };

  const totalPages = Math.ceil( reviews.length / PAGE_SIZE );
  const paged = reviews.slice( ( page - 1 ) * PAGE_SIZE, page * PAGE_SIZE );

  const columns = [
    {
      key: 'rating', header: 'Rating', width: '100px', render: ( r: api.Review ) => (
        <span style={ { color: '#f59e0b', fontSize: 14, letterSpacing: 1 } }>{ stars( r.rating ) }</span>
      )
    },
    {
      key: 'customerName', header: 'Customer', render: ( r: api.Review ) => (
        <div>
          <div style={ { fontWeight: 500, fontSize: 14 } }>{ r.customerName || '—' }</div>
          <div style={ { fontSize: 12, color: '#6b7280', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const } }>{ r.comment || 'No comment' }</div>
        </div>
      )
    },
    { key: 'source', header: 'Source', width: '90px', render: ( r: api.Review ) => r.source },
    {
      // ATTRIBUTION IN THE LIST, not only in the detail modal. The modal already rendered
      // `selected.orderId`, so a staff member could see which order a review was about —
      // but only by opening each row one at a time, which is the opposite of what a
      // moderation queue is for. Nothing WROTE `orderId` until Phase R, so this column was
      // not useful before now.
      //
      // HEADED "Reference", NOT "Order", and the wire field name is the reason it has to
      // be. `orderId` is the pre-existing `api.Review` field and renaming it would fork a
      // shared contract, but what the customer's link actually carries is `/orders/`'s
      // `copyValue` ladder — `order.orderNumber || order.referenceId` — and
      // `referenceId` is a `WD-PAY-…` PAYMENT reference. Labelling that "Order" sends a
      // staff member looking for an order number that does not exist. "Reference" is true
      // of both shapes, and the prefix tells them which one they are holding.
      //
      // `—` rather than blank for an unattributed review: a review left from
      // /leave-review/ has no reference by design, and an empty cell reads as missing data.
      key: 'orderId', header: 'Reference', width: '150px',
      render: ( r: api.Review ) => (
        <span style={ { fontSize: 13, color: r.orderId ? '#1a1a1a' : '#6b7280' } }>
          { r.orderId || '—' }
        </span>
      ),
    },
    { key: 'status', header: 'Status', width: '100px', render: ( r: api.Review ) => statusBadge( r.status ) },
    { key: 'createdAt', header: 'Date', width: '100px', render: ( r: api.Review ) => formatDate( r.createdAt ) },
    {
      key: 'actions', header: '', width: '130px', render: ( r: api.Review ) => (
        <div style={ { display: 'flex', gap: 4 } }>
          { r.status !== 'approved' && <button onClick={ () => handleAction( r, 'approved' ) } title="Approve" style={ actionBtnStyle }>✅</button> }
          { r.status !== 'hidden' && <button onClick={ () => handleAction( r, 'hidden' ) } title="Hide" style={ actionBtnStyle }>🙈</button> }
          { r.status !== 'flagged' && <button onClick={ () => handleAction( r, 'flagged' ) } title="Flag" style={ actionBtnStyle }>🚩</button> }
          <button onClick={ () => setSelected( r ) } title="Details" style={ actionBtnStyle }>👁️</button>
        </div>
      )
    },
  ];

  return (
    <MaybeLayout embedded={ embedded } user={ user } onSignOut={ signOut }>
      <SEO { ...PAGE_SEO.reviews } />
      <div style={ { padding: '24px 32px', maxWidth: 1400 } }>
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 } }>
          <div>
            <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: 0 } }>Reviews</h1>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '4px 0 0' } }>{ reviews.length } reviews</p>
          </div>
          <Button variant="secondary" icon="refresh" onClick={ loadData }>Refresh</Button>
        </div>

        <div style={ { display: 'flex', gap: 12, marginBottom: 16 } }>
          <select value={ statusFilter } onChange={ e => { setStatusFilter( e.target.value ); setPage( 1 ); } } style={ selectStyle }>
            <option value="">All Statuses</option>
            { STATUS_OPTIONS.map( s => <option key={ s } value={ s }>{ s }</option> ) }
          </select>
          <select value={ sourceFilter } onChange={ e => { setSourceFilter( e.target.value ); setPage( 1 ); } } style={ selectStyle }>
            <option value="">All Sources</option>
            { SOURCE_OPTIONS.map( s => <option key={ s } value={ s }>{ s }</option> ) }
          </select>
          <select value={ ratingFilter } onChange={ e => { setRatingFilter( e.target.value ); setPage( 1 ); } } style={ selectStyle }>
            <option value="">All Ratings</option>
            { [ 5, 4, 3, 2, 1 ].map( r => <option key={ r } value={ r }>{ r }+ stars</option> ) }
          </select>
        </div>

        { reviews.length === 0 && !loading ? (
          <EmptyState icon="default" title="No reviews" description="Customer reviews will appear here" />
        ) : (
          <>
            <Table columns={ columns } data={ paged } keyField="reviewId" loading={ loading } />
            { totalPages > 1 && <div style={ { marginTop: 16, display: 'flex', justifyContent: 'center' } }><Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } /></div> }
          </>
        ) }
      </div>

      <Modal isOpen={ !!selected } onClose={ () => setSelected( null ) } title="Review Details" size="md">
        { selected && (
          <div>
            <div style={ { textAlign: 'center', marginBottom: 16 } }>
              <div style={ { color: '#f59e0b', fontSize: 28, letterSpacing: 2 } }>{ stars( selected.rating ) }</div>
              <div style={ { fontSize: 14, color: '#6b7280', marginTop: 4 } }>{ selected.rating }/5</div>
            </div>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 } }>
              <div><span style={ labelStyle }>Customer</span><div style={ { fontWeight: 500 } }>{ selected.customerName || '—' }</div></div>
              <div><span style={ labelStyle }>Phone</span><div>{ selected.customerPhone || '—' }</div></div>
              <div><span style={ labelStyle }>Source</span><div>{ selected.source }</div></div>
              <div><span style={ labelStyle }>Status</span><div>{ statusBadge( selected.status ) }</div></div>
              <div><span style={ labelStyle }>Date</span><div>{ formatDate( selected.createdAt ) }</div></div>
              { /* "Reference" for the same reason as the list column above: this field can
                   hold either a `WD-ORD-…` order number or a `WD-PAY-…` payment reference,
                   so "Order" is true of only one of them. The label was here before Phase R
                   but nothing ever wrote the field, so this is the first release in which
                   it is read by anyone. */ }
              { selected.orderId && <div><span style={ labelStyle }>Reference</span><div>{ selected.orderId }</div></div> }
            </div>
            { selected.comment && <div style={ { marginBottom: 12 } }><span style={ labelStyle }>Comment</span><div style={ { padding: 12, background: '#f9fafb', borderRadius: 8, fontSize: 14, whiteSpace: 'pre-wrap' } }>{ selected.comment }</div></div> }
            { selected.response && <div style={ { marginBottom: 12 } }><span style={ labelStyle }>Response</span><div style={ { padding: 12, background: '#f0fdf4', borderRadius: 8, fontSize: 14, whiteSpace: 'pre-wrap' } }>{ selected.response }</div></div> }
            { !selected.response && (
              <div style={ { marginBottom: 12 } }>
                <span style={ labelStyle }>Write Response</span>
                <textarea id="review-response" rows={ 3 } placeholder="Write a response to this review..." style={ { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 4, resize: 'vertical' } } />
              </div>
            ) }
            <div style={ { display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 } }>
              { !selected.response && <Button variant="secondary" onClick={ async () => {
                const textarea = document.getElementById( 'review-response' ) as HTMLTextAreaElement;
                const response = textarea?.value?.trim();
                if ( !response ) { return; }
                const ok = await api.updateReview( selected.reviewId, { response } as any );
                if ( ok ) { toast.success( 'Response saved' ); loadData(); setSelected( { ...selected, response } ); }
                else toast.error( 'Failed to save response' );
              } }>Save Response</Button> }
              <Button variant="primary" onClick={ () => handleAction( selected, 'approved' ) }>Approve</Button>
              <Button variant="secondary" onClick={ () => handleAction( selected, 'hidden' ) }>Hide</Button>
              <Button variant="danger" onClick={ () => handleAction( selected, 'flagged' ) }>Flag</Button>
            </div>
          </div>
        ) }
      </Modal>
    </MaybeLayout>
  );
};

const selectStyle: React.CSSProperties = { padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14 };
const labelStyle: React.CSSProperties = { fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 2 };
const actionBtnStyle: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, padding: '2px 4px' };

export default ReviewsPage;
