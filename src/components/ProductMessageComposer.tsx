/**
 * Product Message Composer (Part 5 / Commerce)
 * Sends single-product or multi-product (product_list) interactive messages via
 * the /wa-business/messages/send/product route (api.sendTestProduct).
 */
import React, { useState } from 'react';
import * as api from '../api/client';

interface ProductMessageComposerProps {
    phoneNumberId?: string;     // Meta phone number ID to send from
    recipient?: string;         // prefill recipient (E.164, no +)
    onSent?: () => void;
    onError?: ( msg: string ) => void;
    onClose?: () => void;
}

interface SectionDraft {
    title: string;
    retailerIds: string;        // comma-separated product_retailer_ids
}

const input: React.CSSProperties = { width: '100%', padding: '8px 10px', border: '1px solid #d0d0d0', borderRadius: 6, marginTop: 4, marginBottom: 10, fontSize: 14 };
const label: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#444' };
const btn: React.CSSProperties = { padding: '9px 16px', background: '#1a3a2a', color: '#d1f470', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14, fontWeight: 600 };

// Same bounds the handler enforces (_PRODUCT_CAROUSEL_MIN_CARDS / _MAX_CARDS), so the
// refusal happens here with a readable message instead of as a 400 from the route.
const CAROUSEL_MIN_CARDS = 2;
const CAROUSEL_MAX_CARDS = 10;

const MODE_LABELS: Record<string, string> = { single: 'Single product', multi: 'Multi-product', carousel: 'Carousel' };

