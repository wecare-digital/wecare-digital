/**
 * Phone bottom navigation for the rebuilt workspace.
 *
 * This is deliberately NOT a module menu. Business work is reached from Workspace Home,
 * universal search and contextual links. The four permanent phone actions stay stable even as
 * products and providers change underneath them.
 */
import React from 'react';
import { useRouter } from 'next/router';

interface BottomNavProps {
  onSearch: () => void;
  onProfile: () => void;
  profileOpen?: boolean;
}

const Icon: React.FC<{ kind: 'home' | 'search' | 'tasks' | 'me' }> = ( { kind } ) => {
  if ( kind === 'home' ) return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M3.5 10.5 12 3l8.5 7.5"/><path d="M5.5 9.5V21h13V9.5"/><path d="M9.5 21v-6h5v6"/>
    </svg>
  );
  if ( kind === 'search' ) return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>
    </svg>
  );
  if ( kind === 'tasks' ) return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M9 6h11M9 12h11M9 18h11"/><path d="m3.5 6 1.4 1.4L7 5.1M3.5 12l1.4 1.4L7 11.1M3.5 18l1.4 1.4L7 17.1"/>
    </svg>
  );
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="8" r="3.5"/><path d="M4.5 21c.8-4.1 3.3-6.2 7.5-6.2s6.7 2.1 7.5 6.2"/>
    </svg>
  );
};

const BottomNav: React.FC<BottomNavProps> = ( { onSearch, onProfile, profileOpen } ) => {
  const router = useRouter();
  const homeActive = router.pathname === '/workspace';
  const tasksActive = router.pathname.startsWith( '/workspace/task' );

  return (
    <nav className="bottom-nav" aria-label="Workspace">
      <button type="button" className={ `bn-item ${homeActive ? 'active' : ''}` }
        aria-current={ homeActive ? 'page' : undefined } onClick={ () => void router.push( '/workspace' ) }>
        <span className="bn-icon"><Icon kind="home" /></span><span className="bn-label">Home</span>
      </button>
      <button type="button" className="bn-item" onClick={ onSearch } aria-label="Search workspace">
        <span className="bn-icon"><Icon kind="search" /></span><span className="bn-label">Search</span>
      </button>
      <button type="button" className={ `bn-item ${tasksActive ? 'active' : ''}` }
        aria-current={ tasksActive ? 'page' : undefined } onClick={ () => void router.push( '/workspace/task' ) }>
        <span className="bn-icon"><Icon kind="tasks" /></span><span className="bn-label">Tasks</span>
      </button>
      <button type="button" className={ `bn-item ${profileOpen ? 'active' : ''}` }
        aria-expanded={ !!profileOpen } onClick={ onProfile } aria-label="Open profile">
        <span className="bn-icon"><Icon kind="me" /></span><span className="bn-label">Me</span>
      </button>
    </nav>
  );
};

export default BottomNav;
