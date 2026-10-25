/**
 * The approved post merges from config/blog-merges.json, for the build's Node generators.
 *
 * generate-blog-search-index.js and generate-blog-rss.js fetch /api/seo-tools/blog-public on
 * their own, so each must drop a merged-away post exactly as src/lib/public-blog.ts does for the
 * pages. generate-llms-txt.js reads the written search index, so it inherits the exclusion.
 * Otherwise the search index, the feed and llms.txt would keep advertising a URL that answers 301.
 *
 * Read with fs rather than a JSON import so it needs no import-attribute support.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const MERGES_FILE = path.join( path.dirname( fileURLToPath( import.meta.url ) ), '..', 'config', 'blog-merges.json' );

/** Slugs retired by an approved merge. A malformed file fails the build rather than being skipped. */
export function mergedAwaySlugs () {
  const { merges } = JSON.parse( fs.readFileSync( MERGES_FILE, 'utf8' ) );
  if ( !Array.isArray( merges ) ) throw new Error( `${ MERGES_FILE }: "merges" must be an array` );
  return new Set( merges.map( merge => merge.from ) );
}
