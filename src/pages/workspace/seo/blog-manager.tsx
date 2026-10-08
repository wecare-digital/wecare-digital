/**
 * SEO Autopilot — AI-Powered SEO Dashboard
 * Tabs: Posts | Audit | Logs | Blog Creator | Instructions
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
// Moved out of src/pages/. It is a content COMPONENT, but sitting under pages/
// meant Next routed it as [retired public path]/InstructionsContent - a 292-line chrome-less page
// nobody intended to publish.
import InstructionsContent from '../../../components/seo/InstructionsContent';
import { useConfirmDanger } from '../../../components/wa';
import { seoToolsFetch } from '../../../api/seo';

interface PageProps { signOut?: () => void; user?: any; }
interface BlogPost {
  id: string; title: string; slug: string; excerpt: string; url: string;
  seoTitle: string; metaDescription: string; focusKeyword: string; keywords: string[];
  jsonLdCount: number; hasCustomSeo: boolean; tagCount: number;
  publishedDate: string; modifiedDate: string; coverImage: string;
}
interface AuditRecord {
  id: string; blogSlug: string; blogTitle: string;
  currentSeoTitle: string; suggestedSeoTitle: string;
  currentMetaDescription: string; suggestedMetaDescription: string;
  focusKeyword: string; secondaryKeywords: string[];
  suggestedJsonLd: any; internalLinkSuggestions: any[]; imageAltSuggestions: any[];
  seoScoreBefore: number; seoScoreAfter: number; scoreBreakdown: any;
  warnings: string[]; fullAiResponse: any; aiModel: string;
  status: string; createdAt: string; appliedAt?: string;
}
type Tab = 'posts' | 'audit' | 'logs' | 'create' | 'instructions';
type Filter = 'all' | 'pending' | 'audited' | 'approved' | 'applied' | 'noseo';
const th: React.CSSProperties = { padding: '8px 10px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#6b7280' };
const td: React.CSSProperties = { padding: '6px 10px' };
const btn: React.CSSProperties = { padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit' };

const BlogSeoManager: React.FC<PageProps> = ({ signOut, user }) => {
  const confirmDanger = useConfirmDanger();
  const [tab, setTab] = useState<Tab>('posts');
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [audits, setAudits] = useState<AuditRecord[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [auditingSlug, setAuditingSlug] = useState<string | null>(null);
  const [bulkRunning, setBulkRunning] = useState<string | null>(null);
  const [selectedAudit, setSelectedAudit] = useState<AuditRecord | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [log, setLog] = useState<string[]>([]);
  const addLog = (m: string) => setLog(p => [...p, `[${new Date().toLocaleTimeString()}] ${m}`]);

  const fetchPosts = useCallback(async () => {
    setLoading(true); addLog('Fetching posts...');
    try { const r = await seoToolsFetch('blog-posts'); const d = await r.json(); if (d.ok) { setPosts(d.posts); addLog(`${d.total} posts loaded`); } else addLog(`Error: ${d.error}`); }
    catch (e: any) { addLog(e.message); } setLoading(false);
  }, []);
  const fetchAudits = useCallback(async () => {
    try { const d = await (await seoToolsFetch('seo-logs?type=audits')).json(); if (d.ok) setAudits(d.audits || []); } catch {}
  }, []);
  const fetchLogs = useCallback(async () => {
    try { const d = await (await seoToolsFetch('seo-logs?type=logs')).json(); if (d.ok) setLogs(d.logs || []); } catch {}
  }, []);
  useEffect(() => { fetchPosts(); fetchAudits(); }, [fetchPosts, fetchAudits]);

  const getAudit = (slug: string) => audits.filter(a => a.blogSlug === slug).sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt))[0];

  const cleanPost = async (slug: string) => {
    addLog(`Cleaning "${slug}"...`);
    try { const d = await (await seoToolsFetch('seo-clean', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug }) })).json();
      if (d.ok) addLog(`Cleaned: ${d.cleaned.tagsRemoved} tags removed`); else addLog(`Clean failed: ${d.error}`);
    } catch (e: any) { addLog(e.message); }
  };
  const runAudit = async (slug: string) => {
    setAuditingSlug(slug); addLog(`Auditing "${slug}"...`);
    try { const d = await (await seoToolsFetch('ai-seo-audit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug }) })).json();
      if (d.ok) { addLog(`Done: ${d.audit.seoScoreBefore} > ${d.audit.seoScoreAfter} | $${d.log.costEstimate}`); await fetchAudits(); setSelectedAudit(d.audit); setTab('audit'); }
      else addLog(`Failed: ${d.error}`);
    } catch (e: any) { addLog(e.message); } setAuditingSlug(null);
  };
  const cleanAndAudit = async (slug: string) => { await cleanPost(slug); await runAudit(slug); };
  const handleAction = async (id: string, action: string) => {
    addLog(`${action} ${id.substring(0, 20)}...`);
    try { const d = await (await seoToolsFetch('seo-approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auditId: id, action }) })).json();
      if (d.ok) { addLog(`${action} done${d.applied ? ' - saved to AWS post' : ''}`); await fetchAudits(); if (selectedAudit?.id === id) setSelectedAudit(d.audit); }
      else addLog(d.error);
    } catch (e: any) { addLog(e.message); }
  };
  const bulkClean = async (slugs: string[]) => {
    setBulkRunning('clean'); addLog(`Bulk clean ${slugs.length} posts...`);
    for (const s of slugs) { await cleanPost(s); await new Promise(r => setTimeout(r, 2000)); }
    addLog('Bulk clean done'); await fetchPosts(); setBulkRunning(null);
  };
  const bulkAudit = async (slugs: string[]) => {
    setBulkRunning('audit'); let ok = 0;
    for (const s of slugs) {
      addLog(`Auditing ${ok+1}/${slugs.length}: ${s}`);
      try { const d = await (await seoToolsFetch('ai-seo-audit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug: s }) })).json();
        if (d.ok) ok++; } catch {} await new Promise(r => setTimeout(r, 1000));
    }
    addLog(`Bulk audit done: ${ok}/${slugs.length}`); await fetchAudits(); setBulkRunning(null);
  };
  const bulkApprove = async (ids: string[]) => {
    setBulkRunning('approve'); let ok = 0;
    for (const id of ids) { try { const d = await (await seoToolsFetch('seo-approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auditId: id, action: 'approve' }) })).json(); if (d.ok) ok++; } catch {} }
    addLog(`Bulk approve: ${ok}/${ids.length}`); await fetchAudits(); setBulkRunning(null);
  };
  const bulkApply = async (ids: string[]) => {
    setBulkRunning('apply'); let ok = 0;
    for (const id of ids) { try { const d = await (await seoToolsFetch('seo-approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auditId: id, action: 'apply' }) })).json(); if (d.ok) ok++; } catch {} await new Promise(r => setTimeout(r, 2000)); }
    addLog(`Bulk apply: ${ok}/${ids.length}`); await fetchAudits(); setBulkRunning(null);
  };

  const toggleSel = (s: string) => setSelected(p => { const n = new Set(p); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const selAll = () => setSelected(new Set(filtered.map(p => p.slug)));
  const selNone = () => setSelected(new Set());
  const filtered = posts.filter(p => {
    // search filter
    if (search) { const q = search.toLowerCase(); if (!p.title.toLowerCase().includes(q) && !p.slug.toLowerCase().includes(q) && !(p.seoTitle || '').toLowerCase().includes(q) && !(p.focusKeyword || '').toLowerCase().includes(q)) return false; }
    const a = getAudit(p.slug);
    if (filter === 'noseo') return !p.hasCustomSeo && !p.seoTitle && !p.metaDescription;
    if (filter === 'pending') return !a;
    if (filter === 'audited') return a?.status === 'pending_review';
    if (filter === 'approved') return a?.status === 'approved';
    if (filter === 'applied') return a?.status === 'applied';
    return true;
  });
  const noSeoCount = posts.filter(p => !p.hasCustomSeo && !p.seoTitle && !p.metaDescription).length;
  const stats = { total: posts.length, pending: posts.filter(p => !getAudit(p.slug)).length, audited: posts.filter(p => getAudit(p.slug)?.status === 'pending_review').length, approved: posts.filter(p => getAudit(p.slug)?.status === 'approved').length, applied: posts.filter(p => getAudit(p.slug)?.status === 'applied').length };

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="SEO Autopilot" description="AI SEO for all pages" />
      <div className="inner-page">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div>
            <h1 className="inner-page-title" style={{ margin: 0 }}>SEO Autopilot</h1>
            <p style={{ color: '#6b7280', fontSize: 13, margin: '4px 0 0' }}>{stats.total} posts | {stats.applied} applied | {stats.audited} review | {stats.pending} pending</p>
          </div>
          <button className="btn btn-primary" onClick={fetchPosts} disabled={loading} style={{ fontSize: 13 }}>{loading ? 'Loading...' : 'Refresh'}</button>
        </div>
        <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '2px solid #e5e7eb', paddingBottom: 8 }}>
          {([['posts','Posts'],['audit','Audit'],['logs','Logs'],['create','Blog Creator'],['instructions','Instructions']] as [Tab,string][]).map(([t,l]) => (
            <button key={t} onClick={() => { setTab(t); if (t==='logs') fetchLogs(); }} style={{ padding: '8px 16px', borderRadius: '8px 8px 0 0', border: 'none', cursor: 'pointer', fontSize: 13, background: tab===t ? '#d1f470' : 'transparent', color: tab===t ? '#1a3a2a' : '#6b7280', fontWeight: tab===t ? 600 : 400 }}>{l}</button>
          ))}
        </div>

        {/* POSTS TAB */}
        {tab === 'posts' && (<>
          {/* Search box */}
          <div style={{ marginBottom: 10 }}>
            <input value={search} onChange={e => { setSearch(e.target.value); selNone(); }} placeholder="🔍 Search by title, slug, SEO title, keyword..." style={{ width: '100%', padding: '8px 14px', borderRadius: 8, border: '1.5px solid #e5e7eb', fontSize: 13, fontFamily: 'inherit' }} />
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {([['all',`All (${stats.total})`],['noseo',`No SEO (${noSeoCount})`],['pending',`Pending (${stats.pending})`],['audited',`Review (${stats.audited})`],['approved',`Approved (${stats.approved})`],['applied',`Applied (${stats.applied})`]] as [Filter,string][]).map(([f,l]) => (
                <button key={f} onClick={() => { setFilter(f); selNone(); }} style={{ padding: '5px 12px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 11, background: filter===f ? (f === 'noseo' ? '#fee2e2' : '#d1f470') : '#f3f4f6', color: filter===f ? (f === 'noseo' ? '#991b1b' : '#1a3a2a') : '#6b7280', fontWeight: filter===f ? 600 : 400 }}>{l}</button>
              ))}
            </div>
            <div style={{ flex: 1 }} />
            {selected.size > 0 && (<div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: '#6b7280' }}>{selected.size} selected</span>
              <button onClick={() => bulkClean([...selected])} disabled={!!bulkRunning} style={{ ...btn, background: '#fef3c7', fontWeight: 600 }}>{bulkRunning==='clean' ? 'Cleaning...' : `Bulk Clean (${selected.size})`}</button>
              <button onClick={() => bulkAudit([...selected])} disabled={!!bulkRunning} style={{ ...btn, background: '#d1f470', fontWeight: 600 }}>{bulkRunning==='audit' ? 'Auditing...' : `Bulk Audit (${selected.size})`}</button>
              {(() => { const ids = [...selected].map(s => getAudit(s)).filter(a => a?.status==='pending_review').map(a => a!.id); return ids.length ? <button onClick={() => bulkApprove(ids)} disabled={!!bulkRunning} style={{ ...btn, background: '#dbeafe', fontWeight: 600 }}>Bulk Approve ({ids.length})</button> : null; })()}
              {(() => { const ids = [...selected].map(s => getAudit(s)).filter(a => a?.status==='approved').map(a => a!.id); return ids.length ? <button onClick={() => bulkApply(ids)} disabled={!!bulkRunning} style={{ ...btn, background: '#dcfce7', fontWeight: 600 }}>Bulk Apply ({ids.length})</button> : null; })()}
              <button onClick={selNone} style={{ ...btn, background: '#f3f4f6' }}>Clear</button>
            </div>)}
            {selected.size === 0 && filtered.length > 0 && <button onClick={selAll} style={{ ...btn, background: '#f3f4f6' }}>Select All ({filtered.length})</button>}
            {selected.size === 0 && posts.length > 0 && <button onClick={async () => { if (!(await confirmDanger('delete', 'This wipes all existing SEO data.', { title: `Clean ALL ${posts.length} posts?`, confirmInput: 'CLEAN', confirmText: 'Clean all posts' }))) return; setBulkRunning('clean'); addLog(`Bulk cleaning all ${posts.length} posts...`); let ok = 0; for (const p of posts) { await cleanPost(p.slug); ok++; if (ok % 5 === 0) addLog(`Cleaned ${ok}/${posts.length}...`); await new Promise(r => setTimeout(r, 2000)); } addLog(`Bulk clean done: ${ok} posts cleaned`); await fetchPosts(); setBulkRunning(null); }} disabled={!!bulkRunning} style={{ ...btn, background: '#fee2e2', fontWeight: 600 }}>{bulkRunning === 'clean' ? 'Cleaning...' : `Clean All ${posts.length} Posts`}</button>}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead><tr style={{ background: '#f9fafb', borderBottom: '2px solid #e5e7eb' }}>
                <th style={{ ...th, width: 30 }}><input type="checkbox" checked={selected.size===filtered.length && filtered.length>0} onChange={() => selected.size===filtered.length ? selNone() : selAll()} /></th>
                <th style={th}>#</th><th style={th}>Post</th><th style={th}>SEO Title</th><th style={{ ...th, textAlign: 'center' }}>Score</th><th style={{ ...th, textAlign: 'center' }}>Status</th><th style={{ ...th, textAlign: 'center' }}>Actions</th>
              </tr></thead>
              <tbody>{filtered.map((p, i) => { const a = getAudit(p.slug); const busy = auditingSlug===p.slug; return (
                <tr key={p.slug} style={{ borderBottom: '1px solid #f3f4f6', background: selected.has(p.slug) ? '#f0fdf4' : undefined }}>
                  <td style={td}><input type="checkbox" checked={selected.has(p.slug)} onChange={() => toggleSel(p.slug)} /></td>
                  <td style={td}>{i+1}</td>
                  <td style={{ ...td, maxWidth: 200 }}><a href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: '#1a3a2a', textDecoration: 'underline', fontSize: 12 }}>{p.title}</a><div style={{ fontSize: 10, color: '#9ca3af' }}>/{p.slug}</div></td>
                  <td style={{ ...td, maxWidth: 250 }}><div style={{ fontSize: 11 }}>{p.seoTitle || '-'}</div>{p.seoTitle && <div style={{ fontSize: 10, color: p.seoTitle.length>60 ? '#ef4444' : '#22c55e' }}>{p.seoTitle.length}ch</div>}</td>
                  <td style={{ ...td, textAlign: 'center' }}>{a ? <><span style={{ color: '#ef4444', fontSize: 11 }}>{a.seoScoreBefore}</span><span style={{ color: '#9ca3af' }}>{' > '}</span><span style={{ color: '#22c55e', fontWeight: 700, fontSize: 11 }}>{a.seoScoreAfter}</span></> : '-'}</td>
                  <td style={{ ...td, textAlign: 'center' }}>{a ? <span style={{ padding: '2px 8px', borderRadius: 6, fontSize: 10, fontWeight: 600, background: a.status==='applied'?'#dcfce7':a.status==='approved'?'#dbeafe':a.status==='pending_review'?'#fef3c7':'#f3f4f6', color: a.status==='applied'?'#166534':a.status==='approved'?'#1e40af':a.status==='pending_review'?'#92400e':'#6b7280' }}>{a.status.replace('_',' ')}</span> : <span style={{ color: '#9ca3af', fontSize: 10 }}>-</span>}</td>
                  <td style={{ ...td, textAlign: 'center' }}><div style={{ display: 'flex', gap: 3, justifyContent: 'center' }}>
                    <button onClick={() => cleanAndAudit(p.slug)} disabled={busy||!!bulkRunning} title="Clean then Audit" style={{ ...btn, background: '#fef3c7' }}>Clean+Audit</button>
                    <button onClick={() => runAudit(p.slug)} disabled={busy||!!bulkRunning} title="Audit only" style={{ ...btn, background: busy ? '#e5e7eb' : '#d1f470' }}>{busy ? 'Running...' : 'Audit'}</button>
                    {a && <button onClick={() => { setSelectedAudit(a); setTab('audit'); }} style={{ ...btn, background: '#f3f4f6' }}>View</button>}
                  </div></td>
                </tr>); })}{filtered.length===0 && <tr><td colSpan={7} style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>No posts. Click Refresh.</td></tr>}</tbody>
            </table>
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: '#6b7280' }}>{filtered.length} posts</div>
        </>)}

        {/* AUDIT TAB */}
        {tab === 'audit' && (<AuditDetail audit={selectedAudit} audits={audits} onSelect={setSelectedAudit} onAction={handleAction} />)}
        {/* LOGS TAB */}
        {tab === 'logs' && (<LogsView logs={logs} />)}
        {/* CREATE TAB */}
        {tab === 'create' && (<BlogCreator addLog={addLog} />)}
        {/* INSTRUCTIONS TAB */}
        {tab === 'instructions' && (<InstructionsContent />)}

        {log.length > 0 && (<div className="card" style={{ padding: 16, marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Activity</h3>
            <button className="btn btn-secondary" onClick={() => setLog([])} style={{ fontSize: 12, padding: '4px 12px' }}>Clear</button>
          </div>
          <pre style={{ background: '#0f1117', color: '#a3e635', padding: 16, borderRadius: 8, fontSize: 12, lineHeight: 1.6, maxHeight: 200, overflowY: 'auto', fontFamily: 'Consolas, Monaco, monospace', whiteSpace: 'pre-wrap' }}>{log.join('\n')}</pre>
        </div>)}
      </div>
    </Layout>
  );
};

