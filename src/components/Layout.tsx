/**
 * Compatibility adapter for legacy Workspace pages.
 *
 * The real authenticated shell is applied centrally in _app for every /workspace/** route.
 * Existing pages may continue to import Layout during migration; when already inside the
 * canonical WorkspaceShell this component returns only its children, preventing duplicate chrome.
 */
import React, { ReactNode, useContext } from 'react';
import WorkspaceShell, { WorkspaceShellContext } from './WorkspaceShell';

interface LayoutProps {
  children: ReactNode;
  user?: any;
  onSignOut?: () => void;
  showBreadcrumbs?: boolean;
}

const Layout: React.FC<LayoutProps> = ( props ) => {
  const insideCanonicalShell = useContext( WorkspaceShellContext );
  if ( insideCanonicalShell ) return <>{ props.children }</>;
  return <WorkspaceShell { ...props } />;
};

export default Layout;
