/**
 * BSUID & Usernames console (Meta usernames/BSUID rollout 2026)
 * - Subscribe to business_username_updates / user_id_update webhook fields
 * - Delete a Contact Book entry by BSUID
 * - View Parent BSUID account + enrolled portfolios
 * - Claim-status guidance (gated until Meta enables the feature)
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { WHATSAPP_PHONES } from '../../../../config/constants';
import { RawJsonDrawer } from '../../../../components/wa';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const PHONES = [
    { key: 'primary', ...WHATSAPP_PHONES.primary },
    { key: 'secondary', ...WHATSAPP_PHONES.secondary },
];

/**
 * The index is the state, so the option value is the index AS A STRING - `value` is always a
 * string in this contract, and `Number( v )` on the way back is the same conversion the
 * native handler did.
 */
const PHONE_OPTIONS: SelectOption[] = PHONES.map( ( p, i ) => ( {
    value: String( i ),
    label: `${ p.name } — ${ p.display } (WABA ${ p.wabaId })`,
} ) );
/** Layout only: the margins the shared `input` object carried. The box is drawn by CSS now. */
const SELECT_LAYOUT: React.CSSProperties = { marginTop: 4, marginBottom: 10 };

const WEBHOOK_FIELDS = [
    { field: 'business_username_updates', desc: 'Business username status changes (reserved → approved/deleted)' },
    { field: 'user_id_update', desc: 'A user\u2019s BSUID changed — track identity continuity' },
    { field: 'messages', desc: 'Incoming messages (now carry user_id/BSUID + optional username)' },
];

const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e5e5', borderRadius: 8, padding: 16, marginBottom: 16 };
const input: React.CSSProperties = { width: '100%', padding: '8px 10px', border: '1px solid #d0d0d0', borderRadius: 6, marginTop: 4, marginBottom: 10, fontSize: 14 };
const label: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#444' };
const btn: React.CSSProperties = { padding: '9px 16px', background: '#1a3a2a', color: '#d1f470', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14, fontWeight: 600 };

