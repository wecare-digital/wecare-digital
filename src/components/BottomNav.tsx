/**
 * Phone bottom bar — phase 8.3's adaptive navigation, thumb end.
 *
 * WHY A BOTTOM BAR WHEN A DRAWER ALREADY WORKED
 * ---------------------------------------------
 * The hamburger drawer is functional, and that is exactly the problem with leaving it
 * as the only phone navigation: it costs a tap to open, it covers the page you were
 * reading, and its targets sit at the TOP of a 6-inch screen where a thumb does not
 * reach. The drawer stays — it is how you get to all 95 destinations — but the streams
 * you switch between hourly belong within thumb reach.
 *
 * FIVE, NOT EIGHT
 * ---------------
 * `navigationConfig` is a flat list of eight top-level streams (Messages, Contacts,
 * Commerce, Payments, Service, Links, Tasks, SEO). Eight targets across a phone width
 * gives each about 45px, below the 44px minimum once padding is taken off, and the
 * labels truncate to nonsense. So the bar shows the first four — Messages, Contacts,
 * Commerce, Payments, all thumb-reachable daily streams — and a "More" button that
 * opens the same drawer. Four plus More is a deliberate cut, not a truncation: the
 * drawer is one tap away and holds everything.
 *
 * THE WIDGET ABOVE IT
 * -------------------
 * This note used to describe a fight that no longer exists. `#wecarewa-widget` was
 * injected by an external script at `z-index: 2147483647` — the maximum 32-bit integer,
 * so nothing could be stacked above it — and the clearance here had to be GEOMETRIC
 * because that was the only way to win. That script is retired.
 *
 * Its replacement, `SupportWidget`, is a normal element this repo owns at `z-index: 1300`
 * against this bar's 1200, so stacking is now decided the ordinary way and the pill simply
 * sits on top. The geometry still matters for a different reason — overlap would put the
 * pill ON the bar rather than under it — so the widget offsets itself to
 * `bottom: calc(72px + env(safe-area-inset-bottom))` on phones, clearing this 60px row
 * plus the inset. Change that height and the widget's mobile offset has to move with it;
 * `tools/browser/uicheck.js` asserts the pill's anchoring and hit-tests its centre at four
 * widths, so the two staying in step is checked rather than assumed.
 *
 * SAFE AREA
 * ---------
 * `env(safe-area-inset-bottom)` keeps the row above the iPhone home indicator. Without
 * it the last 34px of the bar is unreachable on any notched device, which is the
 * WebView/WKWebView readiness the owner's override requires the web app to keep.
 */
import React from 'react';
import { useRouter } from 'next/router';
import { navigationConfig, isNavItemActive } from '../config/navigation';
import { IconMap, MenuIcon } from '../lib/icons';

interface BottomNavProps {
  /** Opens the existing drawer. The bar does not own a second navigation surface. */
  onMore: () => void;
  moreOpen?: boolean;
}

/** Four streams plus More. See the note above on why not eight. */
const PRIMARY_COUNT = 4;

const BottomNav: React.FC<BottomNavProps> = ( { onMore, moreOpen } ) => {
  const router = useRouter();
  const items = navigationConfig.slice( 0, PRIMARY_COUNT );

  const renderIcon = ( iconName?: string ) => {
    if ( !iconName ) return null;
    const Icon = IconMap[ iconName ];
    return Icon ? <Icon size={ 20 } /> : null;
  };

  return (
    <nav className="bottom-nav" aria-label="Primary">
      { items.map( ( item ) => {
        const active = isNavItemActive( item, router.pathname );
        return (
          <button
            key={ item.path }
            type="button"
            className={ `bn-item ${active ? 'active' : ''}` }
            aria-current={ active ? 'page' : undefined }
            onClick={ () => router.push( item.path ) }
          >
            <span className="bn-icon">{ renderIcon( item.icon ) }</span>
            <span className="bn-label">{ item.label }</span>
          </button>
        );
      } ) }
      <button
        type="button"
        className={ `bn-item ${moreOpen ? 'active' : ''}` }
        onClick={ onMore }
        aria-expanded={ !!moreOpen }
        aria-label="More navigation"
      >
        <span className="bn-icon"><MenuIcon size={ 20 } /></span>
        <span className="bn-label">More</span>
      </button>
    </nav>
  );
};

export default BottomNav;
