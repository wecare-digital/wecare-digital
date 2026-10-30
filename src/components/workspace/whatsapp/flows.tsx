/**
 * Operational WhatsApp Flow inventory: seven retained customer Flow IDs only.
 * Meta's deprecated provider designs are never offered as Workspace actions.
 */
import React, { useEffect, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';
import { WHATSAPP_PHONES } from '../../../config/constants';
import { publishedFlowById } from '../../../lib/canonicalFlows';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const statusColor = (status: string): string =>
  status === 'PUBLISHED' ? 'var(--accent)' : status === 'THROTTLED' ? '#92400e' : '#991b1b';

const FlowsPage: React.FC<PageProps> = ({ signOut, user, embedded = false }) => {
  const toast = useToastContext();
  const [flows, setFlows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [flowDetail, setFlowDetail] = useState<any>(null);

  const loadFlows = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await api.listFlows(WHATSAPP_PHONES.primary.wabaId);
      setFlows(result);
    } catch (e: any) {
      const message = e?.message || 'Failed to load Meta Flows';
      setLoadError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadFlows(); }, []);

  const syncMeta = async () => {
    setSyncing(true);
    try {
      const result = await api.syncFlows(WHATSAPP_PHONES.primary.wabaId);
      if (!result?.success) throw new Error(typeof result?.error === 'string' ? result.error : 'Meta sync was rejected');
      toast.success(`Synced ${result.synced ?? 0} Flow records from Meta`);
      await loadFlows();
    } catch (e: any) {
      toast.error(e?.message || 'Meta synchronization failed');
    } finally {
      setSyncing(false);
    }
  };

  const viewDetails = async (flow: any) => {
    try {
      const detail = await api.getFlow(flow.id);
      setFlowDetail(detail);
    } catch (e: any) {
      toast.error(e?.message || 'Could not load Flow details');
    }
  };

  // Display retained IDs even if Meta reports THROTTLED/BLOCKED: do not hide incidents.
  const retainedFlows = flows.filter(flow => !!publishedFlowById(String(flow.id || '')));

  const content = (
    <>
      <SEO title="WhatsApp Flows" description="Retained WhatsApp Flow status" noindex />
      <div className="inner-page-container" style={{ background: '#fff' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>Published customer Flows</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" onClick={() => void loadFlows()} disabled={loading}
              style={{ padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 8, background: '#fff', cursor: 'pointer' }}>
              {loading ? 'Refreshing...' : 'Refresh Meta'}
            </button>
            <button type="button" onClick={() => void syncMeta()} disabled={syncing || loading}
              style={{ padding: '8px 12px', border: '1px solid var(--accent)', borderRadius: 8, background: 'var(--lime)', color: 'var(--accent)', cursor: 'pointer' }}>
              {syncing ? 'Syncing...' : 'Sync live Meta status'}
            </button>
          </div>
        </div>
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginBottom: 16 }}>
          {retainedFlows.length} of 7 retained Flows found on the primary Messaging Account. Legacy Meta designs are not available from Workspace.
        </p>
        {loading ? <p>Loading Flows...</p> : loadError ? (
          <p style={{ color: '#991b1b' }}>{loadError}</p>
        ) : retainedFlows.length === 0 ? (
          <p>No retained Flows were returned by Meta. Check live provider status.</p>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {retainedFlows.map(flow => (
              <div key={flow.id} style={{ padding: 16, border: '1px solid var(--border)', borderRadius: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                  <strong>{flow.name}</strong>
                  <span style={{ color: statusColor(String(flow.status || '')) }}>{flow.status}</span>
                </div>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>ID: {flow.id}</div>
                <button type="button" onClick={() => void viewDetails(flow)}
                  style={{ marginTop: 10, padding: '4px 12px', border: '1px solid var(--border)', borderRadius: 6, background: '#fff', cursor: 'pointer' }}>
                  Details
                </button>
              </div>
            ))}
          </div>
        )}
        {flowDetail && (
          <div style={{ marginTop: 20, padding: 16, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <h3 style={{ margin: 0 }}>Flow Details: {flowDetail.name}</h3>
              <button type="button" onClick={() => setFlowDetail(null)}>Close</button>
            </div>
            <p>ID: {flowDetail.id} · Meta status: {flowDetail.status}</p>
            <p>JSON version: {flowDetail.json_version || 'N/A'} · Data API: {flowDetail.data_api_version || 'N/A'}</p>
            <p>Endpoint: {flowDetail.endpoint_uri || 'Not configured'}</p>
            {flowDetail.validation_errors?.length > 0 &&
              <p style={{ color: '#991b1b' }}>Validation errors: {JSON.stringify(flowDetail.validation_errors)}</p>}
          </div>
        )}
      </div>
    </>
  );

  if (embedded) return content;
  return <Layout user={user} onSignOut={signOut}>{content}</Layout>;
};

export default FlowsPage;
