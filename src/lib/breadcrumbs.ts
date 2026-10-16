export interface PageCrumb {
  name: string;
  href?: string;
}

export function breadcrumbSchema( crumbs: PageCrumb[], canonical: string, identity: string = canonical ) {
  const url = new URL( canonical, 'https://wecare.digital' ).href;
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    '@id': `${new URL( identity, 'https://wecare.digital' ).href}#breadcrumb`,
    itemListElement: crumbs.map( ( crumb, index ) => ( {
      '@type': 'ListItem', position: index + 1, name: crumb.name,
      item: crumb.href ? new URL( crumb.href, url ).href : url,
    } ) ),
  };
}

/** Route-aware blog trail shared by the view and metadata, including topic pagination. */
export function blogCrumbs( page: number, topic?: string, topicHref?: string ): PageCrumb[] {
  const crumbs: PageCrumb[] = [ { name: 'Home', href: '/' }, { name: 'Blog', href: '/blog/' } ];
  if ( topic ) crumbs.push( { name: topic, href: topicHref } );
  if ( page > 1 ) crumbs.push( { name: `Page ${page}` } );
  else delete crumbs[ crumbs.length - 1 ].href;
  return crumbs;
}

export const shopProductCrumbs = ( name: string ): PageCrumb[] => [
  { name: 'Home', href: '/' }, { name: 'Shop', href: '/shop/' }, { name },
];
