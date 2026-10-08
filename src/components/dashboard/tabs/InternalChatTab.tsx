/**
 * Internal Chat Tab - Dashboard embedded AI assistant
 * Full-featured chat with controls, logs, and settings
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { API_BASE } from '../../../config/constants';
import { fetchAuthSession } from 'aws-amplify/auth';
import { randomToken } from '../../../lib/randomToken';
import { scrollToEnd } from '../../../lib/scroll-to-end';

const API_ENDPOINT = `${API_BASE}/ai/generate`;

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  status?: 'sending' | 'sent' | 'error';
  toolsUsed?: string[];
  duration?: number;
}

interface ChatLog {
  id: string;
  timestamp: Date;
  query: string;
  response: string;
  toolsUsed: string[];
  duration: number;
  status: 'success' | 'error';
}

/**
 * A plan the agent reached for and was refused, as returned by `describe_plan`.
 *
 * `arguments` is already redacted server-side — the recipient is masked to its last
 * four and the message body is omitted entirely. The browser never holds the real
 * values, which is why approving sends only `planHash`: the server looks the draft
 * up and re-derives the intent from its own copy.
 *
 * `wouldApply` is computed from live catalog enablement, not hardcoded, so it cannot
 * drift into claiming a send is possible when it is not.
 */
interface PendingPlan {
  tool: string;
  toolClass: string;
  catalogVersion: string;
  planHash: string;
  idempotencyKey: string;
  createdAt: number;
  arguments: Record<string, unknown>;
  summary: string;
  wouldApply: boolean;
  refusal: string;
}

type ApprovalState =
  | { kind: 'idle' }
  | { kind: 'sending' }
  | { kind: 'approved'; approvedBy: string; expiresAt: number; stillDisabled: boolean }
  | { kind: 'refused'; reason: string };

type SubTab = 'chat' | 'logs' | 'controls';

/**
 * The tool catalog, WITH its real authorisation state.
 *
 * This list used to be 30 bare names and `enabledTools` was initialised to all 30,
 * so the panel read "Tool Capabilities (30/30)" and offered an Enable All toggle -
 * while the backend refuses 18 of them unconditionally. `governance.py` states
 * there is deliberately NO flag to enable an APPLY tool, because the approval,
 * plan-hash and receipt machinery that would make one safe does not exist yet. So
 * the toggle was cosmetic for those 18, and the panel advertised Send WhatsApp,
 * Delete Contact, Clear All Data and Create Invoice as things the agent could do.
 *
 * That is the same defect the UI label gate exists to catch, in the one screen
 * where being wrong matters most: a person reads this list to decide what to ask
 * for.
 *
 * `cls` and `refused` mirror `lambda_utils/agent/governance.py`. A mirror can
 * drift, so `tests/test_agent_ui_truth.py` parses this array and asserts it matches
 * the Python catalog entry for entry - id, class and enablement. Change the catalog
 * and that test fails until this list follows.
 *
 * The refused tools are shown rather than hidden, deliberately. Hiding them loses
 * the information that the capability exists and is withheld on purpose, which is
 * exactly what someone needs to know before asking the agent to send something.
 */
type ToolRow = {
  id: string;
  name: string;
  category: string;
  /** READ or APPLY, from the governance catalog. */
  cls: string;
  /** True when the backend refuses it regardless of any UI toggle. */
  refused: boolean;
};

