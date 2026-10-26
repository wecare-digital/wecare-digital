/**
 * WhatsApp Phone Migration Page
 * Migrate phone numbers between WABAs using Meta Graph API
 * OTP request/verify, register, migrate — all via Direct API
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import Button from '../../../components/ui/Button';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import Select, { type SelectOption } from '../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const OTP_METHOD_OPTIONS: SelectOption[] = [
  { value: 'SMS', label: 'SMS' },
  { value: 'VOICE', label: 'Voice Call' },
];

const MigrationPage: React.FC<PageProps> = ({ signOut, user, embedded }) => {
  const toast = useToastContext();
  const [wabas, setWabas] = useState<api.WABAAccount[]>([]);
  const [loading, setLoading] = useState(true);

  // Form state
  const [phoneId, setPhoneId] = useState('');
  const [phoneDisplay, setPhoneDisplay] = useState('');
  const [sourceWaba, setSourceWaba] = useState('');
  const [targetWaba, setTargetWaba] = useState('');
  const [otpMethod, setOtpMethod] = useState<'SMS' | 'VOICE'>('SMS');
  const [otpCode, setOtpCode] = useState('');
  const [pin, setPin] = useState('');
  const [processing, setProcessing] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);

  const addLog = (msg: string) => setLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);

  const loadWabas = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listWABAs();
      setWabas(data);
      if (data.length > 0) {
        // Load details for first WABA to get phone numbers
        for (const w of data) {
          const detail = await api.getWABADetails(w.id);
          if (detail?.phoneNumbers?.length) {
            setWabas(prev => prev.map(p => p.id === w.id ? { ...p, phoneNumbers: detail.phoneNumbers } : p));
          }
        }
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadWabas(); }, [loadWabas]);

  const handleRequestOTP = async () => {
    if (!phoneId) { toast.error('Enter phone number ID'); return; }
    setProcessing(true);
    addLog(`Requesting OTP via ${otpMethod} for ${phoneDisplay || phoneId}...`);
    try {
      const ok = await api.requestPhoneOTP(phoneId, otpMethod);
      if (ok) { addLog('OTP sent'); toast.success(`Code sent via ${otpMethod}`); }
      else { addLog('Failed to send OTP'); toast.error('Failed'); }
    } catch (err: any) { addLog(`Error: ${err.message || 'Unknown'}`); toast.error('Failed'); }
    setProcessing(false);
  };

  const handleVerifyOTP = async () => {
    if (!otpCode) { toast.error('Enter code'); return; }
    setProcessing(true);
    addLog(`Verifying code: ${otpCode}...`);
    try {
      const ok = await api.verifyPhoneOTP(phoneId, otpCode);
      if (ok) { addLog('Verified'); toast.success('Phone verified'); }
      else { addLog('Invalid code'); toast.error('Invalid code'); }
    } catch (err: any) { addLog(`Error: ${err.message || 'Unknown'}`); toast.error('Failed'); }
    setProcessing(false);
  };

  const handleSetTwoStepPin = async () => {
    if (!phoneId) { toast.error('Enter phone number ID'); return; }
    if (!/^\d{6}$/.test(pin)) { toast.error('Two-step PIN must be exactly 6 digits'); return; }
    setProcessing(true);
    addLog(`Setting two-step verification for ${phoneDisplay || phoneId}...`);
    try {
      const ok = await api.setPhoneTwoStepPin(phoneId, pin);
      if (ok) { addLog('Two-step verification PIN updated'); toast.success('Two-step verification updated'); }
      else { addLog('Failed to update two-step verification'); toast.error('Update failed'); }
    } catch (err: any) { addLog(`Error: ${err.message || 'Unknown'}`); toast.error('Update failed'); }
    setProcessing(false);
  };

  const handleRegister = async () => {
    setProcessing(true);
    addLog(`Registering ${phoneDisplay || phoneId}...`);
    try {
      const ok = await api.registerPhone(phoneId, pin || undefined);
      if (ok) { addLog('Registered'); toast.success('Phone registered'); }
      else { addLog('Failed'); toast.error('Registration failed'); }
    } catch (err: any) { addLog(`Error: ${err.message || 'Unknown'}`); toast.error('Failed'); }
    setProcessing(false);
  };

  const handleMigrate = async () => {
    if (!targetWaba) { toast.error('Enter target WABA ID'); return; }
    setProcessing(true);
    addLog(`Migrating ${phoneDisplay || phoneId} to ${targetWaba}...`);
    try {
      const result = await api.migratePhone({
        phoneNumberId: phoneId, sourceWabaId: sourceWaba, targetWabaId: targetWaba,
        pin: pin || undefined,
      });
      if (result?.success) { addLog('Migration initiated'); toast.success('Migration started'); }
      else { addLog('Failed'); toast.error('Migration failed'); }
    } catch (err: any) { addLog(`Error: ${err.message || 'Unknown'}`); toast.error('Failed'); }
    setProcessing(false);
  };

  const content = (
    <div className="inner-page-container">

      {/* Webhook Info Banner */}
      <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 'var(--text-md)', fontWeight: 600, color: '#166534', marginBottom: 8 }}>Webhook Configuration (Messages + Calling)</div>
        <div style={{ fontSize: 'var(--text-sm)', color: '#15803d', lineHeight: 1.6 }}>
          <div>Set this in <a href="https://developers.facebook.com/apps/2238810740192680/whatsapp-business/wa-settings/" target="_blank" rel="noopener noreferrer" style={{ color: '#166534', textDecoration: 'underline' }}>Meta App Dashboard → WhatsApp Settings</a>:</div>
          <div style={{ background: '#fff', border: '1px solid #d1fae5', borderRadius: 6, padding: '8px 12px', marginTop: 8, fontFamily: 'monospace', fontSize: 'var(--text-xs)' }}>
            <div>Callback URL: <span style={{ userSelect: 'all' }}>https://wecare.digital/api/whatsapp</span></div>
            <div>Verify Token: <span style={{ userSelect: 'all' }}>stored in Secrets Manager: wecare/meta-system-user-token:waba_t_verify_token</span></div>
          </div>
          <div style={{ marginTop: 6, fontSize: 'var(--text-xs)', color: '#4ade80' }}>This single endpoint handles both messages and calling. The handler routes messages to the inbound processor and calls to the calling processor.</div>
        </div>
      </div>

      {/* WABA Overview */}
      <div style={{ background: '#fff', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 'var(--text-md)', fontWeight: 600, marginBottom: 12 }}>Linked WABAs</div>
        {loading ? <div style={{ color: '#9ca3af', fontSize: 'var(--text-sm)' }}>Loading...</div> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {wabas.map(w => (
              <div key={w.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'var(--bg-secondary)', borderRadius: 6, fontSize: 'var(--text-sm)' }}>
                <div>
                  <span style={{ fontWeight: 500 }}>{w.wabaName || w.wabaId}</span>
                  <span style={{ color: '#9ca3af', marginLeft: 8, fontSize: 'var(--text-xs)' }}>{w.id}</span>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 'var(--text-xs)', color: w.enableSending ? '#16a34a' : '#dc2626' }}>{w.enableSending ? 'Send ON' : 'Send OFF'}</span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{w.phoneNumbers?.length || 0} phones</span>
                </div>
              </div>
            ))}
            {wabas.length === 0 && <div style={{ color: '#9ca3af', fontSize: 'var(--text-sm)' }}>No linked WABAs found</div>}
            <div style={{ padding: '8px 12px', background: '#eff6ff', borderRadius: 6, fontSize: 'var(--text-sm)' }}>
              <span style={{ fontWeight: 500 }}>WABA1 (Direct API)</span>
              <span style={{ color: 'var(--text-muted)', marginLeft: 8, fontSize: 'var(--text-xs)' }}>2094615664435155</span>
              <span style={{ marginLeft: 8, fontSize: 'var(--text-xs)', color: '#16a34a' }}>+91 93309 94400 — GREEN</span>
            </div>
          </div>
        )}
      </div>

      {/* Migration Actions */}
      <div style={{ background: '#fff', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 'var(--text-md)', fontWeight: 600, marginBottom: 12 }}>Phone Migration (Meta Graph API)</div>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 16 }}>Migrate phone numbers between WABAs using Meta Graph API directly.</div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', fontWeight: 500, display: 'block', marginBottom: 4 }}>Phone Number ID</label>
            <input value={phoneId} onChange={e => setPhoneId(e.target.value)} placeholder="e.g. 1016149501586345 or phone-number-id-..." style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 'var(--text-sm)' }} />
          </div>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', fontWeight: 500, display: 'block', marginBottom: 4 }}>Display Name (optional)</label>
            <input value={phoneDisplay} onChange={e => setPhoneDisplay(e.target.value)} placeholder="+91 93309 94400" style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 'var(--text-sm)' }} />
          </div>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', fontWeight: 500, display: 'block', marginBottom: 4 }}>Source WABA ID</label>
            <input value={sourceWaba} onChange={e => setSourceWaba(e.target.value)} placeholder="e.g. 2094615664435155" style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 'var(--text-sm)' }} />
          </div>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', fontWeight: 500, display: 'block', marginBottom: 4 }}>Target WABA ID</label>
            <input value={targetWaba} onChange={e => setTargetWaba(e.target.value)} placeholder="e.g. 2094615664435155" style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 'var(--text-sm)' }} />
          </div>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', fontWeight: 500, display: 'block', marginBottom: 4 }}>Two-step verification PIN (6 digits)</label>
            <input value={pin} onChange={e => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="new-password" placeholder="123456" maxLength={6} style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 'var(--text-sm)' }} />
          </div>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', fontWeight: 500, display: 'block', marginBottom: 4 }}>OTP Method</label>
            <Select ariaLabel="OTP Method" value={otpMethod} onChange={v => setOtpMethod(v as 'SMS' | 'VOICE')}
              options={OTP_METHOD_OPTIONS} />
          </div>
        </div>

        {/* Action Buttons */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
          <button onClick={handleRequestOTP} disabled={processing || !phoneId} style={{ padding: '8px 16px', background: 'var(--accent)', color: 'var(--lime)', border: 'none', borderRadius: 8, fontSize: 'var(--text-sm)', cursor: 'pointer', opacity: processing ? 0.5 : 1 }}>
            {processing ? '...' : '1. Request OTP'}
          </button>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <input value={otpCode} onChange={e => setOtpCode(e.target.value)} placeholder="Enter code" maxLength={6} style={{ width: 100, padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 'var(--text-sm)' }} />
            <button onClick={handleVerifyOTP} disabled={processing || !otpCode} style={{ padding: '8px 16px', background: 'var(--accent)', color: 'var(--lime)', border: 'none', borderRadius: 8, fontSize: 'var(--text-sm)', cursor: 'pointer', opacity: processing ? 0.5 : 1 }}>
              2. Verify
            </button>
          </div>
          <button onClick={handleSetTwoStepPin} disabled={processing || !phoneId || !/^\d{6}$/.test(pin)} style={{ padding: '8px 16px', background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 8, fontSize: 'var(--text-sm)', cursor: 'pointer', opacity: processing ? 0.5 : 1 }}>
            Set / Change Two-step PIN
          </button>
          <button onClick={handleRegister} disabled={processing || !phoneId} style={{ padding: '8px 16px', background: '#374151', color: '#fff', border: 'none', borderRadius: 8, fontSize: 'var(--text-sm)', cursor: 'pointer', opacity: processing ? 0.5 : 1 }}>
            3. Register
          </button>
          <button onClick={handleMigrate} disabled={processing || !phoneId || !targetWaba} style={{ padding: '8px 16px', background: '#dc2626', color: '#fff', border: 'none', borderRadius: 8, fontSize: 'var(--text-sm)', cursor: 'pointer', opacity: processing ? 0.5 : 1 }}>
            4. Migrate
          </button>
        </div>

        {/* Quick Presets */}
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 8 }}>Quick presets:</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
          <button onClick={() => { setPhoneId('1016149501586345'); setPhoneDisplay('+91 93309 94400'); setSourceWaba('2094615664435155'); }} style={{ padding: '4px 10px', background: '#f3f4f6', border: '1px solid var(--border)', borderRadius: 6, fontSize: 'var(--text-xs)', cursor: 'pointer' }}>
            WABA1 +919330994400
          </button>
          <button onClick={() => { setPhoneId('1055232054343117'); setPhoneDisplay('+91 99033 00044'); setSourceWaba('2513394156072604'); }} style={{ padding: '4px 10px', background: '#f3f4f6', border: '1px solid var(--border)', borderRadius: 6, fontSize: 'var(--text-xs)', cursor: 'pointer' }}>
            WABA-T +919903300044
          </button>
        </div>
      </div>

      {/* Migration Log */}
      {logs.length > 0 && (
        <div style={{ background: '#000', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: '#9ca3af' }}>Migration Log</span>
            <button onClick={() => setLogs([])} style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer' }}>Clear</button>
          </div>
          <div style={{ fontFamily: 'monospace', fontSize: 'var(--text-xs)', color: 'var(--lime)', maxHeight: 200, overflowY: 'auto' }}>
            {logs.map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </div>
      )}

      {/* How it works */}
      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 8 }}>How Migration Works</div>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.7 }}>
          <p style={{ margin: '0 0 8px' }}>To migrate a phone number between WABAs:</p>
          <ol style={{ margin: 0, paddingLeft: 20 }}>
            <li>Request OTP — sends a verification code to the phone via SMS or voice call</li>
            <li>Verify OTP — enter the code to prove ownership</li>
            <li>Set / Change Two-step PIN — securely configure the 6-digit Meta PIN when required</li>
            <li>Register — register the phone; a PIN may be supplied for Meta registration but is never stored</li>
            <li>Migrate — move the phone from source WABA to target WABA</li>
          </ol>
          <p style={{ margin: '8px 0 0', fontSize: 'var(--text-xs)', color: '#9ca3af' }}>
            This uses Meta Graph API directly.
            The phone will be deregistered from the source WABA and registered on the target.
          </p>
        </div>
      </div>

      <style jsx>{`
        input:focus, select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px rgba(26,58,42,0.1); }
        button:hover:not(:disabled) { opacity: 0.9; }
        @media (max-width: 640px) {
          div[style*="grid-template-columns"] { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );

  if (embedded) return content;
  return <Layout user={user} onSignOut={signOut}>{content}</Layout>;
};

export default MigrationPage;
