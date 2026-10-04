import React, { useCallback, useState } from 'react';
import Link from 'next/link';
import type { GetStaticPaths, GetStaticProps } from 'next';
import ShopProductHead from '../../components/ShopProductHead';
import PageTopBand from '../../components/PageTopBand';
import Breadcrumbs from '../../components/Breadcrumbs';
import { SHOP_PRODUCTS, shopProductBySlug } from '../../content/shop';
import type { ShopProduct } from '../../content/shop';
import { addItem } from '../../lib/cart';

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
 * The top band is components/PageTopBand: the product name as the h1 and its tagline as the
 * sub-line. The PRICE IS NOT IN THE BAND, and that is the rule rather than a layout preference -
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

  const onAdd = useCallback( (): void => {
    addItem( product, 1, variantId || undefined );
    setAdded( true );
  }, [ product, variantId ] );

  return (
    <>
      <ShopProductHead product={ product } />
      <PageTopBand
        heading={ product.name }
        sub={ product.tagline }
        ariaLabel={ product.name }
      >
        <div className="shopd-in">
          {/* TWO ITEMS, NOT THREE, since 2026-10-04. The middle crumb was
              { label: 'Shop', href: '/shop/' } and the catalogue index has been withdrawn on owner
              instruction, so that href now 301s to the home page - a breadcrumb trail whose middle
              step redirects to its own first step.
              THE ITEM IS REMOVED RATHER THAN HAVING ITS href DROPPED: components/Breadcrumbs.tsx
              renders an href-less crumb as <span aria-current="page">, so keeping it would
              announce TWO current pages to a screen reader. ShopProductHead's BreadcrumbList is
              cut to the same two items, because a graph describing a trail the page does not
              render is how a rich result disappears silently. */}
          <Breadcrumbs items={ [
            { label: 'Home', href: '/' },
            { label: product.name },
          ] } />

          {/* aria-label, because this is an unlabelled region otherwise - the page's only heading
              is the h1 in the band above it. section.pdp names itself the same way on the fourteen
              pages ProductPage renders. */}
          <section className="shopd-about" aria-label={ `About ${product.name}` }>
            {/* The price sits with the action, not in the top band. data-wc-no-translate because a
                translated "₹24,999.00" is a different number in a different grouping convention. */}
            <p className="shopd-price" data-wc-no-translate="true">{ product.formattedPrice }</p>

            { !product.inStock && (
              <p className="shopd-oos" role="status">Not available right now.</p>
            ) }

            {/* The product's own words, as TEXT and never as HTML. toParagraphs in
                src/content/shop.ts strips the tags rather than trusting them: this is
                merchant-authored rich text from a third-party CMS, and dangerouslySetInnerHTML
                would make the storefront depend on Wix's sanitiser instead of ours. */}
            { product.body.map( ( paragraph, index ) => (
              <p className="shopd-p" key={ `p-${index}` }>{ paragraph }</p>
            ) ) }

            {/* The page's single lime surface. A button before the item is added (a client action)
                and a link once it is, so a shopper is never stranded. */}
            { product.variants && product.variants.length > 1 && (
              <label className="shopd-options">
                Fit and size
                <select value={ variantId } onChange={ e => { setVariantId( e.target.value ); setAdded( false ); } }>
                  <option value="">Choose your fit and size</option>
                  { product.variants.filter( variant => variant.inStock ).map( variant => (
                    <option key={ variant.id } value={ variant.id }>{ variant.label }</option>
                  ) ) }
                </select>
              </label>
            ) }
            { added
              ? (
                <Link className="shopd-cta" href="/cart/">Go to your cart</Link>
              )
              : (
                <button className="shopd-cta shopd-cta-btn" type="button" disabled={ !!product.variants && product.variants.length > 1 && !variantId } onClick={ onAdd }>
                  Add { product.name } to cart
                </button>
              ) }

            {/* The boundary statement, in the hairline box rather than a lime one - the page's one
                lime surface is already spent on the button above. Shortened on owner instruction
                with nothing dropped: where the price came from, who decides the amount, and that
                nothing is charged. */}
            <p className="shopd-note">
              Review your final total in the cart before payment.
            </p>
            {/* The "All items in the shop" link was here. Removed 2026-10-04: the catalogue index
                is withdrawn, so it pointed at a URL that 301s to the home page - an invitation to
                a list that no longer exists. The Home crumb above is the way out of this page. */}
          </section>
        </div>

        <style jsx>{`
          /* NO TOP PADDING, NO MEASURE AND NO FONT STACK HERE. PageTopBand owns the 108px/96px
             two-height header clearance, the 1300px measure, the gutter and the typeface, which is
             the whole reason this page stopped hand-rolling them: a page that states its own
             clearance has to restate it at both header heights, and getting that wrong paints the
             first line under the header. This div only sets its own reading measure. */
          .shopd-options{display:flex;flex-direction:column;gap:8px;color:#1a3a2a;margin:20px 0;font-weight:700}
          .shopd-options select{font:inherit;padding:14px;border:1px solid #c7d3b4;border-radius:14px;background:#f5f7eb;color:#1a3a2a}
          .shopd-cta-btn:disabled{opacity:.5;cursor:not-allowed}
          .shopd-in{width:100%;max-width:700px;margin:0}

          /* The card rung - 22px/700/lh1.27/-.25px - in dark green rather than lime, for the
             reason .shop-price records: lime means actionable and the page's one lime surface is
             the button. #1a3a2a on white is about 11:1. Tabular figures. */
          .shopd-price{
            font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;
            color:#1a3a2a;margin:0;font-variant-numeric:tabular-nums;
          }
          .shopd-oos{margin:12px 0 0;font-size:16px;font-weight:700;line-height:1.4;color:rgba(0,0,0,.54)}

          .shopd-about{margin:0}
          /* The single body rung the contract allows, identical to .pdp-p and the blog excerpts. */
          .shopd-p{
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);margin:18px 0 0;
          }

          /* .pdp-cta, value for value: full-strength #d1f470 with #1a3a2a type, and a 2px border
             because 1px means a static edge and 2px a hoverable one.
             :global() IS MANDATORY for the link case. styled-jsx attaches its scoping class only
             to lowercase DOM tags it can see in this file; a capitalised component never gets it,
             because styled-jsx cannot know whether the component forwards className to a DOM node.
             Without :global() the compiled rule matches nothing and the CTA renders as bare blue
             underlined text. */
          .shopd-in :global(.shopd-cta){
            display:inline-flex;align-items:center;min-height:52px;margin-top:34px;
            padding:0 26px;border:2px solid #1a3a2a;border-radius:50px;
            background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;text-decoration:none;
            font-family:inherit;line-height:normal;cursor:pointer;
            transition:background-color .2s,transform .2s,box-shadow .2s;
          }
          .shopd-in :global(.shopd-cta:hover){background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
          .shopd-in :global(.shopd-cta:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px}

          /* Static 1px hairline in e5e7eb, per the rule: 1px static, 2px hoverable. */
          .shopd-note{
            margin:34px 0 0;padding:16px 18px;border:1px solid #e5e7eb;border-radius:12px;
            font-size:16px;line-height:1.55;color:rgba(0,0,0,.54);
          }

          /* The .shopd-back rules went with the link they styled, 2026-10-04. The class has no
             other reference in src/ or tools/, so these were dead declarations. */

          @media(max-width:767px){
            .shopd-p{font-size:18px}
          }
          @media(prefers-reduced-motion:reduce){
            .shopd-in :global(.shopd-cta){transition:none}
            .shopd-in :global(.shopd-cta:hover){transform:none;box-shadow:none}
          }
        `}</style>
      </PageTopBand>
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
