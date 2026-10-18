/**
 * RCS Templates Page - Create, list, and manage RCS templates
 * Supports: Text, Rich Card, Rich Card Carousel
 */
import React, { useState, useEffect, useCallback } from 'react';
import Button from '../../../components/ui/Button';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import MaybeLayout from '../../../components/MaybeLayout';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
interface RcsTemplate { name: string; type: string; botId: string; textMessageContent?: string; createdViaApi?: boolean; }

const TEMPLATE_TYPES = [
    { id: 'text_message', label: 'Text', desc: 'Up to 2,500 chars with 10 interactive buttons' },
    { id: 'rich_card', label: 'Rich Card', desc: 'Image/video + title + description + 4 buttons' },
    { id: 'rich_card_carousel', label: 'Carousel', desc: 'Up to 10 Rich Cards in a carousel' },
];

const RcsTemplatesPageBody: React.FC<PageProps> = ( { embedded } ) => {
    const [ templates, setTemplates ] = useState<RcsTemplate[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ showCreate, setShowCreate ] = useState( false );
    const [ creating, setCreating ] = useState( false );
    const toast = useToastContext();

    // Create form state
    const [ newName, setNewName ] = useState( '' );
    const [ newType, setNewType ] = useState( 'text_message' );
    const [ newText, setNewText ] = useState( '' );
    const [ newTitle, setNewTitle ] = useState( '' );
    const [ newDescription, setNewDescription ] = useState( '' );
    const [ newMediaUrl, setNewMediaUrl ] = useState( '' );
    const [ newMediaType, setNewMediaType ] = useState( 'image' );

    const loadTemplates = useCallback( async () => {
        setLoading( true );
        try
        {
            const templates = await api.listRcsTemplates();
            setTemplates( templates );
        } catch ( err ) { toast.error( 'Failed to load templates' ); } finally { setLoading( false ); }
    }, [ toast ] );

    useEffect( () => { loadTemplates(); }, [ loadTemplates ] );

    const handleCreate = async () => {
        if ( !newName.trim() ) { toast.error( 'Template name required' ); return; }
        if ( newType === 'text_message' && !newText.trim() ) { toast.error( 'Template text required' ); return; }
        setCreating( true );
        try
        {
            const name = newName.trim().toLowerCase().replace( /\s+/g, '_' );
            let text = '';

            if ( newType === 'text_message' )
            {
                text = newText;
            } else if ( newType === 'rich_card' )
            {
                text = JSON.stringify( {
                    title: newTitle,
                    description: newDescription,
                    media: { url: newMediaUrl, type: newMediaType },
                } );
            } else
            {
                text = newText; // Carousel uses JSON array
            }

            const data = await api.createRcsTemplate( name, text, newType );
            if ( data?.success || data?.template )
            {
                toast.success( `Template "${newName}" created!` );
                setShowCreate( false );
                resetForm();
                await loadTemplates();
            } else
            {
                toast.error( data?.error || 'Failed to create template' );
            }
        } catch ( err: any ) { toast.error( err.message || 'Create failed' ); } finally { setCreating( false ); }
    };

    const resetForm = () => {
        setNewName( '' ); setNewType( 'text_message' ); setNewText( '' );
        setNewTitle( '' ); setNewDescription( '' ); setNewMediaUrl( '' );
    };

    return (
        <div style={ { padding: 16 } }>
            {/* Header */ }
            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } }>
                <div>
                    <div style={ { fontSize: 11, color: 'var(--text-muted)' } }>Bot: WECARE.DIGITAL (Transactional) | ID: 69e0b2c980cbf50614ffa5fd</div>
                </div>
                <div style={ { display: 'flex', gap: 8 } }>
                    <Button variant="primary" onClick={ () => setShowCreate( true ) }>Create Template</Button>
                    <Button variant="secondary" onClick={ loadTemplates } loading={ loading }>Refresh</Button>
                </div>
            </div>

            {/* Templates List */ }
            { loading ? <div style={ { padding: 40, textAlign: 'center', color: 'var(--text-muted)' } }>Loading templates...</div> : (
                <div style={ { display: 'grid', gap: 12 } }>
                    { templates.map( ( tpl, i ) => (
                        <div key={ i } style={ { border: '1px solid var(--border)', borderRadius: 8, padding: 16, background: '#fff' } }>
                            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' } }>
                                <div>
                                    <div style={ { fontWeight: 600, fontSize: 14 } }>{ tpl.name }</div>
                                    <div style={ { fontSize: 12, color: 'var(--text-muted)', marginTop: 2 } }>Type: { tpl.type } { tpl.createdViaApi ? '(API)' : '' }</div>
                                </div>
                                <span style={ { padding: '2px 8px', borderRadius: 4, fontSize: 11, background: '#f0fdf4', color: '#166534', border: '1px solid #bbf7d0' } }>Active</span>
                            </div>
                            { tpl.textMessageContent && (
                                <div style={ { marginTop: 8, padding: 10, background: 'var(--bg-secondary)', borderRadius: 6, fontSize: 13, whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' } }>
                                    { tpl.textMessageContent }
                                </div>
                            ) }
                        </div>
                    ) ) }
                    { templates.length === 0 && (
                        <div style={ { padding: 40, textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-secondary)', borderRadius: 8 } }>
                            No templates found. Click &quot;Create Template&quot; to add one.
                        </div>
                    ) }
                </div>
            ) }

            {/* Create Template Modal */ }
            { showCreate && (
                <div style={ { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 } } onClick={ () => setShowCreate( false ) }>
                    <div style={ { background: '#fff', borderRadius: 12, padding: 24, width: '100%', maxWidth: 520, maxHeight: '80vh', overflow: 'auto' } } onClick={ e => e.stopPropagation() }>
                        <h3 style={ { margin: '0 0 16px', fontSize: 18 } }>Create RCS Template</h3>

                        {/* Name */ }
                        <div style={ { marginBottom: 12 } }>
                            <label style={ { display: 'block', fontWeight: 500, marginBottom: 4, fontSize: 13 } }>Template Name *</label>
                            <input type="text" value={ newName } onChange={ e => setNewName( e.target.value ) } placeholder="wecare_order_confirm" style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6 } } />
                            <div style={ { fontSize: 11, color: 'var(--text-muted)', marginTop: 2 } }>Lowercase, underscores only. e.g. wecare_order_confirm</div>
                        </div>

                        {/* Type */ }
                        <div style={ { marginBottom: 12 } }>
                            <label style={ { display: 'block', fontWeight: 500, marginBottom: 4, fontSize: 13 } }>Template Type *</label>
                            <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap' } }>
                                { TEMPLATE_TYPES.map( t => (
                                    <button key={ t.id } onClick={ () => setNewType( t.id ) } style={ { padding: '8px 14px', borderRadius: 6, border: newType === t.id ? '2px solid var(--accent)' : '1px solid #d1d5db', background: newType === t.id ? '#f0fdf4' : '#fff', cursor: 'pointer', textAlign: 'left' } }>
                                        <div style={ { fontWeight: 500, fontSize: 13 } }>{ t.label }</div>
                                        <div style={ { fontSize: 11, color: 'var(--text-muted)' } }>{ t.desc }</div>
                                    </button>
                                ) ) }
                            </div>
                        </div>

                        {/* Text Message Content */ }
                        { newType === 'text_message' && (
                            <div style={ { marginBottom: 12 } }>
                                <label style={ { display: 'block', fontWeight: 500, marginBottom: 4, fontSize: 13 } }>Message Text * <span style={ { fontWeight: 400, color: 'var(--text-muted)' } }>(max 2500 chars)</span></label>
                                <textarea value={ newText } onChange={ e => setNewText( e.target.value ) } placeholder="Hi [custom_param1b], your order has been confirmed. Thank you!" rows={ 5 } style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6 } } />
                                <div style={ { fontSize: 11, color: 'var(--text-muted)', marginTop: 2 } }>{ newText.length }/2500 · Use [custom_param1b], [custom_param2b] for variables</div>
                            </div>
                        ) }

                        {/* Rich Card Content */ }
                        { newType === 'rich_card' && (
                            <>
                                <div style={ { marginBottom: 12 } }>
                                    <label style={ { display: 'block', fontWeight: 500, marginBottom: 4, fontSize: 13 } }>Title</label>
                                    <input type="text" value={ newTitle } onChange={ e => setNewTitle( e.target.value ) } placeholder="Order Confirmed!" style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6 } } />
                                </div>
                                <div style={ { marginBottom: 12 } }>
                                    <label style={ { display: 'block', fontWeight: 500, marginBottom: 4, fontSize: 13 } }>Description</label>
                                    <textarea value={ newDescription } onChange={ e => setNewDescription( e.target.value ) } placeholder="Your order has been confirmed..." rows={ 3 } style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6 } } />
                                </div>
                                <div style={ { marginBottom: 12 } }>
                                    <label style={ { display: 'block', fontWeight: 500, marginBottom: 4, fontSize: 13 } }>Media URL</label>
                                    <input type="url" value={ newMediaUrl } onChange={ e => setNewMediaUrl( e.target.value ) } placeholder="https://..." style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6 } } />
                                    <div style={ { display: 'flex', gap: 8, marginTop: 4 } }>
                                        <label style={ { fontSize: 12 } }><input type="radio" name="mediaType" value="image" checked={ newMediaType === 'image' } onChange={ () => setNewMediaType( 'image' ) } /> Image</label>
                                        <label style={ { fontSize: 12 } }><input type="radio" name="mediaType" value="video" checked={ newMediaType === 'video' } onChange={ () => setNewMediaType( 'video' ) } /> Video</label>
                                    </div>
                                </div>
                            </>
                        ) }

                        {/* Carousel Content */ }
                        { newType === 'rich_card_carousel' && (
                            <div style={ { marginBottom: 12 } }>
                                <label style={ { display: 'block', fontWeight: 500, marginBottom: 4, fontSize: 13 } }>Carousel JSON (array of cards)</label>
                                <textarea value={ newText } onChange={ e => setNewText( e.target.value ) } placeholder='[{"title":"Card 1","description":"...","media":{"url":"https://...","type":"image"}}]' rows={ 6 } style={ { width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6, fontFamily: 'monospace', fontSize: 12 } } />
                                <div style={ { fontSize: 11, color: 'var(--text-muted)', marginTop: 2 } }>Max 10 cards. Each card: title, description, media (url + type), buttons</div>
                            </div>
                        ) }

                        {/* Actions */ }
                        <div style={ { display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 } }>
                            <Button variant="secondary" onClick={ () => { setShowCreate( false ); resetForm(); } }>Cancel</Button>
                            <Button variant="primary" onClick={ handleCreate } loading={ creating } disabled={ !newName.trim() }>Create Template</Button>
                        </div>
                    </div>
                </div>
            ) }
        </div>
    );
};
/** Shell-only view of the props: not all six pages declare these. */
type AnyShellProps = { user?: unknown; signOut?: () => void };


/**
 * Standalone shell. This page renders no chrome of its own - it was written as an
 * embedded tab body - so as a live route it had no sidebar, no breadcrumb and no
 * back link, and the sidebar was the only way out. MaybeLayout renders children
 * bare when `embedded`, so every hub that embeds it is unaffected.
 */
const RcsTemplatesPage: React.FC<PageProps> = ( props ) => (
  <MaybeLayout embedded={ props.embedded } user={ ( props as AnyShellProps ).user }
    onSignOut={ ( props as AnyShellProps ).signOut }>
    <RcsTemplatesPageBody { ...props } />
  </MaybeLayout>
);

export default RcsTemplatesPage;
