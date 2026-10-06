/**
 * Design Tokens — WECARE.DIGITAL (single source of truth for TS/TSX)
 *
 * These values MIRROR src/styles/tokens.css (the CSS custom properties).
 * Use these in inline styles / JS where CSS variables are awkward, instead of
 * hardcoding hex values per file. For CSS, prefer the var(--token) equivalents.
 *
 * Theme: Lime (#d1f470) + Dark Forest Green (#1a3a2a) on white. Minimal, high
 * contrast, professional. WCAG 2.1 AA targeted.
 */

/* ── Color palette ─────────────────────────────────────────────────────── */
export const colors = {
    // Brand
    primary: '#1a3a2a',
    primaryHover: '#0f2a1d',
    lime: '#d1f470',
    limeHover: '#c5e866',

    // Surfaces / backgrounds
    white: '#ffffff',
    bg: '#ffffff',
    bgSecondary: '#f9fafb',
    bgHover: '#f5f5f5',
    bgActive: '#ebebeb',
    surface: '#ffffff',

    // Text
    text: '#1a1a1a',
    textSecondary: 'rgba(0, 0, 0, 0.54)',
    textMuted: '#6b7280',
    textLight: '#9ca3af',

    // Borders
    border: '#e5e7eb',
    borderDark: '#d1d5db',
    borderLight: '#f0f0f0',

    // Destructive
    danger: '#dc2626',
    dangerHover: '#b91c1c',
    dangerLight: '#fef2f2',

    // Greyscale ramp
    grey50: '#fafafa',
    grey100: '#f5f5f5',
    grey200: '#e5e7eb',
    grey300: '#d1d5db',
    grey400: '#9ca3af',
    grey500: '#6b7280',
    grey600: 'rgba(0, 0, 0, 0.54)',
    grey700: '#374151',
    grey800: '#1f2937',
    grey900: 'rgba(0, 0, 0, 0.95)',
} as const;

/**
 * Status colors for message/delivery/job states. Distinct hues so users can
 * tell states apart at a glance (the brand greens alone can't convey this).
 * Each has a foreground (fg), background (bg), and solid (dot/border) value.
 */
export const status = {
    sent: { fg: '#1d4ed8', bg: '#eff6ff', solid: '#3b82f6' }, // blue
    delivered: { fg: '#0f766e', bg: '#f0fdfa', solid: '#14b8a6' }, // teal
    read: { fg: '#15803d', bg: '#f0fdf4', solid: '#22c55e' }, // green
    pending: { fg: '#b45309', bg: '#fffbeb', solid: '#f59e0b' }, // amber
    queued: { fg: '#6b7280', bg: '#f9fafb', solid: '#9ca3af' }, // grey
    failed: { fg: '#b91c1c', bg: '#fef2f2', solid: '#ef4444' }, // red
} as const;
export type StatusKey = keyof typeof status;

/* ── Typography ────────────────────────────────────────────────────────── */
export const font = {
    sans: "'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    mono: "'SF Mono', Monaco, Consolas, monospace",
} as const;

export const fontSize = {
    xs: 12, sm: 13, md: 14, base: 16, lg: 16, xl: 18, '2xl': 21, '3xl': 24,
    h1: 32, h2: 26, h3: 21, h4: 18,
} as const;

export const fontWeight = { normal: 400, medium: 500, semibold: 600, bold: 700 } as const;

export const lineHeight = { tight: 1.15, normal: 1.5, relaxed: 1.6 } as const;

/* ── Spacing (4px base scale) ──────────────────────────────────────────── */
export const space = {
    1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40, 12: 48,
} as const;

/* ── Radius ────────────────────────────────────────────────────────────── */
export const radius = {
    sm: 6, md: 8, lg: 12, xl: 14, '2xl': 16, btn: 13, full: 9999,
} as const;

/* ── Elevation / shadows ───────────────────────────────────────────────── */
export const shadow = {
    sm: '0 1px 2px rgba(0,0,0,0.04)',
    md: '0 2px 8px rgba(0,0,0,0.06)',
    lg: '0 4px 12px rgba(0,0,0,0.08)',
    xl: '0 8px 24px rgba(0,0,0,0.12)',
    // Focus ring (lime glow) — matches input/button focus in tokens.css
    focus: '0 0 0 3px rgba(209,244,112,0.45)',
} as const;

/* ── Motion ────────────────────────────────────────────────────────────── */
export const motion = {
    fast: '0.1s ease',
    normal: '0.15s ease',
    slow: '0.25s cubic-bezier(0.16, 1, 0.3, 1)',
    easeOut: 'cubic-bezier(0.16, 1, 0.3, 1)',
    easeInOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
} as const;

/* ── Z-index scale ─────────────────────────────────────────────────────── */
export const zIndex = {
    base: 0,
    dropdown: 1000,
    sticky: 1100,
    header: 1200,
    drawer: 1300,
    modalBackdrop: 1400,
    modal: 1410,
    popover: 1500,
    toast: 1600,
    tooltip: 1700,
    /**
     * A Popover rendered INSIDE the Confirm dialog, and the only entry in this scale whose
     * number comes from the app rather than from the scale.
     *
     * BRACKETED BY TWO MEASURED NUMBERS. Below it: ConfirmContext's backdrop, inline
     * `zIndex: 10000` (design 5.1 cites ConfirmContext.tsx:89; measured on this tree it is
     * ConfirmContext.tsx:215), whose dialog card is a non-positioned child - so 10001 paints
     * above the card. Above it: the toast band at 10002 (Layout.css:1718, inner-ux.css:776),
     * which correctly still wins, because a toast must be readable over an open menu.
     *
     * `popover: 1500` cannot serve this case and `dropdown: 1000` cannot serve the ordinary
     * one: 1000 TIES with the mobile sidebar (Layout.css `.sidebar` at <=768px) and would
     * resolve on DOM order. The rest of this scale is aspirational - the app's real overlay
     * band is 9998-10002 - and reconciling it is a separate task, not a prerequisite for a
     * dropdown. No call site passes layer="overlay" today; the entry exists so the hazard is
     * answered rather than discovered.
     */
    overlayPopover: 10001,
} as const;

/* ── Layout ────────────────────────────────────────────────────────────── */
export const layout = {
    maxWidth: 1200,
    maxWidthWide: 1400,
    sidebarWidth: 240,
    headerHeight: 60,
    tapTarget: 44, // min touch target (px) — accessibility / mobile
} as const;

/* ── Breakpoints (px) ──────────────────────────────────────────────────── */
export const breakpoints = { sm: 480, md: 768, lg: 1024, xl: 1280 } as const;
export const mq = {
    sm: `@media (max-width: ${breakpoints.sm}px)`,
    md: `@media (max-width: ${breakpoints.md}px)`,
    lg: `@media (max-width: ${breakpoints.lg}px)`,
} as const;

/**
 * Back-compat alias for the inline `C` object historically used in pages like
 * design-reference.tsx. Prefer importing `colors` directly in new code.
 */
export const C = {
    primary: colors.primary,
    primaryHover: colors.primaryHover,
    lime: colors.lime,
    limeHover: colors.limeHover,
    white: colors.white,
    bg2: colors.bgSecondary,
    bgHover: colors.bgHover,
    text: colors.text,
    text2: colors.textSecondary,
    textMuted: colors.textLight,
    border: colors.border,
    borderDark: colors.borderDark,
    danger: colors.danger,
    dangerLight: colors.dangerLight,
} as const;

const tokens = {
    colors, status, font, fontSize, fontWeight, lineHeight,
    space, radius, shadow, motion, zIndex, layout, breakpoints, mq, C,
};
export default tokens;
