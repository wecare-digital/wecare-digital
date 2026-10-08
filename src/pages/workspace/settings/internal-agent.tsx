/**
 * Internal Agent Settings — configure the AI-powered admin assistant.
 *
 * THIS FILE MOVED FROM src/app/settings/internal-agent/page.tsx, and the move fixed four
 * things at once. It was the only route in an App Router directory that otherwise held
 * nothing but a seven-line src/app/layout.tsx, and living there meant it bypassed
 * src/pages/_app.tsx entirely:
 *
 *  1. NO AUTHENTICATION. _app.tsx wraps every non-allowlisted Pages route in the Cognito
 *     Authenticator. An App Router page never reaches that wrapper, so this page was served
 *     at HTTP 200 to anyone - verified live on wecare.digital. The API itself is sound
 *     (GET /ai/internal/config returns 401 "No authorization token provided"), so nothing
 *     leaked; the page simply could not work.
 *  2. NO AUTH HEADER EITHER. Both calls below used a bare fetch with no token, so every
 *     request 401'd even for a signed-in operator. They now go through src/api/client.ts,
 *     which attaches the Cognito bearer token.
 *  3. NO STYLING AT ALL. src/app/layout.tsx imported no CSS, and this page's markup is
 *     built from 53 Tailwind-style class attributes while the project has no Tailwind and no
 *     PostCSS installed. Wrapping it in the dashboard Layout gives it the app's stylesheet
 *     and chrome. THE DEAD CLASS NAMES ARE LEFT AS THEY WERE - rewriting the markup of an
 *     internal feature is a separate job, and pretending otherwise would bury it.
 *  4. IT BROKE THE SITE'S 404 PAGE. When an app/ directory exists, Next hands not-found
 *     handling to the App Router, so src/pages/404.tsx was ignored and every mistyped URL
 *     got Next's bare built-in shell - no header, no footer, no widget, no links at all.
 *     Removing src/app/ is what lets the real 404 page render.
 *
 * Nothing linked here: it is absent from src/config/navigation.ts and from every other file
 * in the repo. It is reachable only by typing the URL, which is why none of the above
 * surfaced until the chrome coverage of every route was checked.
 */
import React, { useState, useEffect } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Select, { type SelectOption } from '../../../components/ui/Select';
import * as api from '../../../api/client';

/*
 * The two option lists, hoisted. Same order, same values, same visible text as the <option>
 * rows they replaced - INCLUDING the duplicated `amazon.nova-pro-v1:0`, which was already
 * there and is left exactly as it was. Select's clause 4 is "the first wins for display",
 * with a development-only warning carrying a count and no option text, so the behaviour is
 * the same as the native control's and the duplicate is now reported rather than silent.
 * Correcting it is a product decision about which model "Balanced" should name, not a
 * migration.
 */
const MODEL_OPTIONS: SelectOption[] = [
  { value: 'amazon.nova-pro-v1:0', label: 'Amazon Nova Pro (Fast, Cost-effective)' },
  { value: 'amazon.nova-pro-v1:0', label: 'Amazon Nova Pro (Balanced)' },
  { value: 'amazon.nova-premier-v1:0', label: 'Amazon Nova Premier (Advanced)' },
  { value: 'anthropic.claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (Premium)' },
];
const DEFAULT_CHANNEL_OPTIONS: SelectOption[] = [
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'sms', label: 'SMS' },
  { value: 'email', label: 'Email' },
];

/* LAYOUT ONLY - what `w-full` carried; the box is the trigger's. */
const FULL_WIDTH: React.CSSProperties = { width: '100%' };

interface PageProps { signOut?: () => void; user?: unknown }

interface AgentConfig {
  enabled: boolean;
  modelId: string;
  temperature: number;
  maxTokens: number;
  sessionTimeout: number;
  enabledTools: string[];
  defaultChannel: string;
  autoSearch: boolean;
  conversationHistory: boolean;
}

const AVAILABLE_TOOLS = [
  { id: 'search_contacts', name: 'Search Contacts', category: 'Contact Management' },
  { id: 'create_contact', name: 'Create Contact', category: 'Contact Management' },
  { id: 'update_contact', name: 'Update Contact', category: 'Contact Management' },
  { id: 'send_whatsapp', name: 'Send WhatsApp Text', category: 'WhatsApp' },
  { id: 'send_whatsapp_buttons', name: 'Send Interactive Buttons', category: 'WhatsApp' },
  { id: 'make_voice_call', name: 'Make Voice Call (TTS)', category: 'Voice' },
  { id: 'send_sms', name: 'Send SMS', category: 'SMS' },
  { id: 'send_email', name: 'Send Email', category: 'Email' },
  { id: 'get_messages', name: 'Get Message History', category: 'Analytics' },
  { id: 'get_stats', name: 'Get Dashboard Stats', category: 'Analytics' },
  { id: 'schedule_message', name: 'Schedule Message', category: 'Advanced' },
  { id: 'list_scheduled_messages', name: 'List Scheduled Messages', category: 'Advanced' },
  { id: 'list_templates', name: 'List Templates', category: 'Templates' },
  { id: 'send_template', name: 'Send Template Message', category: 'Templates' },
];

