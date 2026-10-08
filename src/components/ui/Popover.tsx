/**
 * Popover - POSITIONING AND DISMISSAL ONLY. No ARIA role of its own.
 *
 * The consumer supplies the role, because the same geometry serves three different
 * patterns: `listbox` (Select), `dialog` (DateField's calendar) and `radiogroup`
 * (ColorField's swatch grid). A wrapper that declared `role="dialog"` for all three
 * would announce a listbox as a dialog, so this element declares nothing and the child
 * carries the semantics.
 *
 * THIS FOLLOWS src/components/ui/InfoTooltip.tsx RATHER THAN INVENTING A PATTERN. That
 * component already portals to document.body, positions `fixed` from the anchor's
 * getBoundingClientRect(), flips on available space, clamps to an 8px viewport margin,
 * listens to `scroll` with capture plus `resize`, and dismisses on Escape and an outside
 * press. Everything here is that mechanism with two additions it did not need - a flip
 * driven by the MEASURED panel height rather than a 150px heuristic, and dismissal on a
 * route change - and one subtraction: no hover/focus opening, because a menu opens on a
 * deliberate act.
 *
 * PORTAL RATHER THAN IN-PLACE IS DECIDED, NOT OPTIONAL. Workspace panels use
 * `overflow: auto` freely, and an in-place absolutely-positioned menu is clipped by the
 * nearest scroll container - the classic "my dropdown is cut in half" defect. The cost is
 * the scroll/resize bookkeeping below, which is implemented rather than assumed: the
 * listeners go on when `open` turns true and come off in the effect's cleanup, so a closed
 * popover holds no listener at all.
 *
 * STYLING COMES FROM CLASSES IN src/styles/form-controls.css, NOT styled-jsx. A portal
 * escapes styled-jsx's scope hash - the rendered node is not in the tree styled-jsx
 * transformed - so a `<style jsx>` block here would ship CSS that cannot match its own
 * markup. src/test/StyledJsxBuildScope.test.ts exists because that exact defect shipped
 * twice. Only COMPUTED values are inline: `top`, `left`, `width`, and two custom
 * properties carrying numbers that come from props and tokens (the layer and the max
 * height). The DECLARATIONS that consume those numbers - `z-index`, `max-block-size` -
 * live in the stylesheet with everything else, so there is no colour, border, radius or
 * shadow in this file.
 *
 * ANCHOR RE-CLICK is dismissal too, and it is deliberately the ANCHOR's job rather than
 * this component's. A pointerdown on the anchor is NOT treated as an outside press here,
 * because pointerdown precedes click: closing on the press and letting the anchor's own
 * click toggle run would close and immediately reopen. So the anchor keeps a plain
 * open/close toggle (see Select's `onClick`) and this component ignores presses that land
 * inside it - the same arrangement InfoTooltip uses.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Router from 'next/router';

import { zIndex } from '../../lib/design-tokens';

export type PopoverLayer = 'default' | 'overlay';

/** Why the popover is closing. The consumer decides what each one means for its value. */
export type PopoverDismissReason = 'escape' | 'outside' | 'tab' | 'route';

export interface PopoverProps {
    open: boolean;
    /** The element the panel is positioned against, and the element Escape returns focus to. */
    anchorRef: React.RefObject<HTMLElement | null>;
    onDismiss: ( reason: PopoverDismissReason ) => void;
    children: React.ReactNode;
    /** Used for the flip decision before the panel has been measured, and as its ceiling. */
    maxHeight?: number;
    /** Match the anchor's width. A menu narrower than its trigger reads as a different control. */
    matchAnchorWidth?: boolean;
    layer?: PopoverLayer;
    className?: string;
}

/** The viewport inset, as InfoTooltip uses. */
const MARGIN = 8;
/** The gap between the anchor and the panel. */
const GAP = 4;

interface Position {
    top: number;
    left: number;
    width: number;
    placement: 'top' | 'bottom';
}