const BsuidConsole: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();

    const [ phoneIdx, setPhoneIdx ] = useState( 0 );
    const phone = PHONES[ phoneIdx ];

    // Webhook subscription
    const [ selectedFields, setSelectedFields ] = useState<string[]>( [ 'business_username_updates', 'user_id_update' ] );
    const [ subBusy, setSubBusy ] = useState( false );

    // Business username (live status + claim)
    const [ unameInfo, setUnameInfo ] = useState<api.UsernameInfo | null>( null );
    const [ suggestions, setSuggestions ] = useState<string[]>( [] );
    const [ unameLoading, setUnameLoading ] = useState( false );
    const [ claimInput, setClaimInput ] = useState( '' );
    const [ claiming, setClaiming ] = useState( false );

    // Parent BSUID
    const [ businessId, setBusinessId ] = useState( '' );
    const [ parentResult, setParentResult ] = useState<any>( null );
    const [ parentBusy, setParentBusy ] = useState( false );

    const toggleField = ( f: string ) =>
        setSelectedFields( s => s.includes( f ) ? s.filter( x => x !== f ) : [ ...s, f ] );

    const loadUsername = useCallback( async () => {
        setUnameLoading( true );
        setUnameInfo( null );
        setSuggestions( [] );
        try
        {
            const [ info, sug ] = await Promise.all( [
                api.getBusinessUsername( phone.metaPhoneId ),
                api.getBusinessUsernameSuggestions( phone.metaPhoneId ),
            ] );
            setUnameInfo( info );
            setSuggestions( sug?.suggestions || [] );
        } catch
        {
            toast.error( 'Could not load username status' );
        } finally
        {
            setUnameLoading( false );
        }
    }, [ phone.metaPhoneId, toast ] );

    useEffect( () => { loadUsername(); }, [ loadUsername ] );

    const claimUsername = async () => {
        const desired = claimInput.trim().toLowerCase().replace( /^@/, '' );
        if ( !desired ) { toast.error( 'Enter a username to claim' ); return; }
        setClaiming( true );
        const res = await api.claimBusinessUsername( phone.metaPhoneId, desired );
        if ( res.success )
        {
            toast.success( `Claimed @${res.username || desired}` );
            setClaimInput( '' );
            await loadUsername();
        } else
        {
            toast.error( res.error || 'Claim failed' );
        }
        setClaiming( false );
    };

    const subscribe = async () => {
        if ( !selectedFields.length ) { toast.error( 'Select at least one field' ); return; }
        setSubBusy( true );
        const res = await api.subscribeWebhookFields( phone.wabaId, selectedFields );
        if ( res.success ) toast.success( 'Subscribed to ' + selectedFields.join( ', ' ) );
        else toast.error( res.error || 'Subscribe failed' );
        setSubBusy( false );
    };

    const loadParent = async () => {
        if ( !businessId.trim() ) { toast.error( 'Enter a Business Portfolio ID' ); return; }
        setParentBusy( true );
        const res = await api.getParentBsuidAccounts( businessId.trim() );
        if ( res.error ) { toast.error( res.error ); setParentResult( null ); }
        else setParentResult( res );
        setParentBusy( false );
    };

    const content = (
        <div style={ { maxWidth: 760, margin: '0 auto', padding: 16 } }>
            <SEO title="BSUID & Usernames" description="WhatsApp BSUID and username tooling" noindex />
            <h1 style={ { fontSize: 22, fontWeight: 700, marginBottom: 4 } }>BSUID &amp; Usernames</h1>
            <p style={ { color: '#777', fontSize: 13, marginBottom: 16 } }>
                Manage WhatsApp username/BSUID webhooks and contact-book entries. BSUIDs appear in webhooks (early Apr 2026) and can be messaged (from July 2026); phone numbers may be hidden for username-adopters.
            </p>

            <div style={ card }>
                <label style={ label }>WABA / phone context</label>
                <Select ariaLabel="WABA / phone context" value={ String( phoneIdx ) }
                    onChange={ v => setPhoneIdx( Number( v ) ) }
                    options={ PHONE_OPTIONS } style={ SELECT_LAYOUT } />
            </div>

            <div style={ card }>
                <h3 style={ { marginTop: 0, fontSize: 15 } }>Webhook subscriptions</h3>
                <p style={ { fontSize: 12, color: '#777' } }>Subscribe this WABA\u2019s app to username/BSUID webhook fields.</p>
                { WEBHOOK_FIELDS.map( f => (
                    <label key={ f.field } style={ { display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 8, fontSize: 13, cursor: 'pointer' } }>
                        <input type="checkbox" checked={ selectedFields.includes( f.field ) } onChange={ () => toggleField( f.field ) } />
                        <span><code>{ f.field }</code> — <span style={ { color: '#666' } }>{ f.desc }</span></span>
                    </label>
                ) ) }
                <button style={ btn } disabled={ subBusy } onClick={ subscribe }>{ subBusy ? 'Subscribing…' : 'Subscribe fields' }</button>
            </div>

            <div style={ card }>
                <h3 style={ { marginTop: 0, fontSize: 15 } }>Contact book</h3>
                <p style={ { fontSize: 12, color: '#777', margin: 0 } }>
                    Meta stores each contact phone number and BSUID in the portfolio contact book automatically. Deletion is disabled here to prevent accidental removal &mdash; a deleted entry stops the phone number appearing in webhooks (subject to the 30-day cache) and cannot be restored.
                </p>
            </div>

            <div style={ card }>
                <h3 style={ { marginTop: 0, fontSize: 15 } }>Parent BSUID account</h3>
                <p style={ { fontSize: 12, color: '#777' } }>For managed businesses with multiple portfolios enrolled in a parent BSUID account.</p>
                <label style={ label }>Business Portfolio ID</label>
                <input style={ input } value={ businessId } onChange={ e => setBusinessId( e.target.value ) } placeholder="Business ID" />
                <button style={ btn } disabled={ parentBusy } onClick={ loadParent }>{ parentBusy ? 'Loading…' : 'Get parent BSUID account' }</button>
                { parentResult && (
                    <div style={ { marginTop: 10, fontSize: 13 } }>
                        <div><strong>Account ID:</strong> { parentResult.parentBsuidAccountId || '(none)' }</div>
                        <div><strong>Enrolled portfolios:</strong> { ( parentResult.enrolledBusinessPortfolios || [] ).join( ', ' ) || '(none)' }</div>
                        <RawJsonDrawer data={ parentResult } label="Raw response" />
                    </div>
                ) }
            </div>

            <div style={ { ...card, background: '#f0f9ff', border: '1px solid #bae6fd' } }>
                <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'space-between' } }>
                    <h3 style={ { marginTop: 0, marginBottom: 0, fontSize: 15, color: '#0369a1' } }>Business username</h3>
                    <button style={ { ...btn, padding: '4px 10px', fontSize: 12, background: '#e0f2fe', color: '#0369a1' } } disabled={ unameLoading } onClick={ loadUsername }>{ unameLoading ? 'Refreshing…' : 'Refresh' }</button>
                </div>
                <div style={ { marginTop: 10, fontSize: 14 } }>
                    { unameLoading ? (
                        <span style={ { color: '#0369a1' } }>Loading…</span>
                    ) : unameInfo?.username ? (
                        <span>
                            Current: <strong>@{ unameInfo.username }</strong>
                            <span style={ {
                                marginLeft: 8, padding: '2px 8px', borderRadius: 999, fontSize: 12, fontWeight: 600,
                                background: unameInfo.status === 'approved' ? '#dcfce7' : '#fef9c3',
                                color: unameInfo.status === 'approved' ? '#166534' : '#854d0e',
                            } }>
                                { unameInfo.status || 'unknown' }
                            </span>
                        </span>
                    ) : (
                        <span style={ { color: '#666' } }>No username claimed for this number yet.</span>
                    ) }
                </div>
                { suggestions.length > 0 && (
                    <div style={ { marginTop: 10, fontSize: 13 } }>
                        <span style={ { color: '#666' } }>Reserved for you: </span>
                        { suggestions.map( s => (
                            <button key={ s } onClick={ () => setClaimInput( s ) }
                                style={ { marginRight: 6, marginTop: 4, padding: '3px 10px', borderRadius: 999, border: '1px solid #bae6fd', background: '#fff', color: '#0369a1', cursor: 'pointer', fontSize: 12 } }>
                                @{ s }
                            </button>
                        ) ) }
                    </div>
                ) }
                <div style={ { marginTop: 12 } }>
                    <label style={ label }>Claim / change username (3&ndash;35 chars, a&ndash;z 0&ndash;9 . _)</label>
                    <div style={ { display: 'flex', gap: 8 } }>
                        <input style={ { ...input, marginBottom: 0 } } value={ claimInput } onChange={ e => setClaimInput( e.target.value ) } placeholder="e.g. wecaredigital" />
                        <button style={ { ...btn, whiteSpace: 'nowrap' } } disabled={ claiming || !claimInput.trim() } onClick={ claimUsername }>{ claiming ? 'Claiming…' : 'Claim' }</button>
                    </div>
                    <p style={ { fontSize: 11, color: '#777', marginTop: 6, marginBottom: 0 } }>
                        A username maps 1:1 to this phone number and replaces the number in the chat profile once active. No delete option is provided here to avoid accidental removal.
                    </p>
                </div>
            </div>
        </div>
    );

    if ( embedded ) return content;
    return <Layout user={ user } onSignOut={ signOut }>{ content }</Layout>;
};

export default BsuidConsole;
