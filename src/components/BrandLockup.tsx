import React from 'react';

const LOGO_URL = 'https://wecare.digital/get/o/stream/media/m/wecaredigital.png';

interface BrandLockupProps {
  compact?: boolean;
  suffix?: React.ReactNode;
  className?: string;
}

/**
 * `compact` IS NOW IMPLEMENTED. It sat in the interface unused, so every consumer got the
 * header's 60px/23px scale - which is why the footer's signature was exactly as large as
 * the header's primary brand and the page had no brand hierarchy. Compact steps the lockup
 * down to 44px/18px for secondary placements (the footer) while keeping the identical
 * shape: same logo, same two-line split on the dot, same red accent. Size is the only
 * difference, so the two read as one brand at two levels rather than as two brands.
 */
/**
 * data-wc-no-translate: THE WORDMARK IS A COMPANY NAME AND WAS BEING TRANSLATED.
 *
 * SupportWidget's walker collects text nodes and rewrites nodeValue in place. This lockup
 * renders "WECARE" and "DIGITAL" as two separate text nodes (the two-line split below), and
 * neither was protected, so both were collected and sent to the provider. Measured on the
 * built export before this attribute existed: 4 translatable brand nodes on every route -
 * two in the header lockup, two in the footer's compact one.
 *
 * What a visitor saw, from the live site: Arabic rendered the header as "نحن نهتم. رقمي" -
 * a literal translation of "we care" and "digital" - and Hindi rendered "WECARE." followed
 * by "डिजिटल", so the wordmark came apart mid-brand. The provider is behaving correctly;
 * it was handed two ordinary English words with no indication they were a name.
 *
 * ON THE ROOT, NOT ON .brand-copy. The flag has to cover every text node this component can
 * produce, and `suffix` is a ReactNode a consumer can pass in - putting the attribute on the
 * inner wordmark span would leave anything a caller appends unprotected. The walker takes the
 * NEAREST flag, so a consumer that genuinely wants a translatable suffix can still opt back
 * in with data-wc-translate="true" on it.
 *
 * WHY NOT A TRANSLATABLE DESCRIPTOR. BrandBadge.tsx documents the related trap: the flag also
 * catches words sitting beside the brand name, which then never translate. There are none
 * here - this component renders the wordmark and nothing else - so the exclusion is exactly
 * the brand and costs no coverage. That is measured rather than assumed: translatecheck.js
 * asserts the header menu and footer still translate in the same run that asserts this.
 *
 * Asserted by tools/browser/translatecheck.js and BrandLockup.test.tsx.
 */
