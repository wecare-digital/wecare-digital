/**
 * WhatsApp Flows Management
 * Create, manage, publish, and deprecate WhatsApp Flows
 * Ref: https://developers.facebook.com/docs/whatsapp/flows/reference/flowsapi/
 */
import React, { useState, useEffect } from 'react';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import * as api from '../../../../api/client';
import { WHATSAPP_PHONES } from '../../../../config/constants';
import Select, { type SelectOption } from '../../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const WABAS = [
  { id: WHATSAPP_PHONES.primary.wabaId, name: WHATSAPP_PHONES.primary.name, display: WHATSAPP_PHONES.primary.display },
  { id: WHATSAPP_PHONES.secondary.wabaId, name: WHATSAPP_PHONES.secondary.name, display: WHATSAPP_PHONES.secondary.display },
];

const CATEGORIES = ['SIGN_UP', 'SIGN_IN', 'APPOINTMENT_BOOKING', 'LEAD_GENERATION', 'CONTACT_US', 'CUSTOMER_SUPPORT', 'SURVEY', 'OTHER'];

const CATEGORY_OPTIONS: SelectOption[] = CATEGORIES.map(c => ({ value: c, label: c.replace(/_/g, ' ') }));

const STATUS_COLORS: Record<string, string> = {
  DRAFT: '#1a3a2a', PUBLISHED: '#1a3a2a', DEPRECATED: '#9ca3af', BLOCKED: '#1a3a2a', THROTTLED: '#1a3a2a',
};

