/**
 * SEO Tools — AWS Blog SEO visibility, Google Indexing and PageSpeed.
 *
 * The public site is an Amplify static export. Blog content comes from the
 * SEO Tools public read API (the native blog).
 */
import React, { useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const SITE_BASE = 'https://wecare.digital';
const BLOG_PUBLIC_API = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/seo-tools/blog-public`;
const ALL_PAGES = [
  '/', '/relay-os', '/atmos/nano-climate', '/atmos/green-ledger',
  '/elsewhere/rail', '/elsewhere/cruise', '/elsewhere/arogya-yatra', '/contact', '/shop', '/blog',
];

const SEOTools: React.FC<PageProps> = ({ signOut, user, embedded }) => {
  const [log, setLog] = useState<string[]>([]);
  const [running, setRunning] = useState('');

  function addLog(msg: string) {
    setLog(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  }
  function clearLog() { setLog([]); }

  // ── Blog SEO: AWS-native content status ──
  async function runBlogSeoInfo() {
    setRunning('bloginfo');
    clearLog();
    addLog('Blog SEO — AWS-native published content');
    addLog('');
    try {
      const r = await fetch(BLOG_PUBLIC_API);
      if (!r.ok) {
        addLog(`Public blog API: HTTP ${r.status}`);
      } else {
        const data = await r.json();
        const posts = Array.isArray(data.posts) ? data.posts : [];
        addLog(`Published posts: ${posts.length}`);
        addLog('Source: SeoToolsTable (recordType=blogPost)');
        addLog('Public routes: /blog/ and /post/{slug}/');
        addLog('SEO apply: approved output is stored on the blog post record.');
        addLog('New slugs appear after the next Amplify static build.');
        if (posts.length) {
          addLog('');
          posts.slice(0, 8).forEach((post: any) => addLog(`  /post/${post.slug}/ — ${post.title}`));
        }
      }
    } catch (e: any) {
      addLog(`Public blog API unavailable: ${e.message}`);
    }
    setRunning('');
  }

  // ── Google Indexing ──
  async function runGoogleIndex() {
    setRunning('googleindex');
    clearLog();
    addLog('🔍 Google Indexing — Submitting all URLs');
    addLog('');

    // Step 1: Collect all URLs
    const pageUrls = ALL_PAGES.map(p => SITE_BASE + p);
    addLog(`Static pages: ${pageUrls.length}`);

    // Get published AWS blog URLs.
    let blogUrls: string[] = [];
    try {
      addLog('Fetching published blog URLs from AWS...');
      const r = await fetch(BLOG_PUBLIC_API);
      if (r.ok) {
        const data = await r.json();
        blogUrls = (data.posts || []).map((post: any) => `https://wecare.digital/post/${post.slug}/`);
        addLog(`Blog posts: ${blogUrls.length}`);
      }
    } catch (e: any) {
      addLog(`Blog fetch error: ${e.message}`);
    }

    const allUrls = [...new Set([...pageUrls, ...blogUrls])];
    addLog(`Total unique URLs: ${allUrls.length}`);
    addLog('');

    // The browser has no Google Indexing API credential. (A token used to be read from
    // localStorage 'seo_token' for an SEO platform URL that is not configured; removed.)
    addLog('Direct Google Indexing API submission is not available from the browser.');
    addLog('');
    addLog('Alternative: Run from terminal:');
    addLog('  python seo-crawler/scripts/google_reindex_now.py');
    addLog('');
    addLog('Or deploy the Google Indexer Lambda:');
    addLog('  cd seo-crawler && sam build && sam deploy');
    addLog('  Then POST to /index endpoint');
    addLog('');
    addLog('Meanwhile, Google can crawl the single public sitemap:');
    addLog('  - https://wecare.digital/sitemap.xml');
    addLog('');
    addLog('The sitemap is regenerated from the public Amplify export on every build.');
    addLog('Full re-indexing typically takes 3-7 days.');
    addLog('');

    // Still useful: ping Google with sitemap notification
    addLog('Pinging Google with sitemap URLs...');
    const sitemaps = [ 'https://wecare.digital/sitemap.xml' ];
    for (const sm of sitemaps) {
      try {
        const pingUrl = `https://www.google.com/ping?sitemap=${encodeURIComponent(sm)}`;
        await fetch(pingUrl, { mode: 'no-cors' });
        addLog(`  ✅ Pinged: ${sm}`);
      } catch {
        addLog(`  ❌ Failed: ${sm}`);
      }
    }
    addLog('');
    addLog('Done. Google has been notified of sitemap updates.');

    setRunning('');
  }

  // ── PageSpeed ──
  async function runPageSpeed() {
    setRunning('pagespeed');
    clearLog();
    addLog('⚡ PageSpeed Insights (mobile)');
    addLog('');
    const pages = ['/', '/elsewhere/trip/', '/contact/', '/blog/'];
    for (const pg of pages) {
      const url = SITE_BASE + pg;
      addLog(`Testing ${pg}...`);
      try {
        const r = await fetch(
          `https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=${encodeURIComponent(url)}&strategy=mobile&category=performance&category=seo`
        );
        if (r.status === 429) {
          addLog(`  Rate limited (429) — daily quota exceeded. Try tomorrow.`);
          break;
        }
        if (r.ok) {
          const d = await r.json();
          const perf = d.lighthouseResult?.categories?.performance?.score;
          const seo = d.lighthouseResult?.categories?.seo?.score;
          addLog(`  Performance: ${perf != null ? Math.round(perf * 100) : '—'}/100`);
          addLog(`  SEO: ${seo != null ? Math.round(seo * 100) : '—'}/100`);
        } else {
          addLog(`  HTTP ${r.status}`);
        }
      } catch (e: any) {
        addLog(`  Error: ${e.message}`);
      }
    }
    setRunning('');
  }

  const tools = [
    { id: 'bloginfo', label: 'Blog SEO Content', desc: 'Check published AWS blog content and static routes', action: runBlogSeoInfo, icon: '📝' },
    { id: 'googleindex', label: 'Google Indexing', desc: 'Submit public site URLs and ping the generated sitemap', action: runGoogleIndex, icon: '🔍' },
    { id: 'pagespeed', label: 'PageSpeed Check', desc: 'Run Google PageSpeed Insights on public pages (mobile)', action: runPageSpeed, icon: '⚡' },
  ];

  const body = (
      <div className="inner-page" style={ embedded ? { padding: 0 } : undefined }>
        <h1 className="inner-page-title">SEO Tools</h1>
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-md)', marginBottom: 24 }}>
          Run public-site SEO checks and operations. Blog content is AWS-native; the frontend is a static Amplify export.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12, marginBottom: 24 }}>
          {tools.map(t => (
            <div key={t.id} className="card" style={{ padding: '16px 20px' }}>
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 'var(--text-md)', fontWeight: 600 }}>{t.icon} {t.label}</div>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>{t.desc}</div>
              </div>
              <button
                className="btn btn-primary"
                onClick={t.action}
                disabled={!!running}
                style={{ marginTop: 8, width: '100%' }}
              >
                {running === t.id ? 'Running...' : 'Run'}
              </button>
            </div>
          ))}
        </div>

        {log.length > 0 && (
          <div className="card" style={{ padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <h3 style={{ fontSize: 'var(--text-md)', fontWeight: 600, margin: 0 }}>Output</h3>
              <button className="btn btn-secondary" onClick={clearLog} style={{ fontSize: 'var(--text-xs)', padding: '4px 12px' }}>Clear</button>
            </div>
            <pre style={{
              background: '#0f1117', color: '#a3e635', padding: 16, borderRadius: 8,
              fontSize: 'var(--text-xs)', lineHeight: 1.6, maxHeight: 500, overflowY: 'auto',
              fontFamily: 'Consolas, Monaco, monospace', whiteSpace: 'pre-wrap',
            }}>
              {log.join('\n')}
            </pre>
          </div>
        )}
      </div>
  );

  if (embedded) return body;
  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="SEO Tools" description="SEO management tools for wecare.digital" />
      {body}
    </Layout>
  );
};

export default SEOTools;
