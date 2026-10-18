/**
 * Documentation Scraper — [retired public path]/docs
 * Feed external doc URLs (e.g. Meta Business docs), trigger re-fetch ("upgrade"),
 * and view the change log. Backed by the wecare-docs-scraper Lambda; content is
 * stored in s3://wecare-digital-get/o/stream/docs/ (served as
 * https://wecare.digital/get/o/stream/docs/).
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import { useToastContext } from '../../../contexts/ToastContext';
import { authFetch } from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

interface DocSource {
    name: string;
    rootUrl: string;
    pathPrefix?: string;
    contentSelector?: string;
    addedAt?: string;
}
interface ChangeEntry {
    ts: string; source: string; url: string;
    type: 'new' | 'updated' | 'error'; key?: string; error?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

const emptyForm = { name: '', rootUrl: '', pathPrefix: '', contentSelector: 'main' };

const DocsScraperPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
    const toast = useToastContext();
    const [ sources, setSources ] = useState<DocSource[]>( [] );
    const [ changelog, setChangelog ] = useState<ChangeEntry[]>( [] );
    const [ loading, setLoading ] = useState( true );
    const [ form, setForm ] = useState( emptyForm );
    const [ adding, setAdding ] = useState( false );
    const [ scraping, setScraping ] = useState<string | null>( null );

    const load = useCallback( async () => {
        setLoading( true );
        try
        {
            const [ srcRes, logRes ] = await Promise.all( [
                authFetch( `${API_BASE}/docs/sources` ).then( r => r.json() ).catch( () => [] ),
                authFetch( `${API_BASE}/docs/changelog?limit=100` ).then( r => r.json() ).catch( () => [] ),
            ] );
            setSources( Array.isArray( srcRes ) ? srcRes : [] );
            setChangelog( Array.isArray( logRes ) ? logRes : [] );
        } catch ( e )
        {
            toast.error( 'Failed to load documentation sources' );
        } finally
        {
            setLoading( false );
        }
    }, [ toast ] );

    useEffect( () => { load(); }, [ load ] );

    const addSource = async () => {
        if ( !form.name.trim() || !form.rootUrl.trim() )
        {
            toast.error( 'Name and root URL are required' );
            return;
        }
        setAdding( true );
        try
        {
            const res = await authFetch( `${API_BASE}/docs/sources`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify( { action: 'add_source', ...form } ),
            } );
            if ( !res.ok ) throw new Error( await res.text() );
            toast.success( `Added source "${form.name}"` );
            setForm( emptyForm );
            load();
        } catch ( e: any )
        {
            toast.error( `Could not add source: ${e.message || e}` );
        } finally
        {
            setAdding( false );
        }
    };

    const rescrape = async ( source?: string ) => {
        setScraping( source || 'ALL' );
        try
        {
            toast.info( source ? `Re-fetching "${source}"…` : 'Re-fetching all sources…' );
            const res = await authFetch( `${API_BASE}/docs/scrape`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify( { action: 'scrape', source } ),
            } );
            const data = await res.json();
            const changed = data?.changedCount ?? ( data?.changed?.length || 0 );
            toast.success( `Done — ${changed} page(s) changed` );
            load();
        } catch ( e: any )
        {
            toast.error( `Re-fetch failed: ${e.message || e}` );
        } finally
        {
            setScraping( null );
        }
    };

    const body = (
        <>
            <SEO title="Documentation Scraper" description="Fetch and track external documentation with change detection" />
            <div style={ { padding: embedded ? 0 : 24 } }>
                <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } }>
                    <h1 style={ { fontSize: 22, fontWeight: 700, margin: 0 } }>Documentation Scraper</h1>
                    <Button onClick={ () => rescrape() } disabled={ scraping !== null }>
                        { scraping === 'ALL' ? 'Re-fetching…' : 'Re-fetch all' }
                    </Button>
                </div>

                {/* Add a new source */ }
                <div style={ card }>
                    <h2 style={ h2 }>Add a documentation source</h2>
                    <div style={ { display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 10 } }>
                        <input style={ input } placeholder="Name (e.g. meta-business-agent)"
                            value={ form.name } onChange={ e => setForm( { ...form, name: e.target.value } ) } />
                        <input style={ input } placeholder="Root URL (https://developers.facebook.com/documentation/…)"
                            value={ form.rootUrl } onChange={ e => setForm( { ...form, rootUrl: e.target.value } ) } />
                        <input style={ input } placeholder="Path prefix (optional — auto-derived from URL)"
                            value={ form.pathPrefix } onChange={ e => setForm( { ...form, pathPrefix: e.target.value } ) } />
                        <input style={ input } placeholder="Content selector (default: main)"
                            value={ form.contentSelector } onChange={ e => setForm( { ...form, contentSelector: e.target.value } ) } />
                    </div>
                    <div style={ { marginTop: 10 } }>
                        <Button onClick={ addSource } disabled={ adding }>{ adding ? 'Adding…' : 'Add source' }</Button>
                    </div>
                </div>

                {/* Sources */ }
                <div style={ card }>
                    <h2 style={ h2 }>Sources ({ sources.length })</h2>
                    { loading ? <p>Loading…</p> : sources.length === 0 ? <p style={ { color: 'var(--text-muted)' } }>No sources yet. Add one above.</p> : (
                        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-md)' } }>
                            <thead>
                                <tr style={ { textAlign: 'left', color: 'var(--text-muted)' } }>
                                    <th style={ th }>Name</th><th style={ th }>Root URL</th><th style={ th }>Added</th><th style={ th }></th>
                                </tr>
                            </thead>
                            <tbody>
                                { sources.map( s => (
                                    <tr key={ s.name } style={ { borderTop: '1px solid var(--border-light)' } }>
                                        <td style={ td }>{ s.name }</td>
                                        <td style={ td }><a href={ s.rootUrl } target="_blank" rel="noreferrer">{ s.rootUrl }</a></td>
                                        <td style={ td }>{ s.addedAt ? new Date( s.addedAt ).toLocaleDateString() : '—' }</td>
                                        <td style={ td }>
                                            <Button variant="secondary" onClick={ () => rescrape( s.name ) } disabled={ scraping !== null }>
                                                { scraping === s.name ? 'Re-fetching…' : 'Re-fetch' }
                                            </Button>
                                        </td>
                                    </tr>
                                ) ) }
                            </tbody>
                        </table>
                    ) }
                </div>

                {/* Change log */ }
                <div style={ card }>
                    <h2 style={ h2 }>Change log ({ changelog.length })</h2>
                    { changelog.length === 0 ? <p style={ { color: 'var(--text-muted)' } }>No changes recorded yet.</p> : (
                        <div style={ { maxHeight: 360, overflowY: 'auto' } }>
                            { changelog.map( ( c, i ) => (
                                <div key={ i } style={ { padding: '8px 0', borderTop: '1px solid var(--border-light)', fontSize: 'var(--text-sm)' } }>
                                    <span className={ badgeClass( c.type ) }>{ c.type }</span>
                                    <strong style={ { marginLeft: 8 } }>{ c.source }</strong>
                                    <span style={ { color: 'var(--text-muted)', marginLeft: 8 } }>{ new Date( c.ts ).toLocaleString() }</span>
                                    <div style={ { color: 'var(--text-secondary)', wordBreak: 'break-all' } }>{ c.url }{ c.error ? ` — ${c.error}` : '' }</div>
                                </div>
                            ) ) }
                        </div>
                    ) }
                </div>
            </div>
        </>
    );

    return embedded ? body : <Layout user={ user } onSignOut={ signOut }>{ body }</Layout>;
};

// Styling uses shared design tokens (src/styles/tokens.css) so the page matches
// the site theme — no hard-coded colors. Inputs/buttons are globally themed.
const card: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)', marginBottom: 'var(--space-4)', boxShadow: 'var(--shadow-sm)' };
const h2: React.CSSProperties = { fontSize: 'var(--h4)', fontWeight: 600, margin: '0 0 var(--space-3)', color: 'var(--text)' };
const input: React.CSSProperties = { width: '100%' };
const th: React.CSSProperties = { padding: '6px 8px', fontWeight: 600, color: 'var(--text-muted)' };
const td: React.CSSProperties = { padding: 'var(--space-2)' };
// changelog entry type -> shared .status-pill class (new=read/green, updated=sent/blue, error=failed/red)
const badgeClass = ( type: string ): string =>
    `status-pill ${type === 'new' ? 'status-read' : type === 'updated' ? 'status-sent' : 'status-failed'}`;

export default DocsScraperPage;