const TOOLS_LIST: ToolRow[] = [
  { id: 'search_contacts', name: 'Search Contacts', category: 'Contacts', cls: 'READ', refused: false },
  { id: 'create_contact', name: 'Create Contact', category: 'Contacts', cls: 'APPLY', refused: true },
  { id: 'update_contact', name: 'Update Contact', category: 'Contacts', cls: 'APPLY', refused: true },
  { id: 'add_contact_email', name: 'Add Email', category: 'Contacts', cls: 'APPLY', refused: true },
  { id: 'send_whatsapp', name: 'Send WhatsApp', category: 'Messaging', cls: 'APPLY', refused: true },
  { id: 'send_whatsapp_buttons', name: 'Send Buttons', category: 'Messaging', cls: 'APPLY', refused: true },
  { id: 'send_whatsapp_pay', name: 'WhatsApp Pay', category: 'Messaging', cls: 'APPLY', refused: true },
  { id: 'send_whatsapp_flow', name: 'Send Flow', category: 'Messaging', cls: 'APPLY', refused: true },
  { id: 'make_voice_call', name: 'Voice Call', category: 'Messaging', cls: 'APPLY', refused: true },
  { id: 'send_sms', name: 'Send SMS', category: 'Messaging', cls: 'APPLY', refused: true },
  { id: 'send_email', name: 'Send Email', category: 'Messaging', cls: 'APPLY', refused: true },
  { id: 'get_messages', name: 'Get Messages', category: 'Analytics', cls: 'READ', refused: false },
  { id: 'get_stats', name: 'Get Stats', category: 'Analytics', cls: 'READ', refused: false },
  { id: 'schedule_message', name: 'Schedule Message', category: 'Scheduling', cls: 'APPLY', refused: true },
  { id: 'list_scheduled_messages', name: 'List Scheduled', category: 'Scheduling', cls: 'READ', refused: false },
  { id: 'list_templates', name: 'List Templates', category: 'Templates', cls: 'READ', refused: false },
  { id: 'send_template', name: 'Send Template', category: 'Templates', cls: 'APPLY', refused: true },
  { id: 'delete_contact', name: 'Delete Contact', category: 'Data', cls: 'APPLY', refused: true },
  { id: 'delete_messages', name: 'Delete Messages', category: 'Data', cls: 'APPLY', refused: true },
  { id: 'delete_media_files', name: 'Delete Media', category: 'Data', cls: 'APPLY', refused: true },
  { id: 'list_media_files', name: 'List Media', category: 'Data', cls: 'READ', refused: false },
  { id: 'clear_all_contact_data', name: 'Clear All Data', category: 'Data', cls: 'APPLY', refused: true },
  { id: 'get_voice_cdr', name: 'Voice CDR', category: 'Analytics', cls: 'READ', refused: false },
  { id: 'get_billing_summary', name: 'AWS Billing', category: 'Analytics', cls: 'READ', refused: false },
  { id: 'get_invoice_list', name: 'List Invoices', category: 'Invoicing', cls: 'READ', refused: false },
  { id: 'create_invoice', name: 'Create Invoice', category: 'Invoicing', cls: 'APPLY', refused: true },
  { id: 'get_wix_products', name: 'Wix Products', category: 'Ecommerce', cls: 'READ', refused: false },
  { id: 'get_wix_orders', name: 'Wix Orders', category: 'Ecommerce', cls: 'READ', refused: false },
  { id: 'list_submit_requests', name: 'Flow Submissions', category: 'Flows', cls: 'READ', refused: false },
];

