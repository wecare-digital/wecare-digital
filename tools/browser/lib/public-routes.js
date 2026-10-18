'use strict';

/**
 * Canonical public browser-audit route list.
 *
 * The public page catalogue is generated from the render + crawl allowlists and is already
 * guarded in CI. Browser audits must consume that catalogue rather than keeping another
 * hand-written route list that can retain deleted parent pages.
 */
const catalogue = require( '../../../config/public-pages.json' );

const PUBLIC_ROUTES = Object.freeze(
  catalogue.pages.map( page => page.path ),
);

module.exports = { PUBLIC_ROUTES };
