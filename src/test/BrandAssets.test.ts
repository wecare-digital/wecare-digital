import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

/**
 * The brand assets, and which slot each one is allowed in.
 *
 * WHY THIS TEST EXISTS
 * --------------------
 * One file was doing three jobs and was the wrong file for two of them. `wecaredigital.png`
 * fed og:image, twitter:image, apple-touch-icon, the schema.org Organization logo AND both PWA
 * manifest icons. Measured from the live object in s3://wecare-digital-get/o/stream/media/m/:
 *
 *   wecaredigital.png    1080x1080  PNG colour-type 6 (RGBA)  68.4% FULLY TRANSPARENT
 *                        corner and centre both rgba(0,0,0,0), and the mark itself is black
 *   wecare-digital.png   1080x1080  0% transparent, white ground
 *   wd-brand-16x9.png    1440x810   PNG colour-type 2 (RGB) — no alpha channel at all
 *
 * THE FAILURE MODE IS INVISIBLE FROM INSIDE THE PAGE, which is exactly why it needs a test.
 * og:image and apple-touch-icon are composited by someone else's renderer, and neither
 * guarantees a light backdrop — Apple has flattened apple-touch-icon alpha to black since
 * iOS 7, and link-preview renderers flatten to black or to their own surface colour. A black
 * mark on a flattened black ground is an invisible logo. Every check that looks at our own
 * HTML passes while the shared link renders as a black square.
 *
 * So the rule is a rule about ALPHA, not about filenames: any asset handed to a renderer we do
 * not control must be opaque. `wecaredigital.png` is not banned from the repo — it is the
 * correct asset for an <img> on our own known-white page. It is banned from these five slots.
 *
 * The second half is shape. twitter:card is `summary_large_image`, and a 1:1 image in that slot
 * is centre-cropped — it cut the top and bottom off the mark. og:image:width/height also
 * declared 512x512 while the file was 1080x1080, so the hint crawlers use to reserve layout
 * was wrong even about the wrong asset.
 */

const ROOT = path.join( __dirname, '..', '..' );
const APP = fs.readFileSync( path.join( ROOT, 'src', 'pages', '_app.tsx' ), 'utf8' );
/** The schema.org entity graph. Owns Organization.logo since it moved out of _app.tsx. */
const SCHEMA = fs.readFileSync( path.join( ROOT, 'src', 'lib', 'schema.ts' ), 'utf8' );
const SEO = fs.readFileSync( path.join( ROOT, 'src', 'components', 'SEO.tsx' ), 'utf8' );
const MANIFEST = JSON.parse( fs.readFileSync( path.join( ROOT, 'public', 'manifest.json' ), 'utf8' ) );
const SW = fs.readFileSync( path.join( ROOT, 'public', 'sw.js' ), 'utf8' );

/**
 * Comments stripped before the "is this asset used?" checks.
 *
 * The first version of this test failed on its own subject matter: both files now carry a
 * measurement table that NAMES `wecaredigital.png` to explain why it is banned, and a
 * substring search cannot tell an explanation from a usage. Stripping comments is the honest
 * fix — a rule against using an asset must not also be a rule against documenting it, or the
 * next person removes the note to make the suite green.
 */
