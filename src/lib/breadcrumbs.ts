export interface PageCrumb {
  name: string;
  href?: string;
}


/** Route-aware blog trail shared by the view and metadata, including topic pagination. */
export function blogCrumbs( page: number, topic?: string, topicHref?: string ): PageCrumb[] {
  const crumbs: PageCrumb[] = [ { name: 'Home', href: '/' }, { name: 'Blog', href: '/blog/' } ];
  if ( topic ) crumbs.push( { name: topic, href: topicHref } );
  if ( page > 1 ) crumbs.push( { name: `Page ${page}` } );
  // The last crumb is the current page: Blog on /blog/, or the topic on its first page.
  else delete crumbs[ crumbs.length - 1 ].href;
  return crumbs;
}

export const shopProductCrumbs = ( name: string ): PageCrumb[] => [
  { name: 'Home', href: '/' }, { name: 'Shop', href: '/shop/' }, { name },
];
