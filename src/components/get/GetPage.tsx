/**
 * Customer file collection: verify over WhatsApp, pay, download.
 *
 * Design
 * ------
 * Matches the home page's language rather than inventing one: the #d1f470 lime with
 * #1a3a2a on top of it, 14px-radius panels with 2px borders, the 50px pill CTA, and
 * the site's section-heading rung clamp(28px,3.2vw,40px)/700/1.08/-1.2px - byte for
 * byte the declaration used by .home-flow-title, .home-close-title, .cl-h2 and the
 * rest. Body copy sits on the one body level, 20px/400/1.4/-.125px. If those rungs
 * are retuned site-wide, retune this too; `node tools/browser/typecheck.js` reports
 * the gaps.
 *
 * Route ownership
 * ---------------
 * /get/ is the general collection page. /vault/?file=<id> reuses this component for the
 * approved WhatsApp download deep-link, scoped to one file. Amplify's /get/<*> rewrite still
 * sends nested /get/ file requests to CloudFront, so this remains a page component rather than
 * a nested /get/ route.
 *
 * It also has to be in the public allowlist in `_app.tsx`. Without that entry it
 * renders the staff Authenticator at HTTP 200 - which is how it shipped the first
 * time.
 *
 * The trust model, which is the whole point
 * -----------------------------------------
 * Nothing on this page can grant access. Checkout binds one exact file to a server-owned Vault
 * service intent; the customer then uses the same /cart/ -> /checkout/ payment chooser as every
 * other purchase (Pay here or Pay on WhatsApp). The server decides access only from the durable
 * entitlement it writes after authoritative payment verification. Each successful redeem mints a
 * short-lived transport URL while a paid access window is open; ownership and window state are
 * enforced server-side.
 *
 * Paying and renewing
 * -------------------
 * Each file carries `accessState`. UNPAID and EXPIRED files can enter checkout only after this
 * authenticated page asks /services/request-intent to bind that exact fileId to the verified
 * customer. The cart then offers Pay here or Pay on WhatsApp. PAID_UNVERIFIED is never offered a
 * payment: a recorded payment is reconciled, not sold again.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import SEO from '../SEO';
import PillButton from '../PillButton';
import RotatingHero from '../RotatingHero';
import type { CycleWord } from '../RotatingHero';
import * as api from '../../api/client';
import type { SecureFile, SecureFileAccessState } from '../../api/client';
import { serviceByKind } from '../../config/services';
import { setServiceLine } from '../../lib/cart';
import { postRequestIntent } from '../../lib/serviceRequests';
import { CHECKOUT_PATH } from '../../lib/serviceEntry';
import { fetchServicePrices, rupeesFromPaise } from '../../lib/servicePricing';
import { getSession, restoreSession, clearSession } from '../../lib/customerAuth';

function formatBytes ( bytes: number ): string {
    if ( !bytes ) return '0 B';
    const units = [ 'B', 'KB', 'MB', 'GB' ];
    const i = Math.min( Math.floor( Math.log( bytes ) / Math.log( 1024 ) ), units.length - 1 );
    return `${( bytes / Math.pow( 1024, i ) ).toFixed( i === 0 ? 0 : 1 )} ${units[ i ]}`;
}

/** The server's access state, or what an older backend's fields imply. */
function accessStateOf ( file: SecureFile ): SecureFileAccessState {
    if ( file.accessState ) return file.accessState;
    // No server state: a paid id alone does not prove the file is ready to open, so say the
    // payment is confirming (never offered checkout again) rather than READY.
    return file.paidEntitlementId || file.paidGrantId ? 'PAID_UNVERIFIED' : 'UNPAID';
}

/** "26 Oct 2026, 4:30 pm" in the reader's locale, or '' when there is no window end. */
function windowEndLabel ( epochSeconds?: number ): string {
    if ( !epochSeconds ) return '';
    try
    {
        return new Date( epochSeconds * 1000 ).toLocaleString( undefined, { dateStyle: 'medium', timeStyle: 'short' } );
    } catch
    {
        return '';
    }
}

