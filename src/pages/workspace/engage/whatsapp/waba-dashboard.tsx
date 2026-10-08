/**
 * WABA Dashboard
 * Shows WhatsApp Business Account details, phone quality, messaging limits, and system events
 * 
 * APIs Used:
 * - GetLinkedWhatsAppBusinessAccount
 * - GetLinkedWhatsAppBusinessAccountPhoneNumber
 * - ListLinkedWhatsAppBusinessAccounts
 * - System events from webhook handler
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import { SkeletonCard } from '../../../../components/Skeleton';
import { useToastContext } from '../../../../contexts/ToastContext';
import Tabs, { TabItem } from '../../../../components/ui/Tabs';
import Button from '../../../../components/ui/Button';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import * as api from '../../../../api/client';

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

const QUALITY_COLORS: Record<string, string> = {
  GREEN: '#000',
  YELLOW: '#4a4a4a',
  RED: '#1a3a2a',
  UNKNOWN: '#6b6b6b',
};

const QUALITY_LABELS: Record<string, string> = {
  GREEN: 'High Quality',
  YELLOW: 'Medium Quality',
  RED: 'Low Quality',
  UNKNOWN: 'Unknown',
};

/** The 300px the dead `.waba-selector-section select` rule carried; the box is drawn by CSS now. */
const WABA_SELECT_STYLE: React.CSSProperties = { minWidth: 300 };

