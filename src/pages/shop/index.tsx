import React from 'react';
import Link from 'next/link';
import type { GetStaticProps } from 'next';
import PageTopBand from '../../components/PageTopBand';
import Breadcrumbs from '../../components/Breadcrumbs';
import { SHOP_PRODUCTS, shopProductPath } from '../../content/shop';
import type { ShopProduct } from '../../content/shop';

/**
 * /shop/ - the catalogue index.
 *
 * RESTORED 2026-10-10, on owner instruction, after being withdrawn on 2026-10-04. The listing is
 * browsable again: the three /shop 301 rules were removed from
 * scripts/provision_legacy_redirects.py, and '/shop' is back in PUBLIC_PAGE_META (src/pages/_app.tsx)
 * and PUBLIC_EXACT (scripts/generate-sitemap.js). Those two are what make this route render at HTTP
 * 200 with a public shell rather than the staff sign-in page, and keep it in the sitemap.
 *
 * The head is NOT owned here. Unlike /shop/[slug], which is a dynamic route and owns its whole
 * <head> through components/ShopProductHead.tsx, this is a static pathname-keyed route, so the
 * sitewide block in _app.tsx reads PUBLIC_PAGE_META['/shop'] and emits the canonical, the WebPage
 * node and the title. Do not add a second <head> here.
 *
 * The product set is the same SHOP_PRODUCTS the slug pages enumerate - the visible catalogue with
 * the contribution vehicle, the services vehicle and the twelve Wix template samples filtered out,
 * sorted by name. getStaticProps passes it in at build time; next.config.js sets output: 'export',
 * so there is no server and the list is frozen into the static HTML, exactly as getStaticPaths does
 * for the slug pages.
 *
 * NO IMAGES. The snapshot reports mediaCount 0 on every product (see src/content/shop.ts), so a
 * card shows the name, the one-line tagline and the price and nothing else. A grey placeholder
 * frame is a promise that a picture exists.
 *
 * NO PRICE IN THE TOP BAND and NO lime CTA on the index. The price sits on each card next to the
 * link that opens the product, where the add-to-cart action actually lives. The index points at
 * the pages; it does not transact.
 */

interface ShopIndexProps {
  products: ShopProduct[];
}

const ShopIndex: React.FC<ShopIndexProps> = ( { products } ) => (
  <PageTopBand
    heading="Shop"
    sub="Documents, coordination and merchandise, each on its own page. Open one to see what it includes and add it to your cart."
    ariaLabel="Shop"
  >
    <div className="shop-in">
      <Breadcrumbs items={ [
        { label: 'Home', href: '/' },
        { label: 'Shop' },
      ] } />

      <section className="shop-grid" aria-label="Catalogue">
        { products.map( product => (
          <Link
            key={ product.id }
            className="shop-card"
            href={ shopProductPath( product ) }
          >
            <span className="shop-card-name">{ product.name }</span>
            <span className="shop-card-tag">{ product.tagline }</span>
            <span className="shop-card-foot">
              <span className="shop-card-price" data-wc-no-translate="true">{ product.formattedPrice }</span>
              { !product.inStock && (
                <span className="shop-card-oos">Not available right now</span>
              ) }
            </span>
          </Link>
        ) ) }
      </section>

      <style jsx>{`
        /* PageTopBand owns the header clearance, the 1300px measure, the gutter and the typeface.
           This div only sets the stack between the breadcrumb and the grid. */
        .shop-in{width:100%;display:flex;flex-direction:column;gap:28px}

        .shop-grid{
          display:grid;
          grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
          gap:20px;margin:0;padding:0;
        }

        /* :global() IS MANDATORY - styled-jsx attaches its scoping class only to the lowercase DOM
           tags it can see in this file, and <Link> is a capitalised component, so a bare .shop-card
           rule would match nothing and the cards would render as plain blue underlined links. */
        .shop-in :global(.shop-card){
          display:flex;flex-direction:column;gap:10px;
          padding:24px;border:2px solid #e5e7eb;border-radius:16px;
          background:#fff;text-decoration:none;color:inherit;
          transition:border-color .2s,transform .2s,box-shadow .2s;
        }
        .shop-in :global(.shop-card:hover){
          border-color:#1a3a2a;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        .shop-in :global(.shop-card:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px}

        .shop-in :global(.shop-card-name){
          font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px;color:#1a3a2a;
        }
        .shop-in :global(.shop-card-tag){
          font-size:16px;font-weight:400;line-height:1.45;color:rgba(0,0,0,.72);
        }
        .shop-in :global(.shop-card-foot){
          display:flex;align-items:baseline;gap:12px;margin-top:4px;
        }
        /* Dark green, not lime: lime means actionable, and the actionable surface is the
           add-to-cart button on the product page, not the price on an index card. Tabular
           figures, like the product page. */
        .shop-in :global(.shop-card-price){
          font-size:18px;font-weight:700;line-height:1.3;color:#1a3a2a;
          font-variant-numeric:tabular-nums;
        }
        .shop-in :global(.shop-card-oos){
          font-size:14px;font-weight:700;line-height:1.3;color:rgba(0,0,0,.54);
        }

        @media(prefers-reduced-motion:reduce){
          .shop-in :global(.shop-card){transition:none}
          .shop-in :global(.shop-card:hover){transform:none;box-shadow:none}
        }
      `}</style>
    </div>
  </PageTopBand>
);

export const getStaticProps: GetStaticProps<ShopIndexProps> = async () => ( {
  props: { products: SHOP_PRODUCTS },
} );

export default ShopIndex;