/**
 * The hero's rotating nouns, TRUE OF THIS PAGE rather than borrowed from the home page's
 * marketing audiences. This is the collection point for files someone has shared with you, so the
 * rotation names what arrives here. Lengths are 5 / 9 / 7 / 6 characters, inside RotatingHero's
 * 2-4-character spread guidance, and the pill sits on its own line (.rh-head-line is
 * display:block) so the headline's line count cannot change as the word changes. Tints/dots are
 * the four per-subject pairs the Grahak OS hero established and the home page reuses verbatim; no
 * new colour is introduced.
 */
const GET_WORDS: CycleWord[] = [
    { word: 'files', tint: '#dbeafe', dot: '#2563eb' },
    { word: 'documents', tint: '#ede9fe', dot: '#9849e8' },
    { word: 'records', tint: '#e0f7c8', dot: '#3da35a' },
    { word: 'papers', tint: '#fef3c7', dot: '#f0a818' },
];

const AUTH_WORDS: CycleWord[] = [
    { word: 'WECARE.DIGITAL', tint: '#fef3c7', dot: '#f0a818' },
    { word: 'WhatsApp', tint: '#dcfce7', dot: '#22c55e' },
    { word: 'Android', tint: '#e0f2fe', dot: '#0284c7' },
    { word: 'iOS', tint: '#f3f4f6', dot: '#6b7280' },
    { word: 'ChatGPT', tint: '#ede9fe', dot: '#9849e8' },
    { word: 'Claude', tint: '#e0f7c8', dot: '#3da35a' },
    { word: 'Gemini', tint: '#fee2e2', dot: '#dc2626' },
];

const VAULT_AUTH_RETURN_FILE_KEY = 'wecare.vault.authReturnFile';
const VAULT_FILE_ID_PATTERN = /^[A-Za-z0-9_-]{1,120}$/;

type Stage = 'loading' | 'files';

interface FilesPageProps {
    /** Optional WhatsApp Vault deep-link target. Ownership is still proven server-side. */
    targetFileId?: string;
}