const WABADashboard: React.FC<PageProps> = ({ signOut, user, embedded = false }) => {
  const router = useRouter();
  const toast = useToastContext();
  const [loading, setLoading] = useState(true);
  const [wabas, setWabas] = useState<api.WABAAccount[]>([]);
  const [selectedWaba, setSelectedWaba] = useState<api.WABAAccount | null>(null);
  const [systemEvents, setSystemEvents] = useState<api.WABASystemEvents>({
    templateStatus: [],
    phoneQuality: [],
    accountUpdates: [],
  });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'events' | 'sns'>('overview');

  const tabItems: TabItem[] = [
    { id: 'overview', label: 'Phone Numbers' },
    { id: 'events', label: 'System Events' },
    { id: 'sns', label: 'SNS Subscription' },
  ];

  /* Derived from FETCHED data, so it is memoised on the array it comes from rather than
     rebuilt inline - an inline literal would hand Select a new array on every render. */
  const wabaOptions: SelectOption[] = useMemo(
    () => wabas.map((waba) => ({ value: waba.id, label: waba.wabaName || waba.wabaId })),
    [wabas]
  );

  // SNS subscription state
  const [snsStatus, setSnsStatus] = useState<api.WABASNSSubscriptionStatus | null>(null);
  const [snsLoading, setSnsLoading] = useState(false);
  const [customTopicArn, setCustomTopicArn] = useState('');
  const [customRoleArn, setCustomRoleArn] = useState('');

  const loadSnsStatus = async (wabaId?: string) => {
    const id = wabaId || selectedWaba?.id;
    if (!id) return;
    setSnsLoading(true);
    try {
      const status = await api.getWABASNSSubscriptionStatus(id);
      setSnsStatus(status);
      if (status?.defaultTopicArn && !customTopicArn) {
        setCustomTopicArn(status.defaultTopicArn);
      }
    } catch (err) {
      console.error('Failed to load SNS status:', err);
    } finally {
      setSnsLoading(false);
    }
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [wabasData, eventsData] = await Promise.all([
        api.listWABAs(),
        api.getWABASystemEvents(),
      ]);

      setWabas(wabasData);
      setSystemEvents(eventsData);

      if (wabasData.length > 0 && !selectedWaba) {
        const details = await api.getWABADetails(wabasData[0].id);
        if (details) {
          setSelectedWaba(details);
          // Load SNS status for the first WABA
          loadSnsStatus(wabasData[0].id);
        }
      }
      if (wabasData.length === 0) {
        setLoadError('No WABA accounts found. Check your Meta Business Manager configuration.');
      }
    } catch (err) {
      console.error('Failed to load WABA data:', err);
      setLoadError('Failed to load WABA data. Check API connection and permissions.');
      toast.error('Failed to load WABA data');
    } finally {
      setLoading(false);
    }
  }, [selectedWaba]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  const handleSelectWaba = async (wabaId: string) => {
    try {
      const details = await api.getWABADetails(wabaId);
      if (details) {
        setSelectedWaba(details);
        // Also load SNS status for the selected WABA
        loadSnsStatus(wabaId);
      }
    } catch (err) {
      toast.error('Failed to load WABA details');
    }
  };

  const handleSubscribeSNS = async () => {
    if (!selectedWaba) return;
    setSnsLoading(true);
    try {
      const topicArn = customTopicArn || undefined;
      const roleArn = customRoleArn || undefined;
      const success = await api.subscribeWABAToSNS(selectedWaba.id, topicArn, roleArn);
      if (success) {
        toast.success(`WABA ${selectedWaba.wabaName || selectedWaba.wabaId} subscribed to SNS`);
        await loadSnsStatus();
      } else {
        toast.error('Failed to subscribe WABA to SNS');
      }
    } catch (err) {
      toast.error('Failed to subscribe WABA to SNS');
    } finally {
      setSnsLoading(false);
    }
  };

  const handleUnsubscribeSNS = async () => {
    if (!selectedWaba) return;
    setSnsLoading(true);
    try {
      const success = await api.unsubscribeWABAFromSNS(selectedWaba.id);
      if (success) {
        toast.success(`WABA ${selectedWaba.wabaName || selectedWaba.wabaId} unsubscribed from SNS`);
        await loadSnsStatus();
      } else {
        toast.error('Failed to unsubscribe WABA from SNS');
      }
    } catch (err) {
      toast.error('Failed to unsubscribe WABA from SNS');
    } finally {
      setSnsLoading(false);
    }
  };

  const formatTimestamp = (ts: number) => {
    return new Date(ts * 1000).toLocaleString();
  };

  const getEventIcon = (eventType: string) => {
    switch (eventType) {
      case 'APPROVED': return 'OK';
      case 'REJECTED': return 'X';
      case 'PENDING': return '...';
      case 'PAUSED': return '||';
      case 'DISABLED': return 'OFF';
      case 'FLAGGED': return '!';
      case 'UNFLAGGED': return 'OK';
      default: return '-';
    }
  };

  const dashboardContent = (
    <>
      <div className={`page waba-dashboard ${embedded ? 'embedded' : ''}`}>
        {!embedded && (
          <PageHeader 
            title="WA Board" 
            subtitle="WhatsApp Business Account details, phone quality, and system events"
            icon="whatsapp"
            backLink="/workspace/engage/whatsapp"
            backLabel="Back"
            actions={
              <Button variant="secondary" icon="refresh" onClick={loadData} disabled={loading} loading={loading}>Refresh</Button>
          }
        />
        )}

        {loading && wabas.length === 0 ? (
          <div className="loading-state">Loading WABA data...</div>
        ) : loadError && wabas.length === 0 ? (
          <div className="loading-state">
            <p style={{ color: '#1a3a2a', marginBottom: 8 }}>{loadError}</p>
            <button onClick={loadData} style={{ padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 6, cursor: 'pointer' }}>Retry</button>
          </div>
        ) : (
          <div className="dashboard-content">
            {/* WABA Selector */}
            <div className="waba-selector-section">
              <label>Select WABA:</label>
              <Select
                ariaLabel="Select WABA"
                value={selectedWaba?.id || ''}
                onChange={(v) => handleSelectWaba(v)}
                options={wabaOptions}
                style={WABA_SELECT_STYLE}
              />
            </div>

            {/* Tabs */}
            <Tabs 
              items={tabItems} 
              activeTab={activeTab} 
              onChange={(id) => setActiveTab(id as 'overview' | 'events')} 
            />

            {/* Overview Tab */}
            {activeTab === 'overview' && selectedWaba && (
              <div className="overview-section">
                {/* WABA Info Card */}
                <div className="info-card">
                  <h3>Account Information</h3>
                  <div className="info-grid">
                    <div className="info-item">
                      <span className="label">WABA Name</span>
                      <span className="value">{selectedWaba.wabaName || 'N/A'}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">WABA ID</span>
                      <span className="value code">{selectedWaba.wabaId}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">Status</span>
                      <span className={`value status ${selectedWaba.registrationStatus?.toLowerCase()}`}>
                        {selectedWaba.registrationStatus || 'Unknown'}
                      </span>
                    </div>
                    <div className="info-item">
                      <span className="label">Sending</span>
                      <span className={`value ${selectedWaba.enableSending ? 'enabled' : 'disabled'}`}>
                        {selectedWaba.enableSending ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                    <div className="info-item">
                      <span className="label">Receiving</span>
                      <span className={`value ${selectedWaba.enableReceiving ? 'enabled' : 'disabled'}`}>
                        {selectedWaba.enableReceiving ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Phone Numbers */}
                <div className="phone-numbers-section">
                  <h3>Phone Numbers ({selectedWaba.phoneNumbers?.length || 0})</h3>
                  <div className="phone-cards">
                    {selectedWaba.phoneNumbers?.map((phone) => (
                      <div key={phone.phoneNumberId} className="phone-card">
                        <div className="phone-header">
                          <span className="phone-name">{phone.displayPhoneNumberName || 'Phone'}</span>
                          <span
                            className="quality-badge"
                            style={{ backgroundColor: QUALITY_COLORS[phone.qualityRating] }}
                          >
                            {QUALITY_LABELS[phone.qualityRating]}
                          </span>
                        </div>
                        <div className="phone-number">{phone.displayPhoneNumber || phone.phoneNumber}</div>
                        <div className="phone-details">
                          <div className="detail">
                            <span className="label">Phone ID</span>
                            <span className="value code">{phone.phoneNumberId}</span>
                          </div>
                          <div className="detail">
                            <span className="label">Meta ID</span>
                            <span className="value code">{phone.metaPhoneNumberId || 'N/A'}</span>
                          </div>
                          <div className="detail">
                            <span className="label">Region</span>
                            <span className="value">{phone.dataLocalizationRegion || 'Default'}</span>
                          </div>
                        </div>
                        <div className="quality-indicator">
                          <div
                            className="quality-bar"
                            style={{
                              width: phone.qualityRating === 'GREEN' ? '100%' :
                                     phone.qualityRating === 'YELLOW' ? '60%' :
                                     phone.qualityRating === 'RED' ? '30%' : '0%',
                              backgroundColor: QUALITY_COLORS[phone.qualityRating],
                            }}
                          />
                        </div>
                      </div>
                    ))}
                    {(!selectedWaba.phoneNumbers || selectedWaba.phoneNumbers.length === 0) && (
                      <div className="empty-state">No phone numbers found</div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Events Tab */}
            {activeTab === 'events' && (
              <div className="events-section">
                {/* Template Status Events */}
                <div className="events-card">
                  <h3>Template Status Updates</h3>
                  <div className="events-list">
                    {systemEvents.templateStatus.length > 0 ? (
                      systemEvents.templateStatus.map((event, idx) => (
                        <div key={idx} className="event-item">
                          <span className="event-icon">{getEventIcon(event.data?.event)}</span>
                          <div className="event-content">
                            <div className="event-title">
                              {event.data?.templateName || 'Template'} - {event.data?.event}
                            </div>
                            <div className="event-details">
                              Language: {event.data?.templateLanguage || 'N/A'}
                              {event.data?.reason && event.data.reason !== 'NONE' && (
                                <span className="event-reason"> • Reason: {event.data.reason}</span>
                              )}
                            </div>
                            <div className="event-time">{formatTimestamp(event.timestamp)}</div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="empty-state">No template status events</div>
                    )}
                  </div>
                </div>

                {/* Phone Quality Events */}
                <div className="events-card">
                  <h3>Phone Quality Updates</h3>
                  <div className="events-list">
                    {systemEvents.phoneQuality.length > 0 ? (
                      systemEvents.phoneQuality.map((event, idx) => (
                        <div key={idx} className="event-item">
                          <span
                            className="event-icon quality-dot"
                            style={{ backgroundColor: QUALITY_COLORS[event.data?.qualityScore] }}
                          />
                          <div className="event-content">
                            <div className="event-title">
                              {event.data?.displayPhone || 'Phone'} - Quality: {event.data?.qualityScore}
                            </div>
                            <div className="event-details">
                              {event.data?.event && <span>Event: {event.data.event}</span>}
                              {event.data?.currentLimit && (
                                <span> • Limit: {event.data.currentLimit}</span>
                              )}
                            </div>
                            <div className="event-time">{formatTimestamp(event.timestamp)}</div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="empty-state">No phone quality events</div>
                    )}
                  </div>
                </div>

                {/* Account Updates */}
                <div className="events-card">
                  <h3>Account Updates</h3>
                  <div className="events-list">
                    {systemEvents.accountUpdates.length > 0 ? (
                      systemEvents.accountUpdates.map((event, idx) => (
                        <div key={idx} className="event-item">
                          <span className="event-icon">-</span>
                          <div className="event-content">
                            <div className="event-title">
                              {event.data?.event || 'Account Update'}
                            </div>
                            <div className="event-details">
                              {event.data?.phoneNumber && <span>Phone: {event.data.phoneNumber}</span>}
                              {event.data?.currentLimit && (
                                <span> • New Limit: {event.data.currentLimit}</span>
                              )}
                              {event.data?.restrictionType && (
                                <span className="restriction"> • Restriction: {event.data.restrictionType}</span>
                              )}
                            </div>
                            <div className="event-time">{formatTimestamp(event.timestamp)}</div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="empty-state">No account updates</div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* SNS Subscription Tab */}
            {activeTab === 'sns' && selectedWaba && (
              <div className="sns-section">
                {/* Current Status */}
                <div className="info-card">
                  <h3>SNS Event Subscription</h3>
                  <p style={{ fontSize: 13, color: '#666', margin: '0 0 16px' }}>
                    Subscribe this WABA to an SNS topic to receive WhatsApp events (message status, template updates, phone quality changes).
                    AWS will publish events to the configured SNS topic.
                  </p>

                  {snsLoading && !snsStatus ? (
                    <div className="empty-state">Loading subscription status...</div>
                  ) : (
                    <>
                      {/* Status indicator */}
                      <div className="sns-status-row">
                        <span className="label">Status</span>
                        <span className={`sns-badge ${snsStatus?.isSubscribed ? 'active' : 'inactive'}`}>
                          {snsStatus?.isSubscribed ? 'Subscribed' : 'Not Subscribed'}
                        </span>
                      </div>

                      {/* Live event destinations */}
                      {snsStatus?.liveEventDestinations && snsStatus.liveEventDestinations.length > 0 && (
                        <div style={{ marginTop: 16 }}>
                          <span className="label" style={{ display: 'block', marginBottom: 8 }}>Active Event Destinations</span>
                          {snsStatus.liveEventDestinations.map((dest, idx) => (
                            <div key={idx} className="sns-dest-item">
                              <span className="value code" style={{ fontSize: 12 }}>{dest.eventDestinationArn}</span>
                              {dest.roleArn && <span className="value code" style={{ fontSize: 11, color: '#888' }}>Role: {dest.roleArn}</span>}
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Stored config info */}
                      {snsStatus?.storedConfig?.subscribedAt && (
                        <div style={{ marginTop: 12, fontSize: 12, color: '#888' }}>
                          Last subscribed: {new Date(snsStatus.storedConfig.subscribedAt).toLocaleString()}
                        </div>
                      )}
                    </>
                  )}
                </div>

                {/* Subscribe / Unsubscribe Form */}
                <div className="info-card">
                  <h3>{snsStatus?.isSubscribed ? 'Update or Unsubscribe' : 'Subscribe to SNS'}</h3>
                  <div className="sns-form">
                    <div className="sns-field">
                      <label htmlFor="sns-topic-arn">SNS Topic ARN</label>
                      <input
                        id="sns-topic-arn"
                        type="text"
                        value={customTopicArn}
                        onChange={(e) => setCustomTopicArn(e.target.value)}
                        // Generic shape, not our own ARN: the previous placeholder
                        // carried the real AWS account id into the rendered DOM.
                        placeholder="arn:aws:sns:<region>:<account>:<topic>"
                      />
                      <span className="field-hint">Leave default to use the stack-wecare-digital topic</span>
                    </div>
                    <div className="sns-field">
                      <label htmlFor="sns-role-arn">IAM Role ARN (optional)</label>
                      <input
                        id="sns-role-arn"
                        type="text"
                        value={customRoleArn}
                        onChange={(e) => setCustomRoleArn(e.target.value)}
                        placeholder="arn:aws:iam::role/..."
                      />
                      <span className="field-hint">Role that grants SNS publish permissions (optional)</span>
                    </div>
                    <div className="sns-actions">
                      <button
                        className="sns-btn subscribe"
                        onClick={handleSubscribeSNS}
                        disabled={snsLoading}
                      >
                        {snsLoading ? 'Processing...' : snsStatus?.isSubscribed ? 'Update Subscription' : 'Subscribe to SNS'}
                      </button>
                      {snsStatus?.isSubscribed && (
                        <button
                          className="sns-btn unsubscribe"
                          onClick={handleUnsubscribeSNS}
                          disabled={snsLoading}
                        >
                          {snsLoading ? 'Processing...' : 'Unsubscribe'}
                        </button>
                      )}
                      <button
                        className="sns-btn refresh"
                        onClick={() => loadSnsStatus()}
                        disabled={snsLoading}
                      >
                        Refresh Status
                      </button>
                    </div>
                  </div>
                </div>

                {/* How it works */}
                <div className="info-card">
                  <h3>How SNS Events Work</h3>
                  <div style={{ fontSize: 13, color: '#555', lineHeight: 1.6 }}>
                    <p>When subscribed, Meta sends WhatsApp webhook events to the configured endpoint:</p>
                    <ul style={{ paddingLeft: 20, margin: '8px 0' }}>
                      <li>Message delivery status (sent, delivered, read, failed)</li>
                      <li>Template approval/rejection notifications</li>
                      <li>Phone number quality rating changes</li>
                      <li>Account restriction and limit updates</li>
                    </ul>
                    <p>The inbound webhook handler processes these events and stores them in the System Events tab.</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <style jsx>{`
        .waba-dashboard {
          padding: 16px 24px;
          max-width: 1200px;
          margin: 0 auto;
          background: #fff;
        }

        .page-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 24px;
        }

        .header-left {
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .back-btn {
          background: none;
          border: 1px solid #ddd;
          padding: 8px 16px;
          border-radius: 8px;
          cursor: pointer;
        }

        .back-btn:hover {
          background: #f5f5f5;
        }

        h1 {
          margin: 0;
          font-size: 24px;
        }

        .refresh-btn {
          background: #fff;
          color: #000;
          border: 1px solid #000;
          padding: 10px 20px;
          border-radius: 13px;
          cursor: pointer;
        }

        .refresh-btn:hover {
          background: #f5f5f5;
        }

        .refresh-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .loading-state, .empty-state {
          text-align: center;
          padding: 40px;
          color: #666;
        }

        .waba-selector-section {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
        }

        .waba-selector-section select {
          padding: 10px 16px;
          border: 1px solid #ddd;
          border-radius: 8px;
          font-size: 14px;
          min-width: 300px;
        }

        .tabs {
          display: flex;
          gap: 8px;
          margin-bottom: 24px;
          border-bottom: 1px solid #eee;
          padding-bottom: 12px;
          position: relative;
          z-index: 10;
        }

        .tab {
          background: #fff;
          border: 1px solid #000;
          padding: 10px 20px;
          cursor: pointer;
          border-radius: 13px;
          font-size: 14px;
          color: #000;
          position: relative;
          z-index: 11;
        }

        .tab:hover {
          background: #f5f5f5;
        }

        .tab.active {
          background: #f5f5f5;
          color: #000;
          font-weight: 600;
        }

        .info-card {
          background: white;
          border: 1px solid #eee;
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 24px;
        }

        .info-card h3 {
          margin: 0 0 16px 0;
          font-size: 16px;
          color: #333;
        }

        .info-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 16px;
        }

        .info-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .info-item .label {
          font-size: 12px;
          color: #666;
          text-transform: uppercase;
        }

        .info-item .value {
          font-size: 14px;
          font-weight: 500;
        }

        .info-item .value.code {
          font-family: monospace;
          font-size: 12px;
          background: #f5f5f5;
          padding: 4px 8px;
          border-radius: 4px;
        }

        .info-item .value.enabled {
          color: #000;
        }

        .info-item .value.disabled {
          color: #1a3a2a;
        }

        .phone-numbers-section h3 {
          margin: 0 0 16px 0;
        }

        .phone-cards {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 16px;
        }

        .phone-card {
          background: white;
          border: 1px solid #eee;
          border-radius: 12px;
          padding: 16px;
        }

        .phone-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }

        .phone-name {
          font-weight: 600;
        }

        .quality-badge {
          padding: 4px 12px;
          border-radius: 20px;
          font-size: 12px;
          color: white;
        }

        .phone-number {
          font-size: 20px;
          font-weight: 600;
          margin-bottom: 12px;
          color: #333;
        }

        .phone-details {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-bottom: 12px;
        }

        .phone-details .detail {
          display: flex;
          justify-content: space-between;
          font-size: 12px;
        }

        .phone-details .label {
          color: #666;
        }

        .phone-details .value.code {
          font-family: monospace;
          background: #f5f5f5;
          padding: 2px 6px;
          border-radius: 4px;
        }

        .quality-indicator {
          height: 4px;
          background: #eee;
          border-radius: 2px;
          overflow: hidden;
        }

        .quality-bar {
          height: 100%;
          transition: width 0.3s ease;
        }

        .events-section {
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .embedded-page {
          margin-top: 0;
        }

        .embedded-page :global(.page) {
          padding: 0;
          max-width: none;
        }

        .embedded-page :global(.page-header) {
          display: none;
        }

        .events-card {
          background: white;
          border: 1px solid #eee;
          border-radius: 12px;
          padding: 20px;
        }

        .events-card h3 {
          margin: 0 0 16px 0;
          font-size: 16px;
        }

        .events-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
          max-height: 300px;
          overflow-y: auto;
        }

        .event-item {
          display: flex;
          gap: 12px;
          padding: 12px;
          background: #f9f9f9;
          border-radius: 8px;
        }

        .event-icon {
          font-size: 20px;
        }

        .event-icon.quality-dot {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          margin-top: 4px;
        }

        .event-content {
          flex: 1;
        }

        .event-title {
          font-weight: 500;
          margin-bottom: 4px;
        }

        .event-details {
          font-size: 12px;
          color: #666;
        }

        .event-reason {
          color: #DC3545;
        }

        .restriction {
          color: #DC3545;
        }

        .event-time {
          font-size: 11px;
          color: #999;
          margin-top: 4px;
        }

        .embedded {
          padding: 0;
        }

        /* SNS Subscription Styles */
        .sns-section {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }

        .sns-status-row {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-top: 8px;
        }

        .sns-badge {
          display: inline-block;
          padding: 4px 14px;
          border-radius: 20px;
          font-size: 12px;
          font-weight: 600;
        }

        .sns-badge.active {
          background: #d1f470;
          color: #1a3a2a;
        }

        .sns-badge.inactive {
          background: #f3f4f6;
          color: #6b7280;
        }

        .sns-dest-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
          padding: 8px 12px;
          background: #f9fafb;
          border-radius: 6px;
          margin-bottom: 6px;
        }

        .sns-form {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .sns-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .sns-field label {
          font-size: 13px;
          font-weight: 500;
          color: #374151;
        }

        .sns-field input {
          padding: 10px 14px;
          border: 1px solid #d1d5db;
          border-radius: 8px;
          font-size: 13px;
          font-family: monospace;
        }

        .sns-field input:focus {
          outline: none;
          border-color: #1a3a2a;
          box-shadow: 0 0 0 2px rgba(26, 58, 42, 0.1);
        }

        .field-hint {
          font-size: 11px;
          color: #9ca3af;
        }

        .sns-actions {
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
        }

        .sns-btn {
          padding: 10px 20px;
          border: none;
          border-radius: 10px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: opacity 0.15s;
        }

        .sns-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .sns-btn.subscribe {
          background: #1a3a2a;
          color: #d1f470;
        }

        .sns-btn.subscribe:hover:not(:disabled) {
          opacity: 0.9;
        }

        .sns-btn.unsubscribe {
          background: #fee2e2;
          color: #991b1b;
        }

        .sns-btn.unsubscribe:hover:not(:disabled) {
          background: #fecaca;
        }

        .sns-btn.refresh {
          background: #f3f4f6;
          color: #374151;
        }

        .sns-btn.refresh:hover:not(:disabled) {
          background: #e5e7eb;
        }

        @media (max-width: 768px) {
          .waba-dashboard { padding: 12px; }
          .waba-selector-section { flex-direction: column; gap: 8px; }
          .waba-selector-section select { min-width: 100%; }
          .info-grid { grid-template-columns: 1fr 1fr; }
          .phone-cards { grid-template-columns: 1fr; }
          .phone-number { font-size: 16px; }
        }

        @media (max-width: 480px) {
          .waba-dashboard { padding: 8px; }
          .info-grid { grid-template-columns: 1fr; }
        }
      `}</style>
    </>
  );

  if (embedded) {
    return dashboardContent;
  }

  return (
    <Layout user={user} onSignOut={signOut}>
      {dashboardContent}
    </Layout>
  );
};

export default WABADashboard;