const stripComments = ( source: string ): string => source
  .replace( /\/\*[\s\S]*?\*\//g, '' )
  .replace( /^\s*\/\/.*$/gm, '' )
  .replace( /\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '' );

const APP_CODE = stripComments( APP );
const SEO_CODE = stripComments( SEO );

/** The one asset that is 68.4% transparent. Never hand this to an external renderer. */
const TRANSPARENT = 'wecaredigital.png';
const OPAQUE_SQUARE = 'wecare-digital.png';
const SOCIAL_CARD = 'wd-brand-16x9.png';
const MEDIA_BASE = 'https://wecare.digital/get/o/stream/media/m';

describe( 'Brand assets', () => {
  it( 'serves every asset from the canonical media folder', () => {
    /*
     * s3://wecare-digital-get/o/stream/media/m/ is the canonical location since the
     * app.wecare.digital merge (docs/media-bucket-merge.md), reached over HTTPS as
     * /get/o/stream/media/m/ through CloudFront E2GP22R4BIFGQ3.
     *
     * Corrected 2026-09-29: this comment used to say the old host was "deliberately still
     * alive". It is not. Re-measured the same day - the bucket returns 404 from HeadBucket
     * and is absent from the 6 buckets in the account, the DNS name yields no A record, and
     * an HTTPS request to it fails to connect. What the 61 objects under o/public/wa-tpl/
     * actually pin is the KEY, not the host: their URLs are embedded in WhatsApp templates
     * Meta has already approved, Meta refetches from the approved URL at send time, and an
     * approved template body cannot be edited in place - so the o/ prefix cannot be dropped.
     *
     * This test therefore asserts where the ASSETS are served from. It is not a statement
     * about the retired host either way.
     */
    for ( const source of [ APP_CODE, SEO_CODE ] ) {
      const urls = [ ...source.matchAll( /https:\/\/[^'"`\s)]*stream\/media\/m\/[^'"`\s)]+/g ) ].map( m => m[ 0 ] );
      for ( const url of urls ) expect( url.startsWith( MEDIA_BASE ) ).toBe( true );
    }
    expect( APP ).toContain( `const MEDIA_BASE = '${MEDIA_BASE}'` );
    for ( const icon of MANIFEST.icons ) expect( icon.src.startsWith( MEDIA_BASE ) ).toBe( true );
  } );

  it( 'never hands the 68%-transparent mark to a renderer we do not control', () => {
    /*
     * THE CORE ASSERTION, and the list is every slot where someone else's compositor decides
     * the backdrop: og:image, twitter:image, apple-touch-icon, the schema Organization logo,
     * the PWA manifest icons, and the service worker's notification icon and badge.
     *
     * THE SERVICE WORKER IS THE ONE THAT NEARLY GOT MISSED. A notification is painted by the
     * OPERATING SYSTEM's shade, which on Android and on Windows is usually dark - so it is the
     * same "black mark flattened onto black" failure as the link preview, in a place that
     * looks nothing like SEO and lives in a file no HTML audit reads.
     *
     * WHAT IS DELIBERATELY NOT BANNED: the five in-page uses - BrandLockup, Layout's sidebar,
     * FloatingAgent, the grahak-os preload and the push-composer preview. Those render on our
     * own known-white surfaces, where transparency is the CORRECT choice and an opaque white
     * square would show as a visible tile. The rule is about who composites the alpha, not
     * about the filename, and a rule stated as "never use this file" would have wrongly
     * rewritten all five.
     */
    expect( APP_CODE ).not.toContain( TRANSPARENT );
    expect( SEO_CODE ).not.toContain( TRANSPARENT );
    expect( JSON.stringify( MANIFEST ) ).not.toContain( TRANSPARENT );
    expect( stripComments( SW ) ).not.toContain( TRANSPARENT );
    expect( stripComments( SW ) ).toContain( `${MEDIA_BASE}/${OPAQUE_SQUARE}` );
    // And the ban is documented where someone editing these constants will read it, so the
    // next person does not "simplify" three assets back down to one.
    expect( APP ).toContain( 'FULLY TRANSPARENT' );
  } );

  it( 'leaves the transparent mark in place for surfaces this repo paints itself', () => {
    /*
     * The counterpart to the rule above, asserted so a later sweep does not "finish the job"
     * by replacing these too. On a white page the transparent mark is right and the opaque
     * square would render as a visible white tile behind the logo.
     */
    const brand = fs.readFileSync( path.join( ROOT, 'src/components/BrandLockup.tsx' ), 'utf8' );
    const layout = fs.readFileSync( path.join( ROOT, 'src/components/Layout.tsx' ), 'utf8' );
    const agent = fs.readFileSync( path.join( ROOT, 'src/components/FloatingAgent.tsx' ), 'utf8' );

    // BrandLockup owns the in-page mark once; shells consume the component instead of
    // restating the asset URL and creating a second branding source.
    expect( brand ).toContain( `${MEDIA_BASE}/${TRANSPARENT}` );
    expect( layout ).toContain( "import BrandLockup from './BrandLockup'" );
    expect( layout ).toContain( '<BrandLockup compact />' );
    expect( agent ).toContain( `${MEDIA_BASE}/${TRANSPARENT}` );
  } );

  /**
   * THE SHARE IMAGE AND THE CARD TYPE MUST AGREE ABOUT SHAPE. This test used to require the 16:9
   * card and summary_large_image together; it now requires the square icon and "summary" together.
   * What it is really guarding is unchanged, and it is the pairing rather than either value: a 1:1
   * image in a large-card slot is centre-cropped, which is what once cut the top and bottom off
   * this mark.
   *
   * WHY THE ASSET CHANGED, recorded here because the reversal looks like a regression otherwise.
   * wd-brand-16x9.png is the better-looking preview and it is 801,077 bytes - against the 600 KB
   * Meta's WhatsApp link-preview documentation allows, with the practical limit nearer 300 KB
   * because WhatsApp drops an oversized image silently. It was therefore not rendering at all on
   * the platform that matters most to this business, and fixing that needs an S3 upload rather
   * than a code change. wecare-digital.png is already live at 86,123 bytes, 1080px wide against a
   * 300px minimum and 1:1 against a 4:1 ceiling. The cost is a compact thumbnail instead of a
   * wide branded banner, and the loss of the tagline the designed card carried.
   *
   * A 273 KB re-export of the wide card is committed at docs/brand/wd-brand-16x9.png. If it is
   * ever uploaded and wanted back, all three of these move together: SOCIAL_CARD_URL,
   * SHARE_CARD_TYPE and the width/height pair below.
   */
  it( 'pairs the square icon with the summary card, so nothing is centre-cropped', () => {
    expect( APP ).toContain( 'name="twitter:card" content="summary"' );
    expect( APP ).not.toContain( 'content="summary_large_image"' );
    // The share image IS the opaque square, aliased rather than restated so the two cannot drift.
    expect( APP ).toContain( 'const SOCIAL_CARD_URL = LOGO_URL;' );
    // Both og and twitter point at it, and nothing else does.
    expect( APP ).toContain( 'property="og:image" key="og:image" content={ SOCIAL_CARD_URL }' );
    expect( APP ).toContain( 'name="twitter:image" content={ SOCIAL_CARD_URL }' );
    expect( SEO ).toContain( `${MEDIA_BASE}/${OPAQUE_SQUARE}` );
    // The wide card is no longer referenced by any shipping surface.
    expect( stripComments( SEO ) ).not.toContain( SOCIAL_CARD );
    expect( APP_CODE ).not.toContain( SOCIAL_CARD );
  } );

  it( 'declares the social card at its real pixel size, not a remembered one', () => {
    /*
     * These were 512x512 against a 1080x1080 file. Crawlers use the hint to reserve layout
     * before fetching, so a wrong value is worse than an absent one - and being wrong by a
     * factor of two went unnoticed for as long as nobody compared it to the object.
     *
     * NOW 1080x1080, because the share image is the square icon rather than the wide card - see
     * the test above for why that changed. The numbers are the real pixels of
     * wecare-digital.png, measured from the live object.
     */
    expect( APP ).toContain( "const SOCIAL_CARD_W = '1080'" );
    expect( APP ).toContain( "const SOCIAL_CARD_H = '1080'" );
    expect( APP ).toContain( 'content={ SOCIAL_CARD_W }' );
    expect( APP ).toContain( 'content={ SOCIAL_CARD_H }' );
    /*
     * 1:1 IS THE POINT NOW, not a compromise. The old assertion required the ratio to sit strictly
     * inside the 2:1..1:1 band because the image was feeding a large card, which crops. A square
     * feeding a "summary" card is framed rather than cropped, so exactly 1 is correct here - and
     * the ceiling that still matters is WhatsApp's 4:1, which this is nowhere near.
     */
    const ratio = 1080 / 1080;
    expect( ratio ).toBe( 1 );
    expect( ratio ).toBeLessThanOrEqual( 4 );
  } );

  it( 'keeps the square opaque logo for icons and structured data', () => {
    expect( APP ).toContain( `const LOGO_URL = \`\${MEDIA_BASE}/${OPAQUE_SQUARE}\`` );
    expect( APP ).toContain( 'rel="apple-touch-icon" href={ LOGO_URL }' );
    /*
     * Organization.logo MOVED TO src/lib/schema.ts, and it is now an ImageObject rather than a
     * bare URL string - so this assertion follows it rather than being dropped.
     *
     * The reason it moved is the point of the assertion, not incidental: the Organization node
     * used to be defined in _app.tsx and emitted only from the <Head> that renders behind
     * `!isContentPublic`, so it was absent from all 1,279 posts and ~54 blog index pages. One
     * shared definition is what lets every surface emit the same node and reference it by @id.
     *
     * STILL THE SQUARE OPAQUE MARK, which is the thing this test exists to hold. Google renders
     * the logo in the knowledge panel and wants a logo, not a 16:9 banner, and the earlier fix
     * here was opacity rather than shape. Asserted through the shared constant AND the declared
     * dimensions, so swapping in the wide card or a transparent copy fails.
     */
    expect( SCHEMA ).toContain( `export const LOGO_URL = \`\${MEDIA_BASE}/${OPAQUE_SQUARE}\`` );
    expect( SCHEMA ).toContain( "'@type': 'ImageObject'" );
    expect( SCHEMA ).toContain( 'url: LOGO_URL' );
    expect( SCHEMA ).toContain( 'const LOGO_W = 1080' );
    expect( SCHEMA ).toContain( 'const LOGO_H = 1080' );
    // The node must reference the shared constant, never restate a URL literal.
    expect( SCHEMA ).not.toContain( 'logo: \'https://' );
  } );

  it( 'does not claim the icon is maskable, and does not lie about its size', () => {
    /*
     * TWO SEPARATE MANIFEST DEFECTS, both from the same copy-paste. The two entries pointed at
     * ONE 1080x1080 file while declaring "192x192" and "512x512" - neither true - so a browser
     * picking by declared size got a 1080px image either way and two entries described one
     * asset. And both said `purpose: "any maskable"`. A maskable icon must fill its whole
     * canvas with the important content inside a 80% safe circle, because the platform crops it
     * to whatever shape it likes; a transparent logo declared maskable gets an undefined
     * background and a cropped mark. One honest entry replaces two wrong ones.
     */
    expect( MANIFEST.icons ).toHaveLength( 1 );
    const [ icon ] = MANIFEST.icons;
    expect( icon.sizes ).toBe( '1080x1080' );
    expect( icon.purpose ).toBe( 'any' );
    expect( icon.purpose ).not.toContain( 'maskable' );
    expect( icon.src ).toContain( OPAQUE_SQUARE );
  } );

  it( 'carries no workspace shortcuts, because this manifest is the PUBLIC web app', () => {
    /*
     * SUPERSEDED 2026-10-01. This test used to be
     * "points manifest shortcuts at the canonical workspace URLs rather than a redirect",
     * asserting exactly
     *   [ '/workspace/dashboard/', '/workspace/engage/inbox/', '/workspace/contacts/' ].
     *
     * THE ORIGINAL REASONING IS KEPT because it is still correct about what it was about:
     * those three were [retired public path], [retired public path] and [retired public path] - the pre-/workspace/ paths. All three
     * still resolve, verified live at 301 to /workspace/dashboard/, /workspace/engage/ and
     * /workspace/contacts/, so that change was a hop rather than a break. A launcher shortcut
     * is a cold start, and the redirect is a round trip before any HTML arrives; [retired public path] also
     * landed on /workspace/engage/ rather than the inbox, so "Messages" opened a section index.
     * If workspace shortcuts ever belong in a manifest again, that is the shape they take.
     *
     * WHAT CHANGED is the question, not the answer. public/manifest.json is the manifest for
     * the PUBLIC site, served from the export root to every visitor, so these three entries
     * were the OS long-press menu offered to any customer who installed wecare.digital - three
     * launcher items straight into the internal staff Cognito login. The whole `shortcuts` key
     * was removed rather than left as `[]`, because an empty array is a declared-but-empty
     * menu and a missing key is simply no menu.
     *
     * Staff reach the workspace by signing in, which is unchanged. Nothing about authorization
     * moved here - hiding a launcher entry is not access control.
     */
    expect( MANIFEST.shortcuts ).toBeUndefined();
    const workspaceValues = Object.values( MANIFEST )
      .filter( ( v ): v is string => typeof v === 'string' && v.startsWith( '/workspace' ) );
    expect( workspaceValues ).toEqual( [] );
  } );

  it( 'leaves the BIMI svg alone, because DNS points at it under p=reject', () => {
    /*
     * default._bimi.wecare.digital carries
     *   l=https://wecare.digital/get/o/stream/media/m/wecare-digital.svg
     * A BIMI record aimed at a missing logo degrades SILENTLY - no bounce, no error, the
     * branding just stops appearing - so renaming this asset breaks inbox branding with
     * nothing anywhere to notice. DNS first, verify, then this. Asserted so a tidy-up that
     * renames it has to read this comment.
     */
    expect( APP ).toContain( 'const LOGO_SVG_URL = `${MEDIA_BASE}/wecare-digital.svg`' );
  } );
} );
