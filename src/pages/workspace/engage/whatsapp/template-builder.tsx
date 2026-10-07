/**
 * Template Builder wizard (Part 5) — Basics → Header → Body → Footer → Buttons →
 * Flow button → TTL → Preview → Submit. Live chat preview, local validation
 * (errors + warnings), payload + cURL preview, presets, create.
 */
import React, { useState, useMemo, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import {
    WabaSelector, TemplatePreviewCard, ValidationErrorList, WarningList,
    CurlPreview, RawJsonDrawer, MetaErrorPanel, WABA_OPTIONS,
} from '../../../../components/wa';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const inp: React.CSSProperties = { width: '100%', padding: '8px 10px', border: '1px solid #d0d0d0', borderRadius: 6, marginTop: 4, marginBottom: 10, fontSize: 14 };
const lbl: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#444' };
/** Layout only: the two margins `inp` carried. The box comes from form-controls.css now. */
const selectLayout: React.CSSProperties = { marginTop: 4, marginBottom: 10 };
/* The old `<option key={ c }>{ c }</option>` had no `value`, so the native value WAS the text -
   which is why value and label are the same string here. */
const CATEGORY_OPTIONS: SelectOption[] = [ 'UTILITY', 'MARKETING', 'AUTHENTICATION' ]
    .map( c => ( { value: c, label: c } ) );
const HEADER_FORMAT_OPTIONS: SelectOption[] = [ 'NONE', 'TEXT', 'IMAGE', 'VIDEO', 'DOCUMENT', 'LOCATION' ]
    .map( f => ( { value: f, label: f } ) );
const STEPS = [ 'Basics', 'Header', 'Body', 'Footer', 'Buttons', 'Flow button', 'TTL', 'Preview' ];

type BtnType = 'QUICK_REPLY' | 'URL' | 'PHONE_NUMBER' | 'COPY_CODE';

const TemplateBuilder: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const [ step, setStep ] = useState( 0 );
    const [ wabaId, setWabaId ] = useState( WABA_OPTIONS?.[ 0 ]?.wabaId || '' );

    // Basics
    const [ name, setName ] = useState( '' );
    const [ language, setLanguage ] = useState( 'en' );
    const [ category, setCategory ] = useState( 'UTILITY' );
    // Header
    const [ headerFormat, setHeaderFormat ] = useState( 'NONE' );
    const [ headerText, setHeaderText ] = useState( '' );
    // Body / Footer
    const [ bodyText, setBodyText ] = useState( 'Hi {{1}}, ' );
    const [ bodyExample, setBodyExample ] = useState( 'Asha' );
    const [ footerText, setFooterText ] = useState( '' );
    // Buttons
    const [ buttons, setButtons ] = useState<{ type: BtnType; text: string; url?: string; phone_number?: string; example?: string }[]>( [] );
    // Flow button
    const [ flowEnabled, setFlowEnabled ] = useState( false );
    const [ flowName, setFlowName ] = useState( '' );
    const [ flowScreen, setFlowScreen ] = useState( 'WELCOME' );
    const [ flowCtaText, setFlowCtaText ] = useState( 'Open' );
    // TTL
    const [ ttlRules, setTtlRules ] = useState<api.TtlRules | null>( null );
    const [ ttl, setTtl ] = useState<number | ''>( '' );
    // validation + submit
    const [ result, setResult ] = useState<api.TemplateValidationResult | null>( null );
    const [ submitting, setSubmitting ] = useState( false );
    const [ submitError, setSubmitError ] = useState<any>( null );

    useEffect( () => { api.getTemplateTtlRules().then( setTtlRules ).catch( () => { } ); }, [] );

    // Build a Meta template definition from the form state.
    const templateDef = useMemo( () => {
        const components: any[] = [];
        if ( headerFormat === 'TEXT' && headerText ) components.push( { type: 'HEADER', format: 'TEXT', text: headerText } );
        else if ( headerFormat !== 'NONE' && headerFormat !== 'TEXT' ) components.push( { type: 'HEADER', format: headerFormat } );
        const body: any = { type: 'BODY', text: bodyText };
        if ( /\{\{\s*1\s*\}\}/.test( bodyText ) && bodyExample ) body.example = { body_text: [ [ bodyExample ] ] };
        components.push( body );
        if ( footerText ) components.push( { type: 'FOOTER', text: footerText } );
        const btns: any[] = buttons.map( b => ( { ...b } ) );
        if ( flowEnabled && flowName ) btns.push( { type: 'FLOW', text: flowCtaText, flow_name: flowName, flow_action: 'navigate', navigate_screen: flowScreen } );
        if ( btns.length ) components.push( { type: 'BUTTONS', buttons: btns } );
        const def: any = { name, language, category, components };
        if ( ttl !== '' ) def.message_send_ttl_seconds = Number( ttl );
        return def;
    }, [ name, language, category, headerFormat, headerText, bodyText, bodyExample, footerText, buttons, flowEnabled, flowName, flowScreen, flowCtaText, ttl ] );

    const runValidate = useCallback( async () => {
        try { setResult( await api.validateTemplateDefinition( templateDef ) ); }
        catch ( e: any ) { toast.error( e?.message || 'Validation failed' ); }
    }, [ templateDef, toast ] );

    useEffect( () => { if ( step === STEPS.length - 1 ) runValidate(); }, [ step, runValidate ] );

    const loadPreset = async ( presetName: string ) => {
        const p = await api.getTemplatePreset( presetName );
        if ( !p ) return;
        setName( p.name ); setLanguage( p.language ); setCategory( p.category );
        if ( p.message_send_ttl_seconds != null ) setTtl( p.message_send_ttl_seconds );
        for ( const c of p.components || [] )
        {
            const t = ( c.type || '' ).toUpperCase();
            if ( t === 'HEADER' ) { setHeaderFormat( c.format || 'TEXT' ); setHeaderText( c.text || '' ); }
            else if ( t === 'BODY' ) setBodyText( c.text || '' );
            else if ( t === 'FOOTER' ) setFooterText( c.text || '' );
            else if ( t === 'BUTTONS' )
            {
                const flow = ( c.buttons || [] ).find( ( b: any ) => ( b.type || '' ).toUpperCase() === 'FLOW' );
                if ( flow ) { setFlowEnabled( true ); setFlowName( flow.flow_name || '' ); setFlowScreen( flow.navigate_screen || 'WELCOME' ); setFlowCtaText( flow.text || 'Open' ); }
                setButtons( ( c.buttons || [] ).filter( ( b: any ) => ( b.type || '' ).toUpperCase() !== 'FLOW' ).map( ( b: any ) => ( { type: b.type, text: b.text, url: b.url, phone_number: b.phone_number, example: b.example } ) ) );
            }
        }
        toast.success( `Loaded preset ${presetName}` );
    };

    const submit = async () => {
        const v = await api.validateTemplateDefinition( templateDef );
        setResult( v );
        if ( v && !v.ok ) { toast.error( 'Fix validation errors before submitting' ); return; }
        setSubmitting( true ); setSubmitError( null );
        try
        {
            const res = await api.createTemplate( { wabaId, templateDefinition: templateDef as any } );
            if ( res?.metaTemplateId ) toast.success( `Template submitted — ${res.templateStatus}` );
            else setSubmitError( res || 'Submit failed' );
        } catch ( e: any ) { setSubmitError( e?.message || 'Submit failed' ); }
        finally { setSubmitting( false ); }
    };

    const addButton = ( type: BtnType ) => setButtons( b => [ ...b, { type, text: '' } ] );
    const updateButton = ( i: number, patch: any ) => setButtons( b => b.map( ( x, j ) => j === i ? { ...x, ...patch } : x ) );
    const removeButton = ( i: number ) => setButtons( b => b.filter( ( _, j ) => j !== i ) );

    const content = (
        <div style={ { maxWidth: 900, margin: '0 auto', padding: 16 } }>
            <SEO title="Template Builder" description="Build and validate WhatsApp message templates." noindex />
            <h1 style={ { fontSize: 22, fontWeight: 700, marginBottom: 4 } }>Template Builder</h1>
            <p style={ { color: '#777', fontSize: 13, marginBottom: 12 } }>Build, validate, and submit a WhatsApp template. Presets below to start fast.</p>

            <div style={ { display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' } }>
                { [ 'seasonal_promotion', 'order_confirmation', 'flow_lead_generation' ].map( p => (
                    <button key={ p } onClick={ () => loadPreset( p ) } style={ { fontSize: 11, padding: '3px 10px', borderRadius: 999, border: '1px solid #d0d0d0', background: '#fff', cursor: 'pointer' } }>{ p }</button>
                ) ) }
            </div>

            <div style={ { display: 'flex', gap: 4, borderBottom: '1px solid #e5e5e5', marginBottom: 16, flexWrap: 'wrap' } }>
                { STEPS.map( ( s, i ) => (
                    <button key={ s } onClick={ () => setStep( i ) } style={ { padding: '8px 12px', border: 'none', borderBottom: step === i ? '2px solid #1a3a2a' : '2px solid transparent', background: 'none', cursor: 'pointer', fontWeight: step === i ? 700 : 500, color: step === i ? '#1a3a2a' : '#888', fontSize: 13 } }>{ i + 1 }. { s }</button>
                ) ) }
            </div>

            <div style={ { display: 'grid', gridTemplateColumns: '1fr 340px', gap: 20 } }>
                <div>
                    { step === 0 && (
                        <div>
                            <WabaSelector value={ wabaId } onChange={ setWabaId } />
                            <div style={ { marginTop: 10 } } />
                            <label style={ lbl }>Name (lowercase_underscores)</label>
                            <input style={ inp } value={ name } onChange={ e => setName( e.target.value.toLowerCase().replace( /[^a-z0-9_]/g, '_' ) ) } placeholder="order_confirmation" />
                            <label style={ lbl }>Language</label>
                            <input style={ inp } value={ language } onChange={ e => setLanguage( e.target.value ) } />
                            <label style={ lbl }>Category</label>
                            <Select ariaLabel="Category" value={ category } onChange={ v => setCategory( v ) }
                                options={ CATEGORY_OPTIONS } style={ selectLayout } />
                        </div>
                    ) }
                    { step === 1 && (
                        <div>
                            <label style={ lbl }>Header format</label>
                            <Select ariaLabel="Header format" value={ headerFormat } onChange={ v => setHeaderFormat( v ) }
                                options={ HEADER_FORMAT_OPTIONS } style={ selectLayout } />
                            { headerFormat === 'TEXT' && ( <>
                                <label style={ lbl }>Header text (≤60, ≤1 variable)</label>
                                <input style={ inp } value={ headerText } maxLength={ 60 } onChange={ e => setHeaderText( e.target.value ) } />
                            </> ) }
                        </div>
                    ) }
                    { step === 2 && (
                        <div>
                            <label style={ lbl }>Body text (≤1024). Use { '{{1}}' } for variables.</label>
                            <textarea style={ { ...inp, minHeight: 110 } } value={ bodyText } maxLength={ 1024 } onChange={ e => setBodyText( e.target.value ) } />
                            { /\{\{\s*1\s*\}\}/.test( bodyText ) && ( <>
                                <label style={ lbl }>Example for { '{{1}}' }</label>
                                <input style={ inp } value={ bodyExample } onChange={ e => setBodyExample( e.target.value ) } />
                            </> ) }
                        </div>
                    ) }
                    { step === 3 && (
                        <div>
                            <label style={ lbl }>Footer (≤60, no variables)</label>
                            <input style={ inp } value={ footerText } maxLength={ 60 } onChange={ e => setFooterText( e.target.value ) } />
                        </div>
                    ) }
                    { step === 4 && (
                        <div>
                            <div style={ { display: 'flex', gap: 6, marginBottom: 10 } }>
                                { ( [ 'QUICK_REPLY', 'URL', 'PHONE_NUMBER', 'COPY_CODE' ] as BtnType[] ).map( t => (
                                    <button key={ t } onClick={ () => addButton( t ) } style={ { fontSize: 11, padding: '4px 8px', borderRadius: 6, border: '1px solid #d0d0d0', background: '#fff', cursor: 'pointer' } }>+ { t }</button>
                                ) ) }
                            </div>
                            { buttons.map( ( b, i ) => (
                                <div key={ i } style={ { border: '1px solid #eee', borderRadius: 6, padding: 8, marginBottom: 8 } }>
                                    <div style={ { display: 'flex', justifyContent: 'space-between' } }>
                                        <strong style={ { fontSize: 12 } }>{ b.type }</strong>
                                        <button onClick={ () => removeButton( i ) } style={ { border: 'none', background: 'none', color: '#a11', cursor: 'pointer' } }>remove</button>
                                    </div>
                                    <input style={ inp } placeholder="Button text (≤25)" maxLength={ 25 } value={ b.text } onChange={ e => updateButton( i, { text: e.target.value } ) } />
                                    { b.type === 'URL' && <input style={ inp } placeholder="https://…" value={ b.url || '' } onChange={ e => updateButton( i, { url: e.target.value } ) } /> }
                                    { b.type === 'PHONE_NUMBER' && <input style={ inp } placeholder="+91…" value={ b.phone_number || '' } onChange={ e => updateButton( i, { phone_number: e.target.value } ) } /> }
                                    { b.type === 'COPY_CODE' && <input style={ inp } placeholder="Example code (≤20)" maxLength={ 20 } value={ b.example || '' } onChange={ e => updateButton( i, { example: e.target.value } ) } /> }
                                </div>
                            ) ) }
                        </div>
                    ) }
                    { step === 5 && (
                        <div>
                            <label style={ { ...lbl, display: 'flex', gap: 6, alignItems: 'center' } }>
                                <input type="checkbox" checked={ flowEnabled } onChange={ e => setFlowEnabled( e.target.checked ) } /> Add a Flow button
                            </label>
                            { flowEnabled && ( <div style={ { marginTop: 8 } }>
                                <label style={ lbl }>Flow name</label>
                                <input style={ inp } value={ flowName } onChange={ e => setFlowName( e.target.value ) } placeholder="lead-generation-flow" />
                                <label style={ lbl }>CTA text</label>
                                <input style={ inp } value={ flowCtaText } onChange={ e => setFlowCtaText( e.target.value ) } />
                                <label style={ lbl }>Navigate screen</label>
                                <input style={ inp } value={ flowScreen } onChange={ e => setFlowScreen( e.target.value ) } />
                            </div> ) }
                        </div>
                    ) }
                    { step === 6 && (
                        <div>
                            <label style={ lbl }>TTL seconds (message_send_ttl_seconds)</label>
                            <input style={ inp } type="number" value={ ttl } onChange={ e => setTtl( e.target.value === '' ? '' : Number( e.target.value ) ) } placeholder="e.g. 43200" />
                            { ttlRules && ttlRules.categories[ category ] && (
                                <div style={ { fontSize: 12, color: '#888' } }>{ ttlRules.categories[ category ].description }</div>
                            ) }
                        </div>
                    ) }
                    { step === 7 && (
                        <div>
                            <ValidationErrorList errors={ result?.errors } />
                            <WarningList warnings={ result?.warnings } />
                            <CurlPreview spec={ { method: 'POST', url: 'https://graph.facebook.com/v25.0/{WABA_ID}/message_templates', body: templateDef } } />
                            <RawJsonDrawer data={ templateDef } label="Template JSON payload" defaultOpen />
                            { submitError && <MetaErrorPanel error={ submitError } /> }
                            <button onClick={ submit } disabled={ submitting || ( result ? !result.ok : false ) } style={ { marginTop: 12, padding: '10px 18px', borderRadius: 6, border: 'none', fontWeight: 700, background: ( result && !result.ok ) ? '#ccc' : '#1a7a3a', color: '#fff', cursor: 'pointer' } }>
                                { submitting ? 'Submitting…' : 'Submit to Meta' }
                            </button>
                        </div>
                    ) }

                    <div style={ { display: 'flex', justifyContent: 'space-between', marginTop: 16 } }>
                        <button onClick={ () => setStep( s => Math.max( 0, s - 1 ) ) } disabled={ step === 0 } style={ navBtn }>← Back</button>
                        <button onClick={ () => setStep( s => Math.min( STEPS.length - 1, s + 1 ) ) } disabled={ step === STEPS.length - 1 } style={ navBtn }>Next →</button>
                    </div>
                </div>

                <div>
                    <div style={ { fontSize: 12, fontWeight: 600, color: '#444', marginBottom: 6 } }>Live preview</div>
                    <TemplatePreviewCard template={ { ...templateDef, components: templateDef.components } as any } />
                </div>
            </div>
        </div>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

const navBtn: React.CSSProperties = { padding: '8px 16px', border: '1px solid #d0d0d0', background: '#fff', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: 13 };

export default TemplateBuilder;
