import React from 'react';
import PageMeta from '../PageMeta';
import { type PageCrumb } from '../../lib/breadcrumbs';

interface PageShellProps {
  title: string;
  description: string;
  canonical: string;
  crumbs?: PageCrumb[];
  children?: React.ReactNode;
}

/** Page concerns only. _app owns chrome; consumers retain their layout and main landmark. */
export default function PageShell( { title, description, canonical, children }: PageShellProps ) {
  return <>
    <PageMeta title={ title } description={ description } path={ canonical } />
    { children }
  </>;
}
