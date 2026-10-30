import React from 'react';
import { useRouter } from 'next/router';

interface PageProps { signOut?: () => void; user?: any; }

const DocsRedirect: React.FC<PageProps> = () => {
  const router = useRouter();
  // FEAT-005: Drop Docs is a tab on the Service hub now; forward to that hub tab.
  React.useEffect(() => { router.replace('/workspace/service?view=documents'); }, [router]);
  return <div style={{ padding: '24px 32px', textAlign: 'center', color: 'var(--text-muted)' }}>Redirecting to Drop Docs...</div>;
};

export default DocsRedirect;
