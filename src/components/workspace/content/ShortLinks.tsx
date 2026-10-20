/**
 * Content → Short links: a redirect to the single canonical short-link surface.
 *
 * There used to be two full short-link UIs — this one under Content and the one under
 * Communications → Manage → Links (messaging/Links.tsx). Two live implementations of the same
 * capability drift: a lifecycle fix or an attachment field lands in one and not the other, and
 * an operator cannot tell which surface is authoritative. FEAT-004 makes messaging/Links.tsx the
 * single real surface and turns this one into a pointer, so no second implementation stays live
 * and no deep link to /workspace/content?view=links breaks.
 *
 * It is still a `React.FC` named `ShortLinks`, still mounted as `<ShortLinks />` by the content
 * hub, so the content page keeps its "Short links" tab as a door — the door now leads to the
 * canonical room instead of a duplicate of it.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';

const CANONICAL = {
  pathname: '/workspace/communications',
  query: { view: 'manage', section: 'links' },
} as const;

const ShortLinks: React.FC = () => {
  const router = useRouter();

  useEffect( () => {
    void router.replace( CANONICAL );
  }, [ router ] );

  return (
    <div className="content-mode" style={ { padding: 40, textAlign: 'center', color: 'var(--text-muted)' } }>
      <p>Short links now live in Communications → Manage → Links.</p>
      <p>
        <Link href="/workspace/communications?view=manage&section=links">Open Short links →</Link>
      </p>
    </div>
  );
};

export default ShortLinks;
