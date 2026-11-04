import { API_BASE } from '../../config/constants';
import '../../lib/amplifyConfig';
import { apiCall, apiCallResult, authFetch, WA_BIZ_BASE } from '../core';
import type { ApiResult } from '../core';

// ============================================================================
// AUTOMATION RULES API (cross-channel auto-reply rules)
// ============================================================================

export interface AutomationRule {
  id: string;
  name: string;
  enabled: boolean;
  channel: 'any' | 'whatsapp' | 'sms' | 'rcs' | 'email';
  triggerType: 'keyword' | 'any';
  triggerValue: string;
  actionType: 'reply' | 'ai';
  actionValue: string;
  priority: number;
  createdAt?: number;
  updatedAt?: number;
}

export async function listAutomationRules (): Promise<AutomationRule[]> {
  const data = await apiCall<any>( `${API_BASE}/automation/rules` );
  return ( data && data.rules ) ? data.rules : [];
}

export async function createAutomationRule ( rule: Partial<AutomationRule> ): Promise<AutomationRule | null> {
  const data = await apiCall<any>( `${API_BASE}/automation/rules`, {
    method: 'POST',
    body: JSON.stringify( rule ),
  } );
  return data?.rule || null;
}

export async function updateAutomationRule ( id: string, updates: Partial<AutomationRule> ): Promise<AutomationRule | null> {
  const data = await apiCall<any>( `${API_BASE}/automation/rules/${id}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return data?.rule || null;
}

export async function deleteAutomationRule ( id: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/automation/rules/${id}`, { method: 'DELETE' } );
  return !!( data && ( data.success || data.deleted ) );
}

// ============================================================================
// CONVERSATION META API (team-inbox: status / assignee / tags / internal notes)
// ============================================================================

export interface ConversationNote { text: string; by: string; at: number; }
export interface ConversationMeta {
  conversationId: string;
  status: 'open' | 'pending' | 'resolved';
  assignee: string;
  tags: string[];
  notes: ConversationNote[];
  updatedAt?: number;
}

export async function getConversationMeta ( conversationId: string ): Promise<ConversationMeta | null> {
  const data = await apiCall<any>( `${API_BASE}/inbox/meta/${encodeURIComponent( conversationId )}` );
  return data?.meta || null;
}

export async function listConversationMeta (): Promise<ConversationMeta[]> {
  const data = await apiCall<any>( `${API_BASE}/inbox/meta` );
  return ( data && data.meta ) ? data.meta : [];
}

export async function updateConversationMeta ( conversationId: string, updates: { status?: string; assignee?: string; tags?: string[] } ): Promise<ConversationMeta | null> {
  const data = await apiCall<any>( `${API_BASE}/inbox/meta/${encodeURIComponent( conversationId )}`, {
    method: 'PUT', body: JSON.stringify( updates ),
  } );
  return data?.meta || null;
}

export async function addConversationNote ( conversationId: string, text: string, by?: string ): Promise<ConversationMeta | null> {
  const data = await apiCall<any>( `${API_BASE}/inbox/meta/${encodeURIComponent( conversationId )}/note`, {
    method: 'POST', body: JSON.stringify( { text, by: by || 'agent' } ),
  } );
  return data?.meta || null;
}

// ============================================================================
// WA GRAPH ADMIN MODULES (schedules, commerce, QR, conversational automation,
// link preview, assigned users/WABAs, bot details, AI pricing policy)
// ============================================================================

export interface CampaignSchedule {
  id?: string;
  name?: string;
  description?: string;
  delivery_time?: number;
  status?: 'COMPLETED' | 'FAILED' | 'SCHEDULED' | 'SENDING';
}

export async function listSchedules ( wabaId: string ): Promise<CampaignSchedule[]> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/schedules?wabaId=${encodeURIComponent( wabaId )}` );
  return data?.schedules || [];
}

export async function createSchedule ( wabaId: string, body: Record<string, unknown> ): Promise<{ success: boolean; id?: string; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/schedules`, {
    method: 'POST',
    body: JSON.stringify( { wabaId, ...body } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true, id: data?.id };
}

export interface CommerceSettings { is_cart_enabled?: boolean; is_catalog_visible?: boolean; id?: string; }

export async function getCommerceSettings ( phoneId: string ): Promise<CommerceSettings> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/commerce-settings?phoneId=${phoneId}` );
  return data?.commerceSettings || {};
}

export async function updateCommerceSettings ( phoneId: string, settings: CommerceSettings ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/commerce-settings`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...settings } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export interface QrCode { code: string; prefilled_message: string; deep_link_url: string; qr_image_url?: string; }

export async function listQrCodes ( phoneId: string ): Promise<QrCode[]> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/qr-codes?phoneId=${phoneId}&fields=${encodeURIComponent( 'code,prefilled_message,deep_link_url,qr_image_url.format(PNG)' )}` );
  return data?.qrCodes || [];
}

export async function createQrCode ( phoneId: string, prefilledMessage: string, format: 'PNG' | 'SVG' = 'PNG' ): Promise<{ success: boolean; qrCode?: QrCode; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/qr-codes`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, prefilled_message: prefilledMessage, generate_qr_image: format } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true, qrCode: data?.qrCode };
}

export async function deleteQrCode ( phoneId: string, qrId: string ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/qr-codes?phoneId=${phoneId}&qrId=${qrId}`, { method: 'DELETE' } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export interface BotCommand { command_name: string; command_description: string; }

export async function configureConversationalAutomation (
  phoneId: string,
  config: { enable_welcome_message?: boolean; prompts?: string[]; commands?: BotCommand[] }
): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/conversational-automation`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...config } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export interface ConversationalAutomation {
  phoneId: string;
  prompts: string[];
  commands: BotCommand[];
  enable_welcome_message: boolean;
}

export async function getConversationalAutomation ( phoneId: string ): Promise<ConversationalAutomation> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/conversational-automation?phoneId=${encodeURIComponent( phoneId )}` );
  return {
    phoneId,
    prompts: data?.prompts || [],
    commands: data?.commands || [],
    enable_welcome_message: !!data?.enable_welcome_message,
  };
}

export interface ThroughputInfo {
  phoneId: string;
  displayPhoneNumber: string;
  verifiedName: string;
  status: string;
  platformType: string;
  qualityRating: string;
  throughputLevel: string;
  messagesPerSecond: number | null;
}

export async function getThroughput ( phoneId: string ): Promise<ThroughputInfo> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/throughput?phoneId=${encodeURIComponent( phoneId )}` );
  return {
    phoneId,
    displayPhoneNumber: data?.displayPhoneNumber || '',
    verifiedName: data?.verifiedName || '',
    status: data?.status || '',
    platformType: data?.platformType || '',
    qualityRating: data?.qualityRating || '',
    throughputLevel: data?.throughputLevel || '',
    messagesPerSecond: data?.messagesPerSecond ?? null,
  };
}


