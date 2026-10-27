/**
 * SEO Pages Manager — Unified AI-Powered SEO Dashboard for all non-blog pages
 * Tabs: Site Pages | System Pages | Products | New Pages | Audit | Blog Creator | Logs | Instructions
 * Full feature parity with blog-manager: clean, audit, approve, apply, bulk ops, AI blog creator
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
// Moved out of src/pages/. It is a content COMPONENT, but sitting under pages/
// meant Next routed it as [retired public path]/InstructionsContent - a 292-line chrome-less page
// nobody intended to publish.
import InstructionsContent from '../../../components/seo/InstructionsContent';
import { seoToolsFetch } from '../../../api/seo';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
interface SitePage {
  path: string; name: string; type: string; url: string;
  title: string; metaDescription: string; keywords: string[];
  jsonLdTypes: string[]; hasJsonLd: boolean; canonical: string;
}
interface ProductPage {
  id: string; name: string; slug: string; url: string;
  description: string; price: string; priceAmount: number; currency: string;
  inStock: boolean; image: string; type: string;
  hasJsonLd: boolean; jsonLdType: string;
}
interface PageAudit {
  id: string; blogSlug: string; blogTitle: string; pageType: string;
  currentSeoTitle: string; suggestedSeoTitle: string;
  currentMetaDescription: string; suggestedMetaDescription: string;
  focusKeyword: string; secondaryKeywords: string[];
  suggestedJsonLd: any; internalLinkSuggestions: any[]; imageAltSuggestions: any[];
  seoScoreBefore: number; seoScoreAfter: number; scoreBreakdown: any;
  warnings: string[]; fullAiResponse: any; aiModel: string;
  status: string; createdAt: string; appliedAt?: string;
}

type Tab = 'site' | 'system' | 'products' | 'new' | 'audit' | 'create' | 'logs' | 'instructions';
type Filter = 'all' | string;
type StatusFilter = 'all' | 'pending' | 'audited' | 'approved' | 'applied';

const th: React.CSSProperties = { padding: '8px 10px', textAlign: 'left', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-muted)' };
const td: React.CSSProperties = { padding: '6px 10px' };
const btn: React.CSSProperties = { padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 'var(--text-xs)', fontFamily: 'inherit' };
const BASE = 'https://wecare.digital';

const productAuditPath = ( product: ProductPage ): string => {
  try {
    const path = new URL( product.url, BASE ).pathname;
    return path === '/' ? '/' : path.replace( /\/$/, '' );
  } catch {
    const slug = product.slug || product.id;
    return `/shop/${slug}`;
  }
};

const SYSTEM_PAGES: SitePage[] = [
  { path: '/auth', name: 'Customer Sign In', type: 'system', url: `${BASE}/auth`, title: 'Customer Sign In', metaDescription: '', keywords: [], jsonLdTypes: [], hasJsonLd: false, canonical: '' },
  { path: '/orders/', name: 'Orders', type: 'system', url: `${BASE}/orders/`, title: 'Orders', metaDescription: '', keywords: [], jsonLdTypes: [], hasJsonLd: false, canonical: '' },
];

const PagesManager: React.FC<PageProps> = ({ signOut, user, embedded }) => {
  const [tab, setTab] = useState<Tab>('site');
  const [sitePages, setSitePages] = useState<SitePage[]>([]);
  const [products, setProducts] = useState<ProductPage[]>([]);
  const [audits, setAudits] = useState<PageAudit[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Filter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedAudit, setSelectedAudit] = useState<PageAudit | null>(null);
  const [auditingSlug, setAuditingSlug] = useState<string | null>(null);
  const [bulkRunning, setBulkRunning] = useState<string | null>(null);
  const [newPageUrl, setNewPageUrl] = useState('');
  const [newPageName, setNewPageName] = useState('');
  const [customPages, setCustomPages] = useState<SitePage[]>([]);
  const [search, setSearch] = useState('');
  const [log, setLog] = useState<string[]>([]);
  const addLog = (m: string) => setLog(p => [...p, `[${new Date().toLocaleTimeString()}] ${m}`]);

  // ── DATA FETCHING ──
  const fetchSitePages = useCallback(async () => {
    setLoading(true); addLog('Fetching site pages...');
    try { const d = await (await seoToolsFetch('site-pages')).json(); if (d.ok) { setSitePages(d.pages); addLog(`${d.total} site pages loaded`); } else addLog(d.error); }
    catch (e: any) { addLog(e.message); } setLoading(false);
  }, []);
  const fetchProducts = useCallback(async () => {
    setLoading(true); addLog('Fetching product pages...');
    try { const d = await (await seoToolsFetch('product-pages')).json(); if (d.ok) { setProducts(d.products); addLog(`${d.total} products loaded`); } else addLog(d.error); }
    catch (e: any) { addLog(e.message); } setLoading(false);
  }, []);
  const fetchAudits = useCallback(async () => {
    try { const d = await (await seoToolsFetch('seo-logs?type=audits&scope=pages')).json(); if (d.ok) setAudits(d.audits || []); } catch {}
  }, []);
  const fetchLogs = useCallback(async () => {
    try { const d = await (await seoToolsFetch('seo-logs?type=logs&scope=pages')).json(); if (d.ok) setLogs(d.logs || []); } catch {}
  }, []);
  useEffect(() => { fetchSitePages(); fetchProducts(); fetchAudits(); }, [fetchSitePages, fetchProducts, fetchAudits]);

  const getAudit = (slug: string) => audits.filter(a => a.blogSlug === slug).sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt))[0];

  // ── ACTIONS ──
  const cleanPage = async (slug: string, name?: string, pageType?: string) => {
    addLog(`Cleaning "${slug}"...`);
    try { const d = await (await seoToolsFetch('page-clean', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: slug, name, pageType }) })).json();
      if (d.ok) { addLog(`Cleaned: ${d.cleaned.auditsRemoved} audit(s) removed. ${d.cleaned.message}`); await fetchAudits(); }
      else addLog(`Clean failed: ${d.error}`);
    } catch (e: any) { addLog(e.message); }
  };
  const runPageAudit = async (path: string, name: string, pageType: string) => {
    setAuditingSlug(path); addLog(`Auditing "${name}" (${path})...`);
    try { const d = await (await seoToolsFetch('page-audit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path, name, pageType }) })).json();
      if (d.ok) { addLog(`Done: ${d.audit.seoScoreBefore} > ${d.audit.seoScoreAfter}${d.log?.costEstimate ? ' | $' + d.log.costEstimate : ''}`); await fetchAudits(); setSelectedAudit(d.audit); setTab('audit'); }
      else addLog(`Failed: ${d.error}`);
    } catch (e: any) { addLog(e.message); } setAuditingSlug(null);
  };
  const cleanAndAudit = async (path: string, name: string, pageType: string) => { await cleanPage(path, name, pageType); await runPageAudit(path, name, pageType); };
  const handleAction = async (id: string, action: string) => {
    addLog(`${action} ${id.substring(0, 20)}...`);
    try { const d = await (await seoToolsFetch('seo-approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auditId: id, action }) })).json();
      if (d.ok) { addLog(`${action} done${d.applied ? ' — saved to AWS' : ''}`); await fetchAudits(); if (selectedAudit?.id === id) setSelectedAudit(d.audit); }
      else addLog(d.error);
    } catch (e: any) { addLog(e.message); }
  };

  // ── BULK OPS ──
  const bulkClean = async (items: { path: string; name: string; type: string }[]) => {
    setBulkRunning('clean'); addLog(`Bulk clean ${items.length} pages...`);
    for (const item of items) { await cleanPage(item.path, item.name, item.type); await new Promise(r => setTimeout(r, 500)); }
    addLog('Bulk clean done'); await fetchAudits(); setBulkRunning(null);
  };
  const bulkAudit = async (items: { path: string; name: string; type: string }[]) => {
    setBulkRunning('audit'); let ok = 0;
    for (const item of items) {
      addLog(`Auditing ${ok + 1}/${items.length}: ${item.name}`);
      try { const d = await (await seoToolsFetch('page-audit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: item.path, name: item.name, pageType: item.type }) })).json(); if (d.ok) ok++; } catch {}
      await new Promise(r => setTimeout(r, 1000));
    }
    addLog(`Bulk audit done: ${ok}/${items.length}`); await fetchAudits(); setBulkRunning(null);
  };
  const bulkApprove = async (ids: string[]) => {
    setBulkRunning('approve'); let ok = 0;
    for (const id of ids) { try { const d = await (await seoToolsFetch('seo-approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auditId: id, action: 'approve' }) })).json(); if (d.ok) ok++; } catch {} }
    addLog(`Bulk approve: ${ok}/${ids.length}`); await fetchAudits(); setBulkRunning(null);
  };
  // ── HELPERS ──
  const toggleSel = (s: string) => setSelected(p => { const n = new Set(p); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const addCustomPage = () => {
    if (!newPageUrl.trim()) return;
    const path = newPageUrl.startsWith('/') ? newPageUrl.trim() : `/${newPageUrl.trim()}`;
    const name = newPageName.trim() || path.replace(/^\//, '').replace(/-/g, ' ');
    setCustomPages(p => [...p, { path, name, type: 'custom', url: `${BASE}${path}`, title: name, metaDescription: '', keywords: [], jsonLdTypes: [], hasJsonLd: false, canonical: `${BASE}${path}` }]);
    addLog(`Added custom page: ${name} (${path})`); setNewPageUrl(''); setNewPageName('');
  };

  // ── STATS ──
  const siteNoSeo = sitePages.filter(p => !p.hasJsonLd).length;
  const prodNoSeo = products.filter(p => !p.hasJsonLd).length;
  const auditStats = { total: audits.length, pending: audits.filter(a => a.status === 'pending_review').length, approved: audits.filter(a => a.status === 'approved').length, applied: audits.filter(a => a.status === 'applied').length };

  const tabItems: [Tab, string, string][] = [
    ['site', `Site Pages (${sitePages.length})`, '📄'],
    ['system', `System (${SYSTEM_PAGES.length})`, '⚙️'],
    ['products', `Products (${products.length})`, '🛒'],
    ['new', `New Pages (${customPages.length})`, '➕'],
    ['audit', `Audit (${auditStats.total})`, '🔍'],
    ['create', 'Blog Creator', '✍️'],
    ['logs', 'Logs', '📋'],
    ['instructions', 'Instructions', '📖'],
  ];

  const body = (
      <div className="inner-page" style={ embedded ? { padding: 0 } : undefined }>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div>
            <h1 className="inner-page-title" style={{ margin: 0 }}>SEO Pages Manager</h1>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', margin: '4px 0 0' }}>
              {sitePages.length} site | {products.length} products | {SYSTEM_PAGES.length} system | {auditStats.applied} applied | {auditStats.pending} review | {siteNoSeo + prodNoSeo} missing SEO
            </p>
          </div>
          <button className="btn btn-primary" onClick={() => { fetchSitePages(); fetchProducts(); fetchAudits(); }} disabled={loading} style={{ fontSize: 'var(--text-sm)' }}>{loading ? 'Loading...' : 'Refresh All'}</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '2px solid var(--border)', paddingBottom: 8, flexWrap: 'wrap' }}>
          {tabItems.map(([t, l, icon]) => (
            <button key={t} onClick={() => { setTab(t); setFilter('all'); setStatusFilter('all'); setSelected(new Set()); setSearch(''); if (t === 'logs') fetchLogs(); }}
              style={{ padding: '8px 16px', borderRadius: '8px 8px 0 0', border: 'none', cursor: 'pointer', fontSize: 'var(--text-sm)', background: tab === t ? 'var(--lime)' : 'transparent', color: tab === t ? 'var(--accent)' : 'var(--text-muted)', fontWeight: tab === t ? 600 : 400, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>{icon}</span>{l}
            </button>
          ))}
        </div>

        {tab === 'site' && <SitePagesTab pages={sitePages} audits={audits} filter={filter} setFilter={setFilter} statusFilter={statusFilter} setStatusFilter={setStatusFilter} selected={selected} toggleSel={toggleSel} setSelected={setSelected} auditingSlug={auditingSlug} bulkRunning={bulkRunning} onAudit={runPageAudit} onCleanAudit={cleanAndAudit} onBulkClean={bulkClean} onBulkAudit={bulkAudit} onBulkApprove={bulkApprove} onViewAudit={(a: PageAudit) => { setSelectedAudit(a); setTab('audit'); }} getAudit={getAudit} search={search} setSearch={setSearch} />}
        {tab === 'system' && <SystemPagesTab pages={SYSTEM_PAGES} auditingSlug={auditingSlug} bulkRunning={bulkRunning} onAudit={runPageAudit} onCleanAudit={cleanAndAudit} onViewAudit={(a: PageAudit) => { setSelectedAudit(a); setTab('audit'); }} getAudit={getAudit} search={search} setSearch={setSearch} />}
        {tab === 'products' && <ProductPagesTab products={products} audits={audits} auditingSlug={auditingSlug} bulkRunning={bulkRunning} onAudit={runPageAudit} onCleanAudit={cleanAndAudit} onBulkAudit={bulkAudit} onViewAudit={(a: PageAudit) => { setSelectedAudit(a); setTab('audit'); }} getAudit={getAudit} search={search} setSearch={setSearch} />}
        {tab === 'new' && <NewPagesTab customPages={customPages} newPageUrl={newPageUrl} newPageName={newPageName} setNewPageUrl={setNewPageUrl} setNewPageName={setNewPageName} addCustomPage={addCustomPage} auditingSlug={auditingSlug} onAudit={runPageAudit} onCleanAudit={cleanAndAudit} onRemove={(path: string) => setCustomPages(p => p.filter(x => x.path !== path))} search={search} setSearch={setSearch} />}
        {tab === 'audit' && <AuditDetail audit={selectedAudit} audits={audits} onSelect={setSelectedAudit} onAction={handleAction} />}
        {tab === 'create' && <BlogCreator addLog={addLog} />}
        {tab === 'logs' && <LogsView logs={logs} />}
        {tab === 'instructions' && <InstructionsContent />}

        {log.length > 0 && (<div className="card" style={{ padding: 16, marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ fontSize: 'var(--text-md)', fontWeight: 600, margin: 0 }}>Activity</h3>
            <button className="btn btn-secondary" onClick={() => setLog([])} style={{ fontSize: 'var(--text-xs)', padding: '4px 12px' }}>Clear</button>
          </div>
          <pre style={{ background: '#0f1117', color: '#a3e635', padding: 16, borderRadius: 8, fontSize: 'var(--text-xs)', lineHeight: 1.6, maxHeight: 200, overflowY: 'auto', fontFamily: 'Consolas, Monaco, monospace', whiteSpace: 'pre-wrap' }}>{log.join('\n')}</pre>
        </div>)}
      </div>
  );

  if (embedded) return body;
  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="SEO Pages Manager" description="AI SEO for all pages" />
      {body}
    </Layout>
  );
};

// ═══════════════════════════════════════════════════════════════
// SITE PAGES TAB — full deep clean: select, filter, bulk clean/audit/approve
// ═══════════════════════════════════════════════════════════════
function SitePagesTab({ pages, audits, filter, setFilter, statusFilter, setStatusFilter, selected, toggleSel, setSelected, auditingSlug, bulkRunning, onAudit, onCleanAudit, onBulkClean, onBulkAudit, onBulkApprove, onViewAudit, getAudit, search, setSearch }: any) {
  const types = [...new Set(pages.map((p: SitePage) => p.type))] as string[];
  let filtered: SitePage[] = filter === 'all' ? pages : pages.filter((p: SitePage) => p.type === filter);
  if (statusFilter === 'pending') filtered = filtered.filter((p: SitePage) => !getAudit(p.path));
  else if (statusFilter === 'audited') filtered = filtered.filter((p: SitePage) => getAudit(p.path)?.status === 'pending_review');
  else if (statusFilter === 'approved') filtered = filtered.filter((p: SitePage) => getAudit(p.path)?.status === 'approved');
  else if (statusFilter === 'applied') filtered = filtered.filter((p: SitePage) => getAudit(p.path)?.status === 'applied');
  // No SEO filter
  const noSeoCount = pages.filter((p: SitePage) => !p.hasJsonLd && !p.metaDescription).length;
  if (statusFilter === 'noseo' as any) filtered = filtered.filter((p: SitePage) => !p.hasJsonLd && !p.metaDescription);
  // Search filter
  if (search) { const q = search.toLowerCase(); filtered = filtered.filter((p: SitePage) => p.name.toLowerCase().includes(q) || p.path.toLowerCase().includes(q) || (p.title || '').toLowerCase().includes(q) || p.type.toLowerCase().includes(q)); }
  const selAll = () => setSelected(new Set(filtered.map((p: SitePage) => p.path)));
  const selNone = () => setSelected(new Set());
  const stats = { total: pages.length, pending: pages.filter((p: SitePage) => !getAudit(p.path)).length, audited: pages.filter((p: SitePage) => getAudit(p.path)?.status === 'pending_review').length, approved: pages.filter((p: SitePage) => getAudit(p.path)?.status === 'approved').length, applied: pages.filter((p: SitePage) => getAudit(p.path)?.status === 'applied').length };

  return (<>
    {/* Search box */}
    <div style={{ marginBottom: 10 }}>
      <input value={search} onChange={(e: any) => { setSearch(e.target.value); selNone(); }} placeholder="🔍 Search by name, path, title, type..." style={{ width: '100%', padding: '8px 14px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
    </div>
    {/* Type filters */}
    <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
      <button onClick={() => setFilter('all')} style={{ ...btn, background: filter === 'all' ? 'var(--lime)' : '#f3f4f6', fontWeight: filter === 'all' ? 600 : 400 }}>All ({pages.length})</button>
      {types.map((t: string) => <button key={t} onClick={() => { setFilter(t); selNone(); }} style={{ ...btn, background: filter === t ? 'var(--lime)' : '#f3f4f6', fontWeight: filter === t ? 600 : 400 }}>{t} ({pages.filter((p: SitePage) => p.type === t).length})</button>)}
    </div>
    {/* Status filters */}
    <div style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      {([['all', `All (${stats.total})`], ['noseo', `No SEO (${noSeoCount})`], ['pending', `Pending (${stats.pending})`], ['audited', `Review (${stats.audited})`], ['approved', `Approved (${stats.approved})`], ['applied', `Applied (${stats.applied})`]] as [StatusFilter, string][]).map(([f, l]) => (
        <button key={f} onClick={() => { setStatusFilter(f); selNone(); }} style={{ padding: '5px 12px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 'var(--text-xs)', background: statusFilter === f ? (f === 'noseo' as any ? '#fee2e2' : 'var(--lime)') : '#f3f4f6', color: statusFilter === f ? (f === 'noseo' as any ? '#991b1b' : 'var(--accent)') : 'var(--text-muted)', fontWeight: statusFilter === f ? 600 : 400 }}>{l}</button>
      ))}
      <div style={{ flex: 1 }} />
      {selected.size > 0 && (<div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{selected.size} selected</span>
        <button onClick={() => onBulkClean([...selected].map((path: string) => { const p = pages.find((x: SitePage) => x.path === path); return { path, name: p?.name || path, type: p?.type || 'site' }; }))} disabled={!!bulkRunning} style={{ ...btn, background: '#fef3c7', fontWeight: 600 }}>{bulkRunning === 'clean' ? 'Cleaning...' : `Bulk Clean (${selected.size})`}</button>
        <button onClick={() => onBulkAudit([...selected].map((path: string) => { const p = pages.find((x: SitePage) => x.path === path); return { path, name: p?.name || path, type: p?.type || 'site' }; }))} disabled={!!bulkRunning} style={{ ...btn, background: 'var(--lime)', fontWeight: 600 }}>{bulkRunning === 'audit' ? 'Auditing...' : `Bulk Audit (${selected.size})`}</button>
        {(() => { const ids = [...selected].map((s: string) => getAudit(s)).filter((a: any) => a?.status === 'pending_review').map((a: any) => a!.id); return ids.length ? <button onClick={() => onBulkApprove(ids)} disabled={!!bulkRunning} style={{ ...btn, background: '#dbeafe', fontWeight: 600 }}>Bulk Approve ({ids.length})</button> : null; })()}
        <button onClick={selNone} style={{ ...btn, background: '#f3f4f6' }}>Clear</button>
      </div>)}
      {selected.size === 0 && filtered.length > 0 && <button onClick={selAll} style={{ ...btn, background: '#f3f4f6' }}>Select All ({filtered.length})</button>}
    </div>

    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)' }}>
        <thead><tr style={{ background: 'var(--bg-secondary)', borderBottom: '2px solid var(--border)' }}>
          <th style={{ ...th, width: 30 }}><input type="checkbox" checked={selected.size === filtered.length && filtered.length > 0} onChange={() => selected.size === filtered.length ? selNone() : selAll()} /></th>
          <th style={th}>#</th><th style={th}>Page</th><th style={th}>Type</th><th style={th}>SEO Title</th><th style={th}>Meta Desc</th>
          <th style={{ ...th, textAlign: 'center' }}>JSON-LD</th><th style={{ ...th, textAlign: 'center' }}>Keywords</th><th style={{ ...th, textAlign: 'center' }}>Score</th><th style={{ ...th, textAlign: 'center' }}>Status</th><th style={{ ...th, textAlign: 'center' }}>Actions</th>
        </tr></thead>
        <tbody>{filtered.map((p: SitePage, i: number) => { const a = getAudit(p.path); const busy = auditingSlug === p.path; return (
          <tr key={p.path} style={{ borderBottom: '1px solid #f3f4f6', background: selected.has(p.path) ? '#f0fdf4' : undefined }}>
            <td style={td}><input type="checkbox" checked={selected.has(p.path)} onChange={() => toggleSel(p.path)} /></td>
            <td style={td}>{i + 1}</td>
            <td style={{ ...td, maxWidth: 180 }}><a href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', textDecoration: 'underline', fontSize: 'var(--text-xs)' }}>{p.name}</a><div style={{ fontSize: 'var(--text-xs)', color: '#9ca3af' }}>{p.path}</div></td>
            <td style={td}><span style={{ padding: '2px 8px', background: '#f0fdf4', color: '#166534', borderRadius: 6, fontSize: 'var(--text-xs)' }}>{p.type}</span></td>
            <td style={{ ...td, maxWidth: 200 }}><div style={{ fontSize: 'var(--text-xs)' }}>{p.title || '-'}</div>{p.title && <div style={{ fontSize: 'var(--text-xs)', color: p.title.length > 60 ? '#ef4444' : '#22c55e' }}>{p.title.length}ch</div>}</td>
            <td style={{ ...td, maxWidth: 180, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{p.metaDescription ? p.metaDescription.substring(0, 60) + '...' : <span style={{ color: '#ef4444' }}>missing</span>}{p.metaDescription && <div style={{ fontSize: 'var(--text-xs)', color: p.metaDescription.length > 160 ? '#ef4444' : '#22c55e' }}>{p.metaDescription.length}ch</div>}</td>
            <td style={{ ...td, textAlign: 'center' }}>{p.hasJsonLd ? <span style={{ color: '#22c55e', fontSize: 'var(--text-xs)' }}>{p.jsonLdTypes.join(', ')}</span> : <span style={{ color: '#ef4444', fontSize: 'var(--text-xs)' }}>missing</span>}</td>
            <td style={{ ...td, textAlign: 'center', fontSize: 'var(--text-xs)' }}>{p.keywords?.length || <span style={{ color: '#ef4444', fontSize: 'var(--text-xs)' }}>0</span>}</td>
            <td style={{ ...td, textAlign: 'center' }}>{a ? <><span style={{ color: '#ef4444', fontSize: 'var(--text-xs)' }}>{a.seoScoreBefore}</span><span style={{ color: '#9ca3af' }}>{' > '}</span><span style={{ color: '#22c55e', fontWeight: 700, fontSize: 'var(--text-xs)' }}>{a.seoScoreAfter}</span></> : '-'}</td>
            <td style={{ ...td, textAlign: 'center' }}>{a ? <StatusBadge status={a.status} /> : <span style={{ color: '#9ca3af', fontSize: 'var(--text-xs)' }}>-</span>}</td>
            <td style={{ ...td, textAlign: 'center' }}><div style={{ display: 'flex', gap: 3, justifyContent: 'center' }}>
              <button onClick={() => onCleanAudit(p.path, p.name, p.type)} disabled={busy || !!bulkRunning} title="Clean then Audit" style={{ ...btn, background: '#fef3c7' }}>Clean+Audit</button>
              <button onClick={() => onAudit(p.path, p.name, p.type)} disabled={busy || !!bulkRunning} style={{ ...btn, background: busy ? 'var(--border)' : 'var(--lime)' }}>{busy ? 'Running...' : 'Audit'}</button>
              {a && <button onClick={() => onViewAudit(a)} style={{ ...btn, background: '#f3f4f6' }}>View</button>}
            </div></td>
          </tr>); })}{filtered.length === 0 && <tr><td colSpan={11} style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No pages match filter.</td></tr>}</tbody>
      </table>
    </div>
    <div style={{ marginTop: 8, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{filtered.length} pages</div>
  </>);
}

// ═══════════════════════════════════════════════════════════════
// SYSTEM PAGES TAB — noindex monitoring + clean/audit like other tabs
// ═══════════════════════════════════════════════════════════════
function SystemPagesTab({ pages, auditingSlug, bulkRunning, onAudit, onCleanAudit, onViewAudit, getAudit, search, setSearch }: any) {
  const filtered = search ? pages.filter((p: SitePage) => { const q = search.toLowerCase(); return p.name.toLowerCase().includes(q) || p.path.toLowerCase().includes(q); }) : pages;
  return (<>
    <div className="card" style={{ padding: 16, marginBottom: 16, borderLeft: '4px solid #f59e0b' }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: '#92400e', marginBottom: 4 }}>System Pages — noindex by default</h3>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: 0, lineHeight: 1.6 }}>
        These pages should have <code style={{ background: '#f3f4f6', padding: '1px 4px', borderRadius: 3 }}>noindex, nofollow</code> meta robots tag. Monitor for accidental indexing.
      </p>
    </div>
    <div style={{ marginBottom: 10 }}>
      <input value={search} onChange={(e: any) => setSearch(e.target.value)} placeholder="🔍 Search system pages..." style={{ width: '100%', padding: '8px 14px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
    </div>
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)' }}>
        <thead><tr style={{ background: 'var(--bg-secondary)', borderBottom: '2px solid var(--border)' }}>
          <th style={th}>#</th><th style={th}>Page</th><th style={th}>Path</th><th style={{ ...th, textAlign: 'center' }}>Robots</th>
          <th style={{ ...th, textAlign: 'center' }}>Score</th><th style={{ ...th, textAlign: 'center' }}>Status</th><th style={{ ...th, textAlign: 'center' }}>Actions</th>
        </tr></thead>
        <tbody>{filtered.map((p: SitePage, i: number) => { const a = getAudit(p.path); const busy = auditingSlug === p.path; return (
          <tr key={p.path} style={{ borderBottom: '1px solid #f3f4f6' }}>
            <td style={td}>{i + 1}</td>
            <td style={{ ...td, fontWeight: 600 }}>{p.name}</td>
            <td style={{ ...td, fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{p.path}</td>
            <td style={{ ...td, textAlign: 'center' }}><span style={{ padding: '2px 8px', background: '#fef3c7', color: '#92400e', borderRadius: 6, fontSize: 'var(--text-xs)', fontWeight: 600 }}>noindex</span></td>
            <td style={{ ...td, textAlign: 'center' }}>{a ? <><span style={{ color: '#ef4444', fontSize: 'var(--text-xs)' }}>{a.seoScoreBefore}</span><span style={{ color: '#9ca3af' }}>{' > '}</span><span style={{ color: '#22c55e', fontWeight: 700, fontSize: 'var(--text-xs)' }}>{a.seoScoreAfter}</span></> : '-'}</td>
            <td style={{ ...td, textAlign: 'center' }}>{a ? <StatusBadge status={a.status} /> : <span style={{ color: '#9ca3af', fontSize: 'var(--text-xs)' }}>-</span>}</td>
            <td style={{ ...td, textAlign: 'center' }}><div style={{ display: 'flex', gap: 3, justifyContent: 'center' }}>
              <button onClick={() => onCleanAudit(p.path, p.name, 'system')} disabled={busy || !!bulkRunning} title="Clean then Audit" style={{ ...btn, background: '#fef3c7' }}>Clean+Audit</button>
              <button onClick={() => onAudit(p.path, p.name, 'system')} disabled={busy || !!bulkRunning} style={{ ...btn, background: busy ? 'var(--border)' : 'var(--lime)' }}>{busy ? 'Running...' : 'Audit'}</button>
              {a && <button onClick={() => onViewAudit(a)} style={{ ...btn, background: '#f3f4f6' }}>View</button>}
              <a href={p.url} target="_blank" rel="noopener noreferrer" style={{ ...btn, background: '#f3f4f6', textDecoration: 'none', color: '#374151', display: 'inline-flex', alignItems: 'center' }}>Open</a>
            </div></td>
          </tr>); })}</tbody>
      </table>
    </div>
    <div style={{ marginTop: 8, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{filtered.length} system pages</div>
    <div className="card" style={{ padding: 16, marginTop: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>System Pages SEO Rules</h3>
      <div style={{ display: 'grid', gap: 8, fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.6 }}>
        <div><span style={{ fontWeight: 600, color: '#374151' }}>Cart / Checkout:</span> noindex, nofollow. No JSON-LD. Canonical self-referencing.</div>
        <div><span style={{ fontWeight: 600, color: '#374151' }}>404 Page:</span> HTTP 404 status. No indexing. Custom design recommended.</div>
        <div><span style={{ fontWeight: 600, color: '#374151' }}>Login / Signup:</span> noindex. Prevent password pages from search.</div>
        <div><span style={{ fontWeight: 600, color: '#374151' }}>Members Area:</span> noindex, nofollow. All member pages behind auth.</div>
        <div><span style={{ fontWeight: 600, color: '#374151' }}>Order Pages:</span> noindex. Transactional pages with personal data.</div>
      </div>
    </div>
  </>);
}

// ═══════════════════════════════════════════════════════════════
// PRODUCT PAGES TAB — with clean+audit, bulk audit
// ═══════════════════════════════════════════════════════════════
function ProductPagesTab({ products, audits, auditingSlug, bulkRunning, onAudit, onCleanAudit, onBulkAudit, onViewAudit, getAudit, search, setSearch }: any) {
  const noSeoCount = products.filter((p: ProductPage) => !p.hasJsonLd).length;
  const [showNoSeo, setShowNoSeo] = useState(false);
  let filtered = showNoSeo ? products.filter((p: ProductPage) => !p.hasJsonLd) : products;
  if (search) { const q = search.toLowerCase(); filtered = filtered.filter((p: ProductPage) => p.name.toLowerCase().includes(q) || (p.slug || '').toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q)); }
  return (<>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 16 }}>
      <StatCard label="Total Products" value={products.length} />
      <StatCard label="With JSON-LD" value={products.filter((p: ProductPage) => p.hasJsonLd).length} />
      <StatCard label="Missing Schema" value={noSeoCount} />
      <StatCard label="In Stock" value={products.filter((p: ProductPage) => p.inStock).length} />
    </div>
    {/* Search box */}
    <div style={{ marginBottom: 10 }}>
      <input value={search} onChange={(e: any) => setSearch(e.target.value)} placeholder="🔍 Search products by name, slug..." style={{ width: '100%', padding: '8px 14px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
    </div>
    {/* No SEO filter */}
    <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
      <button onClick={() => setShowNoSeo(false)} style={{ ...btn, background: !showNoSeo ? 'var(--lime)' : '#f3f4f6', fontWeight: !showNoSeo ? 600 : 400 }}>All ({products.length})</button>
      <button onClick={() => setShowNoSeo(true)} style={{ ...btn, background: showNoSeo ? '#fee2e2' : '#f3f4f6', color: showNoSeo ? '#991b1b' : 'var(--text-muted)', fontWeight: showNoSeo ? 600 : 400 }}>No SEO ({noSeoCount})</button>
    </div>
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)' }}>
        <thead><tr style={{ background: 'var(--bg-secondary)', borderBottom: '2px solid var(--border)' }}>
          <th style={th}>#</th><th style={th}>Product</th><th style={th}>Price</th><th style={th}>Stock</th>
          <th style={{ ...th, textAlign: 'center' }}>JSON-LD</th><th style={{ ...th, textAlign: 'center' }}>Score</th><th style={{ ...th, textAlign: 'center' }}>Status</th><th style={{ ...th, textAlign: 'center' }}>Actions</th>
        </tr></thead>
        <tbody>{filtered.map((p: ProductPage, i: number) => { const slug = p.slug || p.id; const productPath = productAuditPath( p ); const a = getAudit(productPath); const busy = auditingSlug === productPath; return (
          <tr key={p.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
            <td style={td}>{i + 1}</td>
            <td style={{ ...td, maxWidth: 220 }}><div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {p.image && <img src={p.image} alt="" style={{ width: 32, height: 32, borderRadius: 6, objectFit: 'cover' }} />}
              <div><a href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', textDecoration: 'underline', fontSize: 'var(--text-xs)' }}>{p.name}</a><div style={{ fontSize: 'var(--text-xs)', color: '#9ca3af' }}>/{p.slug}</div></div>
            </div></td>
            <td style={{ ...td, fontWeight: 600 }}>{p.price || `${p.currency} ${p.priceAmount}`}</td>
            <td style={td}><span style={{ padding: '2px 8px', borderRadius: 6, fontSize: 'var(--text-xs)', fontWeight: 600, background: p.inStock ? '#dcfce7' : '#fee2e2', color: p.inStock ? '#166534' : '#991b1b' }}>{p.inStock ? 'In Stock' : 'Out'}</span></td>
            <td style={{ ...td, textAlign: 'center' }}>{p.hasJsonLd ? <span style={{ color: '#22c55e', fontSize: 'var(--text-xs)' }}>{p.jsonLdType || 'Product'}</span> : <span style={{ color: '#ef4444', fontSize: 'var(--text-xs)' }}>missing</span>}</td>
            <td style={{ ...td, textAlign: 'center' }}>{a ? <><span style={{ color: '#ef4444', fontSize: 'var(--text-xs)' }}>{a.seoScoreBefore}</span><span style={{ color: '#9ca3af' }}>{' > '}</span><span style={{ color: '#22c55e', fontWeight: 700, fontSize: 'var(--text-xs)' }}>{a.seoScoreAfter}</span></> : '-'}</td>
            <td style={{ ...td, textAlign: 'center' }}>{a ? <StatusBadge status={a.status} /> : <span style={{ color: '#9ca3af', fontSize: 'var(--text-xs)' }}>-</span>}</td>
            <td style={{ ...td, textAlign: 'center' }}><div style={{ display: 'flex', gap: 3, justifyContent: 'center' }}>
              <button onClick={() => onCleanAudit(productPath, p.name, 'product')} disabled={busy || !!bulkRunning} title="Clean then Audit" style={{ ...btn, background: '#fef3c7' }}>Clean+Audit</button>
              <button onClick={() => onAudit(productPath, p.name, 'product')} disabled={busy || !!bulkRunning} style={{ ...btn, background: busy ? 'var(--border)' : 'var(--lime)' }}>{busy ? 'Running...' : 'Audit'}</button>
              {a && <button onClick={() => onViewAudit(a)} style={{ ...btn, background: '#f3f4f6' }}>View</button>}
            </div></td>
          </tr>); })}{filtered.length === 0 && <tr><td colSpan={8} style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No products match filter.</td></tr>}</tbody>
      </table>
    </div>
    <div style={{ marginTop: 8, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{filtered.length} products</div>
    {filtered.length > 0 && <div style={{ marginTop: 12 }}>
      <button onClick={() => onBulkAudit(filtered.map((p: ProductPage) => ({ path: productAuditPath( p ), name: p.name, type: 'product' })))} disabled={!!bulkRunning} style={{ ...btn, background: 'var(--lime)', fontWeight: 600, padding: '6px 16px' }}>{bulkRunning === 'audit' ? 'Auditing...' : `Audit All ${filtered.length} Products`}</button>
    </div>}
    <div className="card" style={{ padding: 16, marginTop: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>Product Page SEO Standard</h3>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: 0, lineHeight: 1.8 }}>
        Each product needs: Product JSON-LD (name, price, availability, image, brand, review).<br />
        Also: BreadcrumbList, AggregateRating (if reviews), Offer schema.<br />
        Meta title: &quot;Product Name — Price | WECARE.DIGITAL&quot; (max 60ch)<br />
        Meta description: 150-160ch with product benefit + CTA.
      </p>
    </div>
  </>);
}

// ═══════════════════════════════════════════════════════════════
// NEW PAGES TAB — add custom URLs for audit
// ═══════════════════════════════════════════════════════════════
function NewPagesTab({ customPages, newPageUrl, newPageName, setNewPageUrl, setNewPageName, addCustomPage, auditingSlug, onAudit, onCleanAudit, onRemove, search, setSearch }: any) {
  const filtered = search ? customPages.filter((p: SitePage) => { const q = search.toLowerCase(); return p.name.toLowerCase().includes(q) || p.path.toLowerCase().includes(q); }) : customPages;
  return (<>
    <div className="card" style={{ padding: 20, marginBottom: 16 }}>
      <h3 style={{ fontSize: 'var(--text-md)', fontWeight: 600, marginBottom: 12 }}>Add New Page for SEO Audit</h3>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 12 }}>Add any new page URL to audit its SEO — landing pages, campaign pages, newly created pages.</p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 12, alignItems: 'end' }}>
        <div>
          <label style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Page URL Path</label>
          <input value={newPageUrl} onChange={(e: any) => setNewPageUrl(e.target.value)} placeholder="/new-page-path" style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
        </div>
        <div>
          <label style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Page Name (optional)</label>
          <input value={newPageName} onChange={(e: any) => setNewPageName(e.target.value)} placeholder="My New Page" style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
        </div>
        <button onClick={addCustomPage} disabled={!newPageUrl.trim()} style={{ ...btn, background: 'var(--lime)', fontWeight: 600, padding: '8px 16px', fontSize: 'var(--text-sm)' }}>Add Page</button>
      </div>
    </div>
    {customPages.length > 0 ? (<>
      {/* Search box */}
      <div style={{ marginBottom: 10 }}>
        <input value={search} onChange={(e: any) => setSearch(e.target.value)} placeholder="🔍 Search custom pages..." style={{ width: '100%', padding: '8px 14px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
      </div>
      <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)' }}>
        <thead><tr style={{ background: 'var(--bg-secondary)', borderBottom: '2px solid var(--border)' }}>
          <th style={th}>#</th><th style={th}>Page</th><th style={th}>Path</th><th style={{ ...th, textAlign: 'center' }}>Actions</th>
        </tr></thead>
        <tbody>{filtered.map((p: SitePage, i: number) => { const busy = auditingSlug === p.path; return (
          <tr key={p.path} style={{ borderBottom: '1px solid #f3f4f6' }}>
            <td style={td}>{i + 1}</td>
            <td style={{ ...td, fontWeight: 600 }}><a href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', textDecoration: 'underline' }}>{p.name}</a></td>
            <td style={{ ...td, fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{p.path}</td>
            <td style={{ ...td, textAlign: 'center' }}><div style={{ display: 'flex', gap: 3, justifyContent: 'center' }}>
              <button onClick={() => onCleanAudit(p.path, p.name, 'custom')} disabled={busy} title="Clean then Audit" style={{ ...btn, background: '#fef3c7' }}>Clean+Audit</button>
              <button onClick={() => onAudit(p.path, p.name, 'custom')} disabled={busy} style={{ ...btn, background: busy ? 'var(--border)' : 'var(--lime)' }}>{busy ? 'Running...' : 'Audit'}</button>
              <button onClick={() => onRemove(p.path)} style={{ ...btn, background: '#fee2e2', color: '#991b1b' }}>Remove</button>
            </div></td>
          </tr>); })}</tbody>
      </table>
    </div></>) : <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No custom pages added yet.</div>}
  </>);
}

// ═══════════════════════════════════════════════════════════════
// AUDIT DETAIL — Full deep SEO: meta tags, OG, Twitter, canonical,
// robots, keywords, JSON-LD, FAQ schema, internal links, image alt,
// score breakdown, approve/reject/apply
// ═══════════════════════════════════════════════════════════════
function AuditDetail({ audit, audits, onSelect, onAction }: { audit: PageAudit | null; audits: PageAudit[]; onSelect: (a: PageAudit) => void; onAction: (id: string, action: string) => void }) {
  if (!audit) return (<div>{audits.length === 0 ? <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No audits yet. Run an audit from any page tab.</div> :
    <div style={{ display: 'grid', gap: 8 }}>{audits.slice(0, 30).map(a => (
      <button key={a.id} onClick={() => onSelect(a)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: '#fff', border: '1.5px solid var(--border)', borderRadius: 10, cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit', width: '100%' }}>
        <div><div style={{ fontSize: 'var(--text-md)', fontWeight: 600 }}>{a.blogTitle}</div><div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>/{a.blogSlug} — <span style={{ padding: '1px 6px', background: '#f0fdf4', borderRadius: 4, fontSize: 'var(--text-xs)' }}>{a.pageType}</span> — {new Date(a.createdAt).toLocaleString()} — <StatusBadge status={a.status} /></div></div>
        <div><span style={{ color: '#ef4444' }}>{a.seoScoreBefore}</span> {'>'} <span style={{ color: '#22c55e', fontWeight: 700 }}>{a.seoScoreAfter}</span></div>
      </button>))}</div>}</div>);

  const ai = audit.fullAiResponse || {};
  const pageUrl = `${BASE}${audit.blogSlug.startsWith('/') ? '' : '/'}${audit.blogSlug}`;
  const cleanTitle = audit.suggestedSeoTitle?.replace(' | WECARE.DIGITAL', '') || '';
  const ogType = audit.pageType === 'product' ? 'product' : audit.pageType === 'blog_hub' ? 'blog' : 'website';

  // Build comprehensive meta tags list
  const metaTags: [string, string][] = [
    ['title', audit.suggestedSeoTitle || ''],
    ['description', audit.suggestedMetaDescription || ''],
    ['keywords', [audit.focusKeyword, ...(audit.secondaryKeywords || [])].filter(Boolean).join(', ')],
    ['robots', audit.pageType === 'system' ? 'noindex, nofollow' : 'index, follow, max-image-preview:large'],
    ['canonical', pageUrl],
    ['og:title', cleanTitle],
    ['og:description', audit.suggestedMetaDescription || ''],
    ['og:url', pageUrl],
    ['og:type', ogType],
    ['og:site_name', 'WECARE.DIGITAL'],
    ['og:locale', 'en_IN'],
    ['og:image', ai.jsonLd?.image?.[0] || ai.jsonLd?.blogPosting?.image?.[0] || `${BASE}/logo.png`],
    ['twitter:card', 'summary_large_image'],
    ['twitter:title', cleanTitle],
    ['twitter:description', audit.suggestedMetaDescription || ''],
    ['twitter:site', '@wecaredigital'],
    ['author', 'WECARE.DIGITAL'],
  ];
  if (audit.pageType === 'product') {
    metaTags.push(['product:price:amount', ai.price || '']);
    metaTags.push(['product:price:currency', 'INR']);
    metaTags.push(['product:availability', 'in stock']);
  }

  return (<div>
    {/* Header */}
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
      <div>
        <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 700, margin: 0 }}>{audit.blogTitle}</h2>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>/{audit.blogSlug} — <span style={{ padding: '1px 6px', background: '#f0fdf4', borderRadius: 4, fontSize: 'var(--text-xs)' }}>{audit.pageType}</span> — {new Date(audit.createdAt).toLocaleString()} — {audit.status}{audit.aiModel && <span style={{ marginLeft: 8, fontSize: 'var(--text-xs)', color: '#9ca3af' }}>({audit.aiModel})</span>}</div>
      </div>
      <button onClick={() => onSelect(null as any)} style={{ ...btn, background: '#f3f4f6', padding: '6px 14px' }}>← Back</button>
    </div>

    {/* Score Card + Actions */}
    <div className="card" style={{ padding: 16, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
      <div style={{ textAlign: 'center' }}><div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>BEFORE</div><div style={{ fontSize: 'var(--h1)', fontWeight: 800, color: '#ef4444' }}>{audit.seoScoreBefore}</div></div>
      <div style={{ fontSize: 'var(--text-3xl)', color: '#9ca3af' }}>{'>'}</div>
      <div style={{ textAlign: 'center' }}><div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>AFTER</div><div style={{ fontSize: 'var(--h1)', fontWeight: 800, color: '#22c55e' }}>{audit.seoScoreAfter}</div></div>
      <div style={{ flex: 1 }} />
      {audit.status === 'pending_review' && <div style={{ display: 'flex', gap: 8 }}><button onClick={() => onAction(audit.id, 'approve')} style={{ ...btn, background: 'var(--lime)', fontWeight: 600, padding: '6px 16px' }}>Approve</button><button onClick={() => onAction(audit.id, 'reject')} style={{ ...btn, background: '#fee2e2', padding: '6px 16px' }}>Reject</button></div>}
      {audit.status === 'approved' && <span style={{ padding: '6px 14px', background: '#dbeafe', color: '#1e40af', borderRadius: 8, fontSize: 'var(--text-xs)', fontWeight: 600 }}>Approved — apply is available for blog posts only</span>}
      {audit.status === 'applied' && <span style={{ padding: '6px 14px', background: '#dcfce7', color: '#166534', borderRadius: 8, fontSize: 'var(--text-xs)', fontWeight: 600 }}>Applied {audit.appliedAt ? new Date(audit.appliedAt).toLocaleString() : ''}</span>}
    </div>

    {/* Current vs AI Suggested */}
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
      <div className="card" style={{ padding: 16 }}><h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: '#ef4444', marginBottom: 12 }}>Current</h3><CF label="SEO Title" value={audit.currentSeoTitle} max={60} /><CF label="Meta Description" value={audit.currentMetaDescription} max={160} /></div>
      <div className="card" style={{ padding: 16 }}><h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: '#22c55e', marginBottom: 12 }}>AI Suggested</h3><CF label="SEO Title" value={audit.suggestedSeoTitle} max={60} /><CF label="Meta Description" value={audit.suggestedMetaDescription} max={160} /></div>
    </div>

    {/* Keywords — focus + secondary */}
    <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>🔑 Keywords (1 focus + {audit.secondaryKeywords?.length || 0} secondary)</h3>
      <div style={{ marginBottom: 8 }}><span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Focus: </span><span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--accent)', padding: '2px 10px', background: 'var(--lime)', borderRadius: 6 }}>{audit.focusKeyword}</span></div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{audit.secondaryKeywords?.map((kw: string, i: number) => <span key={i} style={{ padding: '2px 8px', background: '#f0fdf4', color: '#166534', borderRadius: 6, fontSize: 'var(--text-xs)' }}>{kw}</span>)}</div>
    </div>

    {/* Meta Tags — full OG, Twitter, robots, canonical */}
    <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>🏷️ Meta Tags (rendered by the public frontend where supported)</h3>
      <div style={{ display: 'grid', gap: 4 }}>{metaTags.map(([prop, val], i) => (
        <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 8px', background: i % 2 === 0 ? 'var(--bg-secondary)' : '#fff', borderRadius: 4, fontSize: 'var(--text-xs)' }}>
          <span style={{ color: 'var(--text-muted)', minWidth: 160, fontFamily: 'monospace', flexShrink: 0 }}>{prop}</span>
          <span style={{ color: 'var(--text)', flex: 1, wordBreak: 'break-word' }}>{val || <span style={{ color: '#ef4444' }}>(empty)</span>}</span>
        </div>
      ))}</div>
    </div>

    {/* Internal Link Suggestions */}
    {audit.internalLinkSuggestions?.length > 0 && <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>🔗 Internal Links ({audit.internalLinkSuggestions.length})</h3>
      {audit.internalLinkSuggestions.map((l: any, i: number) => <div key={i} style={{ padding: '4px 0', fontSize: 'var(--text-xs)' }}><span style={{ fontWeight: 600 }}>{l.text}</span> <a href={l.url} target="_blank" rel="noopener noreferrer" style={{ color: '#2563eb' }}>{l.url}</a> <span style={{ color: '#9ca3af', fontSize: 'var(--text-xs)' }}>({l.reason})</span></div>)}
    </div>}

    {/* Image Alt Suggestions */}
    {audit.imageAltSuggestions?.length > 0 && <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>🖼️ Image Alt Text Suggestions ({audit.imageAltSuggestions.length})</h3>
      {audit.imageAltSuggestions.map((img: any, i: number) => <div key={i} style={{ padding: '4px 0', fontSize: 'var(--text-xs)', display: 'flex', gap: 8 }}><span style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: 'var(--text-xs)' }}>{img.src?.substring(0, 40)}...</span><span style={{ color: '#166534', fontWeight: 600 }}>{img.suggestedAlt}</span></div>)}
    </div>}

    {/* Warnings */}
    {audit.warnings?.length > 0 && <div className="card" style={{ padding: 16, marginBottom: 16, borderLeft: '4px solid #f59e0b' }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: '#92400e', marginBottom: 8 }}>⚠️ Warnings ({audit.warnings.length})</h3>
      {audit.warnings.map((w: string, i: number) => <div key={i} style={{ fontSize: 'var(--text-xs)', color: '#92400e', padding: '2px 0' }}>- {w}</div>)}
    </div>}

    {/* Score Breakdown */}
    {audit.scoreBreakdown && <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>📊 Score Breakdown</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
        {Object.entries(audit.scoreBreakdown).map(([k, v]: any) => <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', background: 'var(--bg-secondary)', borderRadius: 6, fontSize: 'var(--text-xs)' }}>
          <span style={{ color: 'var(--text-muted)' }}>{k}</span><span><span style={{ color: '#ef4444' }}>{v.before}</span>{' > '}<span style={{ color: '#22c55e', fontWeight: 600 }}>{v.after}</span>/{v.max}</span>
        </div>)}
      </div>
    </div>}

    {/* JSON-LD Structured Data */}
    {audit.suggestedJsonLd && <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>🏗️ JSON-LD Structured Data</h3>
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 8 }}>
        Types: {Array.isArray(audit.suggestedJsonLd) ? audit.suggestedJsonLd.map((s: any) => s['@type']).filter(Boolean).join(', ') : (audit.suggestedJsonLd['@type'] || Object.keys(audit.suggestedJsonLd).filter(k => k !== '@context').join(', '))}
      </div>
      <pre style={{ background: '#0f1117', color: '#a3e635', padding: 16, borderRadius: 8, fontSize: 'var(--text-xs)', maxHeight: 400, overflowY: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(audit.suggestedJsonLd, null, 2)}</pre>
    </div>}

    {/* FAQ Schema (if present in AI response) */}
    {(ai.faqSchema || ai.jsonLd?.faqPage) && <div className="card" style={{ padding: 16, marginBottom: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>❓ FAQ Schema (FAQPage)</h3>
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 8 }}>
        {(ai.faqSchema?.mainEntity || ai.jsonLd?.faqPage?.mainEntity || []).length} Q&A pairs — will be injected as FAQPage JSON-LD
      </div>
      {(ai.faqSchema?.mainEntity || ai.jsonLd?.faqPage?.mainEntity || []).map((qa: any, i: number) => (
        <div key={i} style={{ padding: '8px 12px', background: i % 2 === 0 ? 'var(--bg-secondary)' : '#fff', borderRadius: 6, marginBottom: 4 }}>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--accent)' }}>Q: {qa.name || qa.question}</div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>A: {(qa.acceptedAnswer?.text || qa.answer || '').substring(0, 200)}{(qa.acceptedAnswer?.text || qa.answer || '').length > 200 ? '...' : ''}</div>
        </div>
      ))}
      <pre style={{ background: '#0f1117', color: '#a3e635', padding: 12, borderRadius: 8, fontSize: 'var(--text-xs)', maxHeight: 200, overflowY: 'auto', whiteSpace: 'pre-wrap', marginTop: 8 }}>{JSON.stringify(ai.faqSchema || ai.jsonLd?.faqPage, null, 2)}</pre>
    </div>}
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// BLOG CREATOR — AI-powered blog post creation (same as blog-manager)
// ═══════════════════════════════════════════════════════════════
function BlogCreator({ addLog }: { addLog: (m: string) => void }) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [tags, setTags] = useState('');
  const [hashtags, setHashtags] = useState('');
  const [categories, setCategories] = useState<any[]>([]);
  const [availableTags, setAvailableTags] = useState<any[]>([]);
  const [category, setCategory] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (loaded) return;
    seoToolsFetch('blog-create').then(r => r.json()).then(d => {
      if (d.ok) { setCategories(d.categories || []); setAvailableTags(d.tags || []); }
    }).catch(() => {}); setLoaded(true);
  }, [loaded]);

  const publishPost = async () => {
    if (!title.trim() || !content.trim()) { addLog('Title and content required'); return; }
    setPublishing(true); addLog(`Saving published post "${title}" to AWS...`);
    try {
      const body: any = { title: title.trim(), content: content.trim() };
      if (category.trim()) body.category = category.trim();
      if (tags.trim()) body.tagLabels = tags.split(',').map(t => t.trim()).filter(Boolean);
      if (hashtags.trim()) body.hashtags = hashtags.split(',').map(h => h.trim()).filter(Boolean);
      const d = await (await seoToolsFetch('blog-create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
      if (d.ok) { addLog(`Published in AWS: ${d.slug} (${d.postId})`); if (d.rebuildRequired) addLog('Amplify rebuild required before this new static URL is public.'); setTitle(''); setContent(''); setTags(''); setHashtags(''); setCategory(''); }
      else addLog(`Failed: ${d.error}`);
    } catch (e: any) { addLog(e.message); }
    setPublishing(false);
  };

  const wordCount = content.split(/\s+/).filter(Boolean).length;

  return (<div style={{ maxWidth: 800 }}>
    <h2 style={{ fontSize: 'var(--text-base)', fontWeight: 700, marginBottom: 16 }}>✍️ Create Blog Post</h2>
    <div className="card" style={{ padding: 20, marginBottom: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Title</label>
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Blog post title..." style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-md)', fontFamily: 'inherit' }} />
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Content</label>
        <div style={{ fontSize: 'var(--text-xs)', color: '#9ca3af', marginBottom: 4 }}>Use ## for H2, ### for H3. Each line = paragraph. Paste from PDF/Word.</div>
        <textarea value={content} onChange={e => setContent(e.target.value)} placeholder={'Paste blog content here...\n\n## Section Heading\n\nParagraph text goes here...'} rows={15} style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'Georgia, serif', lineHeight: 1.8, resize: 'vertical' }} />
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>{content.length} chars | {wordCount} words {wordCount < 300 && wordCount > 0 ? '(min 300 recommended)' : ''}</div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <div>
          <label style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Category</label>
          <input value={category} onChange={e => setCategory(e.target.value)} list="pages-blog-category-options" placeholder="e.g. Insights" style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
          <datalist id="pages-blog-category-options">{categories.map((c: any) => <option key={c.id} value={c.label} />)}</datalist>
        </div>
        <div>
          <label style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Tags (comma-separated)</label>
          <input value={tags} onChange={e => setTags(e.target.value)} placeholder="philosophy, self-inquiry, relationships" style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
          {availableTags.length > 0 && <div style={{ fontSize: 'var(--text-xs)', color: '#9ca3af', marginTop: 4 }}>Existing: {availableTags.slice(0, 10).map((t: any) => t.label).join(', ')}{availableTags.length > 10 ? ` +${availableTags.length - 10} more` : ''}</div>}
        </div>
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Hashtags (comma-separated)</label>
        <input value={hashtags} onChange={e => setHashtags(e.target.value)} placeholder="Stand, ConsciousChoice, Integrity, Swdhya" style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 'var(--text-sm)', fontFamily: 'inherit' }} />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={publishPost} disabled={publishing || !title.trim() || !content.trim()} style={{ ...btn, background: 'var(--lime)', fontWeight: 600, padding: '8px 20px', fontSize: 'var(--text-sm)' }}>{publishing ? 'Publishing...' : 'Publish'}</button>
        <button onClick={() => { setTitle(''); setContent(''); setTags(''); setHashtags(''); setCategory(''); }} style={{ ...btn, background: '#f3f4f6', padding: '8px 20px', fontSize: 'var(--text-sm)' }}>Clear</button>
      </div>
    </div>
    <div className="card" style={{ padding: 16 }}>
      <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>Formatting Guide</h3>
      <pre style={{ background: 'var(--bg-secondary)', padding: 12, borderRadius: 8, fontSize: 'var(--text-xs)', lineHeight: 1.8, margin: 0, whiteSpace: 'pre-wrap' }}>{`# Heading 1 (rarely used — title is H1)
## Heading 2 (section headings)
### Heading 3 (sub-sections)

Regular text becomes a paragraph.
Each line = one paragraph.
Empty lines are skipped.

Style: WECARE.DIGITAL Amplify article layout
Author: current Admin user
After publishing: go to Blog SEO Manager > Clean+Audit for SEO.
A new slug becomes public after the next Amplify static build.`}</pre>
    </div>
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// LOGS VIEW
// ═══════════════════════════════════════════════════════════════
function LogsView({ logs }: { logs: any[] }) {
  if (!logs.length) return <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No AI logs yet.</div>;
  return (<div style={{ overflowX: 'auto' }}>
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)' }}>
      <thead><tr style={{ background: 'var(--bg-secondary)', borderBottom: '2px solid var(--border)' }}>
        <th style={th}>Time</th><th style={th}>Page</th><th style={th}>Type</th><th style={th}>Model</th>
        <th style={{ ...th, textAlign: 'center' }}>Tokens</th><th style={{ ...th, textAlign: 'center' }}>Cost</th><th style={{ ...th, textAlign: 'center' }}>Status</th>
      </tr></thead>
      <tbody>{logs.slice().reverse().map((l, i) => (
        <tr key={i} style={{ borderBottom: '1px solid #f3f4f6' }}>
          <td style={td}>{new Date(l.createdAt).toLocaleString()}</td>
          <td style={td}>{l.blogSlug}</td>
          <td style={td}><span style={{ padding: '2px 6px', background: '#f0fdf4', borderRadius: 4, fontSize: 'var(--text-xs)' }}>{l.pageType || 'blog'}</span></td>
          <td style={{ ...td, fontSize: 'var(--text-xs)' }}>{l.model?.split('.').pop()?.substring(0, 25)}</td>
          <td style={{ ...td, textAlign: 'center' }}>{l.inputTokens}+{l.outputTokens}</td>
          <td style={{ ...td, textAlign: 'center', fontWeight: 600 }}>${l.costEstimate}</td>
          <td style={{ ...td, textAlign: 'center', color: l.status === 'success' ? '#22c55e' : '#ef4444' }}>{l.status}{l.errorMessage && <div style={{ fontSize: 'var(--text-xs)' }}>{l.errorMessage}</div>}</td>
        </tr>
      ))}</tbody>
    </table>
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// SHARED COMPONENTS
// ═══════════════════════════════════════════════════════════════
function CF({ label, value, max }: { label: string; value: string; max: number }) {
  const len = value?.length || 0;
  return (<div style={{ marginBottom: 12 }}>
    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>{label}</div>
    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text)', lineHeight: 1.5 }}>{value || '(empty)'}</div>
    {value && <div style={{ fontSize: 'var(--text-xs)', color: len > max ? '#ef4444' : '#22c55e', marginTop: 2 }}>{len}/{max} {len > max ? 'over limit' : 'ok'}</div>}
  </div>);
}

function StatusBadge({ status }: { status: string }) {
  const bg = status === 'applied' ? '#dcfce7' : status === 'approved' ? '#dbeafe' : status === 'pending_review' ? '#fef3c7' : '#f3f4f6';
  const color = status === 'applied' ? '#166534' : status === 'approved' ? '#1e40af' : status === 'pending_review' ? '#92400e' : 'var(--text-muted)';
  return <span style={{ padding: '2px 8px', borderRadius: 6, fontSize: 'var(--text-xs)', fontWeight: 600, background: bg, color }}>{status.replace('_', ' ')}</span>;
}

function StatCard({ label, value }: { label: string; value: any }) {
  return (
    <div style={{ background: '#fff', border: '1.5px solid var(--border)', borderRadius: 13, padding: '16px 20px' }}>
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
      <div style={{ fontSize: 'var(--text-3xl)', fontWeight: 700, marginTop: 4, color: 'var(--accent)' }}>{value ?? '—'}</div>
    </div>
  );
}

export default PagesManager;
