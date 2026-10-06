/**
 * Ads that Click to WhatsApp (CTWA) — [retired public path]/whatsapp/ctwa-ads
 *
 * Console for creating "Ads that Click to WhatsApp" via the Meta Marketing API.
 * A click on the ad opens a WhatsApp chat with our business number, optionally
 * pre-filling a greeting + autofill message. Backed by POST /marketing-ads:
 *   ad_accounts / pages / campaigns / ads / upload_image / full_create /
 *   ad_publish / ad_pause / ad_status
 *
 * SAFETY: ads are created PAUSED. Nothing spends money until you explicitly
 * publish an ad (which then goes to Meta review). Uses the ads_management,
 * ads_read, pages_manage_ads, pages_read_engagement, pages_show_list permissions.
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import Button from '../../../../components/ui/Button';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirmDanger } from '../../../../components/wa';
import {
    marketingAdsApi,
    type AdAccount, type FbPage, type AdEntity, type MarketingAdInput, type WabaKey,
} from '../../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 18, marginBottom: 16 };
const label: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 };
const input: React.CSSProperties = { width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 14, marginBottom: 10, boxSizing: 'border-box' };

const WABAS: { key: WabaKey; label: string }[] = [
    { key: 'WABA1', label: 'WABA1 · +91 93309 94400' },
    { key: 'WABA2', label: 'WABA2 · +91 99033 00044' },
];

const CtwaAdsPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const confirmDanger = useConfirmDanger();

    const [ accounts, setAccounts ] = useState<AdAccount[]>( [] );
    const [ pages, setPages ] = useState<FbPage[]>( [] );
    const [ acct, setAcct ] = useState( '' );
    const [ ads, setAds ] = useState<AdEntity[]>( [] );
    const [ busy, setBusy ] = useState( '' );

    // create form
    const [ waba, setWaba ] = useState<WabaKey>( 'WABA1' );
    const [ name, setName ] = useState( 'WECARE CTWA' );
    const [ objective, setObjective ] = useState<MarketingAdInput['objective']>( 'OUTCOME_ENGAGEMENT' );
    const [ dailyBudgetRs, setDailyBudgetRs ] = useState( '120' );
    const [ headline, setHeadline ] = useState( 'Chat with WECARE.DIGITAL' );
    const [ primaryText, setPrimaryText ] = useState( 'Message us on WhatsApp for instant help.' );
    const [ description, setDescription ] = useState( 'Tap to chat' );
    const [ greeting, setGreeting ] = useState( 'Hi! How can WECARE.DIGITAL help you today?' );
    const [ autofill, setAutofill ] = useState( 'Hi, I would like more information.' );
    const [ imageHash, setImageHash ] = useState( '' );

    const loadAccountsPages = useCallback( async () => {
        setBusy( 'meta' );
        try
        {
            const [ a, p ] = await Promise.all( [ marketingAdsApi.adAccounts(), marketingAdsApi.pages() ] );
            const accs = a?.adAccounts?.data || [];
            setAccounts( accs );
            if ( accs.length && !acct ) setAcct( accs[ 0 ].account_id );
            setPages( p?.pages?.data || [] );
        } catch { toast.error( 'Failed to load ad accounts/pages' ); }
        finally { setBusy( '' ); }
    }, [ acct, toast ] );

    const loadAds = useCallback( async () => {
        setBusy( 'ads' );
        try
        {
            const r = await marketingAdsApi.ads( acct || undefined );
            setAds( r?.ads?.data || [] );
        } catch { toast.error( 'Failed to load ads' ); }
        finally { setBusy( '' ); }
    }, [ acct, toast ] );

    useEffect( () => { loadAccountsPages(); }, [ loadAccountsPages ] );
    useEffect( () => { if ( acct ) loadAds(); }, [ acct, loadAds ] );

    const onUpload = async ( e: React.ChangeEvent<HTMLInputElement> ) => {
        const file = e.target.files?.[ 0 ];
        if ( !file ) return;
        setBusy( 'upload' );
        try
        {
            const b64 = await new Promise<string>( ( res, rej ) => {
                const rd = new FileReader();
                rd.onload = () => res( String( rd.result ).split( ',' )[ 1 ] || '' );
                rd.onerror = rej;
                rd.readAsDataURL( file );
            } );
            const r = await marketingAdsApi.uploadImage( b64, file.type || 'image/jpeg', acct || undefined );
            if ( r?.imageHash ) { setImageHash( r.imageHash ); toast.success( 'Image uploaded' ); }
            else toast.error( 'Upload failed: ' + JSON.stringify( r?.raw ).slice( 0, 140 ) );
        } finally { setBusy( '' ); }
    };

    const onCreate = async () => {
        const rs = Number( dailyBudgetRs );
        if ( !name.trim() || !rs ) { toast.error( 'Name and daily budget required' ); return; }
        setBusy( 'create' );
        try
        {
            const r = await marketingAdsApi.fullCreate( {
                name: name.trim(), objective, waba,
                adAccountId: acct || undefined,
                dailyBudget: Math.round( rs * 100 ),   // rupees -> paise
                headline, primaryText, description, greeting, autofill,
                imageHash: imageHash || undefined,
            } );
            if ( r?.created?.ad?.id ) { toast.success( 'Ad created (PAUSED). Publish it when ready.' ); loadAds(); }
            else toast.error( 'Create failed: ' + JSON.stringify( r?.steps || r?.error || r ).slice( 0, 200 ) );
        } finally { setBusy( '' ); }
    };

    const doPublish = async ( adId: string ) => {
        // DELIBERATE, OWNER-APPROVED BEHAVIOUR CHANGE, and the only one in this batch.
        // useConfirmDanger sets confirmInput from VERB.publish, so the operator now TYPES
        // PUBLISH where they previously clicked OK. That friction is the point: publishing
        // commits ad spend, and activating ad spend is one of the actions that must never be
        // casual. Do not "simplify" this back to a 1:1 confirm({ ... danger: true }) — the
        // alternative was offered and the typing requirement was chosen. It stays on
        // useConfirmDanger rather than useConfirm so the next spend-committing action
        // inherits the same friction from one place.
        if ( !( await confirmDanger(
            'publish',
            'It goes to Meta review and, once approved, will start spending your daily budget.',
            { title: 'Publish this ad?' },
        ) ) ) return;
        setBusy( 'pub' + adId );
        try
        {
            const r = await marketingAdsApi.publish( adId );
            if ( r?.status === 'ACTIVE' ) { toast.success( 'Submitted for review' ); loadAds(); }
            else toast.error( 'Publish failed' );
        } finally { setBusy( '' ); }
    };

    const doPause = async ( adId: string ) => {
        setBusy( 'pau' + adId );
        try { const r = await marketingAdsApi.pause( adId ); if ( r ) { toast.success( 'Paused' ); loadAds(); } }
        finally { setBusy( '' ); }
    };

    const body = (
        <div style={ { maxWidth: 1000, margin: '0 auto', padding: embedded ? 0 : 20 } }>
            <h1 style={ { fontSize: 22, fontWeight: 800, marginBottom: 4 } }>Ads that Click to WhatsApp</h1>
            <p style={ { color: '#6b7280', fontSize: 14, marginBottom: 16 } }>
                Create ads that open a WhatsApp chat with your business. Ads are created <b>paused</b> — nothing
                spends until you publish and Meta approves. Uses the Marketing API (<code>ads_management</code>).
            </p>

            <div style={ { ...card, background: '#fffbeb', borderColor: '#fde68a' } }>
                <b style={ { fontSize: 13 } }>Prerequisite</b>
                <p style={ { fontSize: 13, color: '#92400e', margin: '4px 0 0' } }>
                    The Facebook Page used for the ad must have a WhatsApp Business number connected
                    (Meta Business Suite → Page → Settings → WhatsApp). Without it, Meta rejects the ad set
                    with &quot;Page with WhatsApp Business account required&quot;.
                </p>
            </div>

            <div style={ card }>
                <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
                    <div>
                        <label style={ label }>Ad account</label>
                        <select style={ input } value={ acct } onChange={ e => setAcct( e.target.value ) }>
                            { accounts.map( a => <option key={ a.account_id } value={ a.account_id }>{ a.name } · {a.currency}</option> ) }
                        </select>
                    </div>
                    <div>
                        <label style={ label }>Facebook Page</label>
                        <select style={ input } disabled>
                            { pages.map( p => <option key={ p.id } value={ p.id }>{ p.name }</option> ) }
                            { pages.length === 0 && <option>No pages</option> }
                        </select>
                    </div>
                </div>
                <Button onClick={ loadAccountsPages } disabled={ busy !== '' }>{ busy === 'meta' ? 'Loading…' : 'Refresh assets' }</Button>
            </div>

            {/* Create */ }
            <div style={ card }>
                <h2 style={ { fontSize: 16, fontWeight: 700, marginBottom: 10 } }>Create ad</h2>
                <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
                    <div>
                        <label style={ label }>WhatsApp number (destination)</label>
                        <select style={ input } value={ waba } onChange={ e => setWaba( e.target.value as WabaKey ) }>
                            { WABAS.map( w => <option key={ w.key } value={ w.key }>{ w.label }</option> ) }
                        </select>
                    </div>
                    <div>
                        <label style={ label }>Objective</label>
                        <select style={ input } value={ objective } onChange={ e => setObjective( e.target.value as MarketingAdInput['objective'] ) }>
                            <option value="OUTCOME_ENGAGEMENT">Engagement</option>
                            <option value="OUTCOME_LEADS">Leads</option>
                            <option value="OUTCOME_SALES">Sales</option>
                            <option value="OUTCOME_TRAFFIC">Traffic</option>
                        </select>
                    </div>
                    <div><label style={ label }>Campaign name</label><input style={ input } value={ name } onChange={ e => setName( e.target.value ) } /></div>
                    <div><label style={ label }>Daily budget (₹)</label><input style={ input } type="number" value={ dailyBudgetRs } onChange={ e => setDailyBudgetRs( e.target.value ) } /></div>
                    <div style={ { gridColumn: '1 / span 2' } }><label style={ label }>Headline</label><input style={ input } value={ headline } onChange={ e => setHeadline( e.target.value ) } /></div>
                    <div style={ { gridColumn: '1 / span 2' } }><label style={ label }>Primary text</label><input style={ input } value={ primaryText } onChange={ e => setPrimaryText( e.target.value ) } /></div>
                    <div><label style={ label }>Description</label><input style={ input } value={ description } onChange={ e => setDescription( e.target.value ) } /></div>
                    <div>
                        <label style={ label }>Ad image (optional)</label>
                        <input style={ { ...input, padding: 6 } } type="file" accept="image/*" onChange={ onUpload } />
                        { imageHash && <span style={ { fontSize: 11, color: '#065f46' } }>image_hash set ✓</span> }
                    </div>
                    <div style={ { gridColumn: '1 / span 2' } }><label style={ label }>Greeting message (shown in chat)</label><input style={ input } value={ greeting } onChange={ e => setGreeting( e.target.value ) } /></div>
                    <div style={ { gridColumn: '1 / span 2' } }><label style={ label }>Autofill message (pre-typed for the customer)</label><input style={ input } value={ autofill } onChange={ e => setAutofill( e.target.value ) } /></div>
                </div>
                <Button onClick={ onCreate } disabled={ busy !== '' }>{ busy === 'create' ? 'Creating…' : 'Create ad (paused)' }</Button>
            </div>

            {/* Ads list */ }
            <div style={ card }>
                <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } }>
                    <h2 style={ { fontSize: 16, fontWeight: 700, margin: 0 } }>Your ads</h2>
                    <Button onClick={ loadAds } disabled={ busy !== '' }>{ busy === 'ads' ? 'Loading…' : 'Refresh' }</Button>
                </div>
                { ads.length === 0
                    ? <div style={ { fontSize: 13, color: '#9ca3af' } }>No ads yet.</div>
                    : (
                        <table style={ { width: '100%', fontSize: 13, borderCollapse: 'collapse' } }>
                            <thead><tr style={ { textAlign: 'left', color: '#6b7280' } }>
                                <th style={ { padding: 6 } }>Name</th><th>Status</th><th>Effective</th><th></th>
                            </tr></thead>
                            <tbody>
                                { ads.map( a => (
                                    <tr key={ a.id } style={ { borderTop: '1px solid #f0f0f0' } }>
                                        <td style={ { padding: 6 } }>{ a.name }</td>
                                        <td>{ a.status }</td>
                                        <td>{ a.effective_status }</td>
                                        <td style={ { textAlign: 'right' } }>
                                            { a.status === 'ACTIVE'
                                                ? <button onClick={ () => doPause( a.id ) } style={ { fontSize: 12, padding: '4px 10px', borderRadius: 6, border: '1px solid #e5e7eb', background: '#fff', cursor: 'pointer' } }>Pause</button>
                                                : <button onClick={ () => doPublish( a.id ) } style={ { fontSize: 12, padding: '4px 10px', borderRadius: 6, border: 'none', background: '#059669', color: '#fff', cursor: 'pointer' } }>Publish</button> }
                                        </td>
                                    </tr>
                                ) ) }
                            </tbody>
                        </table>
                    ) }
            </div>
        </div>
    );

    if ( embedded ) return body;
    return (
        <Layout onSignOut={ signOut } user={ user }>
            <SEO title="Ads that Click to WhatsApp | WECARE.DIGITAL" description="Create and manage Ads that Click to WhatsApp via the Marketing API" noindex />
            { body }
        </Layout>
    );
};

export default CtwaAdsPage;