const BrandLockup: React.FC<BrandLockupProps> = ( { className = '', compact = false } ) => (
  <span className={ `brand-lockup full ${compact ? 'compact' : ''} ${className}`.trim() } data-wc-no-translate="true">
    {/* width/height ARE THE INTRINSIC SIZE, NOT THE RENDERED SIZE, and that is the point.
        This img shipped with neither, so until the stylesheet applied, the browser knew nothing
        about the file's proportions and reserved a 0x0 box for it - on the header lockup, which
        is the first element on every public page. The CSS below sets height:60px;width:auto, so
        the RENDERED width is derived from the aspect ratio; with no ratio available there is
        nothing to derive it from. Giving the real 1080x1080 lets the browser compute 60x60
        before a single byte of the image arrives, and the CSS still owns the display size.
        Not the rendered numbers: they are 60px, 54px, 44px and 40px across two variants and two
        breakpoints, and an attribute can only hold one pair. The intrinsic size is the one value
        that is true in every slot, which is what these attributes are specified to carry.
        decoding="async" so a 1080px PNG being scaled down to 60 cannot hold up first paint. */}
    {/* loading IS TIED TO `compact`, because compact is the footer and the footer is below
        the fold on every page that uses it. The header and the dashboard rail both render
        the default variant and are the first paint, so those stay eager; lazy-loading the
        header lockup would delay the one copy that is immediately visible.
        Footer.tsx is the only consumer of compact - Header.tsx and Layout.tsx both use the
        default - so this is a precise split rather than a guess about placement.
        WHAT THIS DOES NOT FIX: the object itself is 1080x1080 and 30,226 bytes, and it is
        painted into a 60px box (44px compact, 40px on a compact phone). That is roughly an
        18x linear oversample, and no amount of markup changes it - the CDN serves no
        derivatives (?w= is ignored and an Accept:image/webp request still returns the same
        30,226-byte PNG, both measured). Fixing the weight means uploading a resized object
        to s3://wecare-digital-get/o/stream/media/m/, which this repo cannot perform - the
        same constraint already recorded for wd-brand-16x9.png in _app.tsx. Repointing this
        to a repo-local copy is NOT the workaround: BrandAssets.test.ts documents
        wecaredigital.png as the correct transparent asset for an <img> on our own white
        page, and moving brand media out of the canonical bucket to save 27 kB would trade a
        measured problem for an architectural one. */}
    <img
      src={ LOGO_URL }
      alt=""
      aria-hidden="true"
      width={ 1080 }
      height={ 1080 }
      decoding="async"
      loading={ compact ? 'lazy' : 'eager' }
    />
    {/* WECARE.DIGITAL, split across the same two lines the wordmark has always used.
        The owner asked for "WECARE.DIGITAL" to become WECARE.DIGITAL everywhere; this
        lockup was the one place where that is a shape decision rather than a string
        swap, because it is a two-line stacked wordmark, not a sentence. Splitting on
        the dot keeps the stacked silhouette and the existing two-span structure -
        collapsing it to one long line would have roughly doubled the lockup's width
        and pushed the nav trigger toward the middle of the header. */}
    {/* Split after the dot, with the dot itself carrying the accent - matching the
        owner's reference lockup, which sets WECARE. on the first line and DIGITAL on
        the second with the full stop picked out in colour.
        THE DOT HAS BEEN THROUGH THREE COLOURS, and the reasoning matters because each
        change fixed the previous one's actual defect.
        It was lime (#d1f470), which the owner called "not viable" - correctly: lime on
        white measures about 1.4:1, so at 26px a single full stop in it was invisible.
        Lime is a fill colour here, sitting behind #1a3a2a type; it was never going to
        work AS a mark.
        It then became dark red (#991b1b) at about 7.5:1, which solved legibility and
        introduced a subtler problem the owner then named - asking for something "more
        visible, like neon". At 26px, one glyph of #991b1b reads as near-black: it is
        high-contrast but it does not read as a COLOUR, so the accent stopped registering
        as an accent. Contrast and vividness are not the same measurement.
        It is now #ff0040. That measures about 3.9:1 on white - lower than the dark red,
        deliberately, and still comfortably past the 3:1 that WCAG asks of a non-text
        graphic, which is the right bar for a decorative glyph in a wordmark rather than
        the 4.5:1 for body text. The gain is that it is unmistakably red on screen instead
        of reading as dark ink.
        An earlier pass split this as WECARE / .DIGITAL, which put the dot at the head of
        the second line where it reads as a leading separator rather than as the end of
        a sentence. The dot belongs to WECARE. */}
    <span className="brand-copy">
      <span>WECARE<span className="brand-dot">.</span></span>
      <span className="brand-stack">DIGITAL</span>
    </span>
    <style jsx>{ `
      /* BASE SCALE stays conservative because this component is also used outside the public
         shell (for example the workspace sidebar). Public Header/Footer opt into their larger
         shared variants below so every PUBLIC route inherits the same stronger branding without
         silently resizing internal workspace chrome. */
      .brand-lockup{display:inline-flex;align-items:center;gap:10px;flex-wrap:nowrap;min-width:0}
      .brand-lockup img{height:60px;width:auto;border-radius:12px;flex-shrink:0;display:block;object-fit:contain}
      .brand-copy{display:flex;flex-direction:column;justify-content:center;line-height:1.08}
      .brand-copy>span{font-size:23px;font-weight:800;color:#1a1a1a;letter-spacing:-.5px}
      /* PUBLIC HEADER: common across all public pages. 64px/24px strengthens the brand inside
         the existing 108px desktop header without changing header height. The phone rule below
         uses 58px/22px on normal smartphones and falls back to 54px/21px at <=340px so the
         menu + 44px shopping-bag target still fit the measured narrow-foldable row. */
      .brand-lockup.public-header img{height:64px}
      .brand-lockup.public-header .brand-copy>span{font-size:24px}
      /* The accent is on the dot only, and it is the one place this site uses red. Kept to
         a single glyph so it never competes with lime for meaning: lime marks interaction
         and state, this marks the brand.
         No glow, deliberately. A text-shadow halo is the usual way to make a colour look
         "neon", and at 26px on white it would just blur the one glyph that has to stay
         crisp - the saturation is doing the work instead. */
      .brand-dot{color:#ff0040}
      .brand-stack{display:flex;align-items:center;gap:2px}
      /* Mobile steps DOWN from desktop, and it has to move whenever desktop does.
         Desktop went 68 -> 60px logo and 26 -> 23px type; mobile was 60px/24px, which
         would have left the phone logo identical to the desktop one and the phone
         wordmark LARGER than the desktop wordmark - the ladder inverted. Scaled by the
         same ~0.88 to 54px/21px, which still clears the mobile header's 68px content box
         (96px height less 14px padding each side). */
      /* COMPACT remains the generic secondary scale for non-public consumers. The public
         footer opts into 48px/19px below, still clearly subordinate to the public header. */
      .brand-lockup.compact img{height:44px;border-radius:10px}
      .brand-lockup.compact .brand-copy>span{font-size:18px;letter-spacing:-.4px}
      .brand-lockup.public-footer.compact img{height:48px}
      .brand-lockup.public-footer.compact .brand-copy>span{font-size:19px}

      @media(max-width:767px){
        .brand-lockup{gap:8px}
        .brand-lockup img{height:54px;border-radius:10px}
        .brand-copy>span{font-size:21px}
        .brand-lockup.compact img{height:40px;border-radius:9px}
        .brand-lockup.compact .brand-copy>span{font-size:16px}
        /* Public common-shell scale on normal smartphones. */
        .brand-lockup.public-header img{height:58px}
        .brand-lockup.public-header .brand-copy>span{font-size:22px}
        .brand-lockup.public-footer.compact img{height:44px}
        .brand-lockup.public-footer.compact .brand-copy>span{font-size:18px}
      }
      /* NARROW PHONE / FOLDED DEVICE FALLBACK. Keep the measured pre-increase header scale so
         280-340px devices retain room for the menu trigger and 44px shopping-bag control. The
         footer has no equivalent horizontal pressure and keeps its larger mobile scale. */
      @media(max-width:340px){
        .brand-lockup.public-header img{height:54px}
        .brand-lockup.public-header .brand-copy>span{font-size:21px}
      }
      /* 200%-ZOOM FALLBACK, below the narrowest device that ships (the 280px Galaxy Fold
         cover), so only a zoomed layout reaches it. Under 275px the wordmark no longer fits
         beside the 46px menu trigger and the 44px bag: measured on the built header, it ran
         under both, and the trigger and the bag overlapped each other by up to 26px at 160px,
         so a tap could land on the wrong control. The header keeps the mark alone there - the
         home link's aria-label still names the site - and under 170px the mark steps down to
         the 44px tap floor so the three controls still fit side by side. */
      @media(max-width:274px){
        .brand-lockup.public-header .brand-copy{display:none}
      }
      @media(max-width:169px){
        .brand-lockup.public-header img{height:44px}
      }
    ` }</style>
  </span>
);

export default BrandLockup;
