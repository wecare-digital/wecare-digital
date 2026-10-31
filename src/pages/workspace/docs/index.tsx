import React from 'react';
import { useRouter } from 'next/router';

interface PageProps { signOut?: () => void; user?: any; }

const DocsRedirect: React.FC<PageProps> = () => {
  const router = useRouter();
  // Legacy staff document entry goes to Vault, never the customer Drop Docs Flow.
  React.useEffect(() => { router.replace('/workspace/service?view=vault'); }, [router]);
  return <div style={{ padding: '24px 32px', textAlign: 'center', color: 'var(--text-muted)' }}>Redirecting to Vault...</div>;
};

export default DocsRedirect;