const DEFAULT_CONFIG: AgentConfig = {
  enabled: true,
  modelId: 'amazon.nova-pro-v1:0',
  temperature: 0.7,
  maxTokens: 2048,
  sessionTimeout: 15,
  enabledTools: AVAILABLE_TOOLS.map(t => t.id),
  defaultChannel: 'whatsapp',
  autoSearch: true,
  conversationHistory: true,
};

/** The endpoint, kept local. src/api/client.ts does not export its own base. */
const AGENT_CONFIG_URL = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/ai/internal/config`;

export default function InternalAgentSettings ( { signOut, user }: PageProps ) {
  const [config, setConfig] = useState<AgentConfig>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  // apiCallResult, not a bare fetch: it attaches the Cognito bearer token and retries a 401
  // once with a refreshed one. The previous bare fetch sent no token, so this screen 401'd
  // on every load even for a signed-in operator - it could never have shown real config.
  const loadConfig = async () => {
    try {
      const result = await api.apiCallResult<{ config?: Partial<AgentConfig> }>( AGENT_CONFIG_URL );
      if ( result.ok ) {
        setConfig( { ...DEFAULT_CONFIG, ...( result.data?.config || {} ) } );
      } else {
        setMessage( `Could not load settings: ${result.failure.message}` );
      }
    } catch (error) {
      console.error('Failed to load config:', error);
      setMessage( 'Could not load settings.' );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  const saveConfig = async () => {
    setSaving(true);
    setMessage('');
    try {
      const result = await api.apiCallResult( AGENT_CONFIG_URL, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      } );

      if ( result.ok ) {
        setMessage('Settings saved successfully!');
        setTimeout(() => setMessage(''), 3000);
      } else {
        // The reason, not just "failed" - a 401 and a 503 need different responses from
        // whoever is looking at this screen.
        setMessage( `Failed to save settings: ${result.failure.message}` );
      }
    } catch (error) {
      setMessage('Error saving settings');
    } finally {
      setSaving(false);
    }
  };

  const toggleTool = (toolId: string) => {
    setConfig(prev => ({
      ...prev,
      enabledTools: prev.enabledTools.includes(toolId)
        ? prev.enabledTools.filter(id => id !== toolId)
        : [...prev.enabledTools, toolId]
    }));
  };

  const toggleCategory = (category: string) => {
    const categoryTools = AVAILABLE_TOOLS.filter(t => t.category === category).map(t => t.id);
    const allEnabled = categoryTools.every(id => config.enabledTools.includes(id));
    
    setConfig(prev => ({
      ...prev,
      enabledTools: allEnabled
        ? prev.enabledTools.filter(id => !categoryTools.includes(id))
        : [...new Set([...prev.enabledTools, ...categoryTools])]
    }));
  };

  const categories = [...new Set(AVAILABLE_TOOLS.map(t => t.category))];

  if (loading) {
    return (
      <Layout onSignOut={ signOut } user={ user }>
        <SEO title="Internal Agent Settings" description="Configure the internal AI assistant." />
        <div className="inner-page-container" style={ { padding: '24px 20px' } }>
          <p>Loading settings…</p>
        </div>
      </Layout>
    );
  }

  return (
    <Layout onSignOut={ signOut } user={ user }>
      <SEO title="Internal Agent Settings" description="Configure the internal AI assistant." />
      <div className="inner-page-container" style={ { maxWidth: 960, margin: '0 auto', padding: '24px 20px' } }>
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Internal Agent Settings</h1>
          <p className="text-gray-600 mt-1">Configure your AI-powered admin assistant</p>
        </div>

        {message && (
          <div className={`mb-4 p-4 rounded-lg ${message.includes('success') ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
            {message}
          </div>
        )}

        {/* General Settings */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">General Settings</h2>
          
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <label className="font-medium text-gray-700">Enable Internal Agent</label>
                <p className="text-sm text-gray-500">Turn AI assistant on/off</p>
              </div>
              <button
                onClick={() => setConfig(prev => ({ ...prev, enabled: !prev.enabled }))}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  config.enabled ? 'bg-green-600' : 'bg-gray-300'
                }`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  config.enabled ? 'translate-x-6' : 'translate-x-1'
                }`} />
              </button>
            </div>

            <div>
              {/* The caption is an UNASSOCIATED <label> - no `for`, no wrapped control - so it
                  was never a name source. It stays, and the control takes ariaLabel. The
                  utility classes that SKINNED the native box are dropped rather than
                  forwarded: className on a Select lands on the wrapper, so a border and a
                  focus ring there would paint the whole field. Only the full width survives. */}
              <label className="block font-medium text-gray-700 mb-2">AI Model</label>
              <Select
                ariaLabel="AI model"
                value={config.modelId}
                onChange={v => setConfig(prev => ({ ...prev, modelId: v }))}
                options={MODEL_OPTIONS}
                style={FULL_WIDTH}
              />
            </div>

            <div>
              <label className="block font-medium text-gray-700 mb-2">
                Temperature: {config.temperature}
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={config.temperature}
                onChange={(e) => setConfig(prev => ({ ...prev, temperature: parseFloat(e.target.value) }))}
                className="w-full"
              />
              <p className="text-sm text-gray-500 mt-1">Lower = more focused, Higher = more creative</p>
            </div>

            <div>
              <label className="block font-medium text-gray-700 mb-2">Max Tokens</label>
              <input
                type="number"
                value={config.maxTokens}
                onChange={(e) => setConfig(prev => ({ ...prev, maxTokens: parseInt(e.target.value) }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
                min="512"
                max="4096"
                step="256"
              />
              <p className="text-sm text-gray-500 mt-1">Maximum response length</p>
            </div>

            <div>
              <label className="block font-medium text-gray-700 mb-2">Session Timeout (minutes)</label>
              <input
                type="number"
                value={config.sessionTimeout}
                onChange={(e) => setConfig(prev => ({ ...prev, sessionTimeout: parseInt(e.target.value) }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
                min="5"
                max="60"
                step="5"
              />
              <p className="text-sm text-gray-500 mt-1">Reset conversation after idle time</p>
            </div>

            <div>
              <label className="block font-medium text-gray-700 mb-2">Default Channel</label>
              <Select
                ariaLabel="Default channel"
                value={config.defaultChannel}
                onChange={v => setConfig(prev => ({ ...prev, defaultChannel: v }))}
                options={DEFAULT_CHANNEL_OPTIONS}
                style={FULL_WIDTH}
              />
            </div>

            <div className="flex items-center justify-between">
              <div>
                <label className="font-medium text-gray-700">Auto-search Contacts</label>
                <p className="text-sm text-gray-500">Automatically search for contacts by name</p>
              </div>
              <button
                onClick={() => setConfig(prev => ({ ...prev, autoSearch: !prev.autoSearch }))}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  config.autoSearch ? 'bg-green-600' : 'bg-gray-300'
                }`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  config.autoSearch ? 'translate-x-6' : 'translate-x-1'
                }`} />
              </button>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <label className="font-medium text-gray-700">Conversation History</label>
                <p className="text-sm text-gray-500">Remember context across messages</p>
              </div>
              <button
                onClick={() => setConfig(prev => ({ ...prev, conversationHistory: !prev.conversationHistory }))}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  config.conversationHistory ? 'bg-green-600' : 'bg-gray-300'
                }`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  config.conversationHistory ? 'translate-x-6' : 'translate-x-1'
                }`} />
              </button>
            </div>
          </div>
        </div>

        {/* Tool Capabilities */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Tool Capabilities</h2>
          <p className="text-sm text-gray-600 mb-4">Enable or disable specific agent capabilities</p>

          <div className="space-y-6">
            {categories.map(category => {
              const categoryTools = AVAILABLE_TOOLS.filter(t => t.category === category);
              const allEnabled = categoryTools.every(t => config.enabledTools.includes(t.id));
              const someEnabled = categoryTools.some(t => config.enabledTools.includes(t.id));

              return (
                <div key={category} className="border-b border-gray-200 pb-4 last:border-0">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-medium text-gray-900">{category}</h3>
                    <button
                      onClick={() => toggleCategory(category)}
                      className={`px-3 py-1 rounded text-sm font-medium ${
                        allEnabled
                          ? 'bg-green-100 text-green-700'
                          : someEnabled
                          ? 'bg-yellow-100 text-yellow-700'
                          : 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {allEnabled ? 'All Enabled' : someEnabled ? 'Partial' : 'All Disabled'}
                    </button>
                  </div>
                  
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {categoryTools.map(tool => (
                      <label key={tool.id} className="flex items-center space-x-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={config.enabledTools.includes(tool.id)}
                          onChange={() => toggleTool(tool.id)}
                          className="w-4 h-4 text-green-600 border-gray-300 rounded focus:ring-green-500"
                        />
                        <span className="text-sm text-gray-700">{tool.name}</span>
                      </label>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Usage Stats */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Usage Statistics</h2>
          <div className="grid grid-cols-3 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">-</div>
              <div className="text-sm text-gray-600">Total Queries</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">-</div>
              <div className="text-sm text-gray-600">Tools Used</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-600">-</div>
              <div className="text-sm text-gray-600">Avg Response Time</div>
            </div>
          </div>
        </div>

        {/* Save Button */}
        <div className="flex justify-end space-x-3">
          <button
            onClick={loadConfig}
            className="px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
          >
            Reset
          </button>
          <button
            onClick={saveConfig}
            disabled={saving}
            className="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>
    </Layout>
  );
}