const ProductMessageComposer: React.FC<ProductMessageComposerProps> = ( { phoneNumberId, recipient, onSent, onError, onClose } ) => {
    const [ to, setTo ] = useState( recipient || '' );
    const [ catalogId, setCatalogId ] = useState( '' );
    const [ mode, setMode ] = useState<'single' | 'multi' | 'carousel'>( 'single' );
    const [ busy, setBusy ] = useState( false );

    // single
    const [ retailerId, setRetailerId ] = useState( '' );
    const [ bodyText, setBodyText ] = useState( '' );
    // multi
    const [ headerText, setHeaderText ] = useState( 'Our products' );
    const [ footerText, setFooterText ] = useState( '' );
    const [ sections, setSections ] = useState<SectionDraft[]>( [ { title: '', retailerIds: '' } ] );
    // carousel — a catalog presentation, never a payment surface: no amount, no payment
    // configuration and no order_details anywhere on this path.
    const [ carouselIds, setCarouselIds ] = useState( '' );

    const setSection = ( i: number, patch: Partial<SectionDraft> ) =>
        setSections( s => s.map( ( sec, idx ) => idx === i ? { ...sec, ...patch } : sec ) );
    const addSection = () => setSections( s => [ ...s, { title: '', retailerIds: '' } ] );
    const removeSection = ( i: number ) => setSections( s => s.filter( ( _, idx ) => idx !== i ) );

    const send = async () => {
        if ( !to.trim() ) { onError?.( 'Recipient is required' ); return; }
        if ( !catalogId.trim() ) { onError?.( 'Catalog ID is required' ); return; }
        setBusy( true );
        try
        {
            let opts: any;
            if ( mode === 'single' )
            {
                if ( !retailerId.trim() ) { onError?.( 'Product retailer ID is required' ); setBusy( false ); return; }
                opts = { productRetailerId: retailerId.trim(), bodyText: bodyText || undefined };
            } else if ( mode === 'carousel' )
            {
                const ids = carouselIds.split( ',' ).map( r => r.trim() ).filter( Boolean );
                if ( ids.length < CAROUSEL_MIN_CARDS || ids.length > CAROUSEL_MAX_CARDS )
                {
                    onError?.( `A product carousel needs ${CAROUSEL_MIN_CARDS}-${CAROUSEL_MAX_CARDS} product IDs (${ids.length} given)` );
                    setBusy( false );
                    return;
                }
                if ( !bodyText.trim() ) { onError?.( 'Body text is required for a product carousel' ); setBusy( false ); return; }
                opts = {
                    carouselCards: ids.map( r => ( { productRetailerId: r } ) ),
                    bodyText,
                    headerText: headerText || undefined,
                    footerText: footerText || undefined,
                };
            } else
            {
                const built = sections
                    .map( s => ( {
                        title: s.title.trim(),
                        product_items: s.retailerIds.split( ',' ).map( r => r.trim() ).filter( Boolean ).map( r => ( { product_retailer_id: r } ) ),
                    } ) )
                    .filter( s => s.title && s.product_items.length );
                if ( !built.length ) { onError?.( 'Add at least one section with a title and product IDs' ); setBusy( false ); return; }
                opts = { sections: built, headerText, bodyText: bodyText || undefined, footerText: footerText || undefined };
            }
            const res = await api.sendTestProduct( to.trim(), catalogId.trim(), { ...opts, phoneId: phoneNumberId } );
            if ( res?.success ) { onSent?.(); }
            else onError?.( res?.error || 'Send failed' );
        } catch ( e: any )
        {
            onError?.( e?.message || 'Send failed' );
        } finally
        {
            setBusy( false );
        }
    };

    return (
        <div style={ { border: '1px solid #e5e5e5', borderRadius: 8, padding: 16, background: '#fff' } }>
            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 } }>
                <strong style={ { fontSize: 15 } }>Product Message</strong>
                { onClose && <button onClick={ onClose } style={ { background: 'none', border: 'none', cursor: 'pointer', fontSize: 18 } }>×</button> }
            </div>

            <label style={ label }>Recipient (E.164, no +)</label>
            <input style={ input } value={ to } onChange={ e => setTo( e.target.value ) } placeholder="919900000000" />

            <label style={ label }>Catalog ID</label>
            <input style={ input } value={ catalogId } onChange={ e => setCatalogId( e.target.value ) } placeholder="Meta catalog ID" />

            <div style={ { display: 'flex', gap: 8, marginBottom: 12 } }>
                { ( [ 'single', 'multi', 'carousel' ] as const ).map( m => (
                    <button key={ m } onClick={ () => setMode( m ) } style={ {
                        padding: '6px 14px', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: 13,
                        border: '1px solid ' + ( mode === m ? '#1a3a2a' : '#d0d0d0' ),
                        background: mode === m ? '#1a3a2a' : '#fff', color: mode === m ? '#d1f470' : '#555',
                    } }>{ MODE_LABELS[ m ] }</button>
                ) ) }
            </div>

            { mode === 'single' ? (
                <>
                    <label style={ label }>Product retailer ID</label>
                    <input style={ input } value={ retailerId } onChange={ e => setRetailerId( e.target.value ) } placeholder="SKU / retailer id" />
                    <label style={ label }>Body text (optional)</label>
                    <input style={ input } value={ bodyText } onChange={ e => setBodyText( e.target.value ) } />
                </>
            ) : mode === 'carousel' ? (
                <>
                    <label style={ label }>Product IDs, comma-separated ({ CAROUSEL_MIN_CARDS }–{ CAROUSEL_MAX_CARDS } cards)</label>
                    <input style={ input } value={ carouselIds } onChange={ e => setCarouselIds( e.target.value ) } placeholder="SKU-1, SKU-2, SKU-3" />
                    <label style={ label }>Body text *</label>
                    <input style={ input } value={ bodyText } onChange={ e => setBodyText( e.target.value ) } />
                    <label style={ label }>Header text (optional)</label>
                    <input style={ input } value={ headerText } onChange={ e => setHeaderText( e.target.value ) } />
                    <label style={ label }>Footer text (optional)</label>
                    <input style={ input } value={ footerText } onChange={ e => setFooterText( e.target.value ) } />
                </>
            ) : (
                <>
                    <label style={ label }>Header text</label>
                    <input style={ input } value={ headerText } onChange={ e => setHeaderText( e.target.value ) } />
                    <label style={ label }>Body text (optional)</label>
                    <input style={ input } value={ bodyText } onChange={ e => setBodyText( e.target.value ) } />
                    <label style={ label }>Footer text (optional)</label>
                    <input style={ input } value={ footerText } onChange={ e => setFooterText( e.target.value ) } />
                    <label style={ label }>Sections</label>
                    { sections.map( ( sec, i ) => (
                        <div key={ i } style={ { border: '1px solid #eee', borderRadius: 6, padding: 10, marginBottom: 8 } }>
                            <input style={ input } value={ sec.title } onChange={ e => setSection( i, { title: e.target.value } ) } placeholder="Section title" />
                            <input style={ input } value={ sec.retailerIds } onChange={ e => setSection( i, { retailerIds: e.target.value } ) } placeholder="Product IDs, comma-separated" />
                            { sections.length > 1 && <button onClick={ () => removeSection( i ) } style={ { ...btn, background: '#fee2e2', color: '#991b1b', padding: '4px 10px', fontSize: 12 } }>Remove section</button> }
                        </div>
                    ) ) }
                    <button onClick={ addSection } style={ { ...btn, background: '#fff', color: '#1a3a2a', border: '1px solid #1a3a2a', marginBottom: 12 } }>+ Add section</button>
                </>
            ) }

            <div>
                <button onClick={ send } disabled={ busy } style={ btn }>{ busy ? 'Sending…' : 'Send product message' }</button>
            </div>
        </div>
    );
};

export default ProductMessageComposer;
