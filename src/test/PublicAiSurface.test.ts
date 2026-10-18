import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * HOLDS THE DESCRIPTIONS OF THE PUBLIC SURFACE IN STEP.
 *
 * The site's public page set is stated in four places, in three languages, because the
 * consumers cannot share a module: a React allowlist, a Node sitemap generator, a Node
 * llms.txt generator, and a Python Lambda.
 *
 *   src/pages/_app.tsx                PUBLIC_PAGE_META + the render chains (render allowlist)
 *   scripts/generate-sitemap.js       PUBLIC_EXACT                        (crawl allowlist)
 *   config/public-pages.json          the catalogue        (llms.txt + the MCP server's zip)
 *   amplify/functions/ai/mcp/         READ_ONLY_TOOLS, PROTOCOL_VERSIONS  (what /mcp serves)
 *
 * The retired human-readable AI documentation page is no longer part of this surface.
 *
 * Every remaining pair can drift, and each drift is silent in its own way:
 *
 *   catalogue has a page _app.tsx does not    -> llms.txt advertises a URL that serves the
 *                                                staff sign-in shell at HTTP 200
 *   _app.tsx has a page the catalogue lacks   -> the page is invisible to every agent
 *   ai_surface disagrees with the handler     -> /llms.txt advertises tools that do not exist,
 *                                                and an operator configures a client to them
 *   robots.txt AI group loses a Disallow      -> a named crawler is granted /workspace/
 *
 * Nothing catches any of those at runtime. PublicRouteRegistration.test.ts already guards the
 * first two columns; this file guards the rest, and follows its technique of reading source as
 * TEXT rather than importing it - importing _app.tsx would execute Amplify.configure at module
 * scope, and the values under assertion are literals in the file rather than runtime exports.
 */

const ROOT = process.cwd();
const APP_PATH = path.join( ROOT, 'src', 'pages', '_app.tsx' );
const SITEMAP_PATH = path.join( ROOT, 'scripts', 'generate-sitemap.js' );
const CATALOG_PATH = path.join( ROOT, 'config', 'public-pages.json' );
const ROBOTS_PATH = path.join( ROOT, 'public', 'robots.txt' );
const MCP_HANDLER_PATH = path.join( ROOT, 'amplify', 'functions', 'ai', 'mcp', 'handler.py' );
const REDIRECTS_PATH = path.join( ROOT, 'scripts', 'provision_legacy_redirects.py' );

const appSource = fs.readFileSync( APP_PATH, 'utf8' );
const sitemapSource = fs.readFileSync( SITEMAP_PATH, 'utf8' );
const robotsSource = fs.readFileSync( ROBOTS_PATH, 'utf8' );
const mcpSource = fs.readFileSync( MCP_HANDLER_PATH, 'utf8' );
const catalog = JSON.parse( fs.readFileSync( CATALOG_PATH, 'utf8' ) );
const aiSurface = catalog.ai_surface;

/** Keys of PUBLIC_PAGE_META, sliced the same way PublicRouteRegistration.test.ts does. */
const publicPageMeta = (): Map<string, string> => {
  const start = appSource.indexOf( 'const PUBLIC_PAGE_META' );
  expect( start, 'PUBLIC_PAGE_META not found in _app.tsx' ).toBeGreaterThan( -1 );
  const end = appSource.indexOf( '\nconst ', start + 10 );
  const block = appSource.slice( start, end === -1 ? undefined : end );
  const entries = new Map<string, string>();
  for ( const match of block.matchAll( /^\s*'(\/[a-z0-9-]+(?:\/[a-z0-9-]+)*)'\s*:\s*\{[^}]*description:\s*'((?:[^'\\]|\\.)*)'/gm ) ) {
    entries.set( match[ 1 ], match[ 2 ].replace( /\\'/g, "'" ) );
  }
  expect( entries.size, 'parsed no PUBLIC_PAGE_META entries — this guard needs updating' ).toBeGreaterThan( 5 );
  return entries;
};

/**
 * PUBLIC_EXACT from the sitemap generator.
 *
 * COMMENT LINES ARE STRIPPED FIRST, and they have to be. That declaration carries long
 * explanatory comments between its entries which themselves quote route paths - '[retired public path]'
 * and '[retired public path]', the two names /anew used to have. Matching the raw block picks up
 * 24 paths for 21 entries, so the comparison below would fail against a correct catalogue
 * and the obvious "fix" would be to add two dead routes to it.
 */
const publicExact = (): Set<string> => {
  const start = sitemapSource.indexOf( 'const PUBLIC_EXACT' );
  expect( start, 'PUBLIC_EXACT not found in generate-sitemap.js' ).toBeGreaterThan( -1 );
  const block = sitemapSource.slice( start, sitemapSource.indexOf( '] )', start ) )
    .split( '\n' )
    .filter( line => !line.trim().startsWith( '//' ) )
    .join( '\n' );
  return new Set( Array.from( block.matchAll( /'(\/(?:[a-z0-9-]+(?:\/[a-z0-9-]+)*)?)'/g ) ).map( m => m[ 1 ] ) );
};

/**
 * Routes either render chain admits by a bare pathname comparison.
 *
 * Both `isContentPublic` and `isPublic`, because a route on either one renders. Reading only
 * the second reports '/blog' as unregistered, which it is not - it qualifies through
 * isContentPublic because it declares its own <head> via BlogIndexHead.tsx.
 */
const renderChainLiterals = (): Set<string> => {
  const found = new Set<string>();
  for ( const name of [ 'const isContentPublic', 'const isPublic' ] ) {
    const start = appSource.indexOf( name );
    expect( start, `${name} not found in _app.tsx` ).toBeGreaterThan( -1 );
    const block = appSource.slice( start, appSource.indexOf( ';', start ) );
    for ( const match of block.matchAll( /router\.pathname === '([^']+)'/g ) ) found.add( match[ 1 ] );
  }
  expect( found.size, 'parsed no literal public routes out of _app.tsx' ).toBeGreaterThan( 2 );
  return found;
};

/** A `NAME = frozenset({...})` or `NAME = (...)` literal of strings from the Python handler. */
const pyStringSet = ( name: string ): Set<string> => {
  const start = mcpSource.indexOf( `${name} = ` );
  expect( start, `${name} not found in the MCP handler` ).toBeGreaterThan( -1 );
  const block = mcpSource.slice( start, mcpSource.indexOf( '\n\n', start ) );
  const found = Array.from( block.matchAll( /"([^"]+)"/g ) ).map( m => m[ 1 ] );
  expect( found.length, `parsed no strings out of ${name}` ).toBeGreaterThan( 0 );
  return new Set( found );
};

const catalogPaths = new Set<string>( catalog.pages.map( ( p: { path: string } ) => p.path ) );

/** Disallow values inside the rule group a User-agent line belongs to. */
const disallowsForAgent = ( agent: string ): Set<string> => {
  const lines = robotsSource.split( '\n' ).map( line => line.trim() );
  const index = lines.findIndex( line => line.toLowerCase() === `user-agent: ${agent.toLowerCase()}` );
  expect( index, `robots.txt has no group for ${agent}` ).toBeGreaterThan( -1 );
  // A group is consecutive User-agent lines followed by rules, ending at the next
  // User-agent line that comes AFTER at least one rule.
  const out = new Set<string>();
  let seenRule = false;
  for ( let i = index; i < lines.length; i += 1 ) {
    const line = lines[ i ];
    if ( !line || line.startsWith( '#' ) ) continue;
    const isAgent = /^user-agent\s*:/i.test( line );
    if ( isAgent && seenRule ) break;
    if ( isAgent ) continue;
    if ( /^sitemap\s*:/i.test( line ) ) break;
    seenRule = true;
    const disallow = line.match( /^disallow\s*:\s*(.+)$/i );
    if ( disallow ) out.add( disallow[ 1 ].trim() );
  }
  return out;
};

// --------------------------------------------------------------------------- //

describe( 'the catalogue matches the allowlists that decide what is public', () => {
  it( 'is exactly what a fresh scan of the tree produces', () => {
    /**
     * THE ONE ASSERTION THAT MAKES THE REST SELF-MAINTAINING.
     *
     * `pages` is generated by scripts/generate-public-pages.js from the route files, the two
     * allowlists and src/content/*. Running it in --check mode here means the committed
     * catalogue cannot lag the tree: add, delete or reword a page and this fails until the
     * catalogue is regenerated, rather than /mcp quietly describing a site that no longer
     * exists. That is the failure [retired public path] already produced once - the rename landed
     * everywhere except the copy inside the Lambda's zip, and search_pages handed agents a
     * URL that 404s with nothing reporting it.
     *
     * Spawned rather than imported: the generator is an ESM script that calls process.exit,
     * and running it as a child process is also the exact command CI and the build run, so a
     * green test here means that command passes too.
     */
    let failure = '';
    try {
      execFileSync( process.execPath, [ 'scripts/generate-public-pages.js', '--check' ],
        { cwd: ROOT, encoding: 'utf8', stdio: [ 'ignore', 'pipe', 'pipe' ] } );
    } catch ( error ) {
      const spawned = error as { stdout?: string; stderr?: string };
      failure = `${spawned.stdout || ''}${spawned.stderr || ''}`;
    }
    expect( failure, failure ).toBe( '' );
  } );

  it( 'lists exactly the pages the sitemap allowlist does', () => {
    /**
     * PUBLIC_EXACT is the right comparison rather than PUBLIC_PAGE_META, because it is the
     * superset: it carries '/' and '/blog', which qualify through the render chains rather
     * than through the meta map.
     */
    expect( [ ...catalogPaths ].sort() ).toEqual( [ ...publicExact() ].sort() );
  } );

  it( 'reuses the description _app.tsx already publishes for each page', () => {
    /**
     * Not cosmetic. PUBLIC_PAGE_META.description feeds WebPage.description in the schema
     * graph, so a different sentence here means a crawler and a model reading llms.txt get
     * two different accounts of the same page - and the difference would be invisible in
     * both places. The generator reads it from there for exactly this reason; this asserts
     * the property rather than trusting the implementation that provides it.
     */
    const meta = publicPageMeta();
    const mismatched: string[] = [];
    for ( const page of catalog.pages ) {
      const expected = meta.get( page.path );
      if ( expected === undefined ) continue; // '/' and '/blog' have no meta entry
      if ( expected !== page.description ) {
        mismatched.push( `${page.path}\n    _app.tsx: ${expected}\n    catalogue: ${page.description}` );
      }
    }
    expect( mismatched, `descriptions disagree:\n  ${mismatched.join( '\n  ' )}` ).toEqual( [] );
  } );

  it( 'gives every catalogued page a route that actually renders', () => {
    /**
     * PUBLIC_PAGE_META or a render chain is the ONLY thing that makes a page render. A
     * catalogued route in neither serves the staff sign-in screen at HTTP 200 - "a 404 that
     * does not look like one" - while llms.txt and /mcp advertise it as content.
     */
    const renderable = new Set( [ ...publicPageMeta().keys(), ...renderChainLiterals() ] );
    for ( const page of catalog.pages ) {
      expect( renderable, `${page.path} is catalogued but renders no page` ).toContain( page.path );
    }
  } );

  it( 'puts every page in a declared group', () => {
    const groups = new Set( catalog.groups.map( ( g: { id: string } ) => g.id ) );
    for ( const page of catalog.pages ) expect( groups ).toContain( page.group );
  } );

  it( 'declares no empty group, so llms.txt cannot emit a bare heading', () => {
    for ( const group of catalog.groups ) {
      expect(
        catalog.pages.some( ( p: { group: string } ) => p.group === group.id ),
        `group '${group.id}' has no pages`,
      ).toBe( true );
    }
  } );
} );

describe( 'what the AI surface advertises matches what /mcp serves', () => {
  it( 'documents exactly the tools the handler advertises', () => {
    /**
     * Both directions. A tool added to the handler but not here leaves an undocumented public
     * capability; a tool listed here but absent there sends an operator to configure a client
     * against something that will answer "Unknown tool".
     *
     * READ_ONLY_TOOLS is a frozen allowlist in the handler, so a tool becoming callable and a
     * tool becoming documented are the same two-file edit. That is what keeps a side effect
     * off an unauthenticated route: it cannot arrive as one dict entry.
     */
    const documented = aiSurface.mcp_tools.map( ( tool: { name: string } ) => tool.name ).sort();
    expect( documented ).toEqual( [ ...pyStringSet( 'READ_ONLY_TOOLS' ) ].sort() );
  } );

  it( 'gives every documented tool a summary', () => {
    for ( const tool of aiSurface.mcp_tools ) expect( tool.summary.length ).toBeGreaterThan( 10 );
  } );

  it( 'lists exactly the resources the handler exposes', () => {
    const declared = aiSurface.mcp_resources.map( ( r: { uri: string } ) => r.uri ).sort();
    const served = Array.from( mcpSource.matchAll( /^\s{4}"(wecare:\/\/[^"]+)":/gm ) ).map( m => m[ 1 ] ).sort();
    expect( served.length, 'parsed no resource URIs out of the handler' ).toBeGreaterThan( 0 );
    expect( declared ).toEqual( served );
  } );

  it( 'advertises exactly the protocol versions the handler speaks', () => {
    expect( [ ...aiSurface.mcp_protocol_versions ].sort() )
      .toEqual( [ ...pyStringSet( 'PROTOCOL_VERSIONS' ) ].sort() );
  } );

  it( 'ships a client config that points at the endpoint it documents', () => {
    /**
     * The snippet is published verbatim into /llms.txt, so an operator pastes it into a client
     * without editing it. A config naming a different URL from mcp_endpoint would send every
     * client that trusts the snippet somewhere else.
     *
     * `type: "http"` is the Streamable HTTP transport. `sse` would attempt the deprecated
     * HTTP+SSE transport, which this server does not implement and which fails at the GET.
     */
    const servers = aiSurface.mcp_client_config.mcpServers;
    const entries = Object.values( servers ) as { type: string; url: string }[];
    expect( entries ).toHaveLength( 1 );
    expect( entries[ 0 ].url ).toBe( aiSurface.mcp_endpoint );
    expect( entries[ 0 ].type ).toBe( 'http' );
  } );

  it( 'states what the endpoint cannot do, in the file that feeds llms.txt', () => {
    /**
     * Kept as data rather than prose in the generator, because this is the part a reader is
     * most likely to assume rather than read. Every entry has to name a capability; an empty
     * or one-word list would satisfy a length check while saying nothing.
     */
    expect( aiSurface.mcp_cannot.length ).toBeGreaterThanOrEqual( 4 );
    for ( const limit of aiSurface.mcp_cannot ) expect( limit.length ).toBeGreaterThan( 15 );
  } );

  it( 'points at the apex path, not /api/mcp', () => {
    /**
     * robots.txt disallows /api/, and an MCP client is handed one URL and does not go
     * looking for another. Reaching the apex path needs the Amplify rewrite that
     * scripts/deploy_mcp_server.py installs.
     */
    expect( aiSurface.mcp_endpoint ).toBe( 'https://wecare.digital/mcp' );
    expect( aiSurface.mcp_endpoint ).not.toContain( '/api/' );
  } );
} );

describe( 'robots.txt does not grant a named AI crawler more than everyone else', () => {
  const wildcard = disallowsForAgent( '*' );

  it( 'gives the wildcard group the dashboard Disallows', () => {
    // Sanity-check the parser before trusting the comparison below.
    expect( wildcard ).toContain( '/workspace/' );
    expect( wildcard ).toContain( '/api/' );
  } );

  it.each( [
    'GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'ClaudeBot', 'Claude-User',
    'Claude-SearchBot', 'Google-Extended', 'PerplexityBot', 'Perplexity-User',
    'Applebot-Extended', 'meta-externalagent', 'Bytespider', 'cohere-ai',
    'DuckAssistBot', 'MistralAI-User',
  ] )( '%s is restricted at least as tightly as *', agent => {
    /**
     * THE FOOTGUN THIS EXISTS FOR. robots.txt has no inheritance: a named User-agent group
     * REPLACES the * group for that agent. So
     *
     *     User-agent: GPTBot
     *     Allow: /
     *
     * does not mean "same as everyone, and welcome" - it means GPTBot has no Disallow at
     * all, which grants it /workspace/, the authenticated dashboard that the * group is the
     * only thing holding out of the index. Welcoming a crawler by name and publishing the
     * internal route map is the same edit, and nothing else in the build would notice.
     */
    const theirs = disallowsForAgent( agent );
    for ( const rule of wildcard ) {
      expect( theirs, `${agent} is missing Disallow: ${rule}` ).toContain( rule );
    }
  } );

  it( 'still declares the sitemap', () => {
    expect( robotsSource ).toMatch( /^Sitemap:\s*https:\/\/wecare\.digital\/sitemap\.xml$/m );
  } );
} );

describe( 'the build actually produces the files being advertised', () => {
  const build = JSON.parse( fs.readFileSync( path.join( ROOT, 'package.json' ), 'utf8' ) ).scripts.build;

  it( 'regenerates the catalogue before anything reads it', () => {
    /**
     * Order, and it is the whole point of generating the file. generate-llms-txt.js and the
     * MCP deploy zip both READ config/public-pages.json, so the scan has to have run first or
     * the build publishes the previous page set. It runs before `next build` too, which is
     * deliberate: generate-llms-txt.js refuses to write when a catalogued page is missing from
     * the export, and that check only means something if the catalogue was settled first.
     */
    expect( build ).toContain( 'generate-public-pages.js' );
    expect( build.indexOf( 'generate-public-pages.js' ) ).toBeLessThan( build.indexOf( 'next build' ) );
    expect( build.indexOf( 'generate-public-pages.js' ) ).toBeLessThan( build.indexOf( 'generate-llms-txt.js' ) );
  } );

  it( 'runs the llms.txt generator after the blog search index', () => {
    /**
     * Order, not presence. The generator reads out/blog/search-index.json rather than
     * fetching /api/seo-tools/blog-public a fourth time during one build - that endpoint
     * returns the whole corpus as ~1 MB in about five seconds and is already the hottest
     * function in the fleet. Run it first and the article section silently vanishes.
     */
    expect( build ).toContain( 'generate-llms-txt.js' );
    expect( build.indexOf( 'generate-llms-txt.js' ) )
      .toBeGreaterThan( build.indexOf( 'generate-blog-search-index.js' ) );
  } );

  it( 'keeps the MCP catalogue out of the client bundle', () => {
    /**
     * resolveJsonModule would inline the entire catalogue - every description plus the
     * _comment blocks explaining the file to a human - into any chunk that imports it, and
     * JSON imports are not tree-shaken per key. That is why src/lib/ai-surface.ts existed at
     * all: it restated five values rather than importing 8 kB of commentary.
     *
     * The page it served is gone, so the correct state is that NOTHING under src/ imports the
     * catalogue. Asserted across the tree rather than on one file, because the next person to
     * want these values in a component will reach for the import.
     */
    const offenders: string[] = [];
    const walk = ( dir: string ) => {
      for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) ) {
        const full = path.join( dir, entry.name );
        if ( entry.isDirectory() ) { walk( full ); continue; }
        if ( !/\.(ts|tsx|js|jsx)$/.test( entry.name ) ) continue;
        const source = fs.readFileSync( full, 'utf8' );
        // An import or a require, not a mention: this very test names the file in prose, and
        // so does every comment explaining the arrangement.
        if ( /(?:^|\n)\s*import\s[^\n]*public-pages\.json/.test( source )
          || /require\(\s*['"][^'"]*public-pages\.json/.test( source ) ) {
          offenders.push( path.relative( ROOT, full ) );
        }
      }
    };
    walk( path.join( ROOT, 'src' ) );
    expect( offenders, `these import the catalogue into the bundle:\n  ${offenders.join( '\n  ' )}` )
      .toEqual( [] );
  } );
} );