export default function FilesPage ( { targetFileId = '' }: FilesPageProps ) {
    const router = useRouter();
    const [ stage, setStage ] = useState<Stage>( 'loading' );
    const [ error, setError ] = useState( '' );

    const [ files, setFiles ] = useState<SecureFile[]>( [] );
    // The live catalog price. Null until ProductsTable can be read through the canonical service
    // pricing endpoint; checkout never starts from a guessed or file-local amount.
    const [ price, setPrice ] = useState<number | null>( null );
    const [ payablePrice, setPayablePrice ] = useState<number | null>( null );
    const [ working, setWorking ] = useState<string>( '' );

    const redirectToAuth = useCallback( (): void => {
        if ( targetFileId && VAULT_FILE_ID_PATTERN.test( targetFileId ) )
        {
            try
            {
                window.sessionStorage.setItem( VAULT_AUTH_RETURN_FILE_KEY, targetFileId );
            } catch
            {
                // Same-tab storage is best-effort. Ownership still has to pass on the server.
            }
        }
        const returnPath = targetFileId ? '/vault/' : '/get/';
        window.location.replace( `/auth?return=${ encodeURIComponent( returnPath ) }` );
    }, [ targetFileId ] );

    const loadFiles = useCallback( async () => {
        const result = await api.listMySecureFiles();
        if ( result.ok )
        {
            const ownedFiles = result.data.files || [];
            const visibleFiles = targetFileId
                ? ownedFiles.filter( file => file.fileId === targetFileId )
                : ownedFiles;
            setFiles( visibleFiles );
            setStage( 'files' );
            setError(
                targetFileId && visibleFiles.length === 0
                    ? 'This document is not available right now.'
                    : ''
            );
        } else if ( result.failure.status === 401 )
        {
            clearSession();
            redirectToAuth();
            return;
        } else
        {
            setError( result.failure.message || 'Could not load your files' );
        }
    }, [ targetFileId, redirectToAuth ] );

    // Vault has no file-local or deploy-local price. This is the same ProductsTable-backed
    // endpoint used by service pages; checkout independently re-prices again before a payment
    // attempt exists. A missing price disables new/renewal checkout, never a paid download.
    useEffect( () => {
        let active = true;
        void fetchServicePrices().then( prices => {
            if ( !active ) return;
            const vault = prices.vault;
            setPrice( vault?.available ? vault.paise : null );
            setPayablePrice(
                vault?.available && vault.breakdown
                    ? vault.breakdown.totalPayablePaise
                    : null
            );
        } );
        return () => { active = false; };
    }, [] );

    // /auth is the only customer sign-in surface. Both /get/ and exact-file /vault/ links
    // restore a server-owned customer session here; when none exists, this page redirects to
    // /auth with a return path instead of rendering another phone/OTP form.
    useEffect( () => {
        let active = true;
        void restoreSession()
            .then( restored => {
                if ( !active ) return null;
                if ( !restored )
                {
                    redirectToAuth();
                    return null;
                }
                return api.listMySecureFiles();
            } )
            .then( result => {
                if ( !active || !result ) return;
                if ( result.ok )
                {
                    const ownedFiles = result.data.files || [];
                    const visibleFiles = targetFileId
                        ? ownedFiles.filter( file => file.fileId === targetFileId )
                        : ownedFiles;
                    setFiles( visibleFiles );
                    setStage( 'files' );
                    if ( targetFileId && visibleFiles.length === 0 )
                    {
                        setError( 'This document is not available right now.' );
                    }
                } else if ( result.failure.status === 401 )
                {
                    clearSession();
                    redirectToAuth();
                } else
                {
                    setError( result.failure.message || 'Could not load your files. Please try again.' );
                }
            } )
            .catch( () => {
                if ( active ) setError( 'Sign-in is temporarily unavailable. Please try again.' );
            } );
        return () => { active = false; };
    }, [ targetFileId, redirectToAuth ] );

    const handleDownload = async ( file: SecureFile ) => {
        const accessId = file.paidEntitlementId || file.paidGrantId;
        if ( !accessId )
        {
            setError( 'Paid Vault access is not ready for this file yet.' );
            return;
        }
        setWorking( file.fileId );
        setError( '' );
        try
        {
            const result = await api.redeemSecureFileDownload( file.fileId, accessId );
            if ( !result.ok )
            {
                const code = result.failure.code;
                if ( result.failure.status === 401 )
                {
                    clearSession();
                    setFiles( [] );
                    redirectToAuth();
                    return;
                }
                if ( code === 'ACCESS_WINDOW_CLOSED' )
                {
                    // Every paid window has been used. Show the renewal for this file instead of
                    // telling a customer who paid to contact support.
                    setFiles( current => current.map( row => row.fileId === file.fileId
                        ? { ...row, accessState: 'EXPIRED', accessWindowOpen: false }
                        : row ) );
                    setError( 'Your access window for this file has ended. Renew it through checkout to download it again.' );
                    return;
                }
                setError(
                    code === 'NOT_REGISTERED'
                        ? 'This file is not registered to your verified number.'
                        : code === 'ACCESS_NOT_AUTHORIZED'
                            ? 'We could not confirm a payment for this file. If you already paid, do not pay again; contact us and we will check it.'
                            : ( result.failure.message || 'Could not prepare the download.' )
                );
                return;
            }
            if ( !result.data.downloadUrl )
            {
                setError( 'The download URL was not returned. Please try again.' );
                return;
            }
            // The backend returns a short-lived S3 URL with Content-Disposition: attachment.
            // Top-level navigation lets the browser download it without exposing the S3 key here.
            window.location.assign( result.data.downloadUrl );
        } catch ( err: any )
        {
            setError( err?.message || 'Could not prepare the download.' );
        } finally
        {
            setWorking( '' );
        }
    };

    const handleVaultCheckout = async ( file: SecureFile ) => {
        const state = accessStateOf( file );
        if ( state !== 'UNPAID' && state !== 'EXPIRED' ) return;
        const live = getSession();
        if ( !live ) {
            setFiles( [] );
            redirectToAuth();
            return;
            return;
        }
        const service = serviceByKind( 'VAULT' );
        if ( !service || price === null ) {
            setError( 'The live Vault catalogue price could not be confirmed. Nothing has been charged. Please refresh and try again.' );
            return;
        }
        setWorking( file.fileId );
        setError( '' );
        try {
            const outcome = await postRequestIntent(
                live.accessToken, 'VAULT', undefined, file.fileId,
            );
            if ( outcome.kind === 'expired' ) {
                clearSession();
                setFiles( [] );
                redirectToAuth();
                return;
            }
            if ( outcome.kind !== 'ok' ) {
                if ( outcome.kind === 'refused' ) setError( outcome.message );
                else if ( outcome.kind === 'rate' ) setError( 'Please try again in a moment. Nothing has been charged.' );
                else if ( outcome.kind === 'notFound' ) setError( 'This document is not available right now.' );
                else setError( 'We could not start Vault checkout. Nothing has been charged. Please try again.' );
                return;
            }
            setServiceLine( service.variantId, outcome.intent.intentId, price );
            await router.push( CHECKOUT_PATH );
        } catch {
            setError( 'We could not start Vault checkout. Nothing has been charged. Please try again.' );
        } finally {
            setWorking( '' );
        }
    };

    return (
        <>
            {/* noindex: a personal collection point, not a marketing page. There is
                nothing here for a crawler, and an indexed URL inviting a phone number
                is a phishing template waiting to be copied. */}
            <SEO
                title="Your files"
                description="Collect files shared with you by WECARE.DIGITAL"
                noindex
            />

            {/* THE HOME PAGE'S TOP SECTION, on owner instruction. This page previously opened
                straight into a bordered panel with no hero, which is why it read as a different
                site from the former customer sign-in page, which already sat on RotatingHero. The hero is
                the shared component rather than a copy of its markup, so the "animate as one
                family" guarantee holds (tools/browser/animcheck.js asserts the family shares one
                computed transition set) and this surface cannot drift from the other fifteen.

                NOT SUBORDINATE: the hero owns the page's single <main> landmark and its single
                <h1>, and the panel below is its child. The former <main className="sf-shell"> and
                <h1 className="sf-title"> are therefore GONE - keeping either would produce two
                mains and two h1s, which fails htmlcheck's MANY-MAIN and H1-MANY at once. The
                stage-dependent heading is now an <h2> inside the panel, styled by the same class,
                so nothing moves visually.

                NO badgeLabel, matching the home page and /blog/: the label here would just be the
                company name again, 109px under the header's own lockup, which is exactly what the
                home page removed. The old <p className="sf-eyebrow">WECARE.DIGITAL</p> is gone for
                the same reason. */}
            <RotatingHero
                frame={ targetFileId ? 'One account. Anywhere you need it.' : 'Collect your' }
                words={ targetFileId ? AUTH_WORDS : GET_WORDS }
                sub={ targetFileId
                    ? 'Sign in with WhatsApp. Continue anywhere.'
                    : 'Verify your mobile number on WhatsApp, and whatever has been shared with you is right here.' }
                ariaLabel={ targetFileId ? 'One account. Anywhere you need it.' : 'Collect your files' }
            >
                <div className="sf-card">
                    {/* THE HEADING AND LEAD RENDER ON THE 'files' STAGE ONLY, and that is a fold
                        fix as much as a copy fix.

                        On the two sign-in stages they were SAYING THE HERO'S WORDS BACK. The hero's
                        h1 already reads "Collect your files" and its sub already explains the
                        WhatsApp verification, so an h2 reading "Collect your files" directly
                        beneath it, followed by a lead repeating the same sentence, stated the page
                        twice - the same duplication the owner reported in the menu ("Extra" under a
                        heading also reading "Extra").
                        Measured cost of the repetition: the h2 (40px at 1366px on the
                        clamp(28px,3.2vw,40px) rung, +16px margin) plus the lead (20px x 1.4,
                        +28px margin) pushed the submit control ~115px down the page, and
                        tools/browser/foldprobe.js measured the pill bottom at 845px against a
                        728px limit at 1366x768 - below the fold on a page whose only job is the
                        form. /account/sign-in carries no h2 either.
                        On the 'files' stage it stays: there the hero still says "Collect your",
                        the list below genuinely needs a heading, and there is no submit control
                        racing the fold. */}
                    { stage === 'files' && !targetFileId && (
                        <>
                            <h2 className="sf-title">Your files</h2>
                            <p className="sf-lead">Shared with your number.</p>
                        </>
                    ) }
                    { stage === 'files' && targetFileId && files.length > 0 && (
                        <div className="sf-access-eyebrow">
                            <span className="sf-access-icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" focusable="false">
                                    <path d="M7 3h7l4 4v14H7z"/>
                                    <path d="M14 3v5h5M10 13h5M10 17h5"/>
                                </svg>
                            </span>
                            <span>Access Vault</span>
                        </div>
                    ) }

                    {/* id is load-bearing: PhoneField and PillButton above point their
                        aria-describedby at it, so a screen-reader user who tabs back to the field
                        to correct it is told which control is at fault. The error is rendered here,
                        above the form, rather than beside the field it concerns. */}
                    { error && (
                        <div className="sf-note sf-note-bad" id="sf-error" role="alert">{ error }</div>
                    ) }
                    { stage === 'files' && (
                        <div className="sf-form">
                            { files.length === 0 && (
                                <p className="sf-empty">
                                    There are no files shared with your number right now.
                                </p>
                            ) }

                            { files.map( file => {
                                const state = accessStateOf( file );
                                const isPaid = state === 'OPEN' || state === 'READY';
                                const ends = state === 'OPEN' ? windowEndLabel( file.accessWindowEndsAt ) : '';

                                return (
                                    <div key={ file.fileId } className={ targetFileId ? 'sf-file sf-file-deep' : 'sf-file' }>
                                        <div className="sf-file-head">
                                            { targetFileId && (
                                                <span className="sf-file-icon" aria-hidden="true">
                                                    <svg viewBox="0 0 24 24" focusable="false">
                                                        <path d="M7 3h7l4 4v14H7z"/>
                                                        <path d="M14 3v5h5M10 13h5M10 17h5"/>
                                                    </svg>
                                                </span>
                                            ) }
                                            <div className="sf-file-copy">
                                                <div className="sf-file-name">{ file.displayName }</div>
                                                <div className="sf-file-meta">
                                                    { formatBytes( file.sizeBytes ) }
                                                    { file.contentType === 'application/pdf' ? ' · PDF' : '' }
                                                    { file.downloadCount > 0
                                                        && ` · downloaded ${ file.downloadCount } time${ file.downloadCount === 1 ? '' : 's' }` }
                                                </div>
                                            </div>
                                            { targetFileId && isPaid && <span className="sf-paid-badge">Paid</span> }
                                        </div>

                                        { isPaid ? (
                                            <>
                                                <div className={ targetFileId ? 'sf-file-action' : undefined }>
                                                    <button
                                                        type="button"
                                                        className="sf-download-action"
                                                        onClick={ () => { void handleDownload( file ); } }
                                                        disabled={ working === file.fileId }
                                                        aria-busy={ working === file.fileId }
                                                    >
                                                        { working === file.fileId ? 'Preparing…' : 'Download file' }
                                                    </button>
                                                </div>
                                                <p className={ targetFileId ? 'sf-paid-note' : 'sf-fine' }>
                                                    { state === 'OPEN'
                                                        ? `Paid. Download again for free${ ends ? ` until ${ ends }` : ' while your access window is open' }.`
                                                        : 'Paid. Your access window starts with your first download.' }
                                                </p>
                                            </>
                                        ) : state === 'PAID_UNVERIFIED' ? (
                                            <p className="sf-fine">
                                                Your payment is recorded and its access is being confirmed.
                                                Do not pay again. If this does not clear soon, contact us and we will check it.
                                            </p>
                                        ) : (
                                            <>
                                                <PillButton
                                                    as="button"
                                                    type="button"
                                                    label="Vault"
                                                    action={ working === file.fileId
                                                        ? 'Preparing checkout…'
                                                        : price === null || payablePrice === null
                                                            ? 'Price unavailable'
                                                            : state === 'EXPIRED'
                                                                ? `Renew for ₹${ rupeesFromPaise( payablePrice ) }`
                                                                : `Checkout ₹${ rupeesFromPaise( payablePrice ) }` }
                                                    block
                                                    onClick={ () => { void handleVaultCheckout( file ); } }
                                                    disabled={ working === file.fileId || price === null || payablePrice === null }
                                                    busy={ working === file.fileId }
                                                />
                                                <p className="sf-fine">
                                                    { state === 'EXPIRED' ? 'Your access window has ended. ' : '' }
                                                    This exact document is bound to checkout before payment. Review the
                                                    cart, then choose Pay here or Pay on WhatsApp. The server confirms
                                                    the final payable amount before any payment starts.
                                                </p>
                                            </>
                                        ) }
                                    </div>
                                );
                            } ) }

                            { !targetFileId && (
                                <p className="sf-fine">
                                    Purchases and renewals use the shared checkout; your downloads stay here.
                                </p>
                            ) }
                        </div>
                    ) }
                </div>

            </RotatingHero>

            <style jsx>{ `
                /* NO .sf-shell ANY MORE, and no header offset here.

                   This page used to render its own <main className="sf-shell"> and pad the top by
                   calc(108px + 48px) to clear the fixed header. RotatingHero now owns the <main>
                   and the page measure, and it already handles the header offset for all sixteen
                   surfaces built on it - so repeating the padding here would double it and push
                   the panel half a screen down. The panel is simply the hero's child now.

                   The former min-height:100vh (removed earlier) is likewise still absent: _app.tsx
                   wraps every public route in <Header/> + page + <Footer/>, so claiming the whole
                   viewport pushed the shared footer a full screen down. */

                /* A PLAIN CARD, matching .si-card on /account/sign-in exactly:
                   width:100%;max-width:460px;margin:0. Nothing else.

                   THE TINTED PANEL IS GONE, and dropping it is two fixes at once.
                   It was .home-close-panel's treatment - 2px lime border, 14px radius, the lime
                   tint at .22 alpha - which is the CLOSING-BAND treatment. At the top of a page,
                   directly under the hero, it competed with the hero for the eye, and
                   /account/sign-in (the other half of this same journey) has no panel at all.

                   It was also paying for the fold. THE FOLD HERE IS MEASURED, NOT ASSUMED: before
                   the hero, this page's submit control sat at 540px bottom at 1366x768, because
                   the old .sf-shell paid only calc(108px + 48px) of header clearance. RotatingHero
                   replaces that with .rh-shell{padding-top:108px} plus
                   .rh-layout{padding:80px 24px 96px;gap:96px} and a headline that is ALWAYS two
                   lines (frame block + pill block). Nesting the old tinted panel inside that put
                   the submit roughly 299px lower - below a 768px fold, on a page whose entire job
                   is the form. Removing the panel's clamp(28px,4vw,56px) of padding recovers ~56px
                   of that, and the other mitigations are: no badgeLabel, a one-line sub, and the
                   form as the hero's FIRST child. All four are applied.

                   THE PAGE CANNOT FIX THIS BY RESTYLING THE HERO. styled-jsx scopes only the
                   lowercase tags in the file it compiles and RotatingHero is self-styling, so
                   .rh-layout's 96px gap and .rh-shell's padding are unreachable from here. Every
                   mitigation has to live in the hero's children. Do not try. */
                .sf-card{width:100%;max-width:460px;margin:0}
                .sf-access-eyebrow{
                  display:inline-flex;align-items:center;gap:9px;min-height:42px;margin:0 0 18px;
                  padding:0 15px;border-radius:999px;background:var(--public-brand-lime);
                  color:var(--public-brand-green);font-size:18px;font-weight:700;line-height:1.1;
                }
                .sf-access-icon{width:23px;height:23px;display:inline-flex;align-items:center;justify-content:center}
                .sf-access-icon svg,.sf-file-icon svg{
                  width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:1.7;
                  stroke-linecap:round;stroke-linejoin:round;
                }

                /* The site's section-heading rung, identical to .home-close-title. Now on an <h2>
                   rather than an <h1> (the hero owns the page's one h1); the rule is unchanged
                   because it styles by CLASS, not by tag, so the rung is pixel-identical. */
                .sf-title{
                  margin:0 0 16px;font-size:var(--public-section-size);font-weight:var(--public-section-weight);
                  line-height:var(--public-section-leading);letter-spacing:var(--public-section-tracking);color:var(--public-heading);
                }
                /* The one body level. */
                .sf-lead{
                  margin:0 0 28px;font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);
                  letter-spacing:var(--public-body-tracking);color:var(--public-body);
                }

                .sf-form{display:block}

                /* Matched to .si-label on /account/sign-in: 14px/700. Was weight 600 here, which
                   is a rung this site does not use for a field label. */
                .sf-label{
                  display:block;margin:0 0 8px;font-size:14px;font-weight:700;
                  letter-spacing:-.1px;color:var(--public-brand-green);
                }
                /* Matched to .si-hint on /account/sign-in, so the one line of guidance under the
                   number field reads the same on both sign-in surfaces. */
                .sf-hint{
                  margin:0 0 20px;font-size:16px;line-height:1.55;color:var(--public-muted);
                }
                /* THE CODE FIELD NOW DRESSES LIKE .si-input, byte for byte: 52px (matching the
                   pill below it, so the field and the button it feeds are the same height), 1px
                   #e5e7eb static hairline, 10px radius, 17px type.
                   IT WAS 2px rgba(26,58,42,.18) ON A 12px RADIUS AT 16px - a border, radius and
                   size this site uses nowhere else, which is a large part of why the owner saw the
                   two sign-in surfaces as different. The WhatsApp number beside it is PhoneField,
                   which owns its own outline, radius and height and already matches these numbers;
                   the two controls are styled in two places on purpose.
                   17px also clears the 16px floor below which iOS Safari zooms the viewport on
                   focus, which on a one-field form looks like the page jumping. */
                .sf-input{
                  width:100%;box-sizing:border-box;min-height:52px;padding:0 16px;
                  margin:0 0 20px;font-family:inherit;font-size:17px;color:#1a1a1a;
                  background:#fff;border:1px solid var(--public-hairline);border-radius:999px;
                  transition:border-color .2s;
                }
                .sf-input:focus{outline:none;border-color:var(--public-brand-green)}
                .sf-input:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px;box-shadow:0 0 0 3px rgba(209,244,112,.28)}
                .sf-input:disabled{opacity:.6}
                /* NO .sf-input-code RULE ANY MORE. The code field had bespoke 22px/600/centred
                   type tracked out at .34em, which made the second stage look like a different
                   control from the first - half of exactly what the owner reported. The reference
                   surface settles it: /account/sign-in's code field is a plain .si-input, so plain
                   is both the consistent answer AND the site-matching one. The onChange digit-strip
                   and slice(0,6) stay - that is input hygiene, not styling. */


                /* NO .sf-cta RULE ANY MORE. The primary action on both stages is PillButton - the
                   home-page two-segment pill, and the same control /account/sign-in and /cart/
                   render - so the component owns the shape, colours, focus ring and reduced-motion
                   handling. Two things died with this rule and both were defects:
                     1. border:2px solid #d1f470 - a LIME border on the .22-alpha lime panel, which
                        cannot clear WCAG 1.4.11's 3:1 for a non-text control boundary. Every other
                        own-surface CTA on the site borders #1a3a2a for exactly this reason (see
                        .ship-close-cta), and PillButton does too.
                     2. the single lime surface itself, which the owner replaced with the dark-green
                        + mint pill on the login CTA. This page kept the old treatment and was the
                        last surface still showing it. */

                /* The resend stacks under the verify button rather than sitting beside it: at
                   280px two 52px pills cannot share a row without wrapping mid-label, and a
                   wrapped button row reads as a layout fault. Stacked is the same at every
                   width, and it matches /account/sign-in/. */
                .sf-resend{margin-top:12px}
                /* min-height:44px, NOT padding alone. padding:10px on a 15px line measured 38px
                   tall in the built export - under the 44px floor this site holds everything
                   else to, and only passing on mobile because tokens.css forces 44px on every
                   button below 768px. A tap target should not depend on a breakpoint. */
                .sf-quiet{
                  display:flex;align-items:center;justify-content:center;
                  width:100%;min-height:44px;margin-top:12px;padding:10px;
                  border:0;background:transparent;color:rgba(26,58,42,.72);
                  font-family:inherit;font-size:15px;cursor:pointer;
                }
                .sf-quiet:hover{color:var(--public-brand-green);text-decoration:underline}
                .sf-quiet:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}

                /* White card on the tinted panel, so each file reads as its own object. */
                .sf-file{
                  padding:20px;margin:0 0 14px;background:#fff;
                  border:2px solid rgba(26,58,42,.12);border-radius:12px;
                }
                .sf-file-deep{
                  padding:13px;border:0;box-shadow:inset 0 0 0 1px rgba(26,58,42,.07);
                }
                .sf-file-head{display:flex;gap:11px;align-items:flex-start}
                .sf-file-icon{
                  width:38px;height:38px;border-radius:10px;background:var(--public-lime-tint);
                  color:var(--public-brand-green);display:flex;align-items:center;justify-content:center;flex:0 0 auto;
                }
                .sf-file-copy{min-width:0;flex:1}
                .sf-file-name{
                  font-size:17px;font-weight:600;letter-spacing:-.2px;color:rgba(0,0,0,.95);overflow-wrap:anywhere;
                }
                .sf-file-meta{
                  margin:6px 0 16px;font-size:14px;color:rgba(26,58,42,.68);
                }
                .sf-file-deep .sf-file-name{font-size:15px;color:var(--public-brand-green)}
                .sf-file-deep .sf-file-meta{margin:3px 0 0;font-size:13px}
                .sf-paid-badge{
                  flex:0 0 auto;padding:4px 8px;border-radius:999px;background:var(--public-lime-tint);
                  color:var(--public-brand-green);font-size:11px;font-weight:700;
                }
                .sf-file-action{margin-top:13px}
                .sf-download-action{
                  display:inline-flex;align-items:center;width:max-content;max-width:100%;
                  min-height:calc(var(--tap-min) + 1px);box-sizing:border-box;padding:6px 9px;
                  border:0;border-radius:8px;background:var(--public-lime-tint);
                  color:var(--public-brand-green);font-family:inherit;
                  font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);
                  line-height:1.4;letter-spacing:-.05px;white-space:normal;overflow-wrap:anywhere;
                  text-align:start;text-decoration:underline;text-decoration-thickness:1.5px;
                  text-underline-offset:3px;cursor:pointer;touch-action:manipulation;
                  -webkit-tap-highlight-color:transparent;
                  transition:background-color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s;
                }
                .sf-download-action:hover:not(:disabled){
                  background:var(--public-brand-lime);text-decoration-color:transparent;
                  transform:translateY(-1px);box-shadow:0 5px 14px rgba(26,58,42,.1);
                }
                .sf-download-action:focus-visible{
                  background:var(--public-brand-lime);text-decoration-color:transparent;
                  outline:3px solid var(--public-brand-green);outline-offset:3px;
                }
                .sf-download-action:disabled{opacity:.55;cursor:progress}
                .sf-paid-note{
                  margin:12px 0 0;padding:10px 12px;border-radius:10px;background:#fff;
                  box-shadow:inset 4px 0 0 var(--public-brand-lime);
                  color:var(--public-body);font-size:14px;line-height:1.45;
                }

                /* No secondary website-checkout CTA is rendered for file delivery. */

                .sf-empty,.sf-fine{
                  font-size:15px;line-height:1.5;color:rgba(26,58,42,.72);margin:0;
                }
                .sf-fine{margin-top:18px;font-size:13px}

                /* Status banners. Colour is never the only signal - each carries role
                   alert or status, so a screen reader announces them regardless. */
                .sf-note{
                  margin:0 0 20px;padding:14px 16px;border-radius:999px;
                  font-size:16px;line-height:1.5;
                }
                /* NO RED, matching .si-error on /account/sign-in, which the owner had already
                   stripped of red. This was #fee2e2 on #ef4444 with #7f1d1d text - three colours
                   the home design does not contain, on a site whose only red is the full stop in
                   the wordmark. It is now the lime state tint behind a 4px #d1f470 inline-start
                   edge with #1a3a2a type at weight 700. Colour is not carrying the meaning:
                   role=alert announces it and the sentence states the problem, so the 4px edge and
                   the weight are a luminance and weight step rather than a hue change - which is
                   what survives forced-colors and reduced colour discrimination. Logical
                   inline-start, so the edge follows the reading direction. */
                .sf-note-bad{
                  background:var(--public-lime-tint);border-inline-start:4px solid var(--public-brand-lime);
                  font-weight:700;color:var(--public-brand-green);
                }
                .sf-note-ok{
                  background:#fff;border-inline-start:4px solid #1a3a2a;color:var(--public-brand-green);
                }

                @media(prefers-reduced-motion:reduce){
                  .sf-input,.sf-download-action{transition:none}
                  .sf-download-action:hover:not(:disabled){transform:none;box-shadow:none}
                }
            ` }</style>
        </>
    );
}