// ── AUDIT DETAIL ──
function AuditDetail({ audit, audits, onSelect, onAction }: { audit: AuditRecord|null; audits: AuditRecord[]; onSelect: (a: AuditRecord) => void; onAction: (id: string, action: string) => void }) {
  if (!audit) return (<div>{audits.length===0 ? <div className="card" style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>No audits yet. Run an audit from Posts tab.</div> :
    <div style={{ display: 'grid', gap: 8 }}>{audits.slice(0,20).map(a => (
      <button key={a.id} onClick={() => onSelect(a)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: '#fff', border: '1.5px solid #e5e7eb', borderRadius: 10, cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit', width: '100%' }}>
        <div><div style={{ fontSize: 14, fontWeight: 600 }}>{a.blogTitle}</div><div style={{ fontSize: 11, color: '#6b7280' }}>/{a.blogSlug} - {new Date(a.createdAt).toLocaleString()}</div></div>
        <div><span style={{ color: '#ef4444' }}>{a.seoScoreBefore}</span> {'>'} <span style={{ color: '#22c55e', fontWeight: 700 }}>{a.seoScoreAfter}</span></div>
      </button>))}</div>}</div>);
  const ai = audit.fullAiResponse || {};
  return (<div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
      <div><h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{audit.blogTitle}</h2><div style={{ fontSize: 12, color: '#6b7280' }}>/{audit.blogSlug} - {new Date(audit.createdAt).toLocaleString()} - {audit.status}</div></div>
      <button onClick={() => onSelect(null as any)} style={{ ...btn, background: '#f3f4f6' }}>Back</button>
    </div>
    <div className="card" style={{ padding: 16, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
      <div style={{ textAlign: 'center' }}><div style={{ fontSize: 11, color: '#6b7280' }}>BEFORE</div><div style={{ fontSize: 32, fontWeight: 800, color: '#ef4444' }}>{audit.seoScoreBefore}</div></div>
      <div style={{ fontSize: 24, color: '#9ca3af' }}>{'>'}</div>
      <div style={{ textAlign: 'center' }}><div style={{ fontSize: 11, color: '#6b7280' }}>AFTER</div><div style={{ fontSize: 32, fontWeight: 800, color: '#22c55e' }}>{audit.seoScoreAfter}</div></div>
      <div style={{ flex: 1 }} />
      {audit.status==='pending_review' && <div style={{ display: 'flex', gap: 8 }}><button onClick={() => onAction(audit.id,'approve')} style={{ ...btn, background: '#d1f470', fontWeight: 600, padding: '6px 16px' }}>Approve</button><button onClick={() => onAction(audit.id,'reject')} style={{ ...btn, background: '#fee2e2', padding: '6px 16px' }}>Reject</button></div>}
      {audit.status==='approved' && <button onClick={() => onAction(audit.id,'apply')} style={{ ...btn, background: '#d1f470', fontWeight: 600, padding: '6px 16px' }}>Apply SEO</button>}
      {audit.status==='applied' && <span style={{ padding: '6px 14px', background: '#dcfce7', color: '#166534', borderRadius: 8, fontSize: 12, fontWeight: 600 }}>Applied {audit.appliedAt ? new Date(audit.appliedAt).toLocaleString() : ''}</span>}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
      <div className="card" style={{ padding: 16 }}><h3 style={{ fontSize: 13, fontWeight: 600, color: '#ef4444', marginBottom: 12 }}>Current</h3><CF label="SEO Title" value={audit.currentSeoTitle} max={60} /><CF label="Meta Description" value={audit.currentMetaDescription} max={160} /></div>
      <div className="card" style={{ padding: 16 }}><h3 style={{ fontSize: 13, fontWeight: 600, color: '#22c55e', marginBottom: 12 }}>AI Suggested</h3><CF label="SEO Title" value={audit.suggestedSeoTitle} max={60} /><CF label="Meta Description" value={audit.suggestedMetaDescription} max={160} /></div>
    </div>
    <div className="card" style={{ padding: 16, marginBottom: 16 }}><h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Keywords (1 focus + {audit.secondaryKeywords?.length || 0} secondary)</h3>
      <div style={{ marginBottom: 8 }}><span style={{ fontSize: 11, color: '#6b7280' }}>Focus: </span><span style={{ fontSize: 13, fontWeight: 600, color: '#1a3a2a' }}>{audit.focusKeyword}</span></div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{audit.secondaryKeywords?.map((kw,i) => <span key={i} style={{ padding: '2px 8px', background: '#f0fdf4', color: '#166534', borderRadius: 6, fontSize: 11 }}>{kw}</span>)}</div>
    </div>
    {/* Meta Tags */}
    <div className="card" style={{ padding: 16, marginBottom: 16 }}><h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Meta Tags (rendered by Amplify after Apply)</h3>
      <div style={{ display: 'grid', gap: 4 }}>{[['og:title',audit.suggestedSeoTitle?.replace(' | WECARE.DIGITAL','')],['og:description',audit.suggestedMetaDescription],['og:url',`https://wecare.digital/post/${audit.blogSlug}`],['og:type','article'],['og:site_name','WECARE.DIGITAL'],['og:locale','en_IN'],['og:image',ai.jsonLd?.blogPosting?.image?.[0]||'default logo'],['article:author','Swdhya Vaksetu'],['twitter:card','summary_large_image'],['twitter:title',audit.suggestedSeoTitle?.replace(' | WECARE.DIGITAL','')],['twitter:description',audit.suggestedMetaDescription],['robots','index, follow, max-image-preview:large'],['canonical',`https://wecare.digital/post/${audit.blogSlug}`]].map(([p,v],i) => (
        <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 8px', background: i%2===0?'#f9fafb':'#fff', borderRadius: 4, fontSize: 11 }}><span style={{ color: '#6b7280', minWidth: 140, fontFamily: 'monospace' }}>{p}</span><span style={{ color: '#1a1a1a', flex: 1, wordBreak: 'break-word' }}>{v}</span></div>
      ))}</div>
    </div>
    {audit.internalLinkSuggestions?.length > 0 && <div className="card" style={{ padding: 16, marginBottom: 16 }}><h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Internal Links</h3>{audit.internalLinkSuggestions.map((l:any,i:number) => <div key={i} style={{ padding: '4px 0', fontSize: 12 }}><span style={{ fontWeight: 600 }}>{l.text}</span> <span style={{ color: '#6b7280' }}>{l.url}</span> <span style={{ color: '#9ca3af', fontSize: 10 }}>({l.reason})</span></div>)}</div>}
    {audit.warnings?.length > 0 && <div className="card" style={{ padding: 16, marginBottom: 16, borderLeft: '4px solid #f59e0b' }}><h3 style={{ fontSize: 13, fontWeight: 600, color: '#92400e', marginBottom: 8 }}>Warnings</h3>{audit.warnings.map((w,i) => <div key={i} style={{ fontSize: 12, color: '#92400e', padding: '2px 0' }}>- {w}</div>)}</div>}
    {audit.scoreBreakdown && <div className="card" style={{ padding: 16, marginBottom: 16 }}><h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Score Breakdown</h3><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>{Object.entries(audit.scoreBreakdown).map(([k,v]:any) => <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', background: '#f9fafb', borderRadius: 6, fontSize: 11 }}><span style={{ color: '#6b7280' }}>{k}</span><span><span style={{ color: '#ef4444' }}>{v.before}</span>{' > '}<span style={{ color: '#22c55e', fontWeight: 600 }}>{v.after}</span>/{v.max}</span></div>)}</div></div>}
    {audit.suggestedJsonLd && <div className="card" style={{ padding: 16 }}><h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>JSON-LD</h3><pre style={{ background: '#0f1117', color: '#a3e635', padding: 16, borderRadius: 8, fontSize: 11, maxHeight: 300, overflowY: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(audit.suggestedJsonLd, null, 2)}</pre></div>}
  </div>);
}
function CF({ label, value, max }: { label: string; value: string; max: number }) {
  const len = value?.length || 0;
  return (<div style={{ marginBottom: 12 }}><div style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase', marginBottom: 2 }}>{label}</div><div style={{ fontSize: 12, color: '#1a1a1a', lineHeight: 1.5 }}>{value || '(empty)'}</div>{value && <div style={{ fontSize: 10, color: len > max ? '#ef4444' : '#22c55e', marginTop: 2 }}>{len}/{max} {len > max ? 'over limit' : 'ok'}</div>}</div>);
}

// ── LOGS VIEW ──
function LogsView({ logs }: { logs: any[] }) {
  if (!logs.length) return <div className="card" style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>No AI logs yet.</div>;
  return (<div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
    <thead><tr style={{ background: '#f9fafb', borderBottom: '2px solid #e5e7eb' }}><th style={th}>Time</th><th style={th}>Slug</th><th style={th}>Model</th><th style={{ ...th, textAlign: 'center' }}>Tokens</th><th style={{ ...th, textAlign: 'center' }}>Cost</th><th style={{ ...th, textAlign: 'center' }}>Status</th></tr></thead>
    <tbody>{logs.slice().reverse().map((l,i) => (<tr key={i} style={{ borderBottom: '1px solid #f3f4f6' }}>
      <td style={td}>{new Date(l.createdAt).toLocaleString()}</td><td style={td}>{l.blogSlug}</td><td style={{ ...td, fontSize: 10 }}>{l.model?.split('.').pop()?.substring(0,25)}</td>
      <td style={{ ...td, textAlign: 'center' }}>{l.inputTokens}+{l.outputTokens}</td><td style={{ ...td, textAlign: 'center', fontWeight: 600 }}>${l.costEstimate}</td>
      <td style={{ ...td, textAlign: 'center', color: l.status==='success'?'#22c55e':'#ef4444' }}>{l.status}{l.errorMessage && <div style={{ fontSize: 10 }}>{l.errorMessage}</div>}</td>
    </tr>))}</tbody></table></div>);
}

// ── BLOG CREATOR ──
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
      if (d.ok) {
        addLog(`Published in AWS: ${d.slug} (${d.postId})`);
        if (d.rebuildRequired) addLog('Amplify rebuild required before this new static URL is public.');
        setTitle(''); setContent(''); setTags(''); setHashtags(''); setCategory('');
      }
      else addLog(`Failed: ${d.error}`);
    } catch (e: any) { addLog(e.message); }
    setPublishing(false);
  };

  const wordCount = content.split(/\s+/).filter(Boolean).length;

  return (<div style={{ maxWidth: 800 }}>
    <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Create Blog Post</h2>
    <div className="card" style={{ padding: 20, marginBottom: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Title</label>
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Blog post title..." style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1.5px solid #e5e7eb', fontSize: 14, fontFamily: 'inherit' }} />
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Content</label>
        <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4 }}>Use ## for H2, ### for H3. Each line = paragraph. Paste from PDF/Word.</div>
        <textarea value={content} onChange={e => setContent(e.target.value)} placeholder="Paste blog content here...&#10;&#10;## Section Heading&#10;&#10;Paragraph text goes here..." rows={15} style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1.5px solid #e5e7eb', fontSize: 13, fontFamily: 'Georgia, serif', lineHeight: 1.8, resize: 'vertical' }} />
        <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>{content.length} chars | {wordCount} words {wordCount < 300 && wordCount > 0 ? '(min 300 recommended)' : ''}</div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Category</label>
          <input
            value={category}
            onChange={e => setCategory(e.target.value)}
            list="blog-category-options"
            placeholder="e.g. Insights"
            style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid #e5e7eb', fontSize: 13, fontFamily: 'inherit' }}
          />
          <datalist id="blog-category-options">
            {categories.map(c => <option key={c.id} value={c.label} />)}
          </datalist>
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Tags (comma-separated)</label>
          <input value={tags} onChange={e => setTags(e.target.value)} placeholder="philosophy, self-inquiry, relationships" style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid #e5e7eb', fontSize: 13, fontFamily: 'inherit' }} />
          {availableTags.length > 0 && <div style={{ fontSize: 10, color: '#9ca3af', marginTop: 4 }}>Existing: {availableTags.slice(0, 10).map(t => t.label).join(', ')}{availableTags.length > 10 ? ` +${availableTags.length - 10} more` : ''}</div>}
        </div>
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>Hashtags (comma-separated)</label>
        <input value={hashtags} onChange={e => setHashtags(e.target.value)} placeholder="Stand, ConsciousChoice, Integrity, Swdhya" style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid #e5e7eb', fontSize: 13, fontFamily: 'inherit' }} />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={publishPost} disabled={publishing || !title.trim() || !content.trim()} style={{ ...btn, background: '#d1f470', fontWeight: 600, padding: '8px 20px', fontSize: 13 }}>{publishing ? 'Publishing...' : 'Publish'}</button>
        <button onClick={() => { setTitle(''); setContent(''); setTags(''); setHashtags(''); setCategory(''); }} style={{ ...btn, background: '#f3f4f6', padding: '8px 20px', fontSize: 13 }}>Clear</button>
      </div>
    </div>
    <div className="card" style={{ padding: 16 }}>
      <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Formatting Guide</h3>
      <pre style={{ background: '#f9fafb', padding: 12, borderRadius: 8, fontSize: 11, lineHeight: 1.8, margin: 0, whiteSpace: 'pre-wrap' }}>{`# Heading 1 (rarely used — title is H1)
## Heading 2 (section headings)
### Heading 3 (sub-sections)

Regular text becomes a paragraph.
Each line = one paragraph.
Empty lines are skipped.

Style: WECARE.DIGITAL Amplify article layout
Author: current Admin user (stored with the post)
After publishing: go to Posts tab > Clean+Audit for SEO.
A new slug becomes public after the next Amplify static build.`}</pre>
    </div>
  </div>);
}

export default BlogSeoManager;
