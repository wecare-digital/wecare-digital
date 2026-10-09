/**
 * WhatsApp Welcome Message Configuration
 */

import React, { useState, useEffect } from 'react';
import Layout from '../../../../components/Layout';
import Button from '../../../../components/ui/Button';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';
import { WHATSAPP_PHONES } from '../../../../config/constants';

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

interface WelcomeConfig {
  enabled: boolean;
  textMessage: string;
  welcomeBackMessage: string;
  delaySeconds: number;
  phoneNumberId: string;
}

const defaultConfig: WelcomeConfig = {
  enabled: false,
  textMessage: "Hi there! ?? Welcome to WECARE.DIGITAL\n\nShop, pay, track requests, or get support - all right here.\n\n?? _You're chatting with an AI assistant. Responses may not always be accurate. Please verify important details independently._\n\nTap Menu to get started ??",
  welcomeBackMessage: "Welcome back! ?? What can we help with today? ??",
  delaySeconds: 2,
  phoneNumberId: WHATSAPP_PHONES.primary.id,
};

const WelcomeConfigPage: React.FC<PageProps> = ({ signOut, user, embedded = false }) => {
  const [configs, setConfigs] = useState<Record<string, WelcomeConfig>>({
    [WHATSAPP_PHONES.primary.id]: { ...defaultConfig, phoneNumberId: WHATSAPP_PHONES.primary.id },
    [WHATSAPP_PHONES.secondary.id]: { ...defaultConfig, phoneNumberId: WHATSAPP_PHONES.secondary.id },
  });
  const [activePhone, setActivePhone] = useState(WHATSAPP_PHONES.primary.id);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const toast = useToastContext();

  const config = configs[activePhone];
  const setConfig = (c: WelcomeConfig) => setConfigs({ ...configs, [activePhone]: c });

  const loadConfig = async () => {
    setLoading(true);
    try {
      const [data1, data2] = await Promise.all([
        api.getSystemConfig('welcome_message'),
        api.getSystemConfig('welcome_message_2'),
      ]);
      const newConfigs = { ...configs };
      if (data1) newConfigs[WHATSAPP_PHONES.primary.id] = { ...defaultConfig, ...data1, phoneNumberId: WHATSAPP_PHONES.primary.id };
      if (data2) newConfigs[WHATSAPP_PHONES.secondary.id] = { ...defaultConfig, ...data2, phoneNumberId: WHATSAPP_PHONES.secondary.id };
      setConfigs(newConfigs);
    } catch (err) {
      console.error('Failed to load welcome config:', err);
      toast.error('Failed to load welcome config');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadConfig(); }, []);

  const saveConfig = async () => {
    setSaving(true);
    try {
      const key = activePhone === WHATSAPP_PHONES.primary.id ? 'welcome_message' : 'welcome_message_2';
      if (!(await api.updateSystemConfig(key, config))) {
        throw new Error('Save could not be confirmed. Refresh before trying again.');
      }
      toast.success('Configuration saved!');
    } catch (err: any) {
      toast.error(err.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    const loadingContent = <div style={{ padding: 20, textAlign: 'center' }}>Loading...</div>;
    if (embedded) return loadingContent;
    return (
      <Layout user={user} onSignOut={signOut}>
        {loadingContent}
      </Layout>
    );
  }

  const content = (
    <div className="inner-page-container" style={{ background: '#fff' }}>
      {!embedded && (
        <>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>Welcome Message</h1>
          <p style={{ color: '#666', marginBottom: 24 }}>Configure the welcome messages sent to new and returning WhatsApp users</p>
        </>
      )}

      <div style={{ background: '#fff', borderRadius: 12, padding: 24, boxShadow: embedded ? 'none' : '0 1px 3px rgba(0,0,0,0.08)' }}>
        {/* Info banner */}
        <div style={{ marginBottom: 24, padding: '12px 16px', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 13, color: '#0f2a1d' }}>
          When enabled, these messages override the default bot welcome. Disable to use the Lambda default welcome text.
        </div>

        {/* WABA Tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
          <button
            onClick={() => setActivePhone(WHATSAPP_PHONES.primary.id)}
            style={{
              flex: 1, padding: '12px 16px', border: '2px solid', borderRadius: 8, cursor: 'pointer',
              borderColor: activePhone === WHATSAPP_PHONES.primary.id ? '#1a3a2a' : '#e5e7eb',
              background: activePhone === WHATSAPP_PHONES.primary.id ? '#f9fafb' : '#fff',
              fontWeight: activePhone === WHATSAPP_PHONES.primary.id ? 600 : 400,
            }}
          >
            <div style={{ fontSize: 14 }}>{WHATSAPP_PHONES.primary.name}</div>
            <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>{WHATSAPP_PHONES.primary.display}</div>
          </button>
          <button
            onClick={() => setActivePhone(WHATSAPP_PHONES.secondary.id)}
            style={{
              flex: 1, padding: '12px 16px', border: '2px solid', borderRadius: 8, cursor: 'pointer',
              borderColor: activePhone === WHATSAPP_PHONES.secondary.id ? '#1a3a2a' : '#e5e7eb',
              background: activePhone === WHATSAPP_PHONES.secondary.id ? '#f9fafb' : '#fff',
              fontWeight: activePhone === WHATSAPP_PHONES.secondary.id ? 600 : 400,
            }}
          >
            <div style={{ fontSize: 14 }}>{WHATSAPP_PHONES.secondary.name}</div>
            <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>{WHATSAPP_PHONES.secondary.display}</div>
          </button>
        </div>

        <div style={{ marginBottom: 24 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
              style={{ width: 18, height: 18 }}
            />
            <span>Enable Welcome Message Override</span>
          </label>
        </div>

        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 14, marginBottom: 8 }}>New User Welcome</h3>
          <p style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>Sent when a user messages for the first time (no conversation history)</p>
          <textarea
            value={config.textMessage}
            onChange={(e) => setConfig({ ...config, textMessage: e.target.value })}
            placeholder="Enter your welcome message for new users..."
            rows={5}
            style={{ width: '100%', padding: 10, border: '1px solid #000', borderRadius: 13, resize: 'vertical', boxSizing: 'border-box' }}
          />
        </div>

        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 14, marginBottom: 8 }}>Returning User Welcome</h3>
          <p style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>Sent when a returning user starts a new session (has language preference but no recent messages)</p>
          <textarea
            value={config.welcomeBackMessage}
            onChange={(e) => setConfig({ ...config, welcomeBackMessage: e.target.value })}
            placeholder="Enter your welcome back message..."
            rows={3}
            style={{ width: '100%', padding: 10, border: '1px solid #000', borderRadius: 13, resize: 'vertical', boxSizing: 'border-box' }}
          />
        </div>

        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 14, marginBottom: 12 }}>Delay</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="number"
              value={config.delaySeconds}
              onChange={(e) => setConfig({ ...config, delaySeconds: parseInt(e.target.value) || 0 })}
              min={0}
              max={30}
              style={{ width: 80, padding: 10, border: '1px solid #000', borderRadius: 13 }}
            />
            <span style={{ color: '#666' }}>seconds before sending</span>
          </div>
        </div>

        <Button variant="primary" onClick={saveConfig} disabled={saving} loading={saving} className="welcome-save-btn">
          {saving ? 'Saving...' : 'Save Configuration'}
        </Button>
      </div>
    </div>
  );

  if (embedded) {
    return content;
  }

  return (
    <Layout user={user} onSignOut={signOut}>
      {content}
    </Layout>
  );
};

export default WelcomeConfigPage;
