/**
 * Scroll a message list to its newest entry, with the MOTION DECIDED IN CSS.
 *
 * WHY THIS EXISTS
 * ---------------
 * Four message views each called `scrollIntoView({ behavior: 'smooth' })` directly:
 * components/FloatingAgent.tsx, components/dashboard/tabs/InternalChatTab.tsx,
 * pages/workspace/engage/inbox/index.tsx and pages/workspace/engage/whatsapp/inbox.tsx.
 *
 * THREE of those four remain. The fourth, pages/workspace/engage/whatsapp/inbox.tsx, was a
 * duplicate of the omnichannel inbox and is now a thin wrapper that renders it with
 * channel="whatsapp", so it no longer imports this helper and no longer declares a scroll
 * container of its own. The history above is kept because it is why this function exists; the
 * counts below are the live ones.
 *
 * Passing `behavior: 'smooth'` is a script overriding the stylesheet, and it has one concrete
 * consequence: it animates for a reader who has asked their operating system for reduced motion.
 * `prefers-reduced-motion` is a CSS media query, so a hardcoded JS argument cannot see it. Four
 * copies of the argument meant four places to forget that.
 *
 * OMITTING `behavior` IS THE FIX, not a simplification. Per the CSSOM View spec, a
 * scrollIntoView call with no `behavior` uses the computed `scroll-behavior` of the scrolling box.
 * So the stylesheet decides: the three surviving containers declare `scroll-behavior: smooth`
 * (`.agent-messages` in styles/Layout.css, `.ui-thread-body` in the omnichannel inbox, and the
 * inline-styled list in InternalChatTab.tsx), and the reduced-motion block in
 * styles/inner-ux.css sets `scroll-behavior: auto` for everything. One media query now governs
 * all three call sites, and any container added later inherits the same rule without needing to
 * know this function exists.
 *
 * `block: 'end'` is stated rather than left default. The default is `'start'`, which aligns the
 * sentinel to the TOP of the scrollport - on a short thread that scrolls the last message up under
 * the header instead of resting it at the bottom. Scrolling to the end of a list means the end of
 * the list.
 *
 * NOT DEVICE DETECTION, AND DELIBERATELY SO. Nothing here reads a user agent, a viewport width or
 * a touch capability. The only question asked is what the stylesheet computed, which is the same
 * question on every device.
 */
export function scrollToEnd ( element: HTMLElement | null | undefined ): void {
  element?.scrollIntoView( { block: 'end' } );
}
