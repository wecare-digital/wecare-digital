import React, { useEffect, useState } from 'react';
import PillButton from './PillButton';
import * as api from '../api/client';
import type { SecureFile } from '../api/client';
import { getSession, restoreSession } from '../lib/customerAuth';
import { fetchServicePrices } from '../lib/servicePricing';
import type { ServicePrice } from '../lib/servicePricing';
import { postRequestIntent } from '../lib/serviceRequests';
import { setServiceLine } from '../lib/cart';

export default function VaultFilePurchase () {
  const [ token, setToken ] = useState( '' );
  const [ checked, setChecked ] = useState( false );
  const [ files, setFiles ] = useState<SecureFile[]>( [] );
  const [ price, setPrice ] = useState<ServicePrice | null>( null );
  const [ busy, setBusy ] = useState( '' );
  const [ message, setMessage ] = useState( '' );
  const [ selectedFile, setSelectedFile ] = useState( '' );
  useEffect( () => {
    let alive = true;
    // Preserve the non-secret file pointer through the canonical sign-in return URL.
    const pointerKey = 'wecare.vault.selectedFile';
    const validPointer = ( value: string ) => /^[a-zA-Z0-9_-]{1,120}$/.test( value );
    const query = new URLSearchParams( window.location.search );
    let pointer = query.get( 'file' ) || '';
    try {
      if ( query.has( 'file' ) ) {
        if ( validPointer( pointer ) ) sessionStorage.setItem( pointerKey, pointer );
        else { sessionStorage.removeItem( pointerKey ); pointer = ''; }
      } else pointer = sessionStorage.getItem( pointerKey ) || '';
    } catch { /* The link still works when browser storage is unavailable. */ }
    if ( validPointer( pointer ) ) setSelectedFile( pointer );
    void fetchServicePrices().then( prices => { if ( alive ) setPrice( prices.vault ); } );
    void ( async () => {
      const session = getSession() || await restoreSession();
      if ( !alive ) return;
      if ( !session ) { setChecked( true ); return; }
      setToken( session.accessToken );
      const result = await api.listMySecureFiles();
      if ( !alive ) return;
      if ( result.ok ) setFiles( result.data.files || [] );
      else setMessage( result.failure.message || 'Your files could not be loaded. Please try again.' );
      setChecked( true );
    } )().catch( () => { if ( alive ) { setChecked( true ); setMessage( 'Sign-in is temporarily unavailable. Please try again.' ); } } );
    return () => { alive = false; };
  }, [] );

  const collect = async ( file: SecureFile ) => {
    if ( busy ) return;
    setBusy( file.fileId ); setMessage( '' );
    if ( file.paidGrantId )
    {
      const result = await api.redeemSecureFileDownload( file.fileId, file.paidGrantId );
      if ( result.ok ) { window.location.assign( result.data.downloadUrl ); return; }
      setMessage( result.failure.message || 'Your paid file is not available right now. Please contact us before paying again.' );
    }
    else if ( price?.available )
    {
      const result = await postRequestIntent( token, 'VAULT', undefined, file.fileId );
      if ( result.kind === 'ok' )
      {
        setServiceLine( result.intent.variantId, result.intent.intentId, price.paise );
        window.location.assign( '/cart/' ); return;
      }
      setMessage( result.kind === 'refused' ? result.message : 'This file could not be prepared. Nothing has been charged. Please try again.' );
    }
    setBusy( '' );
  };

  const visibleFiles = selectedFile ? files.filter( file => file.fileId === selectedFile ) : files;

  return <section className="vault-panel" aria-labelledby="vault-files-title">
    <h2 id="vault-files-title">Your documents, ready when you are</h2>
    <p>Choose a file shared with your verified WhatsApp number. One purchase unlocks one download. We will send the access message on WhatsApp, followed by an invitation to review your experience.</p>
    { !checked && <p>Loading your Vault…</p> }
    { checked && !token && <PillButton as="a" href="/account/sign-in/?return=%2Fvault%2F" action="Sign in on WhatsApp" /> }
    { checked && token && files.length === 0 && !message && <p>No documents are ready yet. Our team will upload your file here before you pay.</p> }
    { message && <p role="status">{ message }</p> }
    { checked && token && selectedFile && !visibleFiles.length && <p role="status">This file is not available for your signed-in WhatsApp number. Contact us if you expected access; please do not pay again.</p> }
    { checked && token && selectedFile && <PillButton action="View all your files" onClick={ () => {
      try { sessionStorage.removeItem( 'wecare.vault.selectedFile' ); } catch { /* Optional storage. */ }
      setSelectedFile( '' );
      window.history.replaceState( null, '', '/vault/' );
    } } /> }
    <div className="vault-files">{ visibleFiles.map( file => <article key={ file.fileId }>
      <div><h3>{ file.displayName || file.originalFilename }</h3>
        <p>{ file.paidGrantId ? 'Paid · Ready to download' : price?.available ? `₹${ price.rupees } + the convenience fee shown at checkout` : 'Price currently unavailable' }</p>
        { file.vaultOrderNumber && <p>Order { file.vaultOrderNumber }</p> }</div>
      { ( file.paidGrantId || price?.available ) && <PillButton action={ file.paidGrantId ? 'Download your file' : 'Continue to payment' } disabled={ !!busy } onClick={ () => void collect( file ) } /> }
    </article> ) }</div>
    <style jsx>{`
      .vault-panel{max-width:1040px;margin:0 auto 72px;padding:32px;border:2px solid #1a3a2a;border-radius:14px;color:#1a3a2a;background:#fff}
      h2{font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;letter-spacing:-1.2px;margin:0 0 18px}
      p{font-size:15px;line-height:1.6;max-width:740px;margin:8px 0 18px}
      .vault-files{display:grid;gap:14px;margin-top:24px}
      article{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:24px;background:#f7f9f2;border:1px solid #dce5d3;border-radius:14px}
      h3{font-size:20px;margin:0 0 8px;overflow-wrap:anywhere}article p{margin:4px 0}
      @media(max-width:700px){.vault-panel{margin:0 16px 48px;padding:24px}article{align-items:flex-start;flex-direction:column}}
    `}</style>
  </section>;
}