const InternalChatTab: React.FC = () => {
  const [subTab, setSubTab] = useState<SubTab>('chat');
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'Hi! I\'m your Stack CRM task assistant. I can help you find contacts, review messages, and check stats. Type or use the quick actions below.',
      timestamp: new Date(),
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [logs, setLogs] = useState<ChatLog[]>([]);
  // See FloatingAgent.tsx: Math.random() is not acceptable for a key the backend
  // treats as a conversation identifier.
  const [sessionId] = useState(() => `dash-${Date.now()}-${randomToken()}`);
  // Only the tools the backend will actually run. Seeding this with all 30 was
  // what made the panel claim 30/30.
  const AVAILABLE = TOOLS_LIST.filter(t => !t.refused);
  const [enabledTools, setEnabledTools] = useState<Set<string>>(
    new Set(AVAILABLE.map(t => t.id)));
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [pendingPlans, setPendingPlans] = useState<PendingPlan[]>([]);
  const [approvalState, setApprovalState] = useState<Record<string, ApprovalState>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    scrollToEnd(messagesEndRef.current);
  };

  useEffect(() => { scrollToBottom(); }, [messages]);

  useEffect(() => {
    if (subTab === 'chat' && inputRef.current) inputRef.current.focus();
  }, [subTab]);

  const clearChat = useCallback(() => {
    setMessages([{
      id: Date.now().toString(),
      role: 'assistant',
      content: 'Chat cleared. How can I help you?',
      timestamp: new Date(),
    }]);
    setLogs([]);
  }, []);

  /** Strip <thinking>...</thinking> tags from AI responses */
  const cleanResponse = (text: string): string => {
    return text.replace(/<thinking>[\s\S]*?<\/thinking>\s*/gi, '').trim();
  };

  const extractResponse = (data: any): string | null => {
    if (!data) return null;
    let raw: string | null = null;
    if (data.suggestedResponse) raw = data.suggestedResponse;
    else if (data.suggestion) raw = data.suggestion;
    if (!raw && data.body) {
      try {
        const parsed = typeof data.body === 'string' ? JSON.parse(data.body) : data.body;
        if (parsed.suggestedResponse) raw = parsed.suggestedResponse;
        else if (parsed.suggestion) raw = parsed.suggestion;
      } catch { /* ignore */ }
    }
    return raw ? cleanResponse(raw) : null;
  };

  const MAX_MESSAGES = 100;

  const processCommand = async (text: string): Promise<string> => {
    const startTime = Date.now();
    try {
      setStatusMessage('Understanding your request...');

      let res: Response;
      try {
        const session = await fetchAuthSession();
        const token = session.tokens?.accessToken?.toString() ?? '';
        res = await fetch(API_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify({
            messageContent: text,
            context: 'internal-admin',
            sessionId,
            temperature,
            maxTokens,
          }),
        });
      } catch (fetchErr: any) {
        setStatusMessage('');
        const duration = Date.now() - startTime;
        setLogs(prev => [{
          id: Date.now().toString(), timestamp: new Date(), query: text,
          response: 'Network error', toolsUsed: [], duration, status: 'error'
        }, ...prev]);
        return 'Unable to reach the server. Please check your connection and try again.';
      }

      setStatusMessage('Processing...');

      let data: any;
      try {
        data = await res.json();
      } catch {
        setStatusMessage('');
        const duration = Date.now() - startTime;
        setLogs(prev => [{
          id: Date.now().toString(), timestamp: new Date(), query: text,
          response: 'Invalid response', toolsUsed: [], duration, status: 'error'
        }, ...prev]);
        return 'Received an invalid response from the server. Please try again.';
      }

      setStatusMessage('');
      const duration = Date.now() - startTime;

      // Plans the agent reached for and was refused. Replaced rather than appended:
      // these belong to the turn that just happened, and carrying an earlier turn's
      // plan forward would leave an Approve button attached to a request the
      // operator has moved on from.
      const plans: PendingPlan[] = Array.isArray(data?.pendingPlans)
        ? data.pendingPlans.filter((p: any) => p && typeof p.planHash === 'string')
        : [];
      setPendingPlans(plans);
      setApprovalState({});

      const response = extractResponse(data);
      if (response) {
        setLogs(prev => [{
          id: Date.now().toString(), timestamp: new Date(), query: text,
          response: response.substring(0, 200), toolsUsed: [], duration, status: 'success'
        }, ...prev]);
        return response;
      }

      // No response extracted — log as error
      const errMsg = data?.error || 'No response received';
      console.error('Unexpected response:', JSON.stringify(data).substring(0, 500));
      setLogs(prev => [{
        id: Date.now().toString(), timestamp: new Date(), query: text,
        response: errMsg, toolsUsed: [], duration, status: 'error'
      }, ...prev]);
      return 'Something went wrong on the server. Please try again.';
    } catch (error: any) {
      setStatusMessage('');
      const duration = Date.now() - startTime;
      setLogs(prev => [{
        id: Date.now().toString(), timestamp: new Date(), query: text,
        response: error.message, toolsUsed: [], duration, status: 'error'
      }, ...prev]);
      return 'Something went wrong. Please try again.';
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const text = input.trim();
    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', content: text, timestamp: new Date() };
    setMessages(prev => {
      const updated = [...prev, userMsg];
      return updated.length > MAX_MESSAGES ? updated.slice(-MAX_MESSAGES) : updated;
    });
    setInput('');
    setIsLoading(true);

    const loadingId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: loadingId, role: 'assistant', content: '...', timestamp: new Date(), status: 'sending' }]);

    const response = await processCommand(text);
    setMessages(prev => prev.map(m => m.id === loadingId ? { ...m, content: response, status: 'sent' } : m));
    setIsLoading(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const quickAction = (text: string) => {
    setInput(text);
    setTimeout(() => { if (inputRef.current) inputRef.current.focus(); }, 50);
  };

  /**
   * Record this operator's approval of one exact plan.
   *
   * Only `planHash` is sent. The server holds the draft and re-derives the tool and
   * arguments from its own copy, so this request cannot redirect an approval at a
   * different recipient — and the approver is taken from the bearer token, never
   * from anything here.
   *
   * The route is Admin-only. A non-Admin gets 403, and a 403 is surfaced as what it
   * is rather than as a generic failure, because "you are not allowed to approve
   * this" and "the approval could not be recorded" need different responses.
   */
  const approvePlan = useCallback(async (plan: PendingPlan) => {
    setApprovalState(prev => ({ ...prev, [plan.planHash]: { kind: 'sending' } }));
    try {
      const session = await fetchAuthSession();
      const token = session.tokens?.accessToken?.toString() ?? '';
      const res = await fetch(`${API_BASE}/ai/approvals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ planHash: plan.planHash, catalogVersion: plan.catalogVersion }),
      });
      const data = await res.json().catch(() => null);

      if (res.status === 403) {
        setApprovalState(prev => ({
          ...prev,
          [plan.planHash]: {
            kind: 'refused',
            reason: data?.detail || data?.error
              || 'Approving an agent action needs an Admin account with a second factor enrolled.',
          },
        }));
        return;
      }
      if (!res.ok || !data || data.success !== true) {
        setApprovalState(prev => ({
          ...prev,
          [plan.planHash]: {
            kind: 'refused',
            reason: data?.reason || data?.error || 'The approval was not recorded.',
          },
        }));
        return;
      }
      setApprovalState(prev => ({
        ...prev,
        [plan.planHash]: {
          kind: 'approved',
          approvedBy: String(data.approval?.approvedBy ?? ''),
          expiresAt: Number(data.approval?.expiresAt ?? 0),
          // Taken from the response, never assumed. Every APPLY tool is currently
          // disabled, so this is true — and the panel has to say so rather than let
          // a green tick imply the message went out.
          stillDisabled: data.stillDisabled !== false,
        },
      }));
    } catch {
      setApprovalState(prev => ({
        ...prev,
        [plan.planHash]: { kind: 'refused', reason: 'Could not reach the server. Nothing was approved.' },
      }));
    }
  }, []);

  const toggleTool = (id: string) => {
    setEnabledTools(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const categories = [...new Set(TOOLS_LIST.map(t => t.category))];

  return (
    <div className="internalchat-tab">
      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '16px', borderBottom: '1px solid #e5e7eb', paddingBottom: '8px' }}>
        {(['chat', 'logs', 'controls'] as SubTab[]).map(t => (
          <button key={t} onClick={() => setSubTab(t)} style={{
            padding: '8px 16px', border: 'none', borderRadius: '6px 6px 0 0', cursor: 'pointer', fontSize: '13px', fontWeight: 500,
            background: subTab === t ? '#f9fafb' : 'transparent',
            color: subTab === t ? '#1a3a2a' : '#6b7280',
            borderBottom: subTab === t ? '2px solid #1a3a2a' : '2px solid transparent',
          }}>
            {t === 'chat' ? 'Chat' : t === 'logs' ? 'Logs' : 'Controls'}
          </button>
        ))}
        {subTab === 'chat' && (
          <button onClick={clearChat} style={{
            marginLeft: 'auto', padding: '6px 12px', border: '1px solid #d1d5db', borderRadius: '6px',
            background: 'white', color: '#6b7280', cursor: 'pointer', fontSize: '12px',
          }}>
            Clear Chat
          </button>
        )}
      </div>

      {/* CHAT SUB-TAB */}
      {subTab === 'chat' && (
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 320px)', minHeight: '400px' }}>
          {/* Quick Actions */}
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '12px' }}>
            {[
              { label: 'Find Contact', cmd: 'find contact ' },
              { label: 'Send Message', cmd: 'send message to ' },
              { label: 'Dashboard Stats', cmd: 'show dashboard stats' },
              { label: 'Voice CDR', cmd: 'show recent voice calls' },
              { label: 'AWS Billing', cmd: 'show current month billing' },
              { label: 'Invoices', cmd: 'list recent invoices' },
              { label: 'Wix Products', cmd: 'list wix products' },
              { label: 'Templates', cmd: 'list templates' },
              { label: 'Flow Submissions', cmd: 'list recent submit requests' },
              { label: 'Send Flow', cmd: 'send submit request flow to ' },
            ].map(a => (
              <button key={a.label} onClick={() => quickAction(a.cmd)} style={{
                padding: '4px 10px', border: '1px solid #f3f4f6', borderRadius: '12px',
                background: '#f9fafb', color: '#1a3a2a', cursor: 'pointer', fontSize: '12px',
              }}>
                {a.label}
              </button>
            ))}
          </div>

          {/* Messages */}
          <div style={{
            flex: 1, overflowY: 'auto', scrollBehavior: 'smooth', display: 'flex', flexDirection: 'column', gap: '8px',
            padding: '12px', background: '#fafafa', borderRadius: '8px', border: '1px solid #e5e7eb',
          }}>
            {messages.map(msg => (
              <div key={msg.id} style={{
                alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth: '80%',
              }}>
                <div style={{
                  padding: '10px 14px', borderRadius: '12px', fontSize: '13px', lineHeight: '1.5',
                  background: msg.role === 'user' ? '#1a3a2a' : '#f9fafb',
                  color: msg.role === 'user' ? 'white' : '#1f2937',
                  opacity: msg.status === 'sending' ? 0.6 : 1,
                }}>
                  {msg.content.split('\n').map((line, i) => (
                    <React.Fragment key={i}>{line}{i < msg.content.split('\n').length - 1 && <br />}</React.Fragment>
                  ))}
                </div>
                <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '2px', textAlign: msg.role === 'user' ? 'right' : 'left' }}>
                  {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            ))}
            {statusMessage && (
              <div style={{
                padding: '8px 12px', background: '#f9fafb', border: '1px solid #e5e7eb',
                borderRadius: '8px', color: '#1a3a2a', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '8px',
              }}>
                <span style={{
                  width: '10px', height: '10px', border: '2px solid #1a3a2a', borderTopColor: 'transparent',
                  borderRadius: '50%', animation: 'spin 0.8s linear infinite', display: 'inline-block',
                }} />
                {statusMessage}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/*
            Plans the agent wanted to run and was refused.

            Amber, not green and not red. Green would say "done" and red would say
            "something broke"; this is neither — the action is understood, written
            down, and withheld. The heading states plainly that approving does not
            send, because the one failure this panel could reintroduce is a person
            clicking Approve and believing a message went out.
          */}
          {pendingPlans.length > 0 && (
            <div style={{
              marginTop: '12px', padding: '12px', background: '#fffbeb',
              border: '1px solid #e5e7eb', borderLeft: '3px solid #b45309',
              borderRadius: '8px',
            }}>
              <div style={{ fontSize: '13px', fontWeight: 600, color: '#78350f', marginBottom: '2px' }}>
                {pendingPlans.length === 1 ? 'One action was withheld' : `${pendingPlans.length} actions were withheld`}
              </div>
              <div style={{ fontSize: '12px', color: '#92400e', marginBottom: '10px', lineHeight: 1.5 }}>
                Approving records your decision against this exact request. It does not
                send anything — these tools are switched off in the catalog, so applying
                one still refuses.
              </div>

              {pendingPlans.map(plan => {
                const state = approvalState[plan.planHash] ?? { kind: 'idle' as const };
                return (
                  <div key={plan.planHash} style={{
                    padding: '10px', background: 'white', border: '1px solid #e5e7eb',
                    borderRadius: '6px', marginBottom: '8px',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: '13px', fontWeight: 600, color: '#1f2937' }}>
                          {plan.tool}
                          <span style={{
                            marginLeft: '6px', padding: '1px 6px', borderRadius: '10px',
                            background: '#fef3c7', color: '#92400e', fontSize: '11px', fontWeight: 500,
                          }}>
                            {plan.toolClass}
                          </span>
                        </div>
                        {plan.summary && (
                          <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '3px', lineHeight: 1.5 }}>
                            {plan.summary}
                          </div>
                        )}
                        {Object.keys(plan.arguments ?? {}).length > 0 && (
                          <div style={{
                            fontSize: '12px', color: '#374151', marginTop: '6px',
                            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                            wordBreak: 'break-word',
                          }}>
                            {Object.entries(plan.arguments).map(([key, value]) => (
                              <div key={key}>{key}: {String(value)}</div>
                            ))}
                          </div>
                        )}
                        <div style={{
                          fontSize: '11px', color: '#9ca3af', marginTop: '6px',
                          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                        }}>
                          {/* Enough to match against a log line or an audit row
                              without filling the card with 64 hex characters. */}
                          plan {plan.planHash.slice(0, 12)}…
                        </div>
                      </div>

                      {state.kind === 'approved' ? (
                        <span style={{
                          padding: '6px 12px', borderRadius: '6px', background: '#f3f4f6',
                          color: '#374151', fontSize: '12px', whiteSpace: 'nowrap',
                        }}>
                          Approved
                        </span>
                      ) : (
                        <button
                          onClick={() => approvePlan(plan)}
                          disabled={state.kind === 'sending'}
                          style={{
                            padding: '6px 14px', border: 'none', borderRadius: '6px',
                            background: state.kind === 'sending' ? '#d1d5db' : '#1a3a2a',
                            color: 'white', fontSize: '12px', fontWeight: 500,
                            cursor: state.kind === 'sending' ? 'not-allowed' : 'pointer',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {state.kind === 'sending' ? 'Recording…' : 'Approve'}
                        </button>
                      )}
                    </div>

                    {state.kind === 'approved' && (
                      <div style={{ fontSize: '12px', color: '#374151', marginTop: '8px', lineHeight: 1.5 }}>
                        Recorded for {state.approvedBy || 'you'}
                        {state.expiresAt > 0 && <>, valid until {new Date(state.expiresAt * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</>}.
                        {' '}Single use.
                        {state.stillDisabled && (
                          <> The tool is still disabled, so nothing was sent.</>
                        )}
                      </div>
                    )}
                    {state.kind === 'refused' && (
                      <div style={{ fontSize: '12px', color: '#b91c1c', marginTop: '8px', lineHeight: 1.5 }}>
                        {state.reason}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Input */}
          <div style={{ display: 'flex', gap: '8px', marginTop: '12px', alignItems: 'flex-end' }}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a command... (e.g. find contact Jignesh)"
              disabled={isLoading}
              rows={1}
              style={{
                flex: 1, padding: '10px 14px', border: '1px solid #d1d5db', borderRadius: '8px',
                fontSize: '13px', resize: 'none', outline: 'none', fontFamily: 'inherit',
                minHeight: '40px', maxHeight: '80px',
              }}
              onFocus={e => (e.target.style.borderColor = '#1a3a2a')}
              onBlur={e => (e.target.style.borderColor = '#d1d5db')}
            />
            <button onClick={handleSend} disabled={!input.trim() || isLoading} style={{
              padding: '10px 20px', background: !input.trim() || isLoading ? '#d1d5db' : '#1a3a2a',
              color: 'white', border: 'none', borderRadius: '8px', cursor: !input.trim() || isLoading ? 'not-allowed' : 'pointer',
              fontSize: '13px', fontWeight: 500, whiteSpace: 'nowrap',
            }}>
              {isLoading ? 'Sending...' : 'Send'}
            </button>
          </div>
        </div>
      )}

      {/* LOGS SUB-TAB */}
      {subTab === 'logs' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <span style={{ fontSize: '13px', color: '#6b7280' }}>{logs.length} log entries</span>
            {logs.length > 0 && (
              <button onClick={() => setLogs([])} style={{
                padding: '4px 12px', border: '1px solid #d1d5db', borderRadius: '6px',
                background: 'white', color: '#6b7280', cursor: 'pointer', fontSize: '12px',
              }}>
                Clear Logs
              </button>
            )}
          </div>
          {logs.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px', color: '#9ca3af', fontSize: '14px' }}>
              No logs yet. Start chatting to see activity logs here.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: 'calc(100vh - 340px)', overflowY: 'auto' }}>
              {logs.map(log => (
                <div key={log.id} style={{
                  padding: '12px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '8px',
                  borderLeft: `3px solid ${log.status === 'success' ? '#1a3a2a' : '#1a3a2a'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <span style={{ fontSize: '12px', color: '#6b7280' }}>
                      {log.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </span>
                    <span style={{
                      fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
                      background: log.status === 'success' ? '#f9fafb' : '#f3f4f6',
                      color: log.status === 'success' ? '#1a3a2a' : '#6b7280',
                    }}>
                      {log.duration}ms
                    </span>
                  </div>
                  <div style={{ fontSize: '13px', fontWeight: 500, color: '#1f2937', marginBottom: '4px' }}>
                    {log.query}
                  </div>
                  <div style={{ fontSize: '12px', color: '#6b7280', whiteSpace: 'pre-wrap' }}>
                    {log.response}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* CONTROLS SUB-TAB */}
      {subTab === 'controls' && (
        <div style={{ maxHeight: 'calc(100vh - 320px)', overflowY: 'auto' }}>
          {/* Model Settings */}
          <div style={{ padding: '16px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '8px', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#1f2937', marginBottom: '12px' }}>Model Settings</h3>
            <div style={{ display: 'grid', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '12px', color: '#6b7280', display: 'block', marginBottom: '4px' }}>Temperature: {temperature}</label>
                <input type="range" min="0" max="1" step="0.1" value={temperature}
                  onChange={e => setTemperature(parseFloat(e.target.value))}
                  style={{ width: '100%', accentColor: '#1a3a2a' }} />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#9ca3af' }}>
                  <span>Focused</span><span>Creative</span>
                </div>
              </div>
              <div>
                <label style={{ fontSize: '12px', color: '#6b7280', display: 'block', marginBottom: '4px' }}>Max Tokens: {maxTokens}</label>
                <input type="range" min="512" max="4096" step="256" value={maxTokens}
                  onChange={e => setMaxTokens(parseInt(e.target.value))}
                  style={{ width: '100%', accentColor: '#1a3a2a' }} />
              </div>
            </div>
          </div>

          {/* Tool Capabilities */}
          <div style={{ padding: '16px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '8px', marginBottom: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              {/* Counted against AVAILABLE, not TOOLS_LIST. The old denominator was
                  30, which claimed the agent could do 18 things the backend refuses
                  unconditionally. */}
              <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#1f2937' }}>
                Tool Capabilities ({enabledTools.size}/{AVAILABLE.length} available
                {TOOLS_LIST.length - AVAILABLE.length > 0
                  ? `, ${TOOLS_LIST.length - AVAILABLE.length} refused`
                  : ''})
              </h3>
              <button onClick={() => {
                if (enabledTools.size === AVAILABLE.length) setEnabledTools(new Set());
                else setEnabledTools(new Set(AVAILABLE.map(t => t.id)));
              }} style={{
                padding: '4px 10px', border: '1px solid #d1d5db', borderRadius: '6px',
                background: 'white', color: '#6b7280', cursor: 'pointer', fontSize: '11px',
              }}>
                {enabledTools.size === AVAILABLE.length ? 'Disable All' : 'Enable All'}
              </button>
            </div>
            {categories.map(cat => (
              <div key={cat} style={{ marginBottom: '12px' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#1a3a2a', marginBottom: '6px' }}>{cat}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {TOOLS_LIST.filter(t => t.category === cat).map(tool => (
                    tool.refused ? (
                      /* Not a checkbox. A refused tool cannot be switched on from
                         here or anywhere else - governance.py has no enabling flag
                         by design - so offering a control would be a lie about who
                         is in charge. Shown, not hidden, because knowing the
                         capability exists and is withheld is the useful part. */
                      <span key={tool.id}
                        title={`${tool.cls} — refused until the plan/approval/receipt path exists`}
                        style={{
                          display: 'flex', alignItems: 'center', gap: '4px',
                          padding: '4px 8px', border: '1px solid #b45309',
                          borderRadius: '6px', fontSize: '12px',
                          background: '#fffbeb', color: '#b45309', cursor: 'help',
                        }}>
                        {tool.name}
                        <span style={{ fontSize: '10px', fontWeight: 600 }}>REFUSED</span>
                      </span>
                    ) : (
                      <label key={tool.id} style={{
                        display: 'flex', alignItems: 'center', gap: '4px', padding: '4px 8px',
                        border: '1px solid #e5e7eb',
                        borderRadius: '6px', cursor: 'pointer', fontSize: '12px',
                        background: enabledTools.has(tool.id) ? '#f9fafb' : 'white',
                        color: enabledTools.has(tool.id) ? '#1a3a2a' : '#9ca3af',
                      }}>
                        <input type="checkbox" checked={enabledTools.has(tool.id)} onChange={() => toggleTool(tool.id)}
                          style={{ accentColor: '#1a3a2a', width: '12px', height: '12px' }} />
                        {tool.name}
                      </label>
                    )
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Session Info */}
          <div style={{ padding: '16px', background: 'white', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#1f2937', marginBottom: '12px' }}>Session Info</h3>
            <div style={{ display: 'grid', gap: '8px', fontSize: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#6b7280' }}>Session ID</span>
                <span style={{ color: '#1f2937', fontFamily: 'monospace', fontSize: '11px' }}>{sessionId.substring(0, 20)}...</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#6b7280' }}>Messages</span>
                <span style={{ color: '#1f2937' }}>{messages.length}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#6b7280' }}>Log Entries</span>
                <span style={{ color: '#1f2937' }}>{logs.length}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#6b7280' }}>Model</span>
                <span style={{ color: '#1f2937' }}>Amazon Nova Lite</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#6b7280' }}>Endpoint</span>
                <span style={{ color: '#1f2937', fontFamily: 'monospace', fontSize: '11px' }}>wecare.digital/api</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default InternalChatTab;
