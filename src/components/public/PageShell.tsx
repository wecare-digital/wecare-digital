import React from 'react';
import PageMeta from '../PageMeta';
import Breadcrumbs from '../Breadcrumbs';
import { breadcrumbSchema, type PageCrumb } from '../../lib/breadcrumbs';

interface PageShellProps {
  title: string;
  description: string;
  canonical: string;
  crumbs?: PageCrumb[];
  children?: React.ReactNode;
}

/** Page concerns only. _app owns chrome; consumers retain their layout and main landmark. */
export default function PageShell( { title, description, canonical, crumbs, children }: PageShellProps ) {
  return <>
    <PageMeta title={ title } description={ description } path={ canonical }
      jsonLd={ crumbs?.length ? [ breadcrumbSchema( crumbs, canonical ) ] : undefined } />
    { crumbs?.length ? <div className="page-shell-crumbs">
      <Breadcrumbs items={ crumbs.map( ( { name, href } ) => ( { label: name, href } ) ) } />
    </div> : null }
    { children }
  </>;
}
