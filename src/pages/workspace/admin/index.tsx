/**
 * Legacy redirect — Admin moved under [retired public path]
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

export default function AdminRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace('/workspace/platform?view=system-architecture'); }, [router]);
  return null;
}
