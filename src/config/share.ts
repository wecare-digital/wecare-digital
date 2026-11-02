/**
 * Shared link-preview image and WhatsApp target for public content pages.
 * Keep MEDIA_BASE, SOCIAL_CARD_URL and SHARE_CARD_TYPE aligned with pages/_app.tsx.
 * The opaque square brand icon uses a summary card to avoid large-card cropping.
 */

/** Canonical media folder. Must stay byte-identical to MEDIA_BASE in pages/_app.tsx. */
export const MEDIA_BASE = 'https://wecare.digital/get/o/stream/media/m';

/** 1080x1080, opaque white ground, 86,123 bytes. The link-preview image for every public surface. */
export const SOCIAL_CARD_URL = `${MEDIA_BASE}/wecare-digital.png`;

/**
 * Declared at the asset's REAL pixel size. These were once 512x512 against a 1080x1080 file;
 * crawlers use the hint to reserve layout before fetching, so a wrong value is worse than none.
 * the pair is 1080x1080 because that is what the object at the URL above measures.
 */
export const SOCIAL_CARD_W = '1080';
export const SOCIAL_CARD_H = '1080';
export const SOCIAL_CARD_TYPE = 'image/png';

/**
 * THE CARD TYPE IS TIED TO THE IMAGE'S SHAPE, and that is the whole point of naming it here rather
 * than writing the string into three heads.
 *
 * "summary" renders a small square thumbnail beside the text, which is the correct frame for a 1:1
 * image. "summary_large_image" renders a wide banner and CENTRE-CROPS anything that is not roughly
 * 1.91:1 - so pairing it with this square icon would cut the top and bottom off the mark. That
 * exact mistake is what the previous asset review identified, and it is easy to reintroduce by
 * changing the image in one place and leaving the card type in another. Both now come from here.
 */
export const SHARE_CARD_TYPE = 'summary';

/**
 * og:image:alt is read out by screen readers on the platforms that render the card, so it
 * describes the image rather than repeating the page title - the title is already the next line
 * of the same card.
 */
export const SOCIAL_CARD_ALT = 'The WECARE.DIGITAL bag-and-heart mark';

export const SITE_ORIGIN = 'https://wecare.digital';

/**
 * WHATSAPP SHARE URL: api.whatsapp.com, NOT wa.me - and that is a correctness issue rather than
 * a preference.
 *
 * Both hosts accept the same ?text= parameter, but wa.me is built around wa.me/<number>: called
 * without a phone number it serves an error page instead of a chat picker. A share button does
 * not know who the reader wants to send the link to, so the number cannot be supplied, and
 * api.whatsapp.com/send is the documented form that opens the contact picker with the message
 * pre-filled. It also resolves correctly on desktop, where it hands off to WhatsApp Web.
 *
 * The text is a single encoded string holding the title and the URL, because WhatsApp has one
 * message field - there is no separate url parameter to fill.
 */
export const whatsappShareHref = ( title: string, url: string ): string =>
  `https://api.whatsapp.com/send?text=${encodeURIComponent( `${title}\n\n${url}` )}`;
