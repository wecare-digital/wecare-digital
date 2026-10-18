import React from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../components/Layout';

interface PageProps { signOut?: () => void; user?: any; }

const DocsRedirect: React.FC<PageProps> = ({ signOut, user }) => {
  const router = useRouter();
  // FEAT-005: Drop Docs is a tab on the Service hub now; forward to that hub tab.
  React.useEffect(() => { router.replace('/workspace/engage/service-ops?tab=documents'); }, [router]);
  return (
    <Layout user={user} onSignOut={signOut}>
      <div style={{ padding: '24px 32px', textAlign: 'center', color: 'var(--text-muted)' }}>Redirecting to Drop Docs...</div>
    </Layout>
  );
};

export default DocsRedirect;
