/**
 * Code Repository — Reference library for all backend code, flow JSONs, and templates.
 * Browse, search, and review reusable code assets.
 */

import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import Select, { type SelectOption } from '../../../components/ui/Select';
import * as api from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; }

interface CodeAsset {
  id: string;
  category: string;
  name: string;
  description: string;
  path: string;
  type: 'flow_json' | 'lambda' | 'sms_template' | 'config' | 'script';
  status?: string;
  lastUpdated?: string;
}

// Static registry of all code assets in the stack
const CODE_ASSETS: CodeAsset[] = [
  // ── WhatsApp Flows ──
  { id: 'flow-sr', category: 'WhatsApp Flows', name: '01.WD_SR_PAY — Submit Request', description: 'Multi-screen flow for order service requests with ₹49 payment. Screens: Order Select → Request Form → Terms → Review → Thank You.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/submit-request-flow.json', type: 'flow_json', status: 'Published' },
  { id: 'flow-sr-v2', category: 'WhatsApp Flows', name: '01.WD_SR_PAY v2', description: 'Updated submit request flow with v7.3 format, data_api 4.0, improved UX.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/submit-request-flow-v2.json', type: 'flow_json', status: 'Published' },
  { id: 'flow-sub', category: 'WhatsApp Flows', name: '02.WD_Profile — Subscribe', description: 'Profile/subscription flow collecting name, phone, email, company, job title, delivery address. Single address (billing = delivery). Updates contact with subscriber ID.', path: 'amplify/functions/messaging/whatsapp-business-api/flows/profile-flow.json', type: 'flow_json', status: 'Published' },

  // ── Core Lambdas ──
  { id: 'lambda-auth', category: 'Core Lambdas', name: 'Auth Middleware', description: 'Cognito JWT validation, API Gateway authorizer.', path: 'amplify/functions/core/auth-middleware/handler.py', type: 'lambda' },
  { id: 'lambda-contacts', category: 'Core Lambdas', name: 'Contacts', description: 'CRUD for contacts — create, read, update, delete, search, import. Supports structured addresses.', path: 'amplify/functions/core/contacts/handler.py', type: 'lambda' },
  { id: 'lambda-messages-read', category: 'Core Lambdas', name: 'Messages Read', description: 'Read messages from DynamoDB with pagination, filtering by channel/contact/direction.', path: 'amplify/functions/core/messages-read/handler.py', type: 'lambda' },
  { id: 'lambda-messages-delete', category: 'Core Lambdas', name: 'Messages Delete', description: 'Delete individual messages from inbound/outbound tables.', path: 'amplify/functions/core/messages-delete/handler.py', type: 'lambda' },
  { id: 'lambda-faq', category: 'Core Lambdas', name: 'FAQ Handler', description: 'FAQ management — CRUD for FAQ entries used by AI auto-reply.', path: 'amplify/functions/core/faq-handler/handler.py', type: 'lambda' },
  { id: 'lambda-url', category: 'Core Lambdas', name: 'URL Shortener', description: 'Short URL creation and redirect for tracking links.', path: 'amplify/functions/core/url-shortener/handler.py', type: 'lambda' },

  // ── WhatsApp Lambdas ──
  { id: 'lambda-inbound-wa', category: 'WhatsApp Lambdas', name: 'Inbound WhatsApp', description: 'Main webhook handler — processes all inbound WhatsApp messages, keyword triggers, flow routing, AI automation, media handling.', path: 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py', type: 'lambda' },
  { id: 'lambda-outbound-wa', category: 'WhatsApp Lambdas', name: 'Outbound WhatsApp', description: 'Send WhatsApp messages — text, media, interactive, templates, flows.', path: 'amplify/functions/messaging/outbound-whatsapp/handler.py', type: 'lambda' },
  { id: 'lambda-wa-voice', category: 'WhatsApp Lambdas', name: 'WhatsApp Voice', description: 'Voice note TTS via Amazon Polly, send as WhatsApp audio.', path: 'amplify/functions/messaging/whatsapp-voice/handler.py', type: 'lambda' },
  { id: 'lambda-wa-calling', category: 'WhatsApp Lambdas', name: 'WhatsApp Calling', description: 'WhatsApp calling — permission requests, call records, SIP integration.', path: 'amplify/functions/messaging/whatsapp-calling/handler.py', type: 'lambda' },
  { id: 'lambda-wa-templates', category: 'WhatsApp Lambdas', name: 'WhatsApp Templates', description: 'Template CRUD — create, read, update, delete message templates via Meta API.', path: 'amplify/functions/messaging/whatsapp-templates/handler.py', type: 'lambda' },
  { id: 'lambda-wa-tmpl-mgmt', category: 'WhatsApp Lambdas', name: 'Template Management', description: 'Advanced template management — media upload, template analytics, batch operations.', path: 'amplify/functions/messaging/whatsapp-template-management/handler.py', type: 'lambda' },
  { id: 'lambda-wa-biz-api', category: 'WhatsApp Lambdas', name: 'WhatsApp Business API', description: 'Meta Graph API wrapper — flows, payments, checkout, business profile, webhooks, flow data exchange.', path: 'amplify/functions/messaging/whatsapp-business-api/handler.py', type: 'lambda' },
  { id: 'lambda-waba-mgmt', category: 'WhatsApp Lambdas', name: 'WABA Management', description: 'WABA account management — phone numbers, quality, limits, media, subscriptions.', path: 'amplify/functions/messaging/waba-management/handler.py', type: 'lambda' },
  { id: 'lambda-media-cleanup', category: 'WhatsApp Lambdas', name: 'Media Cleanup', description: 'S3 media lifecycle — clean up expired pre-signed URLs and orphaned media.', path: 'amplify/functions/messaging/media-cleanup/handler.py', type: 'lambda' },
  { id: 'lambda-tmpl-analytics', category: 'WhatsApp Lambdas', name: 'Template Analytics', description: 'Template performance metrics — delivery, read, click rates.', path: 'amplify/functions/messaging/template-analytics/handler.py', type: 'lambda' },

  // ── SMS / Email / Voice Lambdas ──
  { id: 'lambda-outbound-sms', category: 'SMS / Email / Voice', name: 'Outbound SMS', description: 'Send SMS via AWS Pinpoint / SNS.', path: 'amplify/functions/messaging/outbound-sms/handler.py', type: 'lambda' },
  { id: 'lambda-outbound-email', category: 'SMS / Email / Voice', name: 'Outbound Email', description: 'Send email via AWS SES.', path: 'amplify/functions/messaging/outbound-email/handler.py', type: 'lambda' },
  { id: 'lambda-sms-aws', category: 'SMS / Email / Voice', name: 'SMS AWS', description: 'AWS Pinpoint SMS inbound handler.', path: 'amplify/functions/messaging/sms-aws/handler.py', type: 'lambda' },
  // `lambda-sms-airtel` REMOVED 2026-09-25. It pointed at
  // `amplify/functions/messaging/sms-in/airtel/handler.py`, a path that does not
  // exist, for a retired provider whose Lambda is absent from the account.
  { id: 'lambda-voice-aws', category: 'SMS / Email / Voice', name: 'Voice AWS', description: 'AWS Connect voice call handler.', path: 'amplify/functions/messaging/voice-aws/handler.py', type: 'lambda' },
  { id: 'lambda-outbound-voice', category: 'SMS / Email / Voice', name: 'Outbound Voice', description: 'Outbound voice calls via AWS Connect.', path: 'amplify/functions/messaging/outbound-voice/handler.py', type: 'lambda' },

  // ── AI Lambdas ──
  { id: 'lambda-ai-kb', category: 'AI', name: 'AI Query KB', description: 'Query Amazon Bedrock Knowledge Base for RAG-based responses.', path: 'amplify/functions/ai/ai-query-kb/handler.py', type: 'lambda' },
  { id: 'lambda-ai-gen', category: 'AI', name: 'AI Generate Response', description: 'Generate AI responses using Bedrock Claude — context-aware, multi-turn.', path: 'amplify/functions/ai/ai-generate-response/handler.py', type: 'lambda' },
  { id: 'lambda-ai-config', category: 'AI', name: 'AI Config Management', description: 'AI configuration — system prompts, model settings, knowledge base config.', path: 'amplify/functions/ai/ai-config-management/handler.py', type: 'lambda' },
  { id: 'lambda-agent', category: 'AI', name: 'Agent Action Group', description: 'Bedrock Agent action group — tool use for order lookup, payment, etc.', path: 'amplify/functions/ai/agent-action-group/handler.py', type: 'lambda' },

  // ── Payments ──
  { id: 'lambda-razorpay', category: 'Payments', name: 'Razorpay Webhook', description: 'Razorpay payment webhook — capture, refund, dispute events.', path: 'amplify/functions/payments/razorpay-webhook/handler.py', type: 'lambda' },
  { id: 'lambda-payments-read', category: 'Payments', name: 'Payments Read', description: 'Read payment records from DynamoDB.', path: 'amplify/functions/payments/payments-read/handler.py', type: 'lambda' },
  { id: 'lambda-invoice', category: 'Payments', name: 'Invoice Engine', description: 'Invoice creation, PDF generation, WhatsApp delivery, payment link generation.', path: 'amplify/functions/payments/invoice-engine/handler.py', type: 'lambda' },

  // ── Operations ──
  { id: 'lambda-bulk-create', category: 'Operations', name: 'Bulk Job Create', description: 'Create bulk messaging jobs — WhatsApp, SMS, email campaigns.', path: 'amplify/functions/operations/bulk-job-create/handler.py', type: 'lambda' },
  { id: 'lambda-bulk-worker', category: 'Operations', name: 'Bulk Worker', description: 'Process bulk job queue — send messages in batches with rate limiting.', path: 'amplify/functions/operations/bulk-worker/handler.py', type: 'lambda' },
  { id: 'lambda-billing', category: 'Operations', name: 'Billing', description: 'Usage billing — message counts, API calls, storage metrics.', path: 'amplify/functions/operations/billing/handler.py', type: 'lambda' },
  { id: 'lambda-cleanup', category: 'Operations', name: 'System Cleanup', description: 'Scheduled cleanup — expired data, orphaned records, TTL enforcement.', path: 'amplify/functions/operations/system-cleanup/handler.py', type: 'lambda' },

  // ── Ecommerce ──
  { id: 'lambda-wix', category: 'Ecommerce', name: 'Wix Store', description: 'Wix ecommerce integration — order sync, product catalog, webhooks.', path: 'amplify/functions/ecommerce/wix-store/handler.py', type: 'lambda' },
  { id: 'lambda-product-img', category: 'Ecommerce', name: 'Product Image Gen', description: 'AI product image generation using Bedrock Titan Image.', path: 'amplify/functions/ecommerce/product-image-gen/handler.py', type: 'lambda' },
];

const CATEGORIES = [...new Set(CODE_ASSETS.map(a => a.category))];

/* Derived from CATEGORIES so the two cannot drift. 'All' is the filter's own sentinel and
   was its first <option>, so it stays first and keeps its value. */
const CATEGORY_OPTIONS: SelectOption[] = [
  { value: 'All', label: 'All Categories' },
  ...CATEGORIES.map(cat => ({ value: cat, label: cat })),
];

/* LAYOUT ONLY - the filter is a flex child beside a search input, and a native select sized
   itself to its widest option while the trigger shows the selected one. */
const FILTER_STYLE: React.CSSProperties = { width: 190 };

const TYPE_LABELS: Record<string, string> = {
  flow_json: 'Flow JSON',
  lambda: 'Lambda',
  sms_template: 'SMS Template',
  config: 'Config',
  script: 'Script',
};

const TYPE_COLORS: Record<string, string> = {
  flow_json: '#d1f470',
  lambda: '#e0e8e3',
  sms_template: '#dbeafe',
  config: '#fef3c7',
  script: '#f3e8ff',
};

const CodeRepo: React.FC<PageProps> = ({ signOut, user }) => {
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filtered = CODE_ASSETS.filter(a => {
    const matchesSearch = !search || 
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      a.description.toLowerCase().includes(search.toLowerCase()) ||
      a.path.toLowerCase().includes(search.toLowerCase());
    const matchesCategory = selectedCategory === 'All' || a.category === selectedCategory;
    return matchesSearch && matchesCategory;
  });

  const grouped = CATEGORIES.reduce((acc, cat) => {
    const items = filtered.filter(a => a.category === cat);
    if (items.length > 0) acc[cat] = items;
    return acc;
  }, {} as Record<string, CodeAsset[]>);

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="Code Repository" description="Browse and review all backend code assets" noindex={true} />
      <div className="inner-page" style={{ padding: '20px 24px', maxWidth: 1200 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20, color: '#1a3a2a' }}>Code Repository</h2>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: '#6b7280' }}>
              {CODE_ASSETS.length} assets · Browse, search, and review all backend code
            </p>
          </div>
        </div>

        {/* Search + Filter */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          <input
            type="text"
            placeholder="Search flows, lambdas, templates..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ flex: 1, padding: '8px 12px', border: '1px solid #d1f470', borderRadius: 8, fontSize: 13 }}
          />
          {/* The lime border this control carried is NOT reproduced. Lime is the actionable
              colour in this system and must not become a passive control fill or edge, so the
              trigger takes the house box like every other migrated control. */}
          <Select
            ariaLabel="Category"
            value={selectedCategory}
            onChange={v => setSelectedCategory(v)}
            options={CATEGORY_OPTIONS}
            style={FILTER_STYLE}
          />
        </div>

        {/* Asset List */}
        {Object.entries(grouped).map(([category, assets]) => (
          <div key={category} style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 15, color: '#1a3a2a', margin: '0 0 10px', borderBottom: '1px solid #d1f470', paddingBottom: 6 }}>
              {category} <span style={{ color: '#9ca3af', fontWeight: 400, fontSize: 12 }}>({assets.length})</span>
            </h3>
            {assets.map(asset => (
              <div
                key={asset.id}
                style={{
                  border: '1px solid #e5e7eb',
                  borderRadius: 8,
                  padding: '10px 14px',
                  marginBottom: 8,
                  cursor: 'pointer',
                  background: expandedId === asset.id ? '#f9fafb' : '#fff',
                  transition: 'all 0.15s',
                }}
                onClick={() => setExpandedId(expandedId === asset.id ? null : asset.id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      display: 'inline-block',
                      padding: '2px 8px',
                      borderRadius: 4,
                      fontSize: 11,
                      fontWeight: 600,
                      background: TYPE_COLORS[asset.type] || '#e5e7eb',
                      color: '#1a3a2a',
                    }}>
                      {TYPE_LABELS[asset.type] || asset.type}
                    </span>
                    <span style={{ fontSize: 14, fontWeight: 500, color: '#1a3a2a' }}>{asset.name}</span>
                    {asset.status && (
                      <span style={{
                        fontSize: 11,
                        padding: '1px 6px',
                        borderRadius: 4,
                        background: asset.status === 'Published' ? '#d1f470' : '#fef3c7',
                        color: '#1a3a2a',
                        fontWeight: 500,
                      }}>
                        {asset.status}
                      </span>
                    )}
                  </div>
                  <span style={{ fontSize: 12, color: '#9ca3af' }}>{expandedId === asset.id ? '▲' : '▼'}</span>
                </div>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: '#6b7280', lineHeight: 1.4 }}>
                  {asset.description}
                </p>
                {expandedId === asset.id && (
                  <div style={{ marginTop: 10, padding: '8px 10px', background: '#f0f2f5', borderRadius: 6, fontSize: 12 }}>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#6b7280' }}>Path: </span>
                      <code style={{ color: '#1a3a2a', fontFamily: 'monospace', fontSize: 11 }}>{asset.path}</code>
                    </div>
                    <div>
                      <span style={{ color: '#6b7280' }}>Type: </span>
                      <span style={{ color: '#1a3a2a' }}>{TYPE_LABELS[asset.type]}</span>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}

        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>
            No assets found matching your search.
          </div>
        )}
      </div>
    </Layout>
  );
};

export default CodeRepo;
