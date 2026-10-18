import { shopProductCrumbs } from '../../lib/breadcrumbs';
import React, { useCallback, useState } from 'react';
import Link from 'next/link';
import type { GetStaticPaths, GetStaticProps } from 'next';
import ShopProductHead from '../../components/ShopProductHead';
import RotatingHero from '../../components/RotatingHero';
import Breadcrumbs from '../../components/Breadcrumbs';
import { SHOP_PRODUCTS, shopProductBySlug } from '../../content/shop';
import type { ShopProduct } from '../../content/shop';
import { addItem, setContribution } from '../../lib/cart';
import { CONTRIBUTION_CHOICES, CONTRIBUTION_PRODUCT_ID } from '../../config/contribution';
import Select from '../../components/ui/Select';
import PolicyDetails from '../../components/public/PolicyDetails';
import { PRODUCT_SKU_BY_SLUG, productPolicyCopy } from '../../content/productCommerce';

/**
 * /shop/<slug>/ - one page per catalogue item.
 *
 * getStaticPaths enumerates the snapshot, so the set of pages is the set of visible products.
 * `fallback: false` because next.config.js sets `output: 'export'`: there is no server to render an
 * eighth slug on demand, and a request for one gets the export's 404.
 *
 * The document head is owned by components/ShopProductHead, not by PageMeta and the sitewide block
 * in _app.tsx - see that component for why a dynamic route cannot use a pathname-keyed map.
 *
 * The top band is components/RotatingHero (it replaced PageTopBand): "Explore" and the product
 * name as the h1, and its tagline as the sub-line. The PRICE IS NOT IN THE BAND, and that is the rule rather than a layout preference -
 * the top section says what the page is and the conversion furniture belongs below it, so the price
 * sits with the button that acts on it.
 *
 * NO IMAGE. The snapshot reports mediaCount 0 on all seven products, so there is nothing to show.
 * A grey placeholder frame is a promise that a picture exists.
 *
 * The call to action is add-to-cart, and it is the page's single lime surface: lime means actionable
 * on this site and a page gets one. It adds the product's catalogue REFERENCE and a quantity to the
 * browser cart (src/lib/cart.ts) and then points at /cart/. It never charges anything - an order
 * exists only after a payment has been verified server-side, and live payment initiation is off by
 * default, which is what the boundary note below says.
 */

interface ShopProductPageProps {
  product: ShopProduct;
}

