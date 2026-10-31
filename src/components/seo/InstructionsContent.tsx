import React from 'react';

const S: React.CSSProperties = { fontSize: 14, fontWeight: 700, marginBottom: 8, color: '#1a3a2a' };
const pre: React.CSSProperties = { background: '#0f1117', color: '#a3e635', padding: 12, borderRadius: 8, fontSize: 10, lineHeight: 1.6, whiteSpace: 'pre-wrap', margin: 0, maxHeight: 280, overflowY: 'auto' };
const thI: React.CSSProperties = { padding: '8px 12px', textAlign: 'left' as const, fontSize: 11, fontWeight: 600 };
const tdI: React.CSSProperties = { padding: '6px 12px', fontSize: 12 };

function Card ( { title, children }: { title: string; children: React.ReactNode } ) {
  return <div className="card" style={ { padding: 20, marginBottom: 16 } }><h3 style={ S }>{ title }</h3>{ children }</div>;
}

function JCard ( { n, title, desc, code }: { n: string; title: string; desc: string; code: string } ) {
  return (
    <div className="card" style={ { padding: 16, marginBottom: 12 } }>
      <div style={ { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 } }>
        <span style={ { padding: '2px 8px', background: '#d1f470', color: '#1a3a2a', borderRadius: 6, fontSize: 11, fontWeight: 700 } }>#{ n }</span>
        <span style={ { fontSize: 13, fontWeight: 600, color: '#1a1a1a' } }>{ title }</span>
      </div>
      <div style={ { fontSize: 11, color: '#6b7280', marginBottom: 8 } }>{ desc }</div>
      <pre style={ pre }>{ code }</pre>
    </div>
  );
}

