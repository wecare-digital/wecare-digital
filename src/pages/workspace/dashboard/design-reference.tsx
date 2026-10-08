/**
 * Design Reference — WECARE.DIGITAL
 * Complete inner page design system — ALL sections visible on one scrollable page.
 * URL: [retired public path]/design-reference
 * 
 * Shows EVERYTHING: colors, typography, spacing, buttons, inputs, cards,
 * tables, tabs, badges, toasts, empty states, loading, modals, icons,
 * responsive, accessibility, motion, page templates, shadows, and real screenshots.
 */

import React from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { C, status as STATUS } from '../../../lib/design-tokens';

interface PageProps { signOut?: () => void; user?: any; }

// Design tokens come from the shared source of truth: src/lib/design-tokens.ts
// (which mirrors src/styles/tokens.css). Do NOT hardcode hex values here.

const DesignReferencePage: React.FC<PageProps> = ( { signOut, user } ) => {
    return (
        <Layout user={ user } onSignOut={ signOut }>
            <SEO title="Design Reference | WECARE.DIGITAL" description="Complete design system reference" noindex={ true } />
            <div className="inner-page" style={ { padding: 0, overflow: 'auto', background: '#fff' } }>
                <div style={ { maxWidth: 1400, margin: '0 auto', padding: '32px 24px' } }>

                    {/* ═══════════════════════════════════════════════════════════════
              HEADER
          ═══════════════════════════════════════════════════════════════ */}
                    <div style={ { marginBottom: 48, borderBottom: `3px solid ${C.lime}`, paddingBottom: 24 } }>
                        <h1 style={ { fontSize: 34, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>
                            Design Reference — WECARE.DIGITAL
                        </h1>
                        <p style={ { fontSize: 15, color: C.text2, margin: 0 } }>
                            Complete inner page design system. Lime + Dark Green theme. Every component, token, and pattern documented below.
                        </p>
                        <div style={ { marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap' } }>
                            <span style={ { padding: '4px 12px', borderRadius: 20, background: C.lime, color: C.primary, fontSize: 12, fontWeight: 600 } }>v4.0</span>
                            <span style={ { padding: '4px 12px', borderRadius: 20, background: C.bg2, color: C.text2, fontSize: 12, fontWeight: 500 } }>39 Sections</span>
                            <span style={ { padding: '4px 12px', borderRadius: 20, background: C.bg2, color: C.text2, fontSize: 12, fontWeight: 500 } }>WCAG 2.1 AA</span>
                            <span style={ { padding: '4px 12px', borderRadius: 20, background: C.bg2, color: C.text2, fontSize: 12, fontWeight: 500 } }>Mobile-First</span>
                            <span style={ { padding: '4px 12px', borderRadius: 20, background: C.bg2, color: C.text2, fontSize: 12, fontWeight: 500 } }>Single Source of Truth</span>
                        </div>
                        <div style={ { marginTop: 16, background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '12px 16px', fontSize: 13, color: '#374151' } }>
                            <strong>Tokens come from one place.</strong> CSS uses <code style={ { background: '#e5e7eb', padding: '1px 4px', borderRadius: 3 } }>var(--token)</code> from <code style={ { background: '#e5e7eb', padding: '1px 4px', borderRadius: 3 } }>src/styles/tokens.css</code>. TS/TSX imports from <code style={ { background: '#e5e7eb', padding: '1px 4px', borderRadius: 3 } }>src/lib/design-tokens.ts</code> — never hardcode hex.
                        </div>
                    </div>

                    {/* ═══════════════════════════════════════════════════════════════
              1. COLOR PALETTE
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>1. Color Palette</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Lime + Dark Green on white. Minimal, professional, high contrast.</p>

                        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 } }>
                            { [
                                { name: 'Primary', hex: '#1a3a2a', fg: '#fff' },
                                { name: 'Primary Hover', hex: '#0f2a1d', fg: '#fff' },
                                { name: 'Lime', hex: '#d1f470', fg: '#1a3a2a' },
                                { name: 'Lime Hover', hex: '#c5e866', fg: '#1a3a2a' },
                                { name: 'White', hex: '#ffffff', fg: '#1a1a1a' },
                                { name: 'BG Secondary', hex: '#f9fafb', fg: '#1a1a1a' },
                                { name: 'BG Hover', hex: '#f5f5f5', fg: '#1a1a1a' },
                                { name: 'Text Primary', hex: '#1a1a1a', fg: '#fff' },
                                { name: 'Text Secondary', hex: '#6b7280', fg: '#fff' },
                                { name: 'Text Muted', hex: '#9ca3af', fg: '#1a1a1a' },
                                { name: 'Border', hex: '#e5e7eb', fg: '#1a1a1a' },
                                { name: 'Border Dark', hex: '#d1d5db', fg: '#1a1a1a' },
                                { name: 'Danger', hex: '#dc2626', fg: '#fff' },
                                { name: 'Danger Light', hex: '#fef2f2', fg: '#dc2626' },
                            ].map( ( c, i ) => (
                                <div key={ i } style={ { textAlign: 'center' } }>
                                    <div style={ { width: '100%', height: 72, borderRadius: 12, background: c.hex, display: 'flex', alignItems: 'center', justifyContent: 'center', color: c.fg, fontSize: 11, fontWeight: 600, border: '1px solid #e5e7eb' } }>{ c.hex }</div>
                                    <div style={ { marginTop: 6, fontSize: 12, fontWeight: 600, color: '#1a1a1a' } }>{ c.name }</div>
                                </div>
                            ) ) }
                        </div>

                        <div style={ { marginTop: 16, background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '12px 16px', fontSize: 13, color: '#374151' } }>
                            <strong>Rules:</strong> Primary for text/borders/active. Lime for CTAs/active tabs/accent borders. White for backgrounds. Danger only for errors/destructive. Use CSS variables from <code style={ { background: '#e5e7eb', padding: '1px 4px', borderRadius: 3 } }>tokens.css</code>.
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              2. TYPOGRAPHY
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>2. Typography</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Font: Inter. System fallback stack. Clean hierarchy.</p>

                        <div style={ { border: `2px solid ${C.lime}`, borderRadius: 16, overflow: 'hidden' } }>
                            <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 13 } }>
                                <thead>
                                    <tr style={ { background: C.lime } }>
                                        <th style={ { padding: '12px 16px', textAlign: 'left', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', color: C.primary } }>Element</th>
                                        <th style={ { padding: '12px 16px', textAlign: 'left', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', color: C.primary } }>Size</th>
                                        <th style={ { padding: '12px 16px', textAlign: 'left', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', color: C.primary } }>Weight</th>
                                        <th style={ { padding: '12px 16px', textAlign: 'left', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', color: C.primary } }>Preview</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    { [
                                        { el: 'Page Title (h1)', size: '28px', weight: '700', preview: 'Dashboard Overview' },
                                        { el: 'Section Title (h2)', size: '20px', weight: '600', preview: 'Recent Activity' },
                                        { el: 'Card Title (h3)', size: '16px', weight: '600', preview: 'WhatsApp Messages' },
                                        { el: 'Body Text', size: '14px', weight: '400', preview: 'The quick brown fox jumps over the lazy dog.' },
                                        { el: 'Button Label', size: '14px', weight: '500', preview: 'Send Message' },
                                        { el: 'Table Cell', size: '13px', weight: '400', preview: '+91 98765 43210' },
                                        { el: 'Caption / Label', size: '12px', weight: '600', preview: 'TOTAL MESSAGES' },
                                        { el: 'Monospace', size: '12px', weight: '400', preview: 'arn:aws:lambda:ap-south-1:*' },
                                    ].map( ( t, i ) => (
                                        <tr key={ i } style={ { borderBottom: '1px solid #f3f4f6' } }>
                                            <td style={ { padding: '12px 16px', fontWeight: 500 } }>{ t.el }</td>
                                            <td style={ { padding: '12px 16px' } }><code style={ { background: '#f9fafb', padding: '2px 6px', borderRadius: 4, fontSize: 11 } }>{ t.size }</code></td>
                                            <td style={ { padding: '12px 16px' } }>{ t.weight }</td>
                                            <td style={ { padding: '12px 16px', fontSize: t.size, fontWeight: parseInt( t.weight ), fontFamily: t.el.includes( 'Mono' ) ? 'monospace' : 'inherit' } }>{ t.preview }</td>
                                        </tr>
                                    ) ) }
                                </tbody>
                            </table>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              3. SPACING & LAYOUT
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>3. Spacing & Layout</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 } }>
                            <div>
                                <h3 style={ { fontSize: 16, fontWeight: 600, marginBottom: 12 } }>Spacing Scale</h3>
                                { [ 4, 8, 12, 16, 20, 24, 32, 40, 48 ].map( ( v, i ) => (
                                    <div key={ i } style={ { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 } }>
                                        <code style={ { fontSize: 11, background: '#f9fafb', padding: '2px 6px', borderRadius: 4, width: 80, display: 'inline-block' } }>--space-{ [ 1, 2, 3, 4, 5, 6, 8, 10, 12 ][ i ] }</code>
                                        <div style={ { width: v, height: 14, background: C.lime, borderRadius: 3, border: `1px solid ${C.primary}` } } />
                                        <span style={ { fontSize: 11, color: C.text2 } }>{ v }px</span>
                                    </div>
                                ) ) }
                            </div>
                            <div>
                                <h3 style={ { fontSize: 16, fontWeight: 600, marginBottom: 12 } }>Border Radius</h3>
                                <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 } }>
                                    { [
                                        { r: 6, label: 'sm (6px)' },
                                        { r: 8, label: 'md (8px)' },
                                        { r: 13, label: 'btn (13px)' },
                                        { r: 12, label: 'lg (12px)' },
                                        { r: 16, label: '2xl (16px)' },
                                        { r: 9999, label: 'full' },
                                    ].map( ( b, i ) => (
                                        <div key={ i } style={ { textAlign: 'center' } }>
                                            <div style={ { width: 56, height: 56, borderRadius: b.r, border: `2px solid ${C.primary}`, background: C.bg2, margin: '0 auto 6px' } } />
                                            <div style={ { fontSize: 11, color: C.text2 } }>{ b.label }</div>
                                        </div>
                                    ) ) }
                                </div>
                                <h3 style={ { fontSize: 16, fontWeight: 600, margin: '24px 0 12px' } }>Layout Dimensions</h3>
                                <div style={ { fontSize: 13, lineHeight: 2 } }>
                                    <div>Max content: <strong>1400px</strong></div>
                                    <div>Sidebar: <strong>240px</strong></div>
                                    <div>Header: <strong>56px</strong></div>
                                    <div>Page padding: <strong>24px</strong></div>
                                    <div>Card padding: <strong>16-20px</strong></div>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              4. BUTTONS — ALL VARIANTS, SIZES, STATES
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>4. Buttons</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>13px radius, 44px min-height, 1.5px border. All interactive.</p>

                        <h3 style={ { fontSize: 15, fontWeight: 600, marginBottom: 12 } }>4.1 Variants</h3>
                        <div style={ { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 } }>
                            <button className="btn btn-primary btn-md">Primary CTA</button>
                            <button className="btn btn-secondary btn-md">Secondary</button>
                            <button className="btn btn-ghost btn-md">Ghost</button>
                            <button className="btn btn-danger btn-md">Danger</button>
                            <button className="btn btn-primary btn-md" disabled>Disabled</button>
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, marginBottom: 12 } }>4.2 Sizes</h3>
                        <div style={ { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 24 } }>
                            <button className="btn btn-secondary btn-sm">Small 36px</button>
                            <button className="btn btn-secondary btn-md">Medium 44px</button>
                            <button className="btn btn-secondary btn-lg">Large 52px</button>
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, marginBottom: 12 } }>4.3 Icon Buttons</h3>
                        <div style={ { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 24 } }>
                            <button className="icon-btn icon-btn-md" aria-label="Refresh">↻</button>
                            <button className="icon-btn icon-btn-md" aria-label="Add">+</button>
                            <button className="icon-btn icon-btn-md" aria-label="Close">✕</button>
                            <button className="icon-btn icon-btn-md icon-btn-danger" aria-label="Delete">🗑</button>
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, marginBottom: 12 } }>4.4 Button States</h3>
                        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 } }>
                            { [
                                { label: 'Default', bg: '#fff', border: C.primary, color: C.text },
                                { label: 'Hover', bg: C.bg2, border: C.primaryHover, color: C.text },
                                { label: 'Active/Pressed', bg: '#e5e7eb', border: C.primary, color: C.text },
                                { label: 'Focus', bg: '#fff', border: C.primary, color: C.text, shadow: `0 0 0 3px rgba(26,58,42,0.3)` },
                                { label: 'Disabled', bg: '#fff', border: C.primary, color: C.text, opacity: 0.4 },
                                { label: 'Loading', bg: C.lime, border: C.primary, color: C.primary },
                            ].map( ( s, i ) => (
                                <div key={ i } style={ { textAlign: 'center', padding: 12, background: '#f9fafb', borderRadius: 12 } }>
                                    <div style={ { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '10px 18px', minHeight: 44, borderRadius: 13, border: `1.5px solid ${s.border}`, background: s.bg, color: s.color, fontSize: 14, fontWeight: 500, opacity: s.opacity || 1, boxShadow: s.shadow || 'none' } }>
                                        { s.label === 'Loading' ? '⟳ Sending...' : s.label }
                                    </div>
                                    <div style={ { marginTop: 8, fontSize: 11, color: C.text2 } }>{ s.label }</div>
                                </div>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              5. FORM INPUTS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>5. Form Inputs</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>44px height, lime border, dark green focus. 16px font on mobile.</p>

                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            <div className="form-group">
                                <label style={ { display: 'block', fontSize: 14, fontWeight: 500, color: '#374151', marginBottom: 8 } }>Text Input (Default)</label>
                                <input className="search-input" type="text" placeholder="Enter value..." style={ { width: '100%', maxWidth: 'none' } } readOnly />
                            </div>
                            <div className="form-group">
                                <label style={ { display: 'block', fontSize: 14, fontWeight: 500, color: '#374151', marginBottom: 8 } }>Search Input</label>
                                <input className="search-input" type="search" placeholder="🔍 Search contacts..." style={ { width: '100%', maxWidth: 'none' } } readOnly />
                            </div>
                            <div className="form-group">
                                <label style={ { display: 'block', fontSize: 14, fontWeight: 500, color: '#374151', marginBottom: 8 } }>Select Dropdown</label>
                                { /* NOT MIGRATED, on purpose - design section 5.2: a specimen on the
                                     design-reference page is not a surface a custom listbox improves,
                                     and it keeps its Layer-1-skinned native box so the closed state is
                                     already fully ours, which is the whole visible win. */ }
                                <select style={ { width: '100%' } }>
                                    <option>Choose channel...</option>
                                    <option>WhatsApp</option>
                                    <option>SMS</option>
                                    <option>Email</option>
                                    <option>RCS</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label style={ { display: 'block', fontSize: 14, fontWeight: 500, color: '#374151', marginBottom: 8 } }>Error State</label>
                                <input type="text" defaultValue="Invalid phone" className="error" style={ { width: '100%', borderColor: '#dc2626' } } readOnly />
                                <span style={ { fontSize: 12, color: '#dc2626', marginTop: 4, display: 'block' } }>Phone number must start with +91</span>
                            </div>
                            <div className="form-group" style={ { gridColumn: '1 / -1' } }>
                                <label style={ { display: 'block', fontSize: 14, fontWeight: 500, color: '#374151', marginBottom: 8 } }>Textarea</label>
                                <textarea placeholder="Type your WhatsApp message here..." style={ { width: '100%', minHeight: 100 } } readOnly />
                            </div>
                            <div className="form-group">
                                <label style={ { display: 'block', fontSize: 14, fontWeight: 500, color: '#374151', marginBottom: 8 } }>Disabled Input</label>
                                <input type="text" value="Cannot edit" disabled style={ { width: '100%', opacity: 0.5 } } readOnly />
                            </div>
                            <div className="form-group">
                                <label style={ { display: 'block', fontSize: 14, fontWeight: 500, color: '#374151', marginBottom: 8 } }>Checkbox + Radio</label>
                                <div style={ { display: 'flex', gap: 16, alignItems: 'center' } }>
                                    <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 14 } }><input type="checkbox" defaultChecked style={ { accentColor: C.primary } } /> WhatsApp</label>
                                    <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 14 } }><input type="checkbox" style={ { accentColor: C.primary } } /> SMS</label>
                                    <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 14 } }><input type="radio" name="ch" defaultChecked style={ { accentColor: C.primary } } /> Active</label>
                                    <label style={ { display: 'flex', alignItems: 'center', gap: 6, fontSize: 14 } }><input type="radio" name="ch" style={ { accentColor: C.primary } } /> Inactive</label>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              6. CARDS & CONTAINERS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>6. Cards & Containers</h2>

                        <h3 style={ { fontSize: 15, fontWeight: 600, margin: '16px 0 12px' } }>6.1 Stat Cards</h3>
                        <div className="stats-grid" style={ { gridTemplateColumns: 'repeat(4, 1fr)' } }>
                            <div className="stat-card"><div className="stat-value">1,247</div><div className="stat-label">Messages Sent</div></div>
                            <div className="stat-card accent"><div className="stat-value">98.5%</div><div className="stat-label">Delivery Rate</div></div>
                            <div className="stat-card"><div className="stat-value">342</div><div className="stat-label">Contacts</div></div>
                            <div className="stat-card"><div className="stat-value">₹12.4K</div><div className="stat-label">Revenue</div></div>
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, margin: '24px 0 12px' } }>6.2 Action Cards</h3>
                        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16 } }>
                            { [
                                { icon: '📱', title: 'WhatsApp', desc: 'Send via WA Business API' },
                                { icon: '💬', title: 'SMS', desc: 'AWS Pinpoint / IN SMS' },
                                { icon: '📧', title: 'Email', desc: 'Amazon SES integration' },
                                { icon: '📞', title: 'Voice', desc: 'Outbound voice calls' },
                                { icon: '🔔', title: 'Push', desc: 'FCM push notifications' },
                                { icon: '💳', title: 'Pay', desc: 'Razorpay payment links' },
                            ].map( ( c, i ) => (
                                <div key={ i } className="inner-card" style={ { cursor: 'pointer', transition: 'all 0.15s ease' } }>
                                    <div style={ { fontSize: 28, marginBottom: 8 } }>{ c.icon }</div>
                                    <div style={ { fontSize: 15, fontWeight: 600, color: C.text, marginBottom: 4 } }>{ c.title }</div>
                                    <div style={ { fontSize: 13, color: C.text2 } }>{ c.desc }</div>
                                </div>
                            ) ) }
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, margin: '24px 0 12px' } }>6.3 Info Banner</h3>
                        <div className="info-banner">
                            <span>ℹ️</span>
                            <span>WhatsApp Business API requires approved message templates for outbound marketing messages. <a href="#" style={ { color: C.primary, fontWeight: 500 } }>Learn more →</a></span>
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, margin: '24px 0 12px' } }>6.4 Section Card (Content Container)</h3>
                        <div className="inner-card">
                            <h4 style={ { margin: '0 0 12px', fontSize: 16, fontWeight: 600 } }>Recent Messages</h4>
                            <p style={ { margin: 0, fontSize: 14, color: C.text2 } }>This is a section card used to group related content. It has 1.5px lime border, 16px border-radius, and 20px padding.</p>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              7. TABLES
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>7. Tables</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>2px lime border, lime header, hover rows, monospace for data.</p>

                        <div className="table-container">
                            <table className="inner-table">
                                <thead>
                                    <tr>
                                        <th>Contact</th>
                                        <th>Phone</th>
                                        <th>Channel</th>
                                        <th>Status</th>
                                        <th>Last Message</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <td><strong>Rahul Sharma</strong></td>
                                        <td style={ { fontFamily: 'monospace' } }>+91 98765 43210</td>
                                        <td>WhatsApp</td>
                                        <td><span style={ { padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: C.lime, color: C.primary } }>Active</span></td>
                                        <td>2 min ago</td>
                                        <td><button className="btn btn-secondary btn-sm">View</button></td>
                                    </tr>
                                    <tr>
                                        <td><strong>Priya Patel</strong></td>
                                        <td style={ { fontFamily: 'monospace' } }>+91 87654 32109</td>
                                        <td>SMS</td>
                                        <td><span style={ { padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: C.dangerLight, color: C.danger } }>Failed</span></td>
                                        <td>1 hour ago</td>
                                        <td><button className="btn btn-secondary btn-sm">Retry</button></td>
                                    </tr>
                                    <tr>
                                        <td><strong>Amit Kumar</strong></td>
                                        <td style={ { fontFamily: 'monospace' } }>+91 76543 21098</td>
                                        <td>RCS</td>
                                        <td><span style={ { padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: C.bg2, color: C.primary } }>Delivered</span></td>
                                        <td>5 min ago</td>
                                        <td><button className="btn btn-secondary btn-sm">View</button></td>
                                    </tr>
                                    <tr>
                                        <td><strong>Neha Singh</strong></td>
                                        <td style={ { fontFamily: 'monospace' } }>+91 65432 10987</td>
                                        <td>Email</td>
                                        <td><span style={ { padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: '#e5e7eb', color: '#374151' } }>Pending</span></td>
                                        <td>10 min ago</td>
                                        <td><button className="btn btn-secondary btn-sm">View</button></td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              8. TABS & NAVIGATION
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>8. Tabs & Navigation</h2>

                        <h3 style={ { fontSize: 15, fontWeight: 600, margin: '16px 0 12px' } }>8.1 Main Tabs (Lime Container)</h3>
                        <div className="tabs">
                            <button className="tab-btn active">Overview</button>
                            <button className="tab-btn">Messages</button>
                            <button className="tab-btn">Pay</button>
                            <button className="tab-btn">Billing</button>
                            <button className="tab-btn">Health</button>
                            <button className="tab-btn">AI</button>
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, margin: '24px 0 12px' } }>8.2 Sub-Tabs</h3>
                        <div className="tabs tabs-sub">
                            <button className="tab-btn active">All</button>
                            <button className="tab-btn">Sent</button>
                            <button className="tab-btn">Received</button>
                            <button className="tab-btn">Failed</button>
                            <button className="tab-btn">Queued</button>
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, margin: '24px 0 12px' } }>8.3 Sidebar Navigation (Dark)</h3>
                        <div style={ { background: C.primary, borderRadius: 16, padding: 16, maxWidth: 260 } }>
                            { [
                                { label: 'Dashboard', active: true },
                                { label: 'Messages', active: false },
                                { label: 'Pay', active: false },
                                { label: 'Contacts', active: false },
                                { label: 'Store', active: false },
                                { label: 'SEO', active: false },
                            ].map( ( item, i ) => (
                                <div key={ i } style={ { padding: '10px 14px', borderRadius: 8, background: item.active ? 'rgba(209,244,112,0.3)' : 'transparent', borderLeft: item.active ? `3px solid ${C.lime}` : '3px solid transparent', color: item.active ? '#fff' : 'rgba(255,255,255,0.6)', fontSize: 14, fontWeight: item.active ? 500 : 400, marginBottom: 2, cursor: 'pointer' } }>{ item.label }</div>
                            ) ) }
                        </div>

                        <h3 style={ { fontSize: 15, fontWeight: 600, margin: '24px 0 12px' } }>8.4 Breadcrumbs</h3>
                        <div className="breadcrumbs">
                            <ol className="breadcrumbs-list">
                                <li className="breadcrumbs-item"><a className="breadcrumbs-link" href="#">Home</a><span className="breadcrumbs-separator">›</span></li>
                                <li className="breadcrumbs-item"><a className="breadcrumbs-link" href="#">Dashboard</a><span className="breadcrumbs-separator">›</span></li>
                                <li className="breadcrumbs-item"><span className="breadcrumbs-current">Design Reference</span></li>
                            </ol>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              9. BADGES & PILLS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>9. Badges & Status Pills</h2>
                        <div style={ { display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 } }>
                            { [
                                { label: 'Active', bg: C.lime, color: C.primary },
                                { label: 'Delivered', bg: C.bg2, color: C.primary },
                                { label: 'Sent', bg: '#e5e7eb', color: '#374151' },
                                { label: 'Pending', bg: '#fff', color: C.text2 },
                                { label: 'Failed', bg: C.dangerLight, color: C.danger },
                                { label: 'Error', bg: C.primary, color: '#fff' },
                                { label: 'New', bg: C.lime, color: C.primary },
                                { label: 'Draft', bg: '#f9fafb', color: '#9ca3af' },
                                { label: 'Published', bg: C.lime, color: C.primary },
                                { label: 'Archived', bg: '#e5e7eb', color: '#6b7280' },
                                { label: 'Online', bg: '#d1f470', color: '#1a3a2a' },
                                { label: 'Offline', bg: '#fef2f2', color: '#dc2626' },
                            ].map( ( b, i ) => (
                                <span key={ i } style={ { display: 'inline-block', padding: '4px 12px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: b.bg, color: b.color, border: '1px solid ' + ( b.bg === '#fff' ? '#e5e7eb' : 'transparent' ) } }>{ b.label }</span>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              10. TOASTS & ALERTS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>10. Toasts & Alerts</h2>
                        <div style={ { display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 420 } }>
                            <div className="toast toast-success" style={ { position: 'static', animation: 'none' } }>
                                <div className="toast-icon">✓</div>
                                <span className="toast-message">Message sent successfully to +91 98765 43210</span>
                                <button className="toast-close">✕</button>
                            </div>
                            <div className="toast toast-error" style={ { position: 'static', animation: 'none', borderColor: '#dc2626' } }>
                                <div className="toast-icon" style={ { background: C.dangerLight, color: C.danger } }>!</div>
                                <span className="toast-message">Failed to deliver — recipient blocked</span>
                                <button className="toast-close">✕</button>
                            </div>
                            <div className="toast toast-warning" style={ { position: 'static', animation: 'none' } }>
                                <div className="toast-icon">⚠</div>
                                <span className="toast-message">Rate limit: 45/50 messages used this minute</span>
                                <button className="toast-close">✕</button>
                            </div>
                            <div className="toast toast-info" style={ { position: 'static', animation: 'none' } }>
                                <div className="toast-icon">ℹ</div>
                                <span className="toast-message">New template approved by Meta</span>
                                <button className="toast-close">✕</button>
                            </div>
                        </div>
                        <div style={ { marginTop: 16, background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '12px 16px', fontSize: 13 } }>
                            <strong>Rules:</strong> Top-right position. Auto-dismiss: 5s success, 8s error. Max 3 visible. Slide-in from right. Always include close button.
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              11. EMPTY STATES
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>11. Empty States</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            <div className="inner-card">
                                <div className="empty-state">
                                    <div className="empty-state-icon">📭</div>
                                    <h3 className="empty-state-title">No messages yet</h3>
                                    <p className="empty-state-description">Send your first WhatsApp message to get started with customer engagement.</p>
                                    <button className="btn btn-primary btn-md">Send First Message</button>
                                </div>
                            </div>
                            <div className="inner-card">
                                <div className="empty-state">
                                    <div className="empty-state-icon">🔍</div>
                                    <h3 className="empty-state-title">No results found</h3>
                                    <p className="empty-state-description">Try adjusting your search or filter criteria to find what you need.</p>
                                    <button className="btn btn-secondary btn-md">Clear Filters</button>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              12. LOADING STATES
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>12. Loading States</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 } }>
                            {/* Skeleton */ }
                            <div className="inner-card">
                                <h4 style={ { fontSize: 14, fontWeight: 600, marginBottom: 12 } }>Skeleton Loading</h4>
                                <div style={ { height: 14, width: '60%', background: '#f5f5f5', borderRadius: 4, marginBottom: 10 } } className="skeleton" />
                                <div style={ { height: 28, width: '40%', background: '#f5f5f5', borderRadius: 4, marginBottom: 10 } } className="skeleton" />
                                <div style={ { height: 12, width: '80%', background: '#f5f5f5', borderRadius: 4 } } className="skeleton" />
                            </div>
                            {/* Spinner */ }
                            <div className="inner-card" style={ { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 140 } }>
                                <h4 style={ { fontSize: 14, fontWeight: 600, marginBottom: 12 } }>Spinner</h4>
                                <div className="spinner" style={ { width: 32, height: 32, border: '3px solid #f3f4f6', borderTop: `3px solid ${C.primary}`, borderRadius: '50%' } } />
                                <span style={ { marginTop: 8, fontSize: 13, color: C.text2 } }>Loading data...</span>
                            </div>
                            {/* Button Loading */ }
                            <div className="inner-card" style={ { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 140 } }>
                                <h4 style={ { fontSize: 14, fontWeight: 600, marginBottom: 12 } }>Button Loading</h4>
                                <button className="btn btn-primary btn-md btn-loading" disabled>
                                    <span className="spinner" style={ { width: 16, height: 16, border: '2px solid rgba(26,58,42,0.3)', borderTop: `2px solid ${C.primary}`, borderRadius: '50%', display: 'inline-block' } } />
                                    <span className="btn-text-loading">Sending...</span>
                                </button>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              13. MODALS & DIALOGS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>13. Modals & Dialogs</h2>
                        <div style={ { background: 'rgba(0,0,0,0.25)', borderRadius: 16, padding: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' } }>
                            <div style={ { background: '#fff', borderRadius: 16, padding: 24, maxWidth: 420, width: '100%', boxShadow: '0 20px 40px rgba(0,0,0,0.2)' } }>
                                <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } }>
                                    <h3 style={ { margin: 0, fontSize: 18, fontWeight: 600 } }>Delete Contact?</h3>
                                    <button className="icon-btn icon-btn-sm icon-btn-ghost" aria-label="Close">✕</button>
                                </div>
                                <p style={ { fontSize: 14, color: C.text2, margin: '0 0 24px' } }>
                                    Are you sure you want to delete <strong>Rahul Sharma</strong>? This will remove all message history and cannot be undone.
                                </p>
                                <div style={ { display: 'flex', gap: 12, justifyContent: 'flex-end' } }>
                                    <button className="btn btn-secondary btn-md">Cancel</button>
                                    <button className="btn btn-danger btn-md">Delete Contact</button>
                                </div>
                            </div>
                        </div>
                        <div style={ { marginTop: 16, background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '12px 16px', fontSize: 13 } }>
                            <strong>Modal Rules:</strong> Max-width 480px. Radius 16px. Overlay rgba(0,0,0,0.5). Focus trap. ESC to close. Animate: fade + slide-up (250ms). Always include close button.
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              14. ICONS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>14. Icons</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Stroke-based SVGs. 1.5px stroke. Sizes: 14/16/18/20px. Color inherits from parent.</p>
                        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(90px, 1fr))', gap: 12 } }>
                            { [
                                '↻ Refresh', '+ Add', '✕ Close', '🔍 Search', '✏️ Edit', '🗑️ Delete',
                                '📱 WhatsApp', '💬 SMS', '📧 Email', '📞 Voice', '🔔 Push', '💳 Pay',
                                '👤 Contact', '📊 Chart', '⚙️ Settings', '🔗 Link', '📋 Copy', '↗️ Export',
                                '📥 Import', '🔄 Sync', '📄 Document', '🏷️ Tag', '⭐ Star', '🔒 Lock',
                            ].map( ( icon, i ) => (
                                <div key={ i } style={ { textAlign: 'center', padding: 10, background: '#f9fafb', borderRadius: 10, border: '1px solid #e5e7eb' } }>
                                    <div style={ { fontSize: 20, marginBottom: 4 } }>{ icon.split( ' ' )[ 0 ] }</div>
                                    <div style={ { fontSize: 10, color: C.text2 } }>{ icon.split( ' ' ).slice( 1 ).join( ' ' ) }</div>
                                </div>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              15. SHADOWS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>15. Shadows</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 20 } }>
                            { [
                                { name: 'sm', shadow: '0 1px 2px rgba(0,0,0,0.04)' },
                                { name: 'md', shadow: '0 2px 8px rgba(0,0,0,0.06)' },
                                { name: 'lg', shadow: '0 4px 12px rgba(0,0,0,0.08)' },
                                { name: 'xl', shadow: '0 8px 24px rgba(0,0,0,0.12)' },
                            ].map( ( s, i ) => (
                                <div key={ i } style={ { textAlign: 'center' } }>
                                    <div style={ { width: '100%', height: 80, background: '#fff', borderRadius: 12, boxShadow: s.shadow, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, color: C.text2 } }>shadow-{ s.name }</div>
                                    <code style={ { fontSize: 10, color: C.text2, marginTop: 8, display: 'block' } }>{ s.shadow }</code>
                                </div>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              16. RESPONSIVE BREAKPOINTS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>16. Responsive Breakpoints</h2>
                        <div className="table-container">
                            <table className="inner-table">
                                <thead>
                                    <tr>
                                        <th>Breakpoint</th>
                                        <th>Width</th>
                                        <th>Grid</th>
                                        <th>Sidebar</th>
                                        <th>Padding</th>
                                        <th>Notes</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr><td><strong>Mobile S</strong></td><td>≤ 480px</td><td>1 col</td><td>Hidden</td><td>16px</td><td>Stack everything, full-width CTAs</td></tr>
                                    <tr><td><strong>Mobile L</strong></td><td>481–768px</td><td>2 col</td><td>Overlay</td><td>20px</td><td>Hamburger menu, collapsible</td></tr>
                                    <tr><td><strong>Tablet</strong></td><td>769–1024px</td><td>2-3 col</td><td>Collapsed</td><td>24px</td><td>Icons-only sidebar</td></tr>
                                    <tr><td><strong>Desktop</strong></td><td>1025–1440px</td><td>auto-fit</td><td>Full 240px</td><td>24px</td><td>Full layout</td></tr>
                                    <tr><td><strong>Wide</strong></td><td>&gt; 1440px</td><td>auto-fit</td><td>Full 240px</td><td>24px</td><td>Max-width 1400px centered</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              17. ACCESSIBILITY
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>17. Accessibility (WCAG 2.1 AA)</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            <div className="inner-card">
                                <h3 style={ { fontSize: 15, fontWeight: 600, marginBottom: 12, color: C.primary } }>✅ Implemented</h3>
                                <ul style={ { margin: 0, padding: '0 0 0 18px', fontSize: 13, lineHeight: 2.2, color: '#374151' } }>
                                    <li>Min 44px touch targets on all buttons/links</li>
                                    <li>Focus-visible ring: 3px rgba(26,58,42,0.3)</li>
                                    <li>Color contrast: #1a3a2a on #fff = 12.6:1 ✓</li>
                                    <li>Color contrast: #6b7280 on #fff = 5.0:1 ✓</li>
                                    <li>Semantic HTML headings (h1→h4)</li>
                                    <li>Keyboard navigation (Tab, Enter, Escape)</li>
                                    <li>aria-label on icon-only buttons</li>
                                    <li>prefers-reduced-motion: disable animations</li>
                                    <li>16px input font (prevents iOS zoom)</li>
                                    <li>Safe area insets for notch devices</li>
                                    <li>touch-action: manipulation (no double-tap zoom)</li>
                                </ul>
                            </div>
                            <div className="inner-card">
                                <h3 style={ { fontSize: 15, fontWeight: 600, marginBottom: 12, color: C.danger } }>⚠️ Improvements Needed</h3>
                                <ul style={ { margin: 0, padding: '0 0 0 18px', fontSize: 13, lineHeight: 2.2, color: '#374151' } }>
                                    <li>Change lang=&quot;en&quot; → lang=&quot;en-IN&quot;</li>
                                    <li>Add skip-to-content link</li>
                                    <li>Add aria-live=&quot;polite&quot; on toast container</li>
                                    <li>Add role=&quot;alert&quot; on error messages</li>
                                    <li>Complete modal focus trap</li>
                                    <li>Add aria-expanded on sidebar items</li>
                                    <li>Add aria-current=&quot;page&quot; on active nav</li>
                                    <li>Add aria-describedby on form errors</li>
                                    <li>Test with NVDA + VoiceOver</li>
                                    <li>Add high-contrast mode support</li>
                                </ul>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              18. MOTION & TRANSITIONS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>18. Motion & Transitions</h2>
                        <div className="table-container">
                            <table className="inner-table">
                                <thead>
                                    <tr>
                                        <th>Token</th>
                                        <th>Duration</th>
                                        <th>Easing</th>
                                        <th>Use Case</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr><td>--transition-fast</td><td>100ms</td><td>ease</td><td>Button press, toggle</td></tr>
                                    <tr><td>--transition-normal</td><td>150ms</td><td>ease</td><td>Hover states, border changes</td></tr>
                                    <tr><td>--transition-slow</td><td>250ms</td><td>cubic-bezier(0.16,1,0.3,1)</td><td>Modal open, sidebar expand</td></tr>
                                    <tr><td>Toast enter</td><td>200ms</td><td>ease</td><td>Slide in from right</td></tr>
                                    <tr><td>Toast exit</td><td>200ms</td><td>ease</td><td>Slide out to right</td></tr>
                                    <tr><td>Skeleton pulse</td><td>1500ms</td><td>ease-in-out (infinite)</td><td>Loading placeholder</td></tr>
                                    <tr><td>Spinner</td><td>800ms</td><td>linear (infinite)</td><td>Loading rotation</td></tr>
                                    <tr><td>Button active</td><td>instant</td><td>—</td><td>scale(0.98)</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              19. PAGE TEMPLATES
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>19. Page Templates</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            { [
                                { title: '📊 Dashboard Page', desc: 'Stats + Tabs + Content', code: '<Layout>\n  <SEO />\n  <PageHeader />\n  <StatsGrid 4-col />\n  <Tabs>\n    <TabContent />\n  </Tabs>\n</Layout>' },
                                { title: '📝 Form Page', desc: 'Input form + Preview', code: '<Layout>\n  <SEO />\n  <PageHeader />\n  <Grid 2-col>\n    <FormSection />\n    <PreviewCard />\n  </Grid>\n</Layout>' },
                                { title: '💬 Messaging Page', desc: 'Split: Contacts + Chat', code: '<Layout>\n  <SEO />\n  <SplitView>\n    <ContactsSidebar />\n    <ChatArea>\n      <MessageList />\n      <ComposeBar />\n    </ChatArea>\n  </SplitView>\n</Layout>' },
                                { title: '📋 List/Table Page', desc: 'Filters + Table + Pagination', code: '<Layout>\n  <SEO />\n  <PageHeader + CreateBtn />\n  <FilterBar />\n  <Table />\n  <Pagination />\n</Layout>' },
                            ].map( ( t, i ) => (
                                <div key={ i } className="inner-card">
                                    <h4 style={ { margin: '0 0 4px', fontSize: 16, fontWeight: 600 } }>{ t.title }</h4>
                                    <p style={ { margin: '0 0 12px', fontSize: 13, color: C.text2 } }>{ t.desc }</p>
                                    <pre style={ { background: '#f9fafb', borderRadius: 8, padding: 12, fontSize: 11, fontFamily: 'monospace', color: '#374151', margin: 0, whiteSpace: 'pre-wrap', border: '1px solid #e5e7eb' } }>{ t.code }</pre>
                                </div>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              20. COMPLETE FILE REFERENCE
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>20. File Reference</h2>
                        <div className="table-container">
                            <table className="inner-table">
                                <thead>
                                    <tr>
                                        <th>File</th>
                                        <th>Purpose</th>
                                        <th>Priority</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr><td><code>src/styles/tokens.css</code></td><td>CSS variables — colors, spacing, typography, shadows</td><td>Core</td></tr>
                                    <tr><td><code>src/styles/inner-ux.css</code></td><td>Component styles — buttons, tabs, tables, toasts, forms</td><td>Core</td></tr>
                                    <tr><td><code>src/styles/inner-pages.css</code></td><td>Page-level overrides — sidebar, cards, responsive</td><td>Core</td></tr>
                                    <tr><td><code>src/styles/Dashboard.css</code></td><td>Dashboard-specific — stats, billing, messages</td><td>Page</td></tr>
                                    <tr><td><code>src/styles/Layout.css</code></td><td>Layout structure — sidebar, header, content area</td><td>Core</td></tr>
                                    <tr><td><code>src/styles/button.css</code></td><td>Button system — variants, sizes, states</td><td>Component</td></tr>
                                    <tr><td><code>src/components/ui/Button.tsx</code></td><td>Button React component with icons</td><td>Component</td></tr>
                                    <tr><td><code>src/components/ui/Tabs.tsx</code></td><td>Tabs React component</td><td>Component</td></tr>
                                    <tr><td><code>src/components/ui/Table.tsx</code></td><td>Table React component</td><td>Component</td></tr>
                                    <tr><td><code>src/components/ui/Modal.tsx</code></td><td>Modal React component</td><td>Component</td></tr>
                                    <tr><td><code>src/components/ui/Spinner.tsx</code></td><td>Loading spinner</td><td>Component</td></tr>
                                    <tr><td><code>src/components/ui/EmptyState.tsx</code></td><td>Empty state pattern</td><td>Component</td></tr>
                                    <tr><td><code>src/components/ui/Pagination.tsx</code></td><td>Pagination component</td><td>Component</td></tr>
                                    <tr><td><code>src/config/navigation.ts</code></td><td>Sidebar navigation tree</td><td>Config</td></tr>
                                    <tr><td><code>src/components/Layout.tsx</code></td><td>Main layout wrapper</td><td>Core</td></tr>
                                    <tr><td><code>src/components/SEO.tsx</code></td><td>SEO meta tags component</td><td>Core</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              21. LOGIN / AUTH PAGE
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>21. Login / Auth Page (Cognito Authenticator)</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>AWS Amplify Authenticator with custom lime + dark green theme. Shown at /access and any protected route when unauthenticated.</p>

                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Login Form Design</h4>
                                <div style={ { background: '#f5f5f5', borderRadius: 16, padding: 32, display: 'flex', alignItems: 'center', justifyContent: 'center' } }>
                                    <div style={ { background: '#fff', borderRadius: 16, padding: 24, width: '100%', maxWidth: 320, boxShadow: '0 4px 24px rgba(0,0,0,0.08)' } }>
                                        <h3 style={ { margin: '0 0 20px', fontSize: 18, fontWeight: 600, textAlign: 'center' } }>Sign in</h3>
                                        <div style={ { marginBottom: 16 } }>
                                            <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 } }>Username</label>
                                            <input type="text" placeholder="Enter username" style={ { width: '100%', height: 44, padding: '10px 12px', border: `1.5px solid ${C.lime}`, borderRadius: 13, fontSize: 14 } } readOnly />
                                        </div>
                                        <div style={ { marginBottom: 20 } }>
                                            <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 } }>Password</label>
                                            <input type="password" placeholder="Enter password" style={ { width: '100%', height: 44, padding: '10px 12px', border: `1.5px solid ${C.lime}`, borderRadius: 13, fontSize: 14 } } readOnly />
                                        </div>
                                        <button style={ { width: '100%', height: 44, background: C.lime, color: C.primary, border: `1.5px solid ${C.primary}`, borderRadius: 13, fontSize: 14, fontWeight: 600, cursor: 'pointer' } }>Sign in</button>
                                        <div style={ { textAlign: 'center', marginTop: 12 } }>
                                            <a href="#" style={ { fontSize: 13, color: C.primary, textDecoration: 'none' } }>Forgot your password?</a>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Auth Theme Tokens</h4>
                                <div style={ { border: `2px solid ${C.lime}`, borderRadius: 12, overflow: 'hidden' } }>
                                    <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 12 } }>
                                        <thead><tr style={ { background: C.lime } }><th style={ { padding: '10px 12px', textAlign: 'left', fontWeight: 600, color: C.primary } }>Token</th><th style={ { padding: '10px 12px', textAlign: 'left', fontWeight: 600, color: C.primary } }>Value</th></tr></thead>
                                        <tbody>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>brand.primary.40</td><td style={ { padding: '8px 12px' } }>#d1f470 (lime)</td></tr>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>brand.primary.80</td><td style={ { padding: '8px 12px' } }>#1a3a2a (dark green)</td></tr>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>button.primary.bg</td><td style={ { padding: '8px 12px' } }>#d1f470</td></tr>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>button.primary.color</td><td style={ { padding: '8px 12px' } }>#1a3a2a</td></tr>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>fieldcontrol.borderRadius</td><td style={ { padding: '8px 12px' } }>13px</td></tr>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>fieldcontrol.borderColor</td><td style={ { padding: '8px 12px' } }>#d1f470</td></tr>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>fieldcontrol._focus.border</td><td style={ { padding: '8px 12px' } }>#1a3a2a</td></tr>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>fieldcontrol._focus.shadow</td><td style={ { padding: '8px 12px' } }>0 0 0 3px rgba(209,244,112,0.3)</td></tr>
                                            <tr style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { padding: '8px 12px' } }>router.borderWidth</td><td style={ { padding: '8px 12px' } }>0 (no border)</td></tr>
                                            <tr><td style={ { padding: '8px 12px' } }>router.boxShadow</td><td style={ { padding: '8px 12px' } }>0 4px 24px rgba(0,0,0,0.08)</td></tr>
                                        </tbody>
                                    </table>
                                </div>
                                <div style={ { marginTop: 12, fontSize: 13, color: C.text2 } }>
                                    <strong>Layout:</strong> Header + centered Authenticator + Footer. After login → redirect to /dashboard.
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              22. FLOATING AGENT (AI CHAT)
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>22. Floating Agent (AI Chat)</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Bottom-right FAB → slide-out chat panel. Bedrock Nova Lite. Ctrl+. shortcut.</p>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>FAB Button</h4>
                                <div style={ { display: 'flex', alignItems: 'center', gap: 16 } }>
                                    <div style={ { width: 56, height: 56, borderRadius: '50%', background: C.primary, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.2)', cursor: 'pointer' } }>
                                        <span style={ { fontSize: 24 } }>🤖</span>
                                    </div>
                                    <div style={ { fontSize: 13, color: C.text2 } }>56px circle, dark green bg, bottom-right fixed, z-index 9999. Hover: scale(1.05).</div>
                                </div>
                            </div>
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Chat Panel</h4>
                                <div style={ { fontSize: 13, color: C.text2, lineHeight: 2 } }>
                                    <div>Width: 380px, Height: 520px</div>
                                    <div>Position: fixed bottom-right</div>
                                    <div>Border: 2px solid #d1f470</div>
                                    <div>Radius: 16px</div>
                                    <div>Header: dark green bg, white text</div>
                                    <div>Messages: user (lime bg) / assistant (white bg)</div>
                                    <div>Input: lime border, send button</div>
                                    <div>Voice: microphone icon, Web Speech API</div>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              23. SEARCH MODAL
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>23. Search Modal (Ctrl+K)</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Command palette style. Search contacts, messages, pages. Keyboard navigation.</p>
                        <div style={ { background: 'rgba(0,0,0,0.25)', borderRadius: 16, padding: 32, display: 'flex', justifyContent: 'center' } }>
                            <div style={ { background: '#fff', borderRadius: 16, width: '100%', maxWidth: 520, boxShadow: '0 20px 40px rgba(0,0,0,0.2)', overflow: 'hidden' } }>
                                <div style={ { padding: '16px 20px', borderBottom: '1px solid #e5e7eb' } }>
                                    <input type="text" placeholder="Search contacts, pages, actions..." style={ { width: '100%', height: 44, border: 'none', fontSize: 16, outline: 'none' } } readOnly />
                                </div>
                                <div style={ { padding: '8px 0', maxHeight: 240 } }>
                                    { [ '⊞ Dashboard — Overview & stats', '◇ WhatsApp Inbox — Messages', '⊕ Contacts — Manage contacts', '⎙ Templates — WhatsApp templates', '◈ Payments — WhatsApp Pay' ].map( ( item, i ) => (
                                        <div key={ i } style={ { padding: '10px 20px', background: i === 0 ? C.bg2 : 'transparent', cursor: 'pointer', fontSize: 14, color: i === 0 ? C.text : C.text2 } }>{ item }</div>
                                    ) ) }
                                </div>
                                <div style={ { padding: '10px 20px', borderTop: '1px solid #e5e7eb', fontSize: 12, color: C.textMuted, display: 'flex', gap: 16 } }>
                                    <span>↑↓ Navigate</span><span>↵ Open</span><span>ESC Close</span>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              24. CHARTS & DATA VIZ
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>24. Charts & Data Visualization</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>CSS-based charts. No external library. Components: BarChart, DonutChart, Sparkline, ProgressBar, DateRangePicker.</p>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 } }>
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>Bar Chart</h4>
                                <div style={ { display: 'flex', alignItems: 'flex-end', gap: 8, height: 100 } }>
                                    { [ 60, 80, 45, 90, 70, 55, 85 ].map( ( h, i ) => (
                                        <div key={ i } style={ { flex: 1, height: `${h}%`, background: C.primary, borderRadius: '4px 4px 0 0', transition: 'height 0.3s' } } />
                                    ) ) }
                                </div>
                                <div style={ { display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 10, color: C.textMuted } }>
                                    <span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Sun</span>
                                </div>
                            </div>
                            <div className="inner-card" style={ { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' } }>
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>Donut Chart</h4>
                                <div style={ { width: 100, height: 100, borderRadius: '50%', background: `conic-gradient(${C.primary} 0% 72%, ${C.lime} 72% 88%, #e5e7eb 88% 100%)`, display: 'flex', alignItems: 'center', justifyContent: 'center' } }>
                                    <div style={ { width: 60, height: 60, borderRadius: '50%', background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700 } }>72%</div>
                                </div>
                            </div>
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>Progress Bar</h4>
                                { [ { label: 'WhatsApp', pct: 85 }, { label: 'SMS', pct: 45 }, { label: 'Email', pct: 62 } ].map( ( p, i ) => (
                                    <div key={ i } style={ { marginBottom: 12 } }>
                                        <div style={ { display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 } }><span>{ p.label }</span><span style={ { fontWeight: 600 } }>{ p.pct }%</span></div>
                                        <div style={ { height: 8, background: '#f3f4f6', borderRadius: 4 } }><div style={ { height: '100%', width: `${p.pct}%`, background: C.primary, borderRadius: 4 } } /></div>
                                    </div>
                                ) ) }
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              25. HEADER & FOOTER (PUBLIC PAGES)
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>25. Header & Footer (Public Pages)</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Header</h4>
                                <div style={ { background: 'rgba(255,255,255,0.97)', backdropFilter: 'blur(20px)', padding: '12px 20px', borderRadius: 12, border: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', gap: 8 } }>
                                    <div style={ { width: 40, height: 40, borderRadius: 10, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 600 } }>LOGO</div>
                                    <span style={ { fontSize: 14, color: '#1a1a1a' } }>▼</span>
                                </div>
                                <div style={ { marginTop: 12, fontSize: 12, color: C.text2, lineHeight: 2 } }>
                                    Fixed top, z-index 1001. Blur backdrop. Logo 64px + dropdown nav. Dropdown: lime border, 12px radius. Nav items: 21px font, hover lime bg.
                                </div>
                            </div>
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Footer</h4>
                                <div style={ { padding: '16px 20px', background: '#fff', borderRadius: 12, border: '1px solid #e5e7eb' } }>
                                    <a href="#" style={ { fontSize: 18, color: '#1a1a1a', textDecoration: 'none', fontWeight: 500 } }>Contact us</a>
                                </div>
                                <div style={ { marginTop: 12, fontSize: 12, color: C.text2, lineHeight: 2 } }>
                                    Simple footer. Safe-area-inset-bottom for mobile. Font: 21px desktop → 24px tablet → 22px mobile. Single &quot;Contact us&quot; link.
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              26. SKELETON LOADING VARIANTS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>26. Skeleton Loading Variants</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>7 skeleton types for different content areas. Pulse animation 1.5s.</p>
                        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16 } }>
                            { [
                                { name: 'SkeletonText', desc: 'Multi-line text (3 lines, last 60%)' },
                                { name: 'SkeletonAvatar', desc: 'Circle 40px (configurable)' },
                                { name: 'SkeletonCard', desc: 'Avatar + title + text lines' },
                                { name: 'SkeletonTable', desc: 'Header row + 5 data rows' },
                                { name: 'SkeletonMessage', desc: 'Chat bubble (inbound/outbound)' },
                                { name: 'SkeletonContact', desc: 'Avatar 44px + name + phone' },
                                { name: 'SkeletonStat', desc: 'Value 36px + label 12px' },
                            ].map( ( s, i ) => (
                                <div key={ i } className="inner-card" style={ { padding: 16 } }>
                                    <div style={ { height: 12, width: '70%', background: '#f5f5f5', borderRadius: 4, marginBottom: 8 } } className="skeleton" />
                                    <div style={ { height: 8, width: '50%', background: '#f5f5f5', borderRadius: 4, marginBottom: 12 } } className="skeleton" />
                                    <div style={ { fontSize: 13, fontWeight: 600, color: C.text } }>{ s.name }</div>
                                    <div style={ { fontSize: 11, color: C.text2 } }>{ s.desc }</div>
                                </div>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              27. ERROR STATES & COMING SOON
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>27. Error States & Coming Soon</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 } }>
                            <div className="inner-card" style={ { textAlign: 'center', padding: 32 } }>
                                <div style={ { fontSize: 36, marginBottom: 12 } }>⚠️</div>
                                <h4 style={ { margin: '0 0 8px', fontSize: 16, fontWeight: 600 } }>Something went wrong</h4>
                                <p style={ { fontSize: 13, color: C.text2, margin: '0 0 4px' } }>An unexpected error occurred.</p>
                                <p style={ { fontSize: 11, color: C.textMuted, fontFamily: 'monospace', margin: '0 0 16px' } }>ERR-ABC123</p>
                                <div style={ { display: 'flex', gap: 8, justifyContent: 'center' } }>
                                    <button className="btn btn-primary btn-sm">Refresh</button>
                                    <button className="btn btn-secondary btn-sm">Dashboard</button>
                                </div>
                                <div style={ { marginTop: 12, fontSize: 11, color: C.textMuted } }>ErrorBoundary</div>
                            </div>
                            <div className="inner-card" style={ { textAlign: 'center', padding: 32 } }>
                                <div style={ { fontSize: 36, marginBottom: 12 } }>⚠️</div>
                                <h4 style={ { margin: '0 0 8px', fontSize: 16, fontWeight: 600 } }>Failed to load</h4>
                                <p style={ { fontSize: 13, color: C.text2, margin: '0 0 16px' } }>Could not fetch contacts data.</p>
                                <button className="btn btn-primary btn-sm">Retry</button>
                                <div style={ { marginTop: 12, fontSize: 11, color: C.textMuted } }>ErrorState</div>
                            </div>
                            <div className="inner-card" style={ { textAlign: 'center', padding: 32 } }>
                                <div style={ { fontSize: 36, marginBottom: 12 } }>🚧</div>
                                <h4 style={ { margin: '0 0 8px', fontSize: 16, fontWeight: 600 } }>Coming Soon</h4>
                                <p style={ { fontSize: 13, color: C.text2, margin: '0 0 12px' } }>This feature is under development.</p>
                                <ul style={ { textAlign: 'left', fontSize: 12, color: C.text2, margin: '0 0 16px', paddingLeft: 20 } }>
                                    <li>Planned feature 1</li>
                                    <li>Planned feature 2</li>
                                </ul>
                                <a href="#" style={ { fontSize: 13, color: C.primary, fontWeight: 500 } }>View Docs →</a>
                                <div style={ { marginTop: 12, fontSize: 11, color: C.textMuted } }>ComingSoon</div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              28. PWA & MOBILE APP PATTERNS
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>28. PWA & Mobile App Patterns</h2>
                        <div className="table-container">
                            <table className="inner-table">
                                <thead>
                                    <tr>
                                        <th>Pattern</th>
                                        <th>Implementation</th>
                                        <th>File</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr><td>Service Worker</td><td>Offline support, push notifications, notification click → /dashboard</td><td>public/sw.js</td></tr>
                                    <tr><td>Web App Manifest</td><td>Standalone display, theme #1a3a2a, shortcuts (Dashboard, Messages, Contacts)</td><td>public/manifest.json</td></tr>
                                    <tr><td>Capacitor Native</td><td>iOS/Android WebView, push, haptics, splash screen, status bar</td><td>capacitor.config.ts</td></tr>
                                    <tr><td>Safe Area Insets</td><td>padding-top/bottom: env(safe-area-inset-*) for notch devices</td><td>tokens.css</td></tr>
                                    <tr><td>Overscroll Prevention</td><td>overscroll-behavior: none (native app feel)</td><td>tokens.css</td></tr>
                                    <tr><td>Touch Targets</td><td>min-height: 44px on all interactive elements</td><td>tokens.css</td></tr>
                                    <tr><td>iOS Zoom Prevention</td><td>font-size: 16px on inputs (mobile)</td><td>tokens.css</td></tr>
                                    <tr><td>Pull-to-Refresh Block</td><td>overscroll-behavior-y: contain on body</td><td>tokens.css</td></tr>
                                    <tr><td>Double-Tap Zoom Block</td><td>touch-action: manipulation on *</td><td>tokens.css</td></tr>
                                    <tr><td>Text Selection</td><td>user-select: none on UI, text on content</td><td>tokens.css</td></tr>
                                    <tr><td>Momentum Scrolling</td><td>-webkit-overflow-scrolling: touch</td><td>tokens.css</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              29. RICH TEXT EDITOR
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>29. Rich Text Editor (Message Composer)</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>WhatsApp-style editor with templates, variables, AI suggestions, TTS, payment dialog. Used in all messaging pages.</p>

                        <div className="inner-card" style={ { padding: 0, overflow: 'hidden' } }>
                            {/* Toolbar */ }
                            <div style={ { display: 'flex', alignItems: 'center', gap: 4, padding: '8px 12px', borderBottom: `1.5px solid ${C.lime}`, background: C.bg2 } }>
                                { [ '📋 Template', '① Variable', '🤖 AI', '🎤 TTS', '💳 Pay', '📎 Attach', '😀 Emoji', '📍 Location' ].map( ( btn, i ) => (
                                    <button key={ i } style={ { background: 'none', border: '1px solid transparent', borderRadius: 6, padding: '6px 10px', cursor: 'pointer', fontSize: 12, color: C.text2, fontWeight: 500, whiteSpace: 'nowrap' } }>{ btn }</button>
                                ) ) }
                            </div>
                            {/* Editor Area */ }
                            <div style={ { padding: '12px 16px', minHeight: 80, fontSize: 14, color: C.textMuted } }>
                                Type a message... or select a template above
                            </div>
                            {/* Footer */ }
                            <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', borderTop: `1px solid ${C.border}` } }>
                                <span style={ { fontSize: 12, color: C.textMuted } }>0 / 4096 characters</span>
                                <button style={ { width: 40, height: 40, borderRadius: '50%', background: C.lime, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16 } }>➤</button>
                            </div>
                        </div>

                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 20 } }>
                            <div style={ { background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '12px 16px', fontSize: 13 } }>
                                <strong>Editor Specs:</strong>
                                <ul style={ { margin: '8px 0 0', padding: '0 0 0 16px', lineHeight: 2 } }>
                                    <li>Border: 1.5px solid #d1f470, radius 13px</li>
                                    <li>Toolbar: #f9fafb bg, lime bottom border</li>
                                    <li>Toolbar buttons: 6px 10px padding, 6px radius</li>
                                    <li>Send button: 40px circle, lime bg</li>
                                    <li>Max chars: 4096 (WhatsApp limit)</li>
                                    <li>Template dropdown: overlay panel, status badges</li>
                                </ul>
                            </div>
                            <div style={ { background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '12px 16px', fontSize: 13 } }>
                                <strong>Sub-Panels:</strong>
                                <ul style={ { margin: '8px 0 0', padding: '0 0 0 16px', lineHeight: 2 } }>
                                    <li>Template picker: search + list with status badges</li>
                                    <li>Variable input: numbered fields (①②③④)</li>
                                    <li>AI suggestions: auto-complete from Bedrock</li>
                                    <li>TTS panel: language + voice dropdowns</li>
                                    <li>Payment dialog: items, GST, phone, order ID</li>
                                    <li>Emoji picker: grid overlay</li>
                                </ul>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              30. WHATSAPP INBOX SPLIT-VIEW
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>30. WhatsApp Inbox (Split-View Layout)</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Two-panel messaging layout. Contacts sidebar + chat area. Full-height, no scroll on outer container.</p>

                        <div style={ { border: `2px solid ${C.lime}`, borderRadius: 16, overflow: 'hidden', height: 360, display: 'flex' } }>
                            {/* Contacts Sidebar */ }
                            <div style={ { width: 280, borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', flexShrink: 0 } }>
                                <div style={ { padding: '12px', borderBottom: `1px solid ${C.border}` } }>
                                    <input type="text" placeholder="🔍 Search contacts..." style={ { width: '100%', height: 36, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '0 12px', fontSize: 13 } } readOnly />
                                </div>
                                { [
                                    { name: 'Rahul Sharma', msg: 'Thanks for the update!', time: '2m', active: true, color: '#4f46e5' },
                                    { name: 'Priya Patel', msg: 'When will my order arrive?', time: '15m', active: false, color: '#059669' },
                                    { name: 'Amit Kumar', msg: 'Payment confirmed ✓', time: '1h', active: false, color: '#dc2626' },
                                    { name: 'Neha Singh', msg: 'Can I reschedule?', time: '3h', active: false, color: '#d97706' },
                                ].map( ( c, i ) => (
                                    <div key={ i } style={ { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', background: c.active ? '#f3f4f6' : 'transparent', borderLeft: c.active ? `3px solid ${C.primary}` : '3px solid transparent', cursor: 'pointer' } }>
                                        <div style={ { width: 36, height: 36, borderRadius: '50%', background: c.color, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 13, fontWeight: 600, flexShrink: 0 } }>{ c.name[ 0 ] }</div>
                                        <div style={ { flex: 1, minWidth: 0 } }>
                                            <div style={ { fontSize: 13, fontWeight: c.active ? 600 : 500, color: C.text } }>{ c.name }</div>
                                            <div style={ { fontSize: 12, color: C.text2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }>{ c.msg }</div>
                                        </div>
                                        <span style={ { fontSize: 11, color: C.textMuted } }>{ c.time }</span>
                                    </div>
                                ) ) }
                            </div>
                            {/* Chat Area */ }
                            <div style={ { flex: 1, display: 'flex', flexDirection: 'column' } }>
                                <div style={ { padding: '10px 16px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', gap: 10 } }>
                                    <div style={ { width: 32, height: 32, borderRadius: '50%', background: '#4f46e5', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 12, fontWeight: 600 } }>R</div>
                                    <div><div style={ { fontSize: 14, fontWeight: 600 } }>Rahul Sharma</div><div style={ { fontSize: 11, color: C.textMuted } }>+91 98765 43210 • Online</div></div>
                                </div>
                                <div style={ { flex: 1, padding: 16, display: 'flex', flexDirection: 'column', gap: 8, justifyContent: 'flex-end', background: '#fafafa' } }>
                                    <div style={ { alignSelf: 'flex-start', background: '#fff', border: `1px solid ${C.border}`, borderRadius: '12px 12px 12px 4px', padding: '8px 12px', fontSize: 13, maxWidth: '70%' } }>Hi, when will my order be delivered?</div>
                                    <div style={ { alignSelf: 'flex-end', background: '#e5e7eb', borderRadius: '12px 12px 4px 12px', padding: '8px 12px', fontSize: 13, maxWidth: '70%' } }>Your order #WD-1234 is out for delivery. Expected by 4 PM today.</div>
                                    <div style={ { alignSelf: 'flex-start', background: '#fff', border: `1px solid ${C.border}`, borderRadius: '12px 12px 12px 4px', padding: '8px 12px', fontSize: 13, maxWidth: '70%' } }>Thanks for the update! 👍</div>
                                </div>
                                <div style={ { padding: '8px 12px', borderTop: `1px solid ${C.border}`, display: 'flex', gap: 8, alignItems: 'center' } }>
                                    <input type="text" placeholder="Type a message..." style={ { flex: 1, height: 36, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '0 12px', fontSize: 13 } } readOnly />
                                    <button style={ { width: 36, height: 36, borderRadius: '50%', background: C.lime, border: 'none', cursor: 'pointer', fontSize: 14 } }>➤</button>
                                </div>
                            </div>
                        </div>

                        <div style={ { marginTop: 16, background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '12px 16px', fontSize: 13 } }>
                            <strong>Layout Rules:</strong> Contacts sidebar: 280-320px fixed width. Chat area: flex: 1. Full height (calc 100vh - header). Mobile: stack vertically, contacts 35vh max. Active contact: #f3f4f6 bg + 3px left border. Avatar: color-coded initials (first letter). Message bubbles: inbound (white, left-aligned) / outbound (grey, right-aligned).
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              31. MESSAGING PAGE LAYOUTS (SMS / Voice / Email)
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>31. Messaging Page Layouts (SMS / Voice / Email / RCS)</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>All messaging pages follow the same split-view pattern with channel-specific features.</p>

                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            { [
                                { channel: '💬 SMS', features: [ 'Contact list + thread view', 'Character counter (160/SMS)', 'Sender ID selection', 'DLT template compliance', 'Delivery reports' ] },
                                { channel: '📞 Voice', features: [ 'Dialer keypad (16px keys)', 'Call history list', 'Active call UI (timer, mute, hold)', 'Voice recording playback', 'TTS outbound calls' ] },
                                { channel: '📧 Email (SES)', features: [ 'Rich HTML editor', 'Subject line input', 'Attachment support', 'Template selection', 'Bounce/complaint tracking' ] },
                                { channel: '📱 RCS', features: [ 'Rich card composer', 'Carousel builder', 'Suggested actions/replies', 'Media upload (image/video)', 'Template management (Sinch)' ] },
                            ].map( ( ch, i ) => (
                                <div key={ i } className="inner-card">
                                    <h4 style={ { margin: '0 0 12px', fontSize: 16, fontWeight: 600 } }>{ ch.channel }</h4>
                                    <ul style={ { margin: 0, padding: '0 0 0 16px', fontSize: 13, color: C.text2, lineHeight: 2 } }>
                                        { ch.features.map( ( f, j ) => <li key={ j }>{ f }</li> ) }
                                    </ul>
                                </div>
                            ) ) }
                        </div>

                        <div style={ { marginTop: 20, background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '12px 16px', fontSize: 13 } }>
                            <strong>Consistency Rules (All Channels):</strong>
                            <ul style={ { margin: '8px 0 0', padding: '0 0 0 16px', lineHeight: 2 } }>
                                <li>Same split-view layout as WhatsApp (contacts left, content right)</li>
                                <li>Same contact row design (avatar + name + last message + time)</li>
                                <li>Same lime border on inputs, 13px radius on all elements</li>
                                <li>Same tab pattern for sub-views (Inbox / Campaign / Board)</li>
                                <li>Same toast notifications for send success/failure</li>
                                <li>Same empty state when no contacts/messages</li>
                                <li>Same skeleton loading during data fetch</li>
                            </ul>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              32. PAY / PAYMENT PAGES
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>32. Payment Pages (Pay / Pay Flow / Pay Link)</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Razorpay integration. Payment link generation, WhatsApp delivery, status tracking.</p>

                        <div className="inner-card" style={ { padding: 0, overflow: 'hidden' } }>
                            <div style={ { padding: '16px 20px', borderBottom: `1px solid ${C.border}` } }>
                                <h4 style={ { margin: 0, fontSize: 16, fontWeight: 600 } }>Payment Link Generator</h4>
                            </div>
                            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 } }>
                                {/* Form Side */ }
                                <div style={ { padding: 20, borderRight: `1px solid ${C.border}` } }>
                                    <div style={ { marginBottom: 16 } }>
                                        <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 } }>Amount (₹)</label>
                                        <input type="text" value="₹ 499.00" style={ { width: '100%', height: 44, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '0 12px', fontSize: 14 } } readOnly />
                                    </div>
                                    <div style={ { marginBottom: 16 } }>
                                        <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 } }>Description</label>
                                        <input type="text" value="Service Request #SR-001" style={ { width: '100%', height: 44, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '0 12px', fontSize: 14 } } readOnly />
                                    </div>
                                    <div style={ { marginBottom: 16 } }>
                                        <label style={ { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 } }>Send to</label>
                                        <input type="text" value="+91 98765 43210" style={ { width: '100%', height: 44, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '0 12px', fontSize: 14, fontFamily: 'monospace' } } readOnly />
                                    </div>
                                    <button className="btn btn-primary btn-md" style={ { width: '100%' } }>Generate & Send via WhatsApp</button>
                                </div>
                                {/* Preview Side */ }
                                <div style={ { padding: 20, background: C.bg2 } }>
                                    <div style={ { fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: 'uppercase', marginBottom: 12 } }>Preview</div>
                                    <div style={ { background: '#fff', border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: 16 } }>
                                        <div style={ { fontSize: 14, fontWeight: 600, marginBottom: 8 } }>Payment Request</div>
                                        <div style={ { fontSize: 13, color: C.text2, marginBottom: 4 } }>Service Request #SR-001</div>
                                        <div style={ { fontSize: 20, fontWeight: 700, color: C.primary, marginBottom: 12 } }>₹ 499.00</div>
                                        <div style={ { background: C.primary, color: '#fff', textAlign: 'center', padding: '10px', borderRadius: 8, fontSize: 13, fontWeight: 600 } }>Pay Now →</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              33. PAGE CONSISTENCY CHECKLIST
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>33. Page Consistency Checklist</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Every inner page MUST follow these rules for visual consistency across the platform.</p>

                        <div className="table-container">
                            <table className="inner-table">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>Rule</th>
                                        <th>Implementation</th>
                                        <th>Check</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr><td>1</td><td>Layout wrapper</td><td>Every page uses { '<Layout>' } component</td><td>✅</td></tr>
                                    <tr><td>2</td><td>SEO component</td><td>Every page includes { '<SEO title="" />' }</td><td>✅</td></tr>
                                    <tr><td>3</td><td>Page title</td><td>h1, 28px, weight 700, color #1a3a2a</td><td>✅</td></tr>
                                    <tr><td>4</td><td>Button radius</td><td>All buttons: border-radius 13px</td><td>✅</td></tr>
                                    <tr><td>5</td><td>Button height</td><td>Min-height 44px (touch target)</td><td>✅</td></tr>
                                    <tr><td>6</td><td>Input borders</td><td>1.5px solid #d1f470, focus: #1a3a2a</td><td>✅</td></tr>
                                    <tr><td>7</td><td>Input radius</td><td>border-radius: 13px</td><td>✅</td></tr>
                                    <tr><td>8</td><td>Card borders</td><td>1.5px solid #d1f470, radius 16px</td><td>✅</td></tr>
                                    <tr><td>9</td><td>Table headers</td><td>Lime bg (#d1f470), uppercase, 12px</td><td>✅</td></tr>
                                    <tr><td>10</td><td>Active tabs</td><td>Lime fill (#d1f470), dark text (#1a3a2a)</td><td>✅</td></tr>
                                    <tr><td>11</td><td>Sidebar active</td><td>Lime left-border 3px + rgba bg</td><td>✅</td></tr>
                                    <tr><td>12</td><td>Toast position</td><td>Top-right, max 3 visible</td><td>✅</td></tr>
                                    <tr><td>13</td><td>Empty states</td><td>Icon 80px + title + desc + CTA button</td><td>✅</td></tr>
                                    <tr><td>14</td><td>Loading</td><td>Skeleton for initial, spinner for refresh</td><td>✅</td></tr>
                                    <tr><td>15</td><td>Error handling</td><td>ErrorState component with retry button</td><td>✅</td></tr>
                                    <tr><td>16</td><td>Confirm dialogs</td><td>Modal for all destructive actions</td><td>✅</td></tr>
                                    <tr><td>17</td><td>Font family</td><td>Inter (system fallback)</td><td>✅</td></tr>
                                    <tr><td>18</td><td>Monospace data</td><td>Phone numbers, IDs, ARNs use monospace</td><td>✅</td></tr>
                                    <tr><td>19</td><td>Mobile inputs</td><td>font-size: 16px (prevent iOS zoom)</td><td>✅</td></tr>
                                    <tr><td>20</td><td>Focus rings</td><td>0 0 0 3px rgba(26,58,42,0.3)</td><td>✅</td></tr>
                                    <tr><td>21</td><td>Hover states</td><td>border-color → #1a3a2a, bg → #f9fafb</td><td>✅</td></tr>
                                    <tr><td>22</td><td>Danger actions</td><td>Red border/text, never lime for errors</td><td>✅</td></tr>
                                    <tr><td>23</td><td>One primary CTA</td><td>Max 1 lime-filled button per section</td><td>✅</td></tr>
                                    <tr><td>24</td><td>Responsive grid</td><td>auto-fill minmax, stack on mobile</td><td>✅</td></tr>
                                    <tr><td>25</td><td>Max content width</td><td>1400px centered on wide screens</td><td>✅</td></tr>
                                </tbody>
                            </table>
                        </div>

                        <div style={ { marginTop: 20, background: C.bg2, border: `1.5px solid ${C.lime}`, borderRadius: 13, padding: '16px 20px', fontSize: 13 } }>
                            <strong>🎯 How to use this checklist:</strong>
                            <p style={ { margin: '8px 0 0', lineHeight: 1.8 } }>
                                Before shipping any new page or component, verify all 25 rules above. If a page looks different from others, check this reference.
                                All CSS is centralized in <code style={ { background: '#e5e7eb', padding: '1px 4px', borderRadius: 3 } }>tokens.css</code> + <code style={ { background: '#e5e7eb', padding: '1px 4px', borderRadius: 3 } }>inner-ux.css</code> + <code style={ { background: '#e5e7eb', padding: '1px 4px', borderRadius: 3 } }>inner-pages.css</code>.
                                Never add inline colors or custom border-radius — always use the design tokens.
                            </p>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              34. MICRO-COMPONENTS (Toggle, Pagination, Kbd, Accordion, JSON)
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>34. Micro-Components</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Small reusable patterns used across multiple pages.</p>

                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 } }>
                            {/* Toggle Switch */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>Toggle Switch</h4>
                                <div style={ { display: 'flex', gap: 16, alignItems: 'center', marginBottom: 12 } }>
                                    <div style={ { width: 34, height: 18, borderRadius: 9, background: C.primary, position: 'relative', cursor: 'pointer' } }><div style={ { position: 'absolute', top: 2, left: 17, width: 14, height: 14, borderRadius: '50%', background: '#fff', transition: 'left 0.2s' } } /></div>
                                    <span style={ { fontSize: 13 } }>Enabled</span>
                                </div>
                                <div style={ { display: 'flex', gap: 16, alignItems: 'center', marginBottom: 12 } }>
                                    <div style={ { width: 34, height: 18, borderRadius: 9, background: '#d1d5db', position: 'relative', cursor: 'pointer' } }><div style={ { position: 'absolute', top: 2, left: 2, width: 14, height: 14, borderRadius: '50%', background: '#fff', transition: 'left 0.2s' } } /></div>
                                    <span style={ { fontSize: 13 } }>Disabled</span>
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>34×18px, radius 9px. ON: #1a3a2a. OFF: #d1d5db. Dot: 14px white circle.</div>
                            </div>

                            {/* Pagination */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>Pagination</h4>
                                <div style={ { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 } }>
                                    { [ '««', '‹', null, '›', '»»' ].map( ( btn, i ) => btn ? (
                                        <button key={ i } style={ { width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f5f5', border: '1px solid #e5e5e5', borderRadius: 6, fontSize: 12, cursor: 'pointer' } }>{ btn }</button>
                                    ) : (
                                        <span key={ i } style={ { fontSize: 12, color: '#374151', padding: '0 8px', fontWeight: 500 } }>Page 1 of 12</span>
                                    ) ) }
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>28×28px buttons, 6px radius. Disabled: opacity 0.4. Center: page info text.</div>
                            </div>

                            {/* Keyboard Shortcut Keys */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>Keyboard Shortcuts</h4>
                                <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 } }>
                                    { [ [ 'Ctrl', 'K' ], [ 'Ctrl', 'S' ], [ 'Ctrl', '↵' ], [ '?' ], [ 'Esc' ] ].map( ( keys, i ) => (
                                        <div key={ i } style={ { display: 'flex', gap: 2 } }>
                                            { keys.map( ( k, j ) => (
                                                <kbd key={ j } style={ { display: 'inline-block', padding: '3px 8px', background: '#f9fafb', border: '1px solid #d1d5db', borderRadius: 4, fontSize: 11, fontFamily: 'monospace', fontWeight: 600, color: '#374151', boxShadow: '0 1px 0 #d1d5db' } }>{ k }</kbd>
                                            ) ) }
                                        </div>
                                    ) ) }
                                </div>
                                <div style={ { fontSize: 11, color: C.text2 } }>kbd: #f9fafb bg, 1px border, 4px radius, bottom shadow. Trigger: ? key opens modal.</div>
                            </div>

                            {/* Collapsible / Accordion */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>Collapsible / Accordion</h4>
                                <div style={ { border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden' } }>
                                    <div style={ { padding: '10px 14px', background: C.bg2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', fontWeight: 500, fontSize: 13 } }>
                                        <span>Keyword Triggers (3)</span><span>▼</span>
                                    </div>
                                    <div style={ { padding: '10px 14px', fontSize: 12, color: C.text2, borderTop: `1px solid ${C.border}` } }>
                                        Expanded content goes here...
                                    </div>
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>Header: #f9fafb bg. Arrow rotates 180° on open. Content: slide-down 150ms.</div>
                            </div>

                            {/* JSON Preview Block */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>JSON / Code Preview</h4>
                                <div style={ { background: '#1a1a1a', borderRadius: 8, padding: 12, position: 'relative' } }>
                                    <button style={ { position: 'absolute', top: 8, right: 8, background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: 4, padding: '4px 8px', color: '#9ca3af', fontSize: 11, cursor: 'pointer' } }>Copy</button>
                                    <pre style={ { margin: 0, fontSize: 11, color: '#e5e7eb', fontFamily: 'monospace', whiteSpace: 'pre-wrap' } }>{ `{\n  "type": "list",\n  "header": "Menu",\n  "sections": [...]\n}` }</pre>
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>Dark bg #1a1a1a, 8px radius, monospace 11px. Copy button top-right.</div>
                            </div>

                            {/* Mode Toggle (Segmented Control) */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 14, fontWeight: 600 } }>Segmented Control</h4>
                                <div style={ { display: 'inline-flex', background: C.bg2, borderRadius: 10, padding: 3, border: `1px solid ${C.border}` } }>
                                    <button style={ { padding: '8px 16px', borderRadius: 8, border: 'none', background: C.lime, color: C.primary, fontSize: 13, fontWeight: 600, cursor: 'pointer' } }>Single</button>
                                    <button style={ { padding: '8px 16px', borderRadius: 8, border: 'none', background: 'transparent', color: C.text2, fontSize: 13, fontWeight: 500, cursor: 'pointer' } }>Bulk</button>
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>Container: #f9fafb, 10px radius. Active: lime fill. Inactive: transparent.</div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              35. ADVANCED PAGE PATTERNS (Timeline, Inline Edit, Bulk, Hub Grid)
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>35. Advanced Page Patterns</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Complex patterns used in Contacts, SEO Hub, WhatsApp Flows, and Store pages.</p>

                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 } }>
                            {/* Activity Timeline */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Activity Timeline</h4>
                                <div style={ { paddingLeft: 20, borderLeft: `2px solid ${C.lime}` } }>
                                    { [
                                        { icon: '✏️', text: 'Name updated: Rahul → Rahul Sharma', time: '2 min ago' },
                                        { icon: '📱', text: 'WhatsApp message sent', time: '15 min ago' },
                                        { icon: '💳', text: 'Payment ₹499 received', time: '1 hour ago' },
                                        { icon: '👤', text: 'Contact created', time: '2 days ago' },
                                    ].map( ( item, i ) => (
                                        <div key={ i } style={ { position: 'relative', marginBottom: 16, paddingLeft: 16 } }>
                                            <div style={ { position: 'absolute', left: -29, top: 2, width: 20, height: 20, borderRadius: '50%', background: '#fff', border: `2px solid ${C.lime}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10 } }>{ item.icon }</div>
                                            <div style={ { fontSize: 13, color: C.text } }>{ item.text }</div>
                                            <div style={ { fontSize: 11, color: C.textMuted } }>{ item.time }</div>
                                        </div>
                                    ) ) }
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>Left border: 2px lime. Dots: 20px circle on border. Used in contact detail panel.</div>
                            </div>

                            {/* Bulk Selection + Actions */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Bulk Selection + Action Bar</h4>
                                <div style={ { background: C.lime, borderRadius: 10, padding: '10px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 } }>
                                    <span style={ { fontSize: 13, fontWeight: 600, color: C.primary } }>3 selected</span>
                                    <div style={ { display: 'flex', gap: 8 } }>
                                        <button style={ { padding: '6px 12px', borderRadius: 8, border: `1px solid ${C.primary}`, background: '#fff', fontSize: 12, cursor: 'pointer' } }>Tag</button>
                                        <button style={ { padding: '6px 12px', borderRadius: 8, border: '1px solid #dc2626', background: '#fff', color: '#dc2626', fontSize: 12, cursor: 'pointer' } }>Delete</button>
                                        <button style={ { padding: '6px 12px', borderRadius: 8, border: `1px solid ${C.primary}`, background: '#fff', fontSize: 12, cursor: 'pointer' } }>Export</button>
                                    </div>
                                </div>
                                <div style={ { fontSize: 11, color: C.text2 } }>Appears above table when checkboxes selected. Lime bg bar. Actions: Tag, Delete, Export. Dismiss: deselect all.</div>
                            </div>

                            {/* Hub Navigation Grid */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Hub Navigation Grid (SEO style)</h4>
                                <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 } }>
                                    { [
                                        { icon: '📝', label: 'Blog SEO', desc: 'AI audit for 108 posts' },
                                        { icon: '📄', label: 'Site Pages', desc: '37 public pages' },
                                        { icon: '🛒', label: 'Products', desc: 'Product schema' },
                                        { icon: '⚙️', label: 'System', desc: 'noindex monitoring' },
                                    ].map( ( item, i ) => (
                                        <div key={ i } style={ { padding: '12px', border: `1.5px solid ${C.lime}`, borderRadius: 12, cursor: 'pointer', display: 'flex', gap: 10, alignItems: 'center' } }>
                                            <span style={ { fontSize: 20 } }>{ item.icon }</span>
                                            <div><div style={ { fontSize: 13, fontWeight: 600 } }>{ item.label }</div><div style={ { fontSize: 11, color: C.text2 } }>{ item.desc }</div></div>
                                        </div>
                                    ) ) }
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>Card grid with emoji icon + title + description. Lime border, 12px radius. Hover: border → dark green.</div>
                            </div>

                            {/* Inline Edit */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Inline Edit (Click-to-Edit)</h4>
                                <div style={ { border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden' } }>
                                    <div style={ { display: 'flex', alignItems: 'center', padding: '10px 14px', borderBottom: `1px solid ${C.border}` } }>
                                        <span style={ { flex: 1, fontSize: 13 } }>Rahul Sharma</span>
                                        <span style={ { fontSize: 11, color: C.textMuted } }>click to edit</span>
                                    </div>
                                    <div style={ { display: 'flex', alignItems: 'center', padding: '6px 10px', background: '#fffbeb', borderBottom: `1px solid ${C.border}` } }>
                                        <input type="text" defaultValue="Priya Patel" style={ { flex: 1, height: 32, border: `1.5px solid ${C.lime}`, borderRadius: 8, padding: '0 8px', fontSize: 13 } } readOnly />
                                        <span style={ { marginLeft: 8, fontSize: 11, color: C.textMuted } }>↵ save · Esc cancel</span>
                                    </div>
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>Click cell → input appears. Yellow bg (#fffbeb) while editing. Enter saves, Escape cancels.</div>
                            </div>

                            {/* Tag System */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Tag System</h4>
                                <div style={ { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 } }>
                                    { [
                                        { label: 'VIP', color: '#0f2a1d' },
                                        { label: 'Customer', color: '#1a3a2a' },
                                        { label: 'Lead', color: '#0f2a1d' },
                                        { label: 'Partner', color: '#34d399' },
                                    ].map( ( tag, i ) => (
                                        <span key={ i } style={ { display: 'inline-flex', alignItems: 'center', gap: 4, padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: tag.color, color: '#fff' } }>
                                            { tag.label } <span style={ { cursor: 'pointer', opacity: 0.7 } }>✕</span>
                                        </span>
                                    ) ) }
                                    <button style={ { padding: '3px 10px', borderRadius: 10, fontSize: 11, border: `1px dashed ${C.borderDark}`, background: 'transparent', color: C.text2, cursor: 'pointer' } }>+ Add</button>
                                </div>
                                <div style={ { fontSize: 11, color: C.text2 } }>Colored pills with remove ✕. Add button: dashed border. Popover menu for tag selection. Colors from TAG_COLORS map.</div>
                            </div>

                            {/* Detail Side Panel */ }
                            <div className="inner-card">
                                <h4 style={ { margin: '0 0 12px', fontSize: 15, fontWeight: 600 } }>Detail Side Panel</h4>
                                <div style={ { display: 'flex', border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden', height: 160 } }>
                                    <div style={ { flex: 1, padding: 12, fontSize: 12, color: C.text2 } }>
                                        <div style={ { marginBottom: 4 } }>← Table content</div>
                                        <div style={ { height: 8, width: '80%', background: '#f5f5f5', borderRadius: 3, marginBottom: 6 } } />
                                        <div style={ { height: 8, width: '60%', background: '#f5f5f5', borderRadius: 3, marginBottom: 6 } } />
                                        <div style={ { height: 8, width: '70%', background: '#f5f5f5', borderRadius: 3 } } />
                                    </div>
                                    <div style={ { width: 180, borderLeft: `1px solid ${C.border}`, padding: 12, background: C.bg2 } }>
                                        <div style={ { fontSize: 12, fontWeight: 600, marginBottom: 8 } }>Contact Detail</div>
                                        <div style={ { fontSize: 11, color: C.text2, lineHeight: 2 } }>
                                            Name: Rahul<br />Phone: +91...<br />Email: r@...<br />Tags: VIP
                                        </div>
                                    </div>
                                </div>
                                <div style={ { fontSize: 11, color: C.text2, marginTop: 8 } }>Right panel slides in on row click. Width: 320-400px. Close: ✕ button or click outside. #f9fafb bg.</div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              36. STATUS PILLS (message / delivery / job states)
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>36. Status Pills</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Distinct hues per state so delivery/job status is readable at a glance. Use <code style={ { background: '#f3f4f6', padding: '1px 5px', borderRadius: 4 } }>{ '<span class="status-pill status-delivered">' }</code> or the tokens from <code style={ { background: '#f3f4f6', padding: '1px 5px', borderRadius: 4 } }>design-tokens.ts → status</code>.</p>
                        <div style={ { display: 'flex', gap: 10, flexWrap: 'wrap' } }>
                            { ( [ 'sent', 'delivered', 'read', 'pending', 'queued', 'failed' ] as const ).map( ( k ) => (
                                <span key={ k } style={ {
                                    display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px',
                                    borderRadius: 9999, fontSize: 12, fontWeight: 600,
                                    color: STATUS[ k ].fg, background: STATUS[ k ].bg,
                                } }>
                                    <span style={ { width: 6, height: 6, borderRadius: '50%', background: STATUS[ k ].solid } } />
                                    { k.charAt( 0 ).toUpperCase() + k.slice( 1 ) }
                                </span>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              37. FOCUS & ACCESSIBILITY
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>37. Focus &amp; Accessibility</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Keyboard focus shows a clear ring via <code style={ { background: '#f3f4f6', padding: '1px 5px', borderRadius: 4 } }>:focus-visible</code> (mouse clicks don&apos;t). Tab through these to see it.</p>
                        <div style={ { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16 } }>
                            <button className="btn btn-primary btn-md">Tab to me</button>
                            <button className="btn btn-secondary btn-md">And me</button>
                            <input className="search-input" placeholder="And focus me" style={ { maxWidth: 200 } } readOnly />
                        </div>
                        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 } }>
                            { [
                                { label: 'Focus ring (lime)', val: '--focus-ring' },
                                { label: 'Focus ring (strong)', val: '--focus-ring-strong' },
                                { label: 'Min tap target', val: '--tap-target → 44px' },
                                { label: 'Contrast', val: 'WCAG AA (4.5:1 text)' },
                                { label: 'Reduced motion', val: 'prefers-reduced-motion' },
                                { label: 'Labels', val: 'aria-label on icon buttons' },
                            ].map( ( a, i ) => (
                                <div key={ i } style={ { background: C.bg2, borderRadius: 12, padding: '12px 14px' } }>
                                    <div style={ { fontSize: 13, fontWeight: 600, color: C.text } }>{ a.label }</div>
                                    <code style={ { fontSize: 11, color: C.text2 } }>{ a.val }</code>
                                </div>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              38. ELEVATION & Z-INDEX
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>38. Elevation &amp; Z-Index</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 } }>
                            <div>
                                <h3 style={ { fontSize: 15, fontWeight: 600, marginBottom: 12 } }>Shadows</h3>
                                <div style={ { display: 'flex', gap: 16, flexWrap: 'wrap' } }>
                                    { [
                                        { l: 'sm', s: '0 1px 2px rgba(0,0,0,0.04)' },
                                        { l: 'md', s: '0 2px 8px rgba(0,0,0,0.06)' },
                                        { l: 'lg', s: '0 4px 12px rgba(0,0,0,0.08)' },
                                        { l: 'xl', s: '0 8px 24px rgba(0,0,0,0.12)' },
                                    ].map( ( e ) => (
                                        <div key={ e.l } style={ { textAlign: 'center' } }>
                                            <div style={ { width: 72, height: 56, borderRadius: 12, background: '#fff', boxShadow: e.s, border: '1px solid #f0f0f0' } } />
                                            <div style={ { fontSize: 11, color: C.text2, marginTop: 6 } }>shadow-{ e.l }</div>
                                        </div>
                                    ) ) }
                                </div>
                            </div>
                            <div>
                                <h3 style={ { fontSize: 15, fontWeight: 600, marginBottom: 12 } }>Z-Index Scale</h3>
                                <div style={ { fontSize: 13, lineHeight: 1.9, color: '#374151' } }>
                                    { [
                                        [ 'dropdown', 1000 ], [ 'sticky', 1100 ], [ 'header', 1200 ], [ 'drawer', 1300 ],
                                        [ 'modal-backdrop', 1400 ], [ 'modal', 1410 ], [ 'popover', 1500 ], [ 'toast', 1600 ], [ 'tooltip', 1700 ],
                                    ].map( ( [ name, z ] ) => (
                                        <div key={ name } style={ { display: 'flex', justifyContent: 'space-between', maxWidth: 240, borderBottom: '1px solid #f3f4f6', padding: '2px 0' } }>
                                            <code style={ { fontSize: 12 } }>--z-{ name }</code>
                                            <span style={ { fontSize: 12, fontWeight: 600 } }>{ z }</span>
                                        </div>
                                    ) ) }
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              39. MOTION & EASING
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { marginBottom: 56 } }>
                        <h2 style={ { fontSize: 22, fontWeight: 700, color: C.primary, margin: '0 0 8px' } }>39. Motion &amp; Easing</h2>
                        <p style={ { fontSize: 14, color: C.text2, marginBottom: 20 } }>Short, purposeful transitions. All motion is disabled automatically when the OS requests <code style={ { background: '#f3f4f6', padding: '1px 5px', borderRadius: 4 } }>prefers-reduced-motion</code>.</p>
                        <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 } }>
                            { [
                                { l: 'fast', v: '0.1s ease', use: 'Hover/press feedback' },
                                { l: 'normal', v: '0.15s ease', use: 'Most UI transitions' },
                                { l: 'slow', v: '0.25s ease-out', use: 'Panels, modals, drawers' },
                                { l: 'ease-out', v: 'cubic-bezier(.16,1,.3,1)', use: 'Enter animations' },
                                { l: 'ease-in-out', v: 'cubic-bezier(.4,0,.2,1)', use: 'Move/resize' },
                            ].map( ( m, i ) => (
                                <div key={ i } style={ { background: C.bg2, borderRadius: 12, padding: '12px 14px' } }>
                                    <div style={ { fontSize: 13, fontWeight: 600, color: C.text } }>{ m.l }</div>
                                    <code style={ { fontSize: 11, color: C.text2, display: 'block', margin: '2px 0' } }>{ m.v }</code>
                                    <div style={ { fontSize: 11, color: C.text2 } }>{ m.use }</div>
                                </div>
                            ) ) }
                        </div>
                    </section>

                    {/* ═══════════════════════════════════════════════════════════════
              FOOTER SUMMARY
          ═══════════════════════════════════════════════════════════════ */}
                    <section style={ { background: C.bg2, border: `2px solid ${C.lime}`, borderRadius: 16, padding: 24 } }>
                        <h2 style={ { fontSize: 18, fontWeight: 700, color: C.primary, margin: '0 0 16px' } }>📋 Quick Reference Summary</h2>
                        <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 20 } }>
                            <div>
                                <strong style={ { fontSize: 13, display: 'block', marginBottom: 8 } }>Colors</strong>
                                <div style={ { fontSize: 12, lineHeight: 2, color: '#374151' } }>
                                    Primary: #1a3a2a<br />
                                    Lime: #d1f470<br />
                                    Danger: #dc2626<br />
                                    BG: #fff / #f9fafb
                                </div>
                            </div>
                            <div>
                                <strong style={ { fontSize: 13, display: 'block', marginBottom: 8 } }>Dimensions</strong>
                                <div style={ { fontSize: 12, lineHeight: 2, color: '#374151' } }>
                                    Button radius: 13px<br />
                                    Touch target: 44px<br />
                                    Border: 1.5px<br />
                                    Max width: 1400px
                                </div>
                            </div>
                            <div>
                                <strong style={ { fontSize: 13, display: 'block', marginBottom: 8 } }>Typography</strong>
                                <div style={ { fontSize: 12, lineHeight: 2, color: '#374151' } }>
                                    Font: Inter<br />
                                    H1: 28px / 700<br />
                                    Body: 14px / 400<br />
                                    Caption: 12px / 600
                                </div>
                            </div>
                            <div>
                                <strong style={ { fontSize: 13, display: 'block', marginBottom: 8 } }>Key Rules</strong>
                                <div style={ { fontSize: 12, lineHeight: 2, color: '#374151' } }>
                                    1 primary CTA/section<br />
                                    Confirm destructive<br />
                                    Skeleton for loading<br />
                                    16px input on mobile
                                </div>
                            </div>
                        </div>
                    </section>

                </div>
            </div>
        </Layout>
    );
};

export default DesignReferencePage;
