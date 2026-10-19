/**
 * Breadcrumbs Component - WECARE.DIGITAL
 * Navigation breadcrumbs for nested pages
 */

import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { navigationConfig, NavItem, NavSubItem } from '../../config/navigation';

interface BreadcrumbItem {
  label: string;
  path: string;
  isLast: boolean;
}

interface BreadcrumbsProps {
  className?: string;
}

// Build breadcrumb trail from current path
function getBreadcrumbs(pathname: string): BreadcrumbItem[] {
  const crumbs: BreadcrumbItem[] = [];
  
  // Workspace Home is the navigation root. Domains such as Communications and Payments are peers.
  if (pathname !== '/workspace') {
    crumbs.push({ label: 'Workspace', path: '/workspace', isLast: false });
  }
  
  // Find matching nav items
  const findPath = (items: (NavItem | NavSubItem)[], parents: { label: string; path: string }[] = []): boolean => {
    for (const item of items) {
      const currentPath = [...parents, { label: item.label, path: item.path }];
      
      if (pathname === item.path || pathname.startsWith(item.path + '/')) {
        // Add all parents
        currentPath.forEach((p, i) => {
          const isLast = i === currentPath.length - 1 && pathname === item.path;
          if (!crumbs.find(c => c.path === p.path)) {
            crumbs.push({ ...p, isLast });
          }
        });
        
        // If exact match, mark as last
        if (pathname === item.path) {
          const lastCrumb = crumbs[crumbs.length - 1];
          if (lastCrumb) lastCrumb.isLast = true;
          return true;
        }
        
        // Check children
        if ('children' in item && item.children) {
          if (findPath(item.children, currentPath)) {
            return true;
          }
        }
      }
    }
    return false;
  };
  
  findPath(navigationConfig);
  
  // Mark last item
  if (crumbs.length > 0) {
    crumbs[crumbs.length - 1].isLast = true;
  }
  
  return crumbs;
}

const Breadcrumbs: React.FC<BreadcrumbsProps> = ({ className }) => {
  const router = useRouter();
  const breadcrumbs = getBreadcrumbs(router.pathname);
  
  // Don't show breadcrumbs on Workspace Home or if only one item.
  if (router.pathname === '/workspace' || breadcrumbs.length <= 1) {
    return null;
  }
  
  return (
    <nav className={`breadcrumbs ${className || ''}`} aria-label="Breadcrumb">
      <ol className="breadcrumbs-list" role="list">
        {breadcrumbs.map((crumb) => (
          <li key={crumb.path} className="breadcrumbs-item">
            {!crumb.isLast ? (
              <>
                <Link href={crumb.path} className="breadcrumbs-link">
                  {crumb.label}
                </Link>
                <span className="breadcrumbs-separator" aria-hidden="true">/</span>
              </>
            ) : (
              <span className="breadcrumbs-current" aria-current="page">
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
};

export default Breadcrumbs;