const ShopProductPage: React.FC<ShopProductPageProps> = ( { product } ) => {
  // "added" flips once the item is in the cart, turning the CTA into a link to the cart rather
  // than re-adding on every press. Client-only state; the settled markup is the add button, so a
  // no-JS load still shows a coherent page.
  const [ variantId, setVariantId ] = useState<string>( '' );
  const [ added, setAdded ] = useState<boolean>( false );
  const sku = PRODUCT_SKU_BY_SLUG[ product.slug ];
  const policy = sku ? productPolicyCopy( product.slug, product.name ) : null;

  const onAdd = useCallback( (): void => {
    if ( product.id === CONTRIBUTION_PRODUCT_ID ) {
      const choice = CONTRIBUTION_CHOICES[ 0 ];
      if ( choice ) setContribution( choice.variantId );
    } else {
      addItem( product, 1, variantId || undefined );
    }
    setAdded( true );
  }, [ product, variantId ] );

  return (
    <>
      <ShopProductHead product={ product } />
      <RotatingHero
        frame="Explore"
        words={ [ { word: product.name, tint: '#e0f7c8', dot: '#3da35a' } ] }
        sub={ product.tagline }
        ariaLabel={ product.name }
      >
        <div className="shopd-in">
          {/* THREE ITEMS AGAIN, since 2026-10-10. The middle crumb { label: 'Shop', href: '/shop/' }
              was removed on 2026-10-04 when the catalogue index was withdrawn and that href 301'd to
              home. The owner restored the index, so /shop/ resolves at 200 again and the Shop crumb
              points at a real listing. ShopProductHead's BreadcrumbList must carry the same three
              items from the shared shopProductCrumbs helper. */}
          <Breadcrumbs items={ shopProductCrumbs( product.name ).map( ( { name, href } ) => ( { label: name, href } ) ) } />

          {/* aria-label, because this is an unlabelled region otherwise - the page's only heading
              is the h1 in the band above it. section.pdp names itself the same way on the fourteen
              pages ProductPage renders. */}
          <section className="shopd-about" aria-label={ `About ${product.name}` }>
            { !product.inStock && (
              <p className="shopd-oos" role="status">Not available right now.</p>
            ) }

            {/* The product's own words, as TEXT and never as HTML. toParagraphs in
                src/content/shop.ts strips the tags rather than trusting them: this is
                merchant-authored rich text, and dangerouslySetInnerHTML would make the
                storefront depend on an upstream sanitiser instead of ours. */}
            { product.body.map( ( paragraph, index ) => (
              <p className="shopd-p" key={ `p-${index}` }>{ paragraph }</p>
            ) ) }

            {/* The page's single lime surface. A button before the item is added (a client action)
                and a link once it is, so a shopper is never stranded. */}
            {/* THE VARIANT CHOOSER - the one public non-checkout select, and the only one on a
                route a browser harness can actually load. It renders on EXACTLY ONE exported
                page, /shop/merchandise/: that is the only multi-variant product in the snapshot,
                and /shop/kiosk/ is single-variant and renders nothing here.

                THE WRAPPING <label> IS GONE AND THE COMPONENT OWNS THE PAIR. A <button
                role="combobox"> inside a <label> is still associated - a button is a labelable
                element - so the accessible name would be computed by walking the label's subtree,
                which now contains the trigger's own caption: "Fit and size Choose your fit and
                size". Dropping the wrapper and passing label="Fit and size" makes the name
                exactly those three words, which is what ShopCatalogue.test.tsx now resolves it by,
                as an exact string rather than a regex. `.shopd-options` moves onto the field
                wrapper and its two rules become :global(), because styled-jsx only hashes the
                lowercase DOM tags it can see in this file and a className handed to a component
                never receives that hash.

                THE '' ROW IS KEPT AS A REAL OPTION rather than becoming a `placeholder`, so the
                DOM mirrors the native control exactly: the shopper can still re-select "no
                choice", and the add button's `!variantId` guard below is unchanged. */}
            { product.variants && product.variants.length > 1 && (
              <Select
                className="shopd-options"
                label="Fit and size"
                value={ variantId }
                onChange={ value => { setVariantId( value ); setAdded( false ); } }
                options={ [
                  { value: '', label: 'Choose your fit and size' },
                  ...product.variants.filter( variant => variant.inStock )
                    .map( variant => ( { value: variant.id, label: variant.label } ) ),
                ] }
              />
            ) }
            { added
              ? (
                <Link className="shopd-cta" href="/cart/">Go to your cart</Link>
              )
              : (
                <button className="shopd-cta shopd-cta-btn" type="button" disabled={ !!product.variants && product.variants.length > 1 && !variantId } onClick={ onAdd }>
                  { product.id === CONTRIBUTION_PRODUCT_ID ? 'Contribute ₹250' : `Add ${ product.name } to cart` }
                </button>
              ) }

            <p className="shopd-price" data-wc-no-translate="true">{ product.formattedPrice }</p>
            <p className="shopd-offer-note">One-time purchase · Review your final total in the cart before payment</p>

            { sku && policy && (
              <div className="shopd-policy-wrap">
                <p className="shopd-sku" data-wc-no-translate="true"><strong>SKU:</strong> { sku }</p>
                <PolicyDetails
                  shipping={ policy.shipping }
                  returns={ policy.returns }
                  disclaimer={ policy.disclaimer }
                />
              </div>
            ) }
            {/* The way back to the full catalogue. Restored 2026-10-10 with the /shop index: it
                was removed on 2026-10-04 because /shop/ 301'd to home, and now points at a real
                listing again. */}
            <p className="shopd-back">
              <Link href="/shop/">All items in the shop</Link>
            </p>
          </section>

          {/* The page-tail dock is AUTO-MOUNTED by RotatingHero (in its .rh-tail), so the page
              no longer renders its own <PublicShare /> here - that would show the dock twice. */}
        </div>

        <style jsx>{`
          /* NO TOP PADDING, NO MEASURE AND NO FONT STACK HERE. PageTopBand owns the 108px/96px
             two-height header clearance, the 1300px measure, the gutter and the typeface, which is
             the whole reason this page stopped hand-rolling them: a page that states its own
             clearance has to restate it at both header heights, and getting that wrong paints the
             first line under the header. This div only sets its own reading measure. */
          /* :global() IS MANDATORY ON BOTH OF THESE NOW, for the reason .shopd-cta below records
             at length: styled-jsx attaches its scoping class only to the lowercase DOM tags it
             can see in this file, and .shopd-options is now a className handed to the Select
             component, which forwards it to a node styled-jsx never saw. Without :global() the compiled
             rules match nothing and the chooser renders as an unstyled button.
             The flex column with gap:8px is what spaces the label from the trigger, so
             .ui-field-label's own block-end margin is zeroed rather than added to it, and
             colour and weight are inherited from this rule instead of taken from the
             control tokens - the label here is the page's 700-weight dark green, not a
             workspace field label. */
          .shopd-in :global(.shopd-options){display:flex;flex-direction:column;gap:8px;color:var(--public-brand-green);margin:20px 0;font-weight:700}
          .shopd-in :global(.shopd-options .ui-field-label){color:inherit;font-weight:inherit;margin-block-end:0;cursor:pointer}
          /* NO BACKTICK IN A styled-jsx COMMENT - this block is a template literal, so one
             around a selector name terminates it and the parser reports a cascade of JSX errors
             further down the file.
             The .shopd-options select rule is gone with the native control. It had just been
             rewritten in batch 1.3a onto the shared tokens - font:inherit, the 44px floor, the
             2px #e5e7eb box, the 13px radius and the 32px end inset for the chevron - and
             form-controls.css's .ui-select-trigger now declares that exact set for the component
             that replaced it, so nothing about the closed state changes. What changes is the OPEN
             list, which was the one part no stylesheet could reach. */
          .shopd-cta-btn:disabled{opacity:.5;cursor:not-allowed}
          .shopd-in{width:100%;max-width:700px;margin:0}
          

          /* The card rung - 22px/700/lh1.27/-.25px - in dark green rather than lime, for the
             reason .shop-price records: lime means actionable and the page's one lime surface is
             the button. #1a3a2a on white is about 11:1. Tabular figures. */
          .shopd-price{
            font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);
            color:var(--public-brand-green);margin:0;font-variant-numeric:tabular-nums;
          }
          .shopd-sku{margin:10px 0 0;font-size:13px;line-height:1.3;color:var(--public-muted);letter-spacing:.04em;text-transform:uppercase}
          .shopd-oos{margin:12px 0 0;font-size:16px;font-weight:700;line-height:1.4;color:var(--public-muted)}

          .shopd-about{margin:0}
          /* The single body rung the contract allows, identical to .pdp-p and the blog excerpts. */
          .shopd-p{
            font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
            color:var(--public-body);margin:18px 0 0;
          }

          /* .pdp-cta, value for value: full-strength #d1f470 with #1a3a2a type, and a 2px border
             because 1px means a static edge and 2px a hoverable one.
             :global() IS MANDATORY for the link case. styled-jsx attaches its scoping class only
             to lowercase DOM tags it can see in this file; a capitalised component never gets it,
             because styled-jsx cannot know whether the component forwards className to a DOM node.
             Without :global() the compiled rule matches nothing and the CTA renders as bare blue
             underlined text. */
          .shopd-in :global(.shopd-cta){
            display:inline-flex;align-items:center;min-height:var(--public-cta-height);margin-top:34px;
            padding:0 26px;border:var(--public-cta-border) solid var(--public-brand-green);border-radius:var(--public-cta-radius);
            background:var(--public-brand-lime);color:var(--public-brand-green);font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);text-decoration:none;
            font-family:inherit;line-height:normal;cursor:pointer;
            transition:background-color .2s,transform .2s,box-shadow .2s;
          }
          .shopd-in :global(.shopd-cta:hover){background:#fff;transform:translateY(-2px);box-shadow:var(--public-lift-shadow)}
          .shopd-in :global(.shopd-cta:focus-visible){outline:3px solid var(--public-brand-green);outline-offset:3px}

          /* THE CANONICAL BOUNDARY CARD, matched to .pdp-note so every boundary note on the public
             site reads the same: near-white #fcfdfb surface, 1px hairline, 14px radius, 22px
             padding, legal-copy type 17px/400/1.55/-.05px on rgba(0,0,0,.898). Was a transparent
             16px/faded aside. 1px static, per the rule: 1px static, 2px hoverable. */
          .shopd-offer-note{
            max-width:620px;margin:7px 0 0;
            font-size:17px;font-weight:var(--public-body-weight);
            line-height:var(--public-body-leading);letter-spacing:-.05px;
            color:var(--public-muted);
          }
          .shopd-policy-wrap{margin:22px 0 0}
          .shopd-sku{
            margin:0;font-size:17px;font-weight:400;line-height:1.4;
            letter-spacing:-.05px;color:var(--public-muted);
          }
          .shopd-sku strong{color:var(--public-muted);font-weight:600}

          /* The .shopd-back link, restored 2026-10-10 with the /shop index. :global() for the
             same reason as .shopd-cta: it wraps a capitalised <Link> styled-jsx cannot scope. */
          .shopd-back{margin:28px 0 0}
          .shopd-in :global(.shopd-back a){
            font-size:16px;font-weight:600;color:var(--public-brand-green);text-decoration:underline;
            text-underline-offset:3px;
          }
          .shopd-in :global(.shopd-back a:hover){text-decoration:none}
          .shopd-in :global(.shopd-back a:focus-visible){outline:3px solid var(--public-brand-green);outline-offset:3px}

          @media(max-width:767px){
          }
          @media(prefers-reduced-motion:reduce){
            .shopd-in :global(.shopd-cta){transition:none}
            .shopd-in :global(.shopd-cta:hover){transform:none;box-shadow:none}
          }
        `}</style>
      </RotatingHero>
    </>
  );
};

export const getStaticPaths: GetStaticPaths = async () => ( {
  paths: SHOP_PRODUCTS.map( product => ( { params: { slug: product.slug } } ) ),
  // output: 'export' - there is no server, so an unknown slug cannot be rendered on demand.
  fallback: false,
} );

export const getStaticProps: GetStaticProps<ShopProductPageProps> = async ( { params } ) => {
  const product = shopProductBySlug( String( params?.slug || '' ) );
  // notFound rather than a thrown error: getStaticPaths only produces slugs that resolve, so this
  // branch is unreachable in a normal build - but returning notFound means a snapshot edited to
  // remove a product while a stale path list is cached produces a 404 rather than a build crash.
  if ( !product ) return { notFound: true };
  return { props: { product } };
};

export default ShopProductPage;