export default function InstructionsContent () {
  return (
    <div style={ { maxWidth: 960 } }>
      <h2 style={ { fontSize: 18, fontWeight: 700, marginBottom: 16 } }>SEO Autopilot — Instructions & Standards</h2>

      <Card title="Overview">
        <p style={ { fontSize: 13, color: '#374151', lineHeight: 1.7, margin: 0 } }>
          AI-powered SEO for wecare.digital using Claude Sonnet 4.6 via AWS Bedrock.
          AWS-native blog posts plus public site, product, and system pages.
          Every page gets clean JSON-LD (no duplicates), meta tags, keywords, FAQ schema, and SEO score.
          Human approval required. 🧹🤖 = Clean first then Audit. 🤖 = Audit only.
        </p>
      </Card>

      {/* ═══ 1. BLOG POST JSON-LD ═══ */ }
      <JCard n="1" title='Blog Post (/post/*) — BlogPosting + BreadcrumbList + FAQPage'
        desc="AWS-native blog posts. AI can generate BlogPosting, BreadcrumbList and evidence-based FAQPage data; approved SEO is stored with the post and rendered by Amplify."
        code={ `// ── 1. BlogPosting ──
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "Stand: The Practice of Standing With Another",
  "description": "Standing with another is a conscious free choice rooted in responsibility and intentionality—without requiring reciprocity.",
  "keywords": "standing with another, conscious free choice, willingness to be responsible, being in relationship, intentionality",
  "url": "https://wecare.digital/post/stand",
  "image": ["https://wecare.digital/get/o/stream/media/m/wecare-digital.png"],
  "datePublished": "2025-09-12T00:18:04.958Z",
  "dateModified": "2025-09-12T00:18:04.958Z",
  "wordCount": 75,
  "author": { "@type": "Person", "name": "Swdhya Vaksetu", "url": "https://wecare.digital/anew/" },
  "publisher": { "@type": "Organization", "name": "WECARE.DIGITAL", "logo": { "@type": "ImageObject", "url": "https://wecare.digital/get/o/stream/media/m/wecare-digital.png" } },
  "mainEntityOfPage": { "@type": "WebPage", "@id": "https://wecare.digital/post/stand" },
  "inLanguage": "en-IN",
  "articleSection": "Philosophy of Relationship"
}

// ── 2. BreadcrumbList ──
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://wecare.digital/" },
    { "@type": "ListItem", "position": 2, "name": "Blog", "item": "https://wecare.digital/blog" },
    { "@type": "ListItem", "position": 3, "name": "Stand", "item": "https://wecare.digital/post/stand" }
  ]
}

// ── 3. FAQPage (AI-generated from blog content) ──
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "What does it mean to stand with another person?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Standing with another means being willing to be responsible for standing up for and supporting another person, even while acknowledging they may require neither."
      }
    },
    {
      "@type": "Question",
      "name": "Does standing with someone require reciprocity?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "No. Making a choice to stand with another neither requires nor depends on the other person's reciprocity or their choice to also stand with you."
      }
    }
  ]
}`} />

      {/* ═══ 2. SITE PAGE JSON-LD ═══ */ }
      <JCard n="2" title='Site Page (/, /bnb, /legal-champ...) — WebPage + Organization + BreadcrumbList + FAQPage'
        desc="37 public pages. Homepage also gets WebSite + ItemList. FAQ page gets FAQPage with all Q&As."
        code={ `// ── 1. WebPage ──
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Microservices for Everyday Bharat",
  "description": "Digital services for everyday Bharat — travel, legal, ritual, reflection, and dispute resolution with transparent pricing.",
  "keywords": "digital services India, everyday Bharat, travel support, legal support, WECARE.DIGITAL",
  "url": "https://wecare.digital/",
  "image": "https://wecare.digital/get/o/stream/media/m/wecare-digital.png",
  "publisher": { "@type": "Organization", "name": "WECARE.DIGITAL" },
  "mainEntityOfPage": { "@type": "WebPage", "@id": "https://wecare.digital/" },
  "inLanguage": "en-IN"
}

// ── 2. Organization (homepage) ──
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "WECARE.DIGITAL",
  "url": "https://wecare.digital/",
  "logo": "https://wecare.digital/get/o/stream/media/m/wecare-digital.png",
  "email": "one@wecare.digital",
  "telephone": "+91 9330994400",
  "address": { "@type": "PostalAddress", "streetAddress": "The W.B.S.I.D.C. Building", "addressLocality": "Kolkata", "addressRegion": "West Bengal", "postalCode": "700012", "addressCountry": "IN" }
}

// ── 3. BreadcrumbList ──
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://wecare.digital/" },
    { "@type": "ListItem", "position": 2, "name": "Elsewhere · Visa", "item": "https://wecare.digital/elsewhere/visa/" }
  ]
}

// ── 4. FAQPage (AI-generated from page content) ──
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "What services does WECARE.DIGITAL offer?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Travel, legal documentation, ritual kits, self-inquiry sessions, and online dispute resolution across India."
      }
    },
    {
      "@type": "Question",
      "name": "Where is WECARE.DIGITAL based?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Kolkata, West Bengal, India. The W.B.S.I.D.C. Building, Phears Lane, 700012."
      }
    }
  ]
}`} />

      {/* ═══ 3. PRODUCT JSON-LD ═══ */ }
      <JCard n="3" title='Product (/shop/*) — Product + Offer + BreadcrumbList + FAQPage'
        desc="5 products. Includes price, currency (INR), availability. FAQ about the product."
        code={ `// ── 1. Product + Offer ──
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Partner · Merchandise",
  "description": "WECARE.DIGITAL merchandise.",
  "url": "https://wecare.digital/shop/merchandise/",
  "image": "https://d1kf2rchz7yras.cloudfront.net/o/catalog/products/example.png",
  "brand": { "@type": "Brand", "name": "WECARE.DIGITAL" },
  "offers": {
    "@type": "Offer",
    "price": "1999",
    "priceCurrency": "INR",
    "availability": "https://schema.org/InStock",
    "url": "https://wecare.digital/shop/merchandise/"
  },
  "inLanguage": "en-IN"
}

// ── 2. BreadcrumbList ──
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://wecare.digital/" },
    { "@type": "ListItem", "position": 2, "name": "Store", "item": "https://wecare.digital/shop/" },
    { "@type": "ListItem", "position": 3, "name": "Merchandise", "item": "https://wecare.digital/shop/merchandise/" }
  ]
}

// ── 3. FAQPage ──
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "What is WECARE.DIGITAL Merchandise?",
      "acceptedAnswer": { "@type": "Answer", "text": "WECARE.DIGITAL merchandise available through the shop." }
    },
    {
      "@type": "Question",
      "name": "How much does Merchandise cost?",
      "acceptedAnswer": { "@type": "Answer", "text": "₹1,999.00 at the current catalogue price." }
    }
  ]
}`} />

      {/* ═══ 4. SYSTEM PAGE JSON-LD ═══ */ }
      <JCard n="4" title='System Page (checkout, status, 404...) — no rich schema'
        desc="Checkout and payment status pages are noindex. The legacy cart URL serves a noindex checkout handoff for existing links."
        code={ `// Checkout → null (noindex, nofollow — no JSON-LD)
// Payment status → null (noindex, nofollow — no JSON-LD)
// Cart URL → noindex client-side handoff to /checkout/
// Login-gated pages → null (not crawlable)` } />

      {/* ═══ 5. NEW PAGE ═══ */ }
      <JCard n="5" title='Any New Page (future) — AI auto-detects type'
        desc="New blog/page/product created → AI detects type → applies correct schema set."
        code={ `// New blog post is saved in the SEO Tools DynamoDB table
// Admin runs AI audit → BlogPosting + BreadcrumbList + optional FAQPage
// Saved as pending_review → admin approves → SEO saved back to the AWS BlogPost

// New site page → manual audit from dashboard
// AI generates: WebPage + BreadcrumbList + Organization + FAQPage

// New product → manual audit from dashboard
// AI generates: Product + Offer + BreadcrumbList + FAQPage

// System page → minimal WebPage or null (noindex)`} />

      {/* Phases */ }
      <Card title="Phases">
        <table style={ { width: '100%', borderCollapse: 'collapse', fontSize: 12 } }>
          <thead><tr style={ { borderBottom: '2px solid #e5e7eb', background: '#f9fafb' } }>
            <th style={ thI }>Phase</th><th style={ thI }>Scope</th><th style={ { ...thI, textAlign: 'center' as const } }>Cost</th><th style={ { ...thI, textAlign: 'center' as const } }>Status</th>
          </tr></thead>
          <tbody>
            { [ [ '1. Pilot', 'Stand blog post', '$0.08', '✅ Done' ], [ '2. All Blogs', '108 blog posts', '$6.48', '⏳' ], [ '3. Site Pages', '37 public pages', '$2.22', '⏳' ], [ '4. Products', '5 products', '$0.30', '⏳' ], [ '5. System', '14 system pages', '$0.84', '⏳' ], [ '6. Autopilot', 'New posts auto', '$0.08/post', '✅ Active' ] ].map( ( [ a, b, c, d ] ) => (
              <tr key={ a } style={ { borderBottom: '1px solid #f3f4f6' } }><td style={ { ...tdI, fontWeight: 600 } }>{ a }</td><td style={ tdI }>{ b }</td><td style={ { ...tdI, textAlign: 'center' as const, fontWeight: 600 } }>{ c }</td><td style={ { ...tdI, textAlign: 'center' as const } }>{ d }</td></tr>
            ) ) }
          </tbody>
        </table>
      </Card>

      {/* Rules */ }
      <Card title="Rules">
        <ul style={ { fontSize: 13, color: '#374151', lineHeight: 2, margin: 0, paddingLeft: 20 } }>
          <li>🧹🤖 Clean + Audit = wipe all old SEO data first, then run AI audit (recommended for first time)</li>
          <li>🤖 Audit only = run AI on current state (use for re-audits after content changes)</li>
          <li>Blog titles: expert-written only — AI suggests but NEVER auto-publishes</li>
          <li>All AI SEO changes require human approval before they are saved to the published AWS post</li>
          <li>No monthly refresh — set once, done. Re-audit only on request</li>
          <li>Focus and secondary keywords are stored with the AWS post and rendered by Amplify metadata</li>
          <li>All old duplicate JSON-LD wiped on Apply — complete replacement</li>
          <li>Author is stored per AWS post; the current Admin identity is the default</li>
          <li>Model: Claude Sonnet 4.6 via Bedrock — ~$0.05/page (fallback: Nova Pro)</li>
        </ul>
      </Card>

      {/* Architecture */ }
      <Card title="Architecture">
        <pre style={ { ...pre, lineHeight: 1.8 } }>{ `Dashboard → authenticated wecare.digital/api/seo-tools/*
         → SEO Lambda → AWS-native BlogPost records in SeoToolsTable
         → AWS Bedrock (Claude Sonnet 4.6, fallback models)
         → retained DynamoDB audit + AI log records (PITR)
         → conditional approval → SEO saved to the AWS BlogPost
         → public read API → Amplify static /blog and /post/{slug}

Keywords: focus + secondary keywords are stored on the BlogPost and rendered in public metadata
JSON-LD: BlogPosting + BreadcrumbList + FAQPage (3 scripts, no duplicates)
Mutations: fail-closed idempotency claims; actor always comes from Cognito
Pages/products: audit and review only; apply is intentionally unsupported

Flow: clean or audit → pending_review → approve/reject → blog apply`}</pre>
      </Card>
    </div>
  );
}