// `betaGated` and `restricted` are DIFFERENT conditions and must stay separate.
// betaGated  = Graph code 100 whose error_data.details says the category requires
//              Direct Send, i.e. this WABA is not onboarded yet.
// restricted = 139200 / 131064, i.e. access existed and Meta enforcement blocked or
//              capped it. Conflating the two is what made the not-onboarded case
//              impossible to explain in the UI.
export interface DirectSendResult { success: boolean; error?: string; directSendHint?: string; betaGated?: boolean; restricted?: boolean; result?: any; }

export async function directSend (
  phoneId: string,
  payload: { to: string; category: 'utility' | 'authentication'; text: string; templateName?: string; ttlSeconds?: number }
): Promise<DirectSendResult> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/direct-send`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...payload } ),
  } );
  if ( data?.error )
  {
    const msg = typeof data.error === 'string' ? data.error : ( data.error?.message || data.error?.error?.message || JSON.stringify( data.error ) );
    return { success: false, error: msg, directSendHint: data.directSendHint, betaGated: data.betaGated, restricted: data.restricted };
  }
  return { success: true, result: data?.result };
}

// `directSendUploadSample` was removed on 2026-10-06. It POSTed to
// /{waba_id}/message_samples, which appears in none of Meta's Direct Send
// documentation and could not be corroborated. The backend route now answers 410.

export interface GeneratedTemplate { name: string; status: string; category: string; correct_category?: string; source: string; language: string; }

export async function listGeneratedTemplates ( wabaId: string ): Promise<{ total: number; templates: GeneratedTemplate[] }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/direct-send/templates?wabaId=${encodeURIComponent( wabaId )}` );
  return { total: data?.total || 0, templates: data?.templates || [] };
}

export async function getMmOnboardingStatus ( wabaId: string ): Promise<{ onboardingStatus: string; time: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/mm-onboarding-status?wabaId=${encodeURIComponent( wabaId )}` );
  return { onboardingStatus: data?.onboardingStatus || '', time: data?.time || '' };
}

// MM API conversion metrics. The route answers 200 with available:false when the edge
// does not resolve for this account, carrying the edge it tried, a reason and the last
// cached reading — so render the cached numbers with their timestamp rather than an
// error. `metrics` rows are Meta's own, unreshaped: their shape is unverified here.
// Returns null until GET /wa-business/mm-conversion-metrics exists (deploy-time work).
export interface MmConversionMetrics {
  wabaId: string;
  available: boolean;
  edge: string;
  metrics?: any[];
  readAt?: number;
  reason?: string;
  cached?: { metrics?: any[]; readAt?: number };
  note?: string;
}

export async function getMmConversionMetrics ( wabaId: string, opts?: { since?: string; until?: string } ): Promise<MmConversionMetrics | null> {
  const qs = new URLSearchParams( { wabaId } );
  if ( opts?.since ) qs.set( 'since', opts.since );
  if ( opts?.until ) qs.set( 'until', opts.until );
  const data = await apiCall<any>( `${WA_BIZ_BASE}/mm-conversion-metrics?${qs.toString()}` );
  if ( !data || typeof data.available !== 'boolean' ) return null;
  return data as MmConversionMetrics;
}

export async function sendMarketingMessage (
  phoneId: string,
  payload: { to: string; templateName: string; language?: string; params?: string[]; messageActivitySharing?: boolean; productPolicy?: 'CLOUD_API_FALLBACK' | 'STRICT' }
): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/marketing-message`, {
    method: 'POST',
    body: JSON.stringify( { phoneId, ...payload } ),
  } );
  if ( data?.error )
  {
    const msg = typeof data.error === 'string' ? data.error : ( data.error?.message || data.error?.error?.message || JSON.stringify( data.error ) );
    return { success: false, error: msg };
  }
  return { success: true };
}

export interface LinkPreviewResult { url: string; ok: boolean; og: Record<string, string>; warnings: string[]; note?: string; }

export async function checkLinkPreview ( url: string ): Promise<LinkPreviewResult> {
  const data = await apiCall<LinkPreviewResult>( `${WA_BIZ_BASE}/link-preview`, {
    method: 'POST',
    body: JSON.stringify( { url } ),
  } );
  return data || { url, ok: false, og: {}, warnings: [ 'No response from server' ] };
}

export interface AssignedUser { id: string; name: string; user_type?: string; }

