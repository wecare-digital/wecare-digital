import type { GetStaticProps } from 'next';
import BlogIndexView from '../../components/BlogIndexView';
import BlogIndexHead from '../../components/BlogIndexHead';
import { blogIndexProps, type BlogIndexPageProps } from '../../lib/blog-index-props';

/**
 * /blog/ — page 1 of the blog index.
 *
 * THIN ON PURPOSE. This page used to be 250 lines of markup, styles and filtering over all
 * 834 posts in one document; it is now a route that says "page 1". The view lives in
 * components/BlogIndexView.tsx, the head in components/BlogIndexHead.tsx and the data in
 * lib/blog-index-props.ts, all three shared with /blog/page/[page].tsx - two routes render
 * the identical page and a copy of any of it would drift. Read BlogIndexView's docblock for
 * why the blog is paginated at all.
 *
 * PAGE 1 IS HERE AND NOT AT /blog/page/1/. Two URLs serving the same 24 cards is duplicate
 * content, and /blog/ is the one in the sitemap, the mega-menu and every existing inbound
 * link. getStaticPaths in the sibling route therefore starts at 2, and blogPageHref() knows
 * to send page 1 here.
 */
export default function BlogIndex ( props: BlogIndexPageProps ) {
  return (
    <>
      <BlogIndexHead page={ props.page } totalPages={ props.totalPages } posts={ props.posts } />
      <BlogIndexView { ...props } />
    </>
  );
}

// Static-export content refresh marker: 2026-09-28 Gastronomy batch 001.
// Publishing to the native blog changes the source of truth; a new frontend build snapshots
// the latest published posts into /blog/, /blog/page/N/ and /post/[slug]/ static pages.
export const getStaticProps: GetStaticProps<BlogIndexPageProps> = async () => ( {
  props: await blogIndexProps( 1 ),
} );
