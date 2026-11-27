/**
 * EmbeddedSignupPanel — reusable WhatsApp Embedded Signup (Facebook Login for
 * Business) launcher. Used by:
 *   - public  /partners/           (prospective partners)
 *   - in-app  [retired public path]/whatsapp/embedded-signup/  (admins connecting a WABA)
 *
 * Launches Meta's Embedded Signup, captures the returned waba_id/phone_number_id
 * and OAuth code, then POSTs the code to the backend for server-side exchange.
 *
 * Config (env):
 *   NEXT_PUBLIC_ENABLE_PARTNER_SIGNUP = "true"   // enable the live button
 *   NEXT_PUBLIC_FB_ES_CONFIG_ID       = <config> // Tech Provider / ES config id
 *   NEXT_PUBLIC_FB_GRAPH_VERSION      = "v27.0"   // optional
 */
import React, { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '../config/constants';

const GREEN = '#1a3a2a';
const LIME = '#d1f470';

const ENABLED = process.env.NEXT_PUBLIC_ENABLE_PARTNER_SIGNUP === 'true';
const ES_CONFIG_ID = process.env.NEXT_PUBLIC_FB_ES_CONFIG_ID || '';

type Status = 'idle' | 'launching' | 'captured' | 'exchanging' | 'done' | 'error';

interface SignupResult { wabaId?: string; phoneNumberId?: string; businessId?: string; }

const cta: React.CSSProperties = { padding: '14px 26px', background: LIME, color: GREEN, border: 'none', borderRadius: 12, fontSize: 16, fontWeight: 700, cursor: 'pointer' };
const ctaDisabled: React.CSSProperties = { ...cta, background: '#eee', color: '#999', cursor: 'not-allowed' };

interface StepResult { step: string; ok: boolean | null; detail?: string; }

interface Props {
    /** internal admin context shows richer status + is not gated by the flag */
    admin?: boolean;
    /** 'onboard' = new/existing number, 'migrate' = move a number from another provider */
    mode?: 'onboard' | 'migrate';
    /** optional customer email — when set, a limited-access login is auto-created for them */
    customerEmail?: string;
    onConnected?: ( r: SignupResult ) => void;
}

const STEP_LABELS: Record<string, string> = {
    share_credit_line: 'Share line of credit',
    subscribe_app: 'Subscribe app to WABA',
    register_phone: 'Register number for Cloud API',
};

const EmbeddedSignupPanel: React.FC<Props> = ( { admin = false, mode = 'onboard', customerEmail, onConnected } ) => {
    const [ status, setStatus ] = useState<Status>( 'idle' );
    const [ result, setResult ] = useState<SignupResult>( {} );
    const [ message, setMessage ] = useState<string>( '' );
    const [ steps, setSteps ] = useState<StepResult[]>( [] );

    const usable = ENABLED || ( admin && !!ES_CONFIG_ID );

    useEffect( () => {
        if ( !usable ) return;
        const onMessage = ( event: MessageEvent ) => {
            if ( event.origin !== 'https://www.facebook.com' && event.origin !== 'https://web.facebook.com' ) return;
            try
            {
                const data = typeof event.data === 'string' ? JSON.parse( event.data ) : event.data;
                if ( data?.type === 'WA_EMBEDDED_SIGNUP' )
                {
                    if ( data.event === 'FINISH' || data.event === 'FINISH_ONLY_WABA' )
                    {
                        setResult( ( r ) => ( { ...r, wabaId: data.data?.waba_id, phoneNumberId: data.data?.phone_number_id, businessId: data.data?.business_id } ) );
                        setStatus( 'captured' );
                    } else if ( data.event === 'CANCEL' )
                    {
                        setStatus( 'idle' );
                        setMessage( 'Signup was cancelled before completion.' );
                    }
                }
            } catch { /* ignore non-JSON messages */ }
        };
        window.addEventListener( 'message', onMessage );
        return () => window.removeEventListener( 'message', onMessage );
    }, [ usable ] );

    const exchange = useCallback( async ( code: string, r: SignupResult ) => {
        setStatus( 'exchanging' );
        try
        {
            const res = await fetch( `${API_BASE}/partners/embedded-signup`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify( { code, wabaId: r.wabaId, phoneNumberId: r.phoneNumberId, businessId: r.businessId, mode, customerEmail: customerEmail || undefined } ),
            } );
            const data = await res.json().catch( () => ( {} ) );
            if ( !res.ok || data?.success === false ) throw new Error( data?.error || `Onboarding service returned ${res.status}` );
            setSteps( Array.isArray( data?.steps ) ? data.steps : [] );
            setStatus( 'done' );
            setMessage( admin ? `${mode === 'migrate' ? 'Migrated' : 'Connected'} WABA ${r.wabaId || ''}.` : 'Your WhatsApp Business Account is connected. Our team will reach out with next steps.' );
            onConnected?.( r );
        } catch ( e: any )
        {
            setStatus( 'error' );
            setMessage( e?.message || 'Could not complete onboarding. Please try again.' );
        }
    }, [ admin, mode, customerEmail, onConnected ] );

    const launch = useCallback( () => {
        const FB = ( typeof window !== 'undefined' && ( window as any ).FB ) || null;
        if ( !FB || !ES_CONFIG_ID )
        {
            setStatus( 'error' );
            setMessage( 'Embedded Signup is not configured yet (missing FB config id).' );
            return;
        }
        setStatus( 'launching' );
        setMessage( '' );
        FB.login( ( response: any ) => {
            const code = response?.authResponse?.code;
            if ( code )
            {
                setResult( ( r ) => { exchange( code, r ); return r; } );
            } else
            {
                setStatus( 'idle' );
                setMessage( 'No authorization was returned. Please try again.' );
            }
        }, {
            config_id: ES_CONFIG_ID,
            response_type: 'code',                 // System User access token flow
            override_default_response_type: true,
            extras: {
                setup: {},
                featureType: 'whatsapp_business_app_onboarding',
                sessionInfoVersion: '3',
                version: 'v4-public-preview',
                features: [ { name: 'marketing_messages_lite' } ],
            },
        } );
    }, [ exchange ] );

    const launchLabel = mode === 'migrate' ? 'Migrate WhatsApp Number' : 'Connect WhatsApp Business';

    const busy = status === 'launching' || status === 'exchanging';

    if ( !usable )
    {
        return (
            <div>
                <button style={ ctaDisabled } disabled>Connect WhatsApp Business — coming soon</button>
                <p style={ { fontSize: 13, color: '#777', marginTop: 12 } }>
                    { admin
                        ? 'Set NEXT_PUBLIC_FB_ES_CONFIG_ID (Meta Tech Provider config) to enable Embedded Signup.'
                        : <>Partner onboarding is launching soon. Want early access? <a href="https://wa.me/919903300044" style={ { color: GREEN, fontWeight: 600 } }>Message us on WhatsApp</a>.</> }
                </p>
            </div>
        );
    }

    return (
        <div>
            <button style={ busy ? ctaDisabled : cta } onClick={ launch } disabled={ busy }>
                { status === 'launching' ? 'Opening Meta signup…' : status === 'exchanging' ? 'Finishing setup…' : launchLabel }
            </button>
            <p style={ { fontSize: 13, color: '#777', marginTop: 12 } }>
                { mode === 'migrate'
                    ? 'Migration requires two-step verification to be OFF on the number at the current provider. You’ll be guided through Meta’s secure flow.'
                    : 'You’ll be guided through Meta’s secure Embedded Signup. WECARE.DIGITAL never sees the Facebook password.' }
            </p>
            { status === 'captured' && (
                <div style={ { marginTop: 16, fontSize: 14, color: GREEN } }>Account received (WABA { result.wabaId || '—' }). Finalizing…</div>
            ) }
            { ( status === 'done' || status === 'error' ) && (
                <div style={ { marginTop: 16, fontSize: 14, color: status === 'done' ? GREEN : '#374151' } }>{ message }</div>
            ) }
            { status === 'done' && steps.length > 0 && (
                <ul style={ { marginTop: 12, paddingLeft: 18, fontSize: 13, lineHeight: 1.7 } }>
                    { steps.map( ( s, i ) => (
                        <li key={ i } style={ { color: s.ok === true ? GREEN : s.ok === false ? '#374151' : '#a60' } }>
                            { s.ok === true ? '✓' : s.ok === false ? '✕' : '•' } { STEP_LABELS[ s.step ] || s.step }
                            { s.detail ? ` — ${s.detail}` : '' }
                        </li>
                    ) ) }
                </ul>
            ) }
            { status === 'idle' && message && (
                <div style={ { marginTop: 16, fontSize: 14, color: '#a60' } }>{ message }</div>
            ) }
        </div>
    );
};

export default EmbeddedSignupPanel;