export async function listAssignedUsers ( wabaId: string, business: string ): Promise<{ users: AssignedUser[]; total: number }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/assigned-users?wabaId=${wabaId}&business=${encodeURIComponent( business )}` );
  return { users: data?.users || data?.data || [], total: data?.summary?.total_count || 0 };
}

export async function addAssignedUser ( wabaId: string, user: string, tasks: string[] ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/assigned-users`, {
    method: 'POST', body: JSON.stringify( { wabaId, user, tasks } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export async function removeAssignedUser ( wabaId: string, user: string ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/assigned-users?wabaId=${wabaId}`, {
    method: 'DELETE', body: JSON.stringify( { wabaId, user } ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export async function listAssignedWabas ( userId: string ): Promise<Array<{ id: string; name?: string }>> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/assigned-wabas?userId=${userId}` );
  return data?.wabas || [];
}

export interface AiPolicyMarket { countryCode: string; country?: string; effectiveDate?: string; active?: boolean; note?: string; }

export async function listAiPolicyMarkets (): Promise<{ markets: AiPolicyMarket[]; activeCount: number; analyticsPricingCategory: string; webhookPricingCategory: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/ai-pricing-policy` );
  return {
    markets: data?.markets || [],
    activeCount: data?.activeCount || 0,
    analyticsPricingCategory: data?.analyticsPricingCategory || 'AI_BOT',
    webhookPricingCategory: data?.webhookPricingCategory || 'general_purpose_ai',
  };
}

export async function upsertAiPolicyMarket ( market: AiPolicyMarket ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/ai-pricing-policy`, {
    method: 'POST', body: JSON.stringify( market ),
  } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

export async function deleteAiPolicyMarket ( countryCode: string ): Promise<{ success: boolean; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/ai-pricing-policy?countryCode=${encodeURIComponent( countryCode )}`, { method: 'DELETE' } );
  if ( data?.error ) return { success: false, error: typeof data.error === 'string' ? data.error : data.error?.message };
  return { success: true };
}

// ═══════════════════════════════════════════════════════════════════
// Meta Business AI Agent — management API (POST ${API_BASE}/meta-agent)
// The Lambda dispatches on `action`; every call takes a WABA entity.
// ═══════════════════════════════════════════════════════════════════

export type WabaKey = 'WABA1' | 'WABA2';

export interface AgentSettings {
  agent_id?: string;
  channel?: string;
  rollout?: { enabled: boolean };
  handoff?: { enabled: boolean; message?: string };
  followup?: { enabled: boolean; followup_interval_in_seconds?: number; message?: string };
  ai_audience?: 'ALLOWLISTED_ONLY' | 'EVERYONE';
}

export interface AgentBusinessInfo {
  payment_method?: string;
  return_policy?: string;
  purchase_info?: string;
  delivery_and_shipping?: string;
  business_description?: string;
  contact_info?: { email?: string; hours_of_operation?: string; address?: string };
}

export interface AgentFaq {
  id?: string;
  question: string;
  answer: string;
  created_at?: number;
}

export interface AgentAllowlistEntry {
  id: string;
  consumer_phone_number: string;
}

async function metaAgent<T> ( action: string, params: Record<string, unknown> = {} ): Promise<T | null> {
  return apiCall<T>( `${API_BASE}/meta-agent`, {
    method: 'POST',
    body: JSON.stringify( { action, ...params } ),
  } );
}

export const aiAgentApi = {
  eligibility: ( waba: WabaKey ) =>
    metaAgent<{ eligibility: { is_eligible?: boolean }; entityId: string }>( 'eligibility', { waba } ),

  getSettings: ( waba: WabaKey ) =>
    metaAgent<{ settings: AgentSettings[] | AgentSettings; entityId: string }>( 'settings', { waba } ),

  updateSettings: ( waba: WabaKey, settings: Partial<AgentSettings> & { enabled?: boolean; aiAudience?: string } ) =>
    metaAgent<{ settings: AgentSettings; entityId: string }>( 'settings_update', { waba, ...settings } ),

  enable: ( waba: WabaKey ) => metaAgent<unknown>( 'enable', { waba } ),
  disable: ( waba: WabaKey ) => metaAgent<unknown>( 'disable', { waba } ),

  getBusinessInfo: ( waba: WabaKey ) =>
    metaAgent<{ business_info: AgentBusinessInfo; entityId: string }>( 'business_info', { waba } ),

  updateBusinessInfo: ( waba: WabaKey, businessInfo: AgentBusinessInfo ) =>
    metaAgent<{ business_info: AgentBusinessInfo; entityId: string }>( 'business_info_update', { waba, businessInfo } ),

  listFaqs: ( waba: WabaKey ) =>
    metaAgent<{ faqs: AgentFaq[]; entityId: string }>( 'faq', { waba } ),

  createFaq: ( waba: WabaKey, question: string, answer: string ) =>
    metaAgent<{ faq: AgentFaq; entityId: string }>( 'faq_create', { waba, question, answer } ),

  updateFaq: ( waba: WabaKey, faqId: string, question: string, answer: string ) =>
    metaAgent<{ faq: AgentFaq; entityId: string }>( 'faq_update', { waba, faqId, question, answer } ),

  deleteFaq: ( waba: WabaKey, faqId: string ) =>
    metaAgent<{ deleted: boolean }>( 'faq_delete', { waba, faqId } ),

  listAllowlist: ( waba: WabaKey ) =>
    metaAgent<{ allowlist: AgentAllowlistEntry[]; entityId: string }>( 'allowlist', { waba } ),

  addAllowlist: ( waba: WabaKey, consumerPhoneNumber: string ) =>
    metaAgent<{ entry: AgentAllowlistEntry }>( 'allowlist_add', { waba, consumerPhoneNumber } ),

  removeAllowlist: ( waba: WabaKey, entryId: string ) =>
    metaAgent<{ deleted: boolean }>( 'allowlist_remove', { waba, entryId } ),

  listWebsites: ( waba: WabaKey ) =>
    metaAgent<{ websites: AgentWebsite[]; entityId: string }>( 'websites', { waba } ),

  addWebsite: ( waba: WabaKey, url: string ) =>
    metaAgent<{ website: AgentWebsite; entityId: string }>( 'websites_add', { waba, url } ),

  removeWebsite: ( waba: WabaKey, websiteId: string ) =>
    metaAgent<{ deleted: boolean }>( 'websites_remove', { waba, websiteId } ),

  listSkills: ( waba: WabaKey ) =>
    metaAgent<{ skills: AgentSkill[]; entityId: string }>( 'skills', { waba } ),

  createSkill: ( waba: WabaKey, title: string, description: string, skill: string ) =>
    metaAgent<{ skill: AgentSkill; entityId: string }>( 'skills_create', { waba, title, description, skill } ),

  updateSkill: ( waba: WabaKey, skillId: string, title: string, description: string, skill: string ) =>
    metaAgent<{ skill: AgentSkill; entityId: string }>( 'skills_update', { waba, skillId, title, description, skill } ),

  deleteSkill: ( waba: WabaKey, skillId: string ) =>
    metaAgent<{ deleted: boolean }>( 'skills_delete', { waba, skillId } ),

  // ── Connectors + Tools (agent_connectors) — enterprise/Tech-Provider ──
  listConnectors: ( waba: WabaKey ) =>
    metaAgent<{ connectors: AgentConnector[] | { error?: unknown }; entityId: string }>( 'connectors', { waba } ),

  addConnector: ( waba: WabaKey, connector: AgentConnectorInput ) =>
    metaAgent<{ created: AgentConnector | { error?: unknown }; entityId: string }>( 'connectors_add', { waba, connector } ),

  removeConnector: ( waba: WabaKey, connectorId: string ) =>
    metaAgent<{ deleted: boolean; detail?: unknown }>( 'connectors_remove', { waba, connectorId } ),

  listTools: ( waba: WabaKey, connectorId: string ) =>
    metaAgent<{ tools: AgentTool[] | { error?: unknown }; entityId: string }>( 'tools', { waba, connectorId } ),

  addTool: ( waba: WabaKey, connectorId: string, tool: Record<string, unknown> ) =>
    metaAgent<{ created: AgentTool | { error?: unknown }; entityId: string }>( 'tools_add', { waba, connectorId, tool } ),

  removeTool: ( waba: WabaKey, connectorId: string, toolId: string ) =>
    metaAgent<{ deleted: boolean; detail?: unknown }>( 'tools_remove', { waba, connectorId, toolId } ),

  runTool: ( waba: WabaKey, connectorId: string, toolId: string, input: string ) =>
    metaAgent<{ result: unknown; entityId: string }>( 'tools_run', { waba, connectorId, toolId, input } ),

  // ── Tech Provider panel extras ──
  getConnector: ( waba: WabaKey, connectorId: string ) =>
    metaAgent<{ connector: AgentConnector; entityId: string }>( 'connector_get', { waba, connectorId } ),

  connectorLogs: ( waba: WabaKey, connectorId: string, includeStats = true ) =>
    metaAgent<{ logs: AgentConnectorLogs | { error?: unknown }; entityId: string }>( 'connector_logs', { waba, connectorId, includeStats } ),

  upsertConnectorApiKey: ( waba: WabaKey, connectorId: string, headerName: string, headerValue: string, prefix?: string ) =>
    metaAgent<{ result: unknown; entityId: string }>( 'connector_upsert_apikey', { waba, connectorId, headerName, headerValue, prefix } ),

  upsertConnectorOAuth: ( waba: WabaKey, connectorId: string, auth: Record<string, unknown> ) =>
    metaAgent<{ result: unknown; entityId: string }>( 'connector_upsert_oauth', { waba, connectorId, auth } ),

  // Consolidated Tech Provider overview for both WABAs (or one, if waba passed)
  providerStatus: ( waba?: WabaKey ) =>
    metaAgent<{ providers: AgentProviderStatus[] }>( 'provider_status', waba ? { waba } : {} ),

  // Tech Partner upgrade readiness — live measurement of the 4 eligibility gates.
  techPartnerReadiness: () =>
    metaAgent<TechPartnerReadiness>( 'tp_eligibility' ),
  // ── Conversation Routing thread control ──
  // Both go through the same POST ${API_BASE}/meta-agent dispatcher as every other
  // agent action, so no new route is needed. A thread is identified by BSUID where
  // one is known (that is how a routing event identifies it) with the consumer phone
  // as the fallback. There is deliberately NO takeThread: the handler answers 409,
  // because taking control needs this account to be the designated escalation
  // partner and that designation is an unanswered owner question.
  releaseThread: ( waba: WabaKey, opts: ThreadControlTarget = {} ) =>
    metaAgent<ThreadControlResult>( 'thread_control', { waba, action: 'release', ...opts } ),
  passThread: ( waba: WabaKey, targetRole: string, opts: ThreadControlTarget = {} ) =>
    metaAgent<ThreadControlResult>( 'thread_control', { waba, action: 'pass', targetRole, ...opts } ),
};
export interface ThreadControlTarget {
  /** Business-scoped user id — preferred, because routing identifies a thread by it. */
  bsuid?: string;
  /** Consumer phone in E.164 — the fallback, and what an operator usually has. */
  to?: string;
  /** A raw phone-number id, when the caller is not selecting by WABA key. */
  entityId?: string;
}
export interface ThreadControlResult {
  thread_control: unknown;
  action: string;
  entityId: string;
  bsuid: string;
  targetRole: string | null;
}

export interface TechPartnerGate { pass: boolean; label: string; }
export interface TechPartnerReadiness {
  eligible: boolean;
  checkedAt: number;
  gates: {
    provider: TechPartnerGate & { detail?: string };
    quality: TechPartnerGate & {
      byWaba: Record<string, { phone?: string; rating?: string; status?: string; ok: boolean }>;
    };
    volume: TechPartnerGate & {
      avgPerDay: number; threshold: number; total7d: number;
      byWaba: Record<string, { total7d: number; points: number }>;
    };
    clients: TechPartnerGate & {
      active: number; threshold: number; error?: string;
      ownedWabas?: number; testCount?: number;
      clientList?: Array<{ id: string; name: string; isTest: boolean }>;
    };
  };
}

// ═══════════════════════════════════════════════════════════════════
// Marketing Ads — Ads that Click to WhatsApp (CTWA) via the Marketing API
// (POST ${API_BASE}/marketing-ads, dispatched on `action`). Everything is
// created PAUSED; publishing an ad is an explicit, separate call.
// ═══════════════════════════════════════════════════════════════════
export interface AdAccount { id: string; account_id: string; name: string; account_status: number; currency: string; }
export interface FbPage { id: string; name: string; }
export interface AdEntity { id: string; name?: string; status?: string; effective_status?: string; objective?: string; adset_id?: string; campaign_id?: string; created_time?: string; }

async function marketingAds<T> ( action: string, params: Record<string, unknown> = {} ): Promise<T | null> {
  return apiCall<T>( `${API_BASE}/marketing-ads`, {
    method: 'POST',
    body: JSON.stringify( { action, ...params } ),
  } );
}

export const marketingAdsApi = {
  adAccounts: () => marketingAds<{ adAccounts: { data?: AdAccount[] } }>( 'ad_accounts' ),
  pages: () => marketingAds<{ pages: { data?: FbPage[] } }>( 'pages' ),
  campaigns: ( adAccountId?: string ) =>
    marketingAds<{ campaigns: { data?: AdEntity[] } }>( 'campaigns', adAccountId ? { adAccountId } : {} ),
  ads: ( adAccountId?: string ) =>
    marketingAds<{ ads: { data?: AdEntity[] } }>( 'ads', adAccountId ? { adAccountId } : {} ),
  uploadImage: ( imageData: string, contentType = 'image/jpeg', adAccountId?: string ) =>
    marketingAds<{ imageHash: string | null; raw: unknown }>( 'upload_image', { imageData, contentType, adAccountId } ),
  // One-shot create of campaign+adset+creative+ad (all PAUSED).
  fullCreate: ( input: MarketingAdInput ) =>
    marketingAds<{ created?: Record<string, { id?: string; error?: unknown }>; error?: string; steps?: unknown }>( 'full_create', input as unknown as Record<string, unknown> ),
  publish: ( adId: string ) => marketingAds<{ updated: unknown; status: string }>( 'ad_publish', { adId } ),
  pause: ( adId: string ) => marketingAds<{ updated: unknown; status: string }>( 'ad_pause', { adId } ),
  adStatus: ( adId: string ) => marketingAds<{ ad: AdEntity }>( 'ad_status', { adId } ),
};

export interface MarketingAdInput {
  name: string;
  objective?: 'OUTCOME_ENGAGEMENT' | 'OUTCOME_LEADS' | 'OUTCOME_SALES' | 'OUTCOME_TRAFFIC';
  optimizationGoal?: string;
  waba?: WabaKey;
  adAccountId?: string;
  pageId?: string;
  whatsappPhoneNumber?: string;
  dailyBudget: number;          // minor units (paise for INR); must be > ~9600
  headline?: string;
  primaryText?: string;
  description?: string;
  greeting?: string;
  autofill?: string;
  imageHash?: string;
  targeting?: Record<string, unknown>;
}

// ── Meta Business Agent connectors (external APIs the agent can call) ──
export interface AgentConnector {
  id: string;
  name: string;
  description?: string;
  base_url?: string;
  auth_type?: 'OAUTH2_CLIENT_CREDENTIALS' | 'API_KEY' | 'NONE' | string;
  connection_status?: { status?: string; error_message?: string };
}

export interface AgentConnectorInput {
  name: string;                 // letters/numbers/underscores only
  description: string;
  base_url: string;
  auth_type: 'API_KEY' | 'NONE' | 'OAUTH2_CLIENT_CREDENTIALS';
  auth_config?: {
    api_key?: {
      headers?: { field_name: string; value: string; prefix?: string }[];
      query_params?: { field_name: string; value: string; prefix?: string }[];
      body_params?: { field_name: string; value: string; prefix?: string }[];
    };
  };
}

export interface AgentTool {
  id?: string;
  name?: string;
  description?: string;
  [ k: string ]: unknown;
}

export interface AgentConnectorLogs {
  data?: Array<Record<string, unknown>>;
  stats?: {
    total?: number;
    success?: number;
    error?: number;
    success_rate?: number;
    [ k: string ]: unknown;
  };
  [ k: string ]: unknown;
}

export interface AgentProviderStatusConnector {
  id: string;
  name?: string;
  status?: string;
  authType?: string;
  baseUrl?: string;
}

export interface AgentProviderStatus {
  waba: WabaKey;
  entityId: string;
  wabaId: string;
  eligible: boolean;
  eligibilityStatus: number;
  eligibility?: unknown;
  connectorsReadable: boolean;
  workspaceProvisioned: boolean;
  connectorCount: number;
  connectors: AgentProviderStatusConnector[];
}

export interface AgentWebsite {
  id: string;
  url: string;
  crawl_status?: string;
}

export interface AgentSkill {
  id?: string;
  title?: string;
  description?: string;
  skill: string;
  created_at?: number;
}

// ── AI Hybrid Routing (which triggers the bot handles vs the Meta AI) ──
export interface AiRoutingConfig {
  enabled: boolean;
  keywords: string[];
  contains: string[];
  types: string[];
  commandPrefix: string;
}

export async function getAiRouting (): Promise<{ routing: AiRoutingConfig; defaults: AiRoutingConfig } | null> {
  return apiCall<{ routing: AiRoutingConfig; defaults: AiRoutingConfig }>( `${API_BASE}/wa-business/ai-routing` );
}

export async function updateAiRouting ( cfg: Partial<AiRoutingConfig> ): Promise<{ success: boolean; routing: AiRoutingConfig } | null> {
  return apiCall<{ success: boolean; routing: AiRoutingConfig }>( `${API_BASE}/wa-business/ai-routing`, {
    method: 'POST', body: JSON.stringify( cfg ),
  } );
}

// ============================================================================
// Conversions API for Business Messaging (Click-to-WhatsApp)
// Uses whatsapp_business_manage_events. Logs in-thread conversions (Purchase,
// LeadSubmitted, ...) to Meta so CTWA ad campaigns can optimize & measure.
// ============================================================================
export interface CapiCapturedClick {
  ctwaClid?: string;
  phone?: string;
  wabaId?: string;
  sourceType?: string;
  sourceId?: string;
  headline?: string;
  ts?: number;
}
export interface CapiEventLogEntry {
  ts?: number;
  wabaId?: string;
  event?: string;
  ctwaClid?: string;
  phone?: string;
  value?: number;
  currency?: string;
  ok?: boolean;
  response?: any;
}
export interface CapiStatus {
  wabaId: string;
  partnerAgent: string;
  // `fixed: true` means the id came from configuration (the one dataset both WABAs share) and
  // was NOT read back from Meta — so it says the destination is configured, not that Events
  // Manager has it linked to this WABA. The panel must not render it as a verified state.
  // `cached: true` is the other non-live source: the per-WABA create path's DynamoDB cache.
  dataset: { datasetId?: string; wabaId?: string; cached?: boolean; fixed?: boolean; error?: any };
  supportedEvents: string[];
  capturedClicks: CapiCapturedClick[];
  recentEvents: CapiEventLogEntry[];
}

export async function getCapiStatus ( wabaId?: string ): Promise<CapiStatus | null> {
  const qs = wabaId ? `?wabaId=${encodeURIComponent( wabaId )}` : '';
  return apiCall<CapiStatus>( `${API_BASE}/wa-business/capi${qs}` );
}

export async function createCapiDataset ( wabaId: string ): Promise<{ success: boolean; datasetId?: string; fixed?: boolean; error?: any } | null> {
  return apiCall<{ success: boolean; datasetId?: string; fixed?: boolean; error?: any }>( `${API_BASE}/wa-business/capi/dataset`, {
    method: 'POST', body: JSON.stringify( { wabaId } ),
  } );
}

export async function logCapiEvent ( input: {
  wabaId?: string; eventName: string; phone?: string; ctwaClid?: string;
  value?: number; currency?: string; orderId?: string;
} ): Promise<{ success: boolean; datasetId?: string; eventName?: string; result?: any; error?: any } | null> {
  return apiCall<{ success: boolean; datasetId?: string; eventName?: string; result?: any; error?: any }>(
    `${API_BASE}/wa-business/capi/event`, { method: 'POST', body: JSON.stringify( input ) } );
}

// ─────────────────────────────────────────────────────────────────────────────
// Secure file sharing — wecare.digital/get/secure
//
// Two tiers live on the same bucket. `o/` is open and needs no API at all; these
// calls are the gated `secure/` tier, where a named customer verifies over
// WhatsApp OTP and pays per download.
//
// The S3 key never appears in any of these payloads. Objects are stored under an
// opaque `wecare-digital-<uuid>-<uuid>` name and the backend is the only thing
// that knows which key belongs to whom, so the UI works purely in `fileId`.
// ─────────────────────────────────────────────────────────────────────────────

export interface SecureFile {
  /** Current name for the paid access record; `paidGrantId` is the legacy alias the backend still mirrors. */
  paidEntitlementId?: string;
  paidGrantId?: string;
  deliveryStatus?: string;
  vaultPaymentStatus?: string;
  vaultOrderNumber?: string;
  vaultRequestNumber?: string;
  fileId: string;
  displayName: string;
  /** Staff-only pointer to the originating Drop Docs record; never an S3 key. */
  sourceDocumentId?: string;
  originalFilename: string;
  contentType: string;
  sizeBytes: number;
  status: 'pending' | 'active' | 'revoked';
  createdAt: string;
  downloadCount: number;
  /** Operator label for finding a file later (display-only, never part of a key). */
  tag?: string;
  /** 24h access-window view (display-only; the backend _redeem is the authoritative gate). */
  accessWindowStatus?: string;
  accessWindowOpen?: boolean;
  accessWindowEndsAt?: number;
  accessWindowCount?: number;
  /**
   * What can be done with the file now: UNPAID (₹49 buys a window), OPEN (download free),
   * READY (paid; the next download opens the window), EXPIRED (renewal needed) or
   * PAID_UNVERIFIED (a payment is recorded but its access could not be read: reconcile, never
   * charge again). Absent from older backends.
   */
  accessState?: SecureFileAccessState;
  /** Admin views only — masked to the last four digits, never the full number. */
  ownerName?: string;
  ownerPhoneMasked?: string;
  uploadedBy?: string;
  workspaceRecordVersion?: number;
  /** Staff-authored approved template body {{1}}, unrelated to storage name. */
  lastOfferBodyText?: string;
  /** Staff send audit; Meta accepted does not establish delivered/read. */
  lastOfferRequestedBy?: string;
  lastOfferRequestedAt?: string;
  lastOfferOutcome?: string;
  lastPaymentRequestedBy?: string;
  lastPaymentRequestedAt?: string;
  lastPaymentRequestOutcome?: string;
  /** Server-computed: the earlier card was a legacy 15-minute card WhatsApp already cancelled. */
  paymentRequestLapsed?: boolean;
  accessResendRequestId?: string;
  accessResendState?: string;
  lastAccessSentBy?: string;
  lastAccessSentAt?: string;
  lastAccessSendOutcome?: string;
}

export interface SecureFileLog extends SecureFile {
  legacyRecord?: boolean;
  storageOriginalPresent?: boolean | null;
  storageDeliveryPresent?: boolean | null;
  revokedAt?: string;
  revokedBy?: string;
}

export interface SecureFileStorage {
  bucket: string;
  sourcePrefix: string;
  deliveryPrefix: string;
}

export type SecureFileAccessState = 'UNPAID' | 'OPEN' | 'READY' | 'EXPIRED' | 'PAID_UNVERIFIED';

/** The answer to a one-shot staff Vault action. `message` is the server's sentence. */
export interface SecureFileActionResult {
  ok: boolean;
  /** HTTP status, or null when the request never got an answer. 202 = may have been sent. */
  status: number | null;
  /** The server outcome or refusal code, e.g. PAYMENT_REQUEST_SENT, VAULT_LINK_SENT. */
  outcome: string;
  message: string;
}

/**
 * POST one staff action on a Vault file, exactly once.
 *
 * Deliberately NOT `apiCallResult`: that aborts at 8 s and retries on abort and on 502/503, and
 * a payment request is a WhatsApp send. A retried send is a second message (or a refusal that
 * hides a first one that worked), so an unanswered request is reported as "check the chat".
 */
async function secureFileAction (
  fileId: string, action: 'send-offer' | 'request-payment' | 'send-access',
  options?: { offerBodyText?: string; paymentItemDescription?: string; expectedTotalPaise?: number; deliveryAddressConfirmation?: VaultDeliveryAddressConfirmation; requestId?: string; previousRequestId?: string },
): Promise<SecureFileActionResult> {
  const url = `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/${action}`;
  try
  {
    const requestBody = action === 'send-offer' && options?.offerBodyText !== undefined
      ? JSON.stringify( { offerBodyText: options.offerBodyText } )
      : action === 'request-payment'
        ? JSON.stringify( { ...(options?.paymentItemDescription === undefined ? {} : {paymentItemDescription: options.paymentItemDescription}), ...(options?.expectedTotalPaise === undefined ? {} : {expectedTotalPaise: options.expectedTotalPaise}), ...(options?.deliveryAddressConfirmation === undefined ? {} : {deliveryAddressConfirmation: options.deliveryAddressConfirmation}) } )
        : action === 'send-access' ? JSON.stringify({requestId: options?.requestId, previousRequestId: options?.previousRequestId}) : '{}';
    const response = await authFetch( url, { method: 'POST', body: requestBody } );
    let body: { outcome?: unknown; error?: unknown; message?: unknown } = {};
    try { body = await response.json(); } catch { body = {}; }
    if ( response.status >= 502 && typeof body.outcome !== 'string' )
    {
      // A gateway timeout, not the handler's answer: the send may still have happened.
      return {
        ok: false, status: null, outcome: 'NO_RESPONSE',
        message: 'No answer was received in time. Check the WhatsApp chat before trying again.',
      };
    }
    const outcome = typeof body.outcome === 'string' && body.outcome
      ? body.outcome
      : typeof body.error === 'string' && body.error ? body.error : `HTTP_${response.status}`;
    const message = typeof body.message === 'string' && body.message
      ? body.message
      : response.ok ? 'Done.' : `The request failed (${response.status}).`;
    return { ok: response.ok, status: response.status, outcome, message };
  } catch
  {
    return {
      ok: false, status: null, outcome: 'NO_RESPONSE',
      message: 'No answer was received. Check the WhatsApp chat before trying again.',
    };
  }
}

/** Start the manual Vault journey with the approved IMAGE + Unlock Vault quick reply.
 * The customer tap (not the staff upload) initiates native Review and Pay. */
export function sendSecureFileOffer (
  fileId: string, offerBodyText?: string,
): Promise<SecureFileActionResult> {
  // Existing callers may omit this while migrating their UI; the Vault workbench
  // always supplies independently edited text and the backend validates it.
  if ( offerBodyText === undefined ) return secureFileAction( fileId, 'send-offer' );
  return secureFileAction( fileId, 'send-offer', { offerBodyText } );
}

/** Direct native Review and Pay for authenticated checkout or an explicit staff payment action. */
export interface VaultDeliveryAddressConfirmation {
  confirmed: true;
  checkoutAddressUpdatedAt: number;
}
/** Vault is always physical goods. A saved address without explicit staff review is insufficient. */
export function requestSecureFilePayment (
  fileId: string, paymentItemDescription?: string, expectedTotalPaise?: number,
  deliveryAddressConfirmation?: VaultDeliveryAddressConfirmation,
): Promise<SecureFileActionResult> {
  return secureFileAction(fileId, 'request-payment', {
    ...(paymentItemDescription === undefined ? {} : {paymentItemDescription}),
    ...(expectedTotalPaise === undefined ? {} : {expectedTotalPaise}),
    ...(deliveryAddressConfirmation === undefined ? {} : {deliveryAddressConfirmation}),
  });
}

/** Resend the Access Vault link for a paid file. Never charges. */
export function sendSecureFileAccess ( fileId: string, requestId?: string, previousRequestId?: string ): Promise<SecureFileActionResult> {
  return secureFileAction( fileId, 'send-access', {requestId, previousRequestId} );
}

/** Authenticated, 60-second S3 GET preview of the two already-approved payment assets.
 * Only the backend selects keys. Never use these URLs as outbound WhatsApp media. */
export interface VaultPaymentMediaPreview {
  headerPreviewUrl: string;
  itemPreviewUrl: string;
  expiresInSeconds: number;
}
export function getVaultPaymentMediaPreview (): Promise<ApiResult<VaultPaymentMediaPreview>> {
  return apiCallResult<VaultPaymentMediaPreview>( `${API_BASE}/secure-files/payment-media-preview`,
    { cache: 'no-store' } );
}

/** Timed actions use the existing five-minute scheduled-messages worker, but dispatch
 * only through the same owner-verified Vault backend (never generic template params). */
export type VaultScheduleAction = 'offer' | 'payment' | 'access';
export interface VaultScheduledAction {
  scheduledId: string;
  fileId: string;
  action: VaultScheduleAction;
  offerBodyText?: string;
  scheduledAt: string;
  status: 'PENDING' | 'DISPATCHING' | 'SENT' | 'FAILED' | 'DISPATCH_UNKNOWN' | 'CANCELLED';
  createdAt: string;
  sentAt?: string;
  updatedAt?: string;
  errorMessage?: string;
}
export function scheduleVaultAction (
  fileId: string, action: VaultScheduleAction, scheduledAt: string,
  offerBodyText?: string, paymentItemDescription?: string,
): Promise<ApiResult<{ schedule: VaultScheduledAction; message: string }>> {
  return apiCallResult( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/schedules`, {
    method: 'POST',
    body: JSON.stringify( { action, scheduledAt,
      ...( action === 'offer' ? { offerBodyText } : {} ),
      ...( action === 'payment' && paymentItemDescription !== undefined
        ? { paymentItemDescription } : {} ) } ),
  } );
}
export function listVaultSchedules (
  fileId: string,
): Promise<ApiResult<{ schedules: VaultScheduledAction[] }>> {
  return apiCallResult( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/schedules`,
    { cache: 'no-store' } );
}
export function cancelVaultScheduledAction (
  fileId: string, scheduledId: string,
): Promise<ApiResult<{ scheduledId: string; status: string }>> {
  return apiCallResult(
    `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/schedules/${encodeURIComponent( scheduledId )}`,
    { method: 'DELETE' },
  );
}

/** Staff-only Vault upload, independent of customer-facing Drop Docs.
 * Server chooses the opaque file name and writes only to the private, edge-gated
 * s3://wecare-digital-get/secure/d/public/valut/ prefix.
 * The server feature flag keeps this unavailable until the live edge gate is verified. */
export interface VaultUploadTicket {
  fileId: string;
  displayName: string;
  uploadUrl: string;
  contentType: string;
  expiresInSeconds: number;
}
export async function initVaultFileUpload ( input: {
  name: string;
  mobile: string;
  originalFilename: string;
  contentType: string;
  sizeBytes: number;
} ): Promise<ApiResult<VaultUploadTicket>> {
  return apiCallResult( `${API_BASE}/secure-files/upload-init`, {
    method: 'POST',
    body: JSON.stringify( input ),
  } );
}
export async function uploadVaultFileBytes (
  uploadUrl: string, file: File, contentType: string,
): Promise<boolean> {
  // Vault-only create-if-absent upload. S3 verifies this header in the
  // presigned URL; an already-confirmed/paid file cannot be overwritten while
  // the 15-minute URL is still valid. Do not change generic media uploads.
  try {
    const response = await fetch( uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': contentType, 'If-None-Match': '*' },
      body: file,
    } );
    return response.ok;
  } catch {
    return false;
  }
}
export async function confirmVaultFileUpload ( fileId: string ): Promise<ApiResult<{
  fileId: string;
  status: string;
  sizeBytes: number;
  deliverable: string;
}>> {
  return apiCallResult( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/confirm`, {
    method: 'POST',
  } );
}
/** Operator preview, not the customer download route (which requires verified payment). */
export async function getVaultStaffDownloadUrl ( fileId: string ): Promise<string | null> {
  const result = await apiCallResult<{ url: string }>(
    `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/staff-download`,
    { cache: 'no-store' },
  );
  return result.ok && typeof result.data.url === 'string' ? result.data.url : null;
}
/** Admin listing. Pass a mobile number to scope it to one customer via the GSI. */
export async function listSecureFiles ( mobile?: string ): Promise<ApiResult<{
  files: SecureFile[]; count: number; truncated?: boolean; storage?: SecureFileStorage;
}>> {
  const qs = new URLSearchParams();
  if ( mobile ) qs.set( 'mobile', mobile );
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiCallResult( `${API_BASE}/secure-files${suffix}`, { cache: 'no-store' } );
}

/** Historical Vault audit rows. The backend verifies S3 object presence but never exposes keys.
 * Always bypass browser caches: staff use this view to verify deletes/revokes in real time. */
export async function listSecureFileLogs ( mobile?: string ): Promise<ApiResult<{
  logs: SecureFileLog[]; count: number; truncated?: boolean; storage?: SecureFileStorage;
}>> {
  const qs = new URLSearchParams( { view: 'logs' } );
  if ( mobile ) qs.set( 'mobile', mobile );
  return apiCallResult( `${API_BASE}/secure-files?${qs.toString()}`, { cache: 'no-store' } );
}

/** File-bound webhook evidence. Only confirmed provider IDs recorded on this file
 * may be looked up; unrelated order/invoice WAMIDs are never guessed. */
export interface VaultMessageDeliveryEvidence {
  status: 'NOT_TRACKED' | 'UNAVAILABLE' | 'ACCEPTED' | 'SENT' | 'DELIVERED' | 'READ' | 'FAILED' | 'UNKNOWN' | 'PENDING';
  observedAt: number | null;
  /** SEND_LOG means provider acceptance only; MESSAGE_STATUS may include real webhook evidence. */
  source?: 'SEND_LOG' | 'MESSAGE_STATUS';
}
export interface VaultMessageDeliveryLog {
  fileId: string;
  verifiedInvoice?: {invoiceId: string; invoiceNumber: string} | null;
  evidence: {
    offer: VaultMessageDeliveryEvidence;
    nativePay?: VaultMessageDeliveryEvidence;
    processing?: VaultMessageDeliveryEvidence;
    completed?: VaultMessageDeliveryEvidence;
    invoice?: VaultMessageDeliveryEvidence;
    /** Automatic Access Vault template, bound to the verified paid service request. */
    autoAccess?: VaultMessageDeliveryEvidence;
    /** Separate explicit staff resends, if any. */
    access: VaultMessageDeliveryEvidence;
  };
  scope: string;
  otherStages: string;
}
export function readVaultMessageDeliveryLog ( fileId: string ): Promise<ApiResult<VaultMessageDeliveryLog>> {
  return apiCallResult( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/message-log`, {
    cache: 'no-store',
  } );
}

/** Revoke rather than delete, so the record of who was charged survives. */
export async function revokeSecureFile ( fileId: string ): Promise<ApiResult<{
  fileId: string; status: string;
}>> {
  return apiCallResult( `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/revoke`, {
    method: 'POST',
  } );
}

/**
 * Customer-token fetch, for the three routes below.
 *
 * These must NOT go through `apiCall`/`authFetch`. Those attach the Amplify
 * session, which belongs to the **staff** pool (us-east-1_cSx0RHCIR). A customer
 * signs in against a different pool entirely (us-east-1_46ULYuukt) via WhatsApp
 * OTP, and their token lives in sessionStorage rather than in Amplify.
 *
 * Sending a staff token to a customer route does not fail cleanly either: the
 * backend validates it, sees the wrong issuer, and answers 401 - which looks
 * exactly like an expired customer session and would send the customer round the
 * verification loop forever.
 */
async function customerApiCall<T> ( url: string, options?: RequestInit ): Promise<ApiResult<T>> {
  const { getSession, restoreSession } = await import( '../../lib/customerAuth' );
  let session;
  try { session = getSession() || await restoreSession(); }
  catch {
    return { ok: false, failure: {
      kind: 'unavailable', status: 503,
      message: 'Sign-in is temporarily unavailable. Please try again.',
      url, retryable: true, at: Date.now(),
    } };
  }

  if ( !session )
  {
    return {
      ok: false,
      failure: {
        kind: 'unauthenticated',
        status: 401,
        message: 'Verification required',
        url,
        retryable: false,
        at: Date.now(),
      },
    };
  }

  try
  {
    const response = await fetch( url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...( options?.headers as Record<string, string> || {} ),
        Authorization: `Bearer ${session.accessToken}`,
      },
    } );

    const text = await response.text();
    const parsed = text ? JSON.parse( text ) : {};

    if ( !response.ok )
    {
      return {
        ok: false,
        failure: {
          // 403 stays `forbidden` rather than collapsing into `http`: it is the
          // status the backend uses for both "not your file" and "grant not
          // redeemable", and the page needs to tell those from a transport error.
          kind: response.status === 401
            ? 'unauthenticated'
            : response.status === 403 ? 'forbidden' : 'http',
          status: response.status,
          message: parsed.message || parsed.error || `Request failed (${response.status})`,
          // One 403 status covers "not your file", "not paid" and "window closed"; the code is
          // what lets the Vault page answer each one differently.
          code: typeof parsed.error === 'string' && /^[A-Z][A-Z0-9_]+$/.test( parsed.error ) ? parsed.error : undefined,
          url,
          retryable: false,
          at: Date.now(),
        },
      };
    }
    return { ok: true, data: parsed as T };
  } catch ( err: any )
  {
    return {
      ok: false,
      failure: {
        kind: 'network',
        status: null,
        message: err?.message || 'Network error',
        url,
        retryable: true,
        at: Date.now(),
      },
    };
  }
}

export interface CustomerVaultPaymentRequest {
  outcome: string;
  fileId: string;
  message: string;
  renewal: boolean;
  accessState: SecureFileAccessState;
}

/**
 * Ensure this authenticated customer has the shared phone-bound ContactsTable identity used by
 * native WhatsApp payment. Empty POST is intentional: customer-profile may claim an existing
 * WhatsApp contact or create only the minimal verified-phone contact; it does not invent profile
 * fields or payment state.
 */
export async function ensureCustomerPaymentIdentity (): Promise<ApiResult<Record<string, unknown>>> {
  return customerApiCall(
    `${API_BASE}/customer/profile`,
    { method: 'POST', body: '{}' },
  );
}

/**
 * Ask the backend to send native WhatsApp Review and Pay for this exact owned Vault file.
 *
 * The browser supplies only the file id in the path. The customer-pool token proves the caller;
 * secure-files re-reads owner + entitlement state, and the existing native payment rail owns
 * ProductsTable pricing, GST/fees and the Meta ORDER_DETAILS message. No cart is seeded here.
 */
export async function requestMySecureFilePayment (
  fileId: string, deliveryAddressConfirmation: VaultDeliveryAddressConfirmation,
): Promise<ApiResult<CustomerVaultPaymentRequest>> {
  return customerApiCall(
    `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/request-payment`,
    { method: 'POST', body: JSON.stringify({ deliveryAddressConfirmation }) },
  );
}

/** The signed-in customer's own files. Requires a customer-pool token. */
export async function listMySecureFiles (): Promise<ApiResult<{
  files: SecureFile[]; count: number;
}>> {
  return customerApiCall( `${API_BASE}/secure-files/mine` );
}

/**
 * Look up ONLY the exact owner-bound Vault document from the unique customer link.
 * The same customer-pool token used for /secure-files/mine is checked server-side.
 * Never search through the first 100 results to authorize a direct file link.
 */
export async function getMySecureFile ( fileId: string ): Promise<ApiResult<{
  files: SecureFile[]; count: number;
}>> {
  return customerApiCall(
    `${API_BASE}/secure-files/mine?file=${encodeURIComponent( fileId )}`,
  );
}

/**
 * Redeem paid Vault entitlement for a short-lived download URL.
 *
 * The paid entitlement is durable. The backend issues renewable short-lived
 * download sessions while the customer's access window is open.
 */
export async function redeemSecureFileDownload ( fileId: string, grantId: string ): Promise<ApiResult<{
  downloadUrl: string; expiresInSeconds: number;
}>> {
  return customerApiCall(
    `${API_BASE}/secure-files/${encodeURIComponent( fileId )}/download`
    + `?grant=${encodeURIComponent( grantId )}`,
  );
}

