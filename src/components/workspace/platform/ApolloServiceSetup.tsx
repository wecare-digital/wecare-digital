import React, { useEffect, useState } from 'react';
import { workspaceMCP } from '../../../lib/workspace-mcp';
import Button from '../../ui/Button';
import styles from '../../../styles/MCPConnections.module.css';

interface SetupStatus { gmailConnected: boolean; delegated: boolean; credentialsConfigured: boolean; }

/** Admin-only secret entry. The password is encrypted on the server and never read back. */
export default function ApolloServiceSetup (): React.ReactElement {
  const [ status, setStatus ] = useState<SetupStatus | null>( null );
  const [ password, setPassword ] = useState( '' );
  const [ approved, setApproved ] = useState( false );
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState( '' );
  const [ message, setMessage ] = useState( '' );

  async function refresh (): Promise<void> {
    setBusy( true ); setError( '' );
    try { setStatus( await workspaceMCP<SetupStatus>( 'arogya_provider_status' ) ); }
    catch ( failure ) { setError( failure instanceof Error ? failure.message : 'Could not check Apollo setup.' ); }
    finally { setBusy( false ); }
  }
  useEffect( () => { void refresh(); }, [] );

  async function activate ( event: React.FormEvent ): Promise<void> {
    event.preventDefault();
    if ( busy || !approved || !password ) return;
    setBusy( true ); setError( '' ); setMessage( '' );
    try {
      await workspaceMCP( 'arogya_provider_configure', { password, authorizeService: true } );
      setMessage( 'Apollo configuration saved securely. The service will sign in and read Apollo OTP emails on demand.' );
      setStatus( { gmailConnected: true, delegated: true, credentialsConfigured: true } );
      setApproved( false );
    } catch ( failure ) { setError( failure instanceof Error ? failure.message : 'Apollo setup could not complete.' ); }
    finally { setPassword( '' ); setBusy( false ); }
  }

  return <section className={ styles.card } aria-label="Arogya live Apollo connection">
    <h2>Arogya live Apollo connection</h2>
    <p>First connect and verify “Gmail · Apollo OTP” above using wecare.digital.bw@gmail.com, then refresh this setup.</p>
    <p>Mailbox: { status?.gmailConnected ? 'Connected to your Admin account' : 'Not connected' }. Service: { status?.delegated && status.credentialsConfigured ? 'Configuration saved' : 'Setup required' }.</p>
    <Button disabled={ busy } onClick={ () => { void refresh(); } }>Refresh setup</Button>
    <form onSubmit={ event => { void activate( event ); } }>
      <label htmlFor="apollo-service-password">Apollo account password</label>
      <input id="apollo-service-password" type="password" autoComplete="off" maxLength={ 256 } required value={ password } onChange={ event => setPassword( event.target.value ) } disabled={ busy || !status?.gmailConnected } />
      <label><input type="checkbox" checked={ approved } onChange={ event => setApproved( event.target.checked ) } disabled={ busy || !status?.gmailConnected } />Authorize the Arogya service to use this business mailbox grant for Apollo login codes and store the Apollo password encrypted in AWS.</label>
      <div className={ styles.actions }><Button variant="primary" type="submit" disabled={ busy || !status?.gmailConnected || !approved || !password }>Save service connection</Button></div>
    </form>
    { error && <p role="alert">{ error }</p> }
    { message && <p role="status">{ message }</p> }
  </section>;
}
