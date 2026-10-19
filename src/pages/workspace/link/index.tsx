/**
 * Legacy standalone route for the shared Short Links workspace component.
 *
 * Primary navigation now owns this capability under /workspace/content?view=links. Keeping this
 * wrapper preserves old bookmarks without creating a second implementation.
 */
import React from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import ShortLinks from '../../../components/workspace/content/ShortLinks';

interface PageProps { signOut?: () => void; user?: any; }

const LinkPage: React.FC<PageProps> = ( { signOut, user } ) => (
  <Layout user={ user } onSignOut={ signOut }>
    <SEO title="Short Links" description="URL shortener and deep links — wecare.digital/r" noindex />
    <ShortLinks />
  </Layout>
);

export default LinkPage;