const FlowsPage: React.FC<PageProps> = ({ signOut, user, embedded = false }) => {
  const toast = useToastContext();
  const confirm = useConfirm();
  const [selectedWaba, setSelectedWaba] = useState(WABAS[0]);
  const [flows, setFlows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newCategory, setNewCategory] = useState('OTHER');
  const [creating, setCreating] = useState(false);
  const [selectedFlow, setSelectedFlow] = useState<any>(null);
  const [flowDetail, setFlowDetail] = useState<any>(null);
  const [actionLoading, setActionLoading] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadFlows = async (waba: typeof WABAS[0]) => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.listFlows(waba.id);
      setFlows(data);
    } catch (e: any) {
      const msg = e?.message || 'Failed to load flows';
      setLoadError(msg);
      toast.error(msg);
    }
    setLoading(false);
  };

  useEffect(() => { loadFlows(selectedWaba); }, [selectedWaba]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const result = await api.createFlow(selectedWaba.id, newName.trim(), [newCategory]);
      if (result) { toast.success('Flow created'); setShowCreate(false); setNewName(''); loadFlows(selectedWaba); }
      else toast.error('Create failed');
    } catch (e) { toast.error('Create failed'); }
    setCreating(false);
  };

  const handlePublish = async (flowId: string) => {
    setActionLoading(flowId);
    const ok = await api.publishFlow(flowId);
    if (ok) { toast.success('Flow published'); loadFlows(selectedWaba); }
    else toast.error('Publish failed');
    setActionLoading('');
  };

  const handleDeprecate = async (flowId: string) => {
    setActionLoading(flowId);
    const ok = await api.deprecateFlow(flowId);
    if (ok) { toast.success('Flow deprecated'); loadFlows(selectedWaba); }
    else toast.error('Deprecate failed');
    setActionLoading('');
  };

  const handleDelete = async (flowId: string) => {
    if (!(await confirm('Delete this flow?'))) return;
    setActionLoading(flowId);
    const ok = await api.deleteFlow(flowId);
    if (ok) { toast.success('Flow deleted'); loadFlows(selectedWaba); }
    else toast.error('Delete failed — only DRAFT flows can be deleted');
    setActionLoading('');
  };

  const viewDetails = async (flow: any) => {
    setSelectedFlow(flow);
    const detail = await api.getFlow(flow.id);
    setFlowDetail(detail);
  };

  const content = (
    <>
      <SEO title="WhatsApp Flows" description="Manage WhatsApp Flows" noindex />
      <div className="inner-page-container" style={{ background: '#fff' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>WhatsApp Flows</h2>
          <button onClick={() => setShowCreate(true)} style={{ padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: '1.5px solid #1a3a2a', borderRadius: 13, cursor: 'pointer', fontSize: 13 }}>
            + Create Flow
          </button>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
          {WABAS.map(w => (
            <button key={w.id} onClick={() => { setSelectedWaba(w); setSelectedFlow(null); }}
              style={{ padding: '8px 16px', borderRadius: 6, border: selectedWaba.id === w.id ? '2px solid #1a3a2a' : '1px solid #ddd', background: selectedWaba.id === w.id ? '#f9fafb' : '#fff', cursor: 'pointer', fontSize: 13 }}>
              {w.name} ({w.display})
            </button>
          ))}
        </div>

        {/* Create Modal */}
        {showCreate && (
          <div style={{ background: '#f9fafb', padding: 20, borderRadius: 8, marginBottom: 20, border: '1px solid #e5e7eb' }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>Create New Flow</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12, marginBottom: 12 }}>
              <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Flow name"
                style={{ padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 }} />
              <Select ariaLabel="Flow category" value={newCategory} onChange={v => setNewCategory(v)}
                options={CATEGORY_OPTIONS} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={handleCreate} disabled={creating} style={{ padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button onClick={() => setShowCreate(false)} style={{ padding: '8px 16px', background: '#fff', border: '1px solid #ddd', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>Cancel</button>
            </div>
          </div>
        )}

        {loading ? <p>Loading flows...</p> : loadError ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#666' }}>
            <p style={{ fontSize: 16, color: '#1a3a2a' }}>Failed to load flows</p>
            <p style={{ fontSize: 13, marginTop: 8 }}>{loadError}</p>
            <button onClick={() => loadFlows(selectedWaba)} style={{ marginTop: 12, padding: '8px 16px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
              Retry
            </button>
          </div>
        ) : flows.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#666' }}>
            <p style={{ fontSize: 16 }}>No flows found for this WABA</p>
            <p style={{ fontSize: 13 }}>Create a flow to build forms, surveys, and step-based experiences</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {flows.map(flow => (
              <div key={flow.id} style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8, padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ fontWeight: 600, fontSize: 15 }}>{flow.name}</span>
                    <span style={{ marginLeft: 10, padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, color: '#fff', background: STATUS_COLORS[flow.status] || '#666' }}>
                      {flow.status}
                    </span>
                    {flow.categories?.map((c: string) => (
                      <span key={c} style={{ marginLeft: 6, padding: '2px 6px', borderRadius: 4, fontSize: 11, background: '#f3f4f6', color: '#374151' }}>{c.replace(/_/g, ' ')}</span>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button onClick={() => viewDetails(flow)} style={{ padding: '4px 10px', fontSize: 12, border: '1px solid #ddd', borderRadius: 4, background: '#fff', cursor: 'pointer' }}>Details</button>
                    {flow.status === 'DRAFT' && (
                      <>
                        <button onClick={() => handlePublish(flow.id)} disabled={actionLoading === flow.id} style={{ padding: '4px 10px', fontSize: 12, border: 'none', borderRadius: 4, background: '#d1f470', color: '#1a3a2a', cursor: 'pointer' }}>Publish</button>
                        <button onClick={() => handleDelete(flow.id)} disabled={actionLoading === flow.id} style={{ padding: '4px 10px', fontSize: 12, border: 'none', borderRadius: 4, background: '#d1f470', color: '#1a3a2a', cursor: 'pointer' }}>Delete</button>
                      </>
                    )}
                    {flow.status === 'PUBLISHED' && (
                      <button onClick={() => handleDeprecate(flow.id)} disabled={actionLoading === flow.id} style={{ padding: '4px 10px', fontSize: 12, border: '1px solid #1a3a2a', borderRadius: 4, background: '#fff', color: '#1a3a2a', cursor: 'pointer' }}>Deprecate</button>
                    )}
                  </div>
                </div>
                <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>ID: {flow.id}</div>
              </div>
            ))}
          </div>
        )}

        {/* Flow Detail Panel */}
        {selectedFlow && flowDetail && (
          <div style={{ marginTop: 20, background: '#f9fafb', padding: 20, borderRadius: 8, border: '1px solid #e5e7eb' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 style={{ margin: 0, fontSize: 16 }}>Flow Details: {flowDetail.name}</h3>
              <button onClick={() => { setSelectedFlow(null); setFlowDetail(null); }} style={{ padding: '4px 10px', fontSize: 12, border: '1px solid #ddd', borderRadius: 4, background: '#fff', cursor: 'pointer' }}>Close</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, fontSize: 13 }}>
              <div><span style={{ color: '#666' }}>ID:</span> {flowDetail.id}</div>
              <div><span style={{ color: '#666' }}>Status:</span> {flowDetail.status}</div>
              <div><span style={{ color: '#666' }}>JSON Version:</span> {flowDetail.json_version || 'N/A'}</div>
              <div><span style={{ color: '#666' }}>Data API Version:</span> {flowDetail.data_api_version || 'N/A'}</div>
              <div style={{ gridColumn: '1 / -1' }}><span style={{ color: '#666' }}>Endpoint URI:</span> {flowDetail.endpoint_uri || 'Not set'}</div>
            </div>
            {flowDetail.validation_errors?.length > 0 && (
              <div style={{ marginTop: 12, padding: 12, background: '#f9fafb', borderRadius: 6, fontSize: 13 }}>
                <strong style={{ color: '#1a3a2a' }}>Validation Errors:</strong>
                <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                  {flowDetail.validation_errors.map((e: any, i: number) => <li key={i}>{e.error || JSON.stringify(e)}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );

  if (embedded) return content;

  return (
    <Layout user={user} onSignOut={signOut}>
      {content}
    </Layout>
  );
};

export default FlowsPage;
