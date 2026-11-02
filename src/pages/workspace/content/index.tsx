/**
 * Canonical Content workspace.
 *
 * Three operator jobs, one primary destination:
 * Blog | SEO | Short links.
 *
 * Only AWS-native/currently supported SEO surfaces are mounted here. Older external seoFetch
 * routes remain compatibility/history pages and are not advertised as live capabilities.
 */
import React, { Suspense } from 'react';
import { useRouter } from 'next/router';
import SEO from '../../../components/SEO';
import PageShell, { ShellTab } from '../../../components/PageShell';
import ShortLinks from '../../../components/workspace/content/ShortLinks';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }
type View = 'blog' | 'seo' | 'links';
type SeoArea = 'tools' | 'pages';

const TABS: ShellTab[] = [
  { id: 'blog', label: 'Blog' },
  { id: 'seo', label: 'SEO' },
  { id: 'links', label: 'Short links' },
];

function one ( raw: string | string[] | undefined ): string {
  return Array.isArray( raw ) ? ( raw[ 0 ] || '' ) : ( raw || '' );
}

function resolveView ( raw: string | string[] | undefined ): View {
  const value = one( raw );
  return value === 'seo' || value === 'links' ? value : 'blog';
}

function resolveSeoArea ( raw: string | string[] | undefined ): SeoArea {
  return one( raw ) === 'pages' ? 'pages' : 'tools';
}

const ContentPage: React.FC<PageProps> = ( { signOut, user } ) => {
  const router = useRouter();
  const view = resolveView( router.query.view );
  const seoArea = resolveSeoArea( router.query.area );

  const go = ( next: View, area?: SeoArea ) => {
    const query: Record<string, string> = { view: next };
    if ( next === 'seo' && area ) query.area = area;
    void router.push( { pathname: '/workspace/content', query } );
  };

  return (
    <>
      <SEO
        title="Content"
        description="Blog, AWS-native SEO and short links."
        noindex
      />
      <PageShell
        title="Content"
        subtitle="Manage published blog content, SEO and short links."
        tabs={ TABS }
        activeTab={ view }
        defaultTab={ view }
        onTabChange={ next => go( resolveView( next ) ) }
      >
        { active => (
          <Suspense fallback={ <div className="content-state">Loading…</div> }>
            { active === 'blog' && (
              <section className="content-mode">
                <div className="content-context" role="status">
                  <div>
                    <strong>Blog editor retired</strong>
                    <span>The former SEO/Blog management components were deliberately removed.
                      Public articles remain available, but no unpublished editing workflow is
                      offered until its replacement has been reviewed.</span>
                  </div>
                </div>
              </section>
            ) }

            { active === 'seo' && (
              <section className="content-mode">
                <nav className="content-subtabs" aria-label="SEO">
                  <button
                    type="button"
                    className={ seoArea === 'tools' ? 'active' : '' }
                    aria-current={ seoArea === 'tools' ? 'page' : undefined }
                    onClick={ () => go( 'seo', 'tools' ) }
                  >
                    Tools
                  </button>
                  <button
                    type="button"
                    className={ seoArea === 'pages' ? 'active' : '' }
                    aria-current={ seoArea === 'pages' ? 'page' : undefined }
                    onClick={ () => go( 'seo', 'pages' ) }
                  >
                    Pages
                  </button>
                </nav>
                <div className="content-context" role="status">
                  <div>
                    <strong>{seoArea === 'tools' ? 'SEO tools retired' : 'SEO pages editor retired'}</strong>
                    <span>The deleted legacy SEO component is not loaded. Existing public
                      pages and the separately operated SEO backend are unchanged.</span>
                  </div>
                </div>
              </section>
            ) }

            { active === 'links' && (
              <section className="content-mode">
                <ShortLinks />
              </section>
            ) }
          </Suspense>
        ) }
      </PageShell>

      <style jsx>{`
        .content-mode{min-width:0}
        .content-state{padding:48px;text-align:center;color:var(--text-muted)}
        .content-context{
          display:flex;align-items:center;justify-content:space-between;gap:16px;
          padding:12px 14px;margin:0 0 16px;border:1px solid var(--border);
          border-radius:14px;background:var(--bg-secondary)
        }
        .content-context>div{display:flex;flex-direction:column;gap:3px;min-width:0}
        .content-context strong{font-size:var(--text-sm);color:var(--text)}
        .content-context span{font-size:var(--text-xs);color:var(--text-muted);line-height:1.45}
        .content-context :global(a){
          min-height:44px;display:inline-flex;align-items:center;white-space:nowrap;
          padding:8px 12px;border-radius:11px;background:#fff;border:1px solid var(--border);
          color:var(--text);text-decoration:none;font-size:var(--text-sm);font-weight:650
        }
        .content-context :global(a:hover),.content-context :global(a:focus-visible){border-color:var(--lime);background:#fff}
        .content-subtabs{
          display:flex;gap:6px;width:max-content;max-width:100%;padding:4px;margin:0 0 16px;
          border:1px solid var(--border);border-radius:12px;background:var(--bg-secondary)
        }
        .content-subtabs button{
          min-height:44px;min-width:100px;padding:8px 14px;border:0;border-radius:9px;
          background:transparent;color:var(--text-muted);font:inherit;font-weight:700;cursor:pointer
        }
        .content-subtabs button.active{background:#fff;color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.08)}
        @media(max-width:640px){
          .content-context{align-items:stretch;flex-direction:column}
          .content-context :global(a){align-self:flex-start}
          .content-subtabs{width:100%}
          .content-subtabs button{flex:1;min-width:0}
        }
        @media(forced-colors:active){.content-context,.content-subtabs{border-color:CanvasText}}
      `}</style>
    </>
  );
};

export default ContentPage;