const Popover: React.FC<PopoverProps> = ( {
    open,
    anchorRef,
    onDismiss,
    children,
    maxHeight = 320,
    matchAnchorWidth = true,
    layer = 'default',
    className,
} ) => {
    const [ mounted, setMounted ] = useState( false );
    const [ pos, setPos ] = useState<Position>( { top: 0, left: 0, width: 0, placement: 'bottom' } );
    const panelRef = useRef<HTMLDivElement>( null );

    useEffect( () => setMounted( true ), [] );

    const reposition = useCallback( () => {
        const anchor = anchorRef.current;
        if ( !anchor ) return;
        const r = anchor.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const width = matchAnchorWidth ? r.width : 0;

        // The MEASURED height once the panel is in the DOM, the ceiling before that. A flip
        // decided on a guess is the reason InfoTooltip's 150px heuristic is not copied: a
        // 320px menu under a trigger 200px from the bottom must flip, and a 60px one must not.
        const measured = panelRef.current?.getBoundingClientRect().height ?? 0;
        const height = Math.min( measured || maxHeight, Math.max( 0, vh - MARGIN * 2 ) );

        const below = vh - r.bottom - MARGIN;
        const above = r.top - MARGIN;
        const flip = height > below && above > below;

        const rawTop = flip ? r.top - GAP - height : r.bottom + GAP;
        const top = Math.min(
            Math.max( MARGIN, rawTop ),
            Math.max( MARGIN, vh - MARGIN - height )
        );
        const left = Math.min(
            Math.max( MARGIN, r.left ),
            Math.max( MARGIN, vw - MARGIN - width )
        );

        const placement: 'top' | 'bottom' = flip ? 'top' : 'bottom';
        // Bail out when nothing moved. Not a micro-optimisation: `reposition` runs from a
        // scroll listener on every frame of a scroll, and returning the SAME state object is
        // what stops each of those frames re-rendering the consumer's whole menu.
        setPos( prev => (
            prev.top === top && prev.left === left && prev.width === width && prev.placement === placement
                ? prev
                : { top, left, width, placement }
        ) );
    }, [ anchorRef, matchAnchorWidth, maxHeight ] );

    /**
     * Position, then RE-position on the next frame so the flip is decided on the panel's real
     * height. Two passes rather than one because a browser that has not laid the node out yet
     * reports a zero height on the first, and a single pass would place a tall menu off the
     * bottom of the viewport on the frame it opens.
     *
     * `children` is DELIBERATELY NOT A DEPENDENCY. It is a fresh element on every render, so
     * including it would run this effect after every render - and with the bailout in
     * `reposition` removed or defeated that is an infinite loop (position -> render -> effect
     * -> position). Content that changes size while the menu is open is handled by the
     * scroll/resize pass below, which is the case that actually occurs.
     */
    useEffect( () => {
        if ( !open ) return;
        reposition();
        const raf = typeof window.requestAnimationFrame === 'function'
            ? window.requestAnimationFrame( () => reposition() )
            : null;
        return () => { if ( raf !== null ) window.cancelAnimationFrame( raf ); };
    }, [ open, reposition ] );

    /**
     * The listeners, added on open and REMOVED on close - which is the cost the portal
     * decision buys and the half that is easy to leave out.
     *
     * `scroll` with capture true, because a scroll inside a workspace panel does not bubble
     * to window; without capture the panel detaches from its anchor the moment the page
     * behind it moves.
     */
    useEffect( () => {
        if ( !open ) return;

        const onScroll = () => reposition();
        const onResize = () => reposition();
        const onKeyDown = ( e: KeyboardEvent ) => {
            if ( e.key === 'Escape' ) {
                onDismiss( 'escape' );
                // Focus returns to the anchor. Nothing else can hold it: DOM focus never
                // enters the panel, so without this the operator is dropped on <body>.
                anchorRef.current?.focus();
                return;
            }
            // Tab closes and does NOT preventDefault here, so focus moves on - which is what a
            // native select does, and Select is the consumer that pattern is right for.
            //
            // IT IS NOT RIGHT FOR A CONSUMER THAT PUTS DOM FOCUS INSIDE THE PANEL. For those,
            // the default move would be computed from a node the unmount has already removed,
            // so the operator lands on <body>. That cannot be fixed here - this handler cannot
            // know where focus is meant to return to, and cancelling the default for every
            // consumer would break Select - so the 'tab' reason is reported and the consumer
            // decides. See DateField's and ColorField's `onDismiss` and `onGridKeyDown`, which
            // cancel it themselves and refocus their trigger. The same applies to 'outside'.
            if ( e.key === 'Tab' ) onDismiss( 'tab' );
        };
        const onPointerDown = ( e: Event ) => {
            const target = e.target as Node | null;
            if ( !target ) return;
            if ( panelRef.current?.contains( target ) ) return;
            // Not "outside": see the anchor-re-click note at the top of this file.
            if ( anchorRef.current?.contains( target ) ) return;
            onDismiss( 'outside' );
        };

        window.addEventListener( 'scroll', onScroll, true );
        window.addEventListener( 'resize', onResize );
        window.addEventListener( 'keydown', onKeyDown );
        document.addEventListener( 'pointerdown', onPointerDown );
        return () => {
            window.removeEventListener( 'scroll', onScroll, true );
            window.removeEventListener( 'resize', onResize );
            window.removeEventListener( 'keydown', onKeyDown );
            document.removeEventListener( 'pointerdown', onPointerDown );
        };
    }, [ open, reposition, onDismiss, anchorRef ] );

    /**
     * Route change. On `routeChangeStart`, not Complete, for the reason SupportWidget.tsx:358
     * records: at Start the old tree is still attached, so the menu is gone before the next
     * page paints instead of hanging over it for a frame.
     *
     * THE SINGLETON'S `events`, NOT `useRouter().events`, and that is a correction rather than
     * a preference. `useRouter()` THROWS "NextRouter was not mounted" when no RouterContext is
     * present - it does not return null - so a component that calls it cannot be unit-tested
     * on its own, and this primitive will be mounted by dozens of suites that provide no
     * router. `Router.events` is a module-level emitter that exists with or without a mounted
     * router, which makes the listener both safe here and drivable from a test.
     */
    useEffect( () => {
        if ( !open ) return;
        const events = Router.events;
        if ( !events ) return;
        const close = () => onDismiss( 'route' );
        events.on( 'routeChangeStart', close );
        return () => { events.off( 'routeChangeStart', close ); };
    }, [ open, onDismiss ] );

    if ( !mounted || !open ) return null;

    return createPortal(
        <div
            ref={ panelRef }
            data-ui-popover=""
            data-placement={ pos.placement }
            className={ [ 'ui-popover', className ].filter( Boolean ).join( ' ' ) }
            style={ {
                top: pos.top,
                left: pos.left,
                width: pos.width || undefined,
                // Computed numbers handed to the stylesheet. The `z-index` and
                // `max-block-size` DECLARATIONS live in form-controls.css; these carry the
                // values, which cannot be CSS constants because one is a prop and the other
                // is a token the layering analysis in design 5.1 picked per layer.
                '--ui-popover-z': layer === 'overlay' ? zIndex.overlayPopover : zIndex.popover,
                '--ui-popover-max-h': `${ maxHeight }px`,
            } as React.CSSProperties }
        >
            { children }
        </div>,
        document.body
    );
};

export default Popover;
