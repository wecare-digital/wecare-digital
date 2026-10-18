import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import Pagination from '../../../components/ui/Pagination';
import DateField from '../../../components/ui/DateField';
import { useConfirmDanger } from '../../../components/wa';
import * as api from '../../../api/client';

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

/**
 * One VoiceCDRTable row as plivo-answer writes it today: the camelCase fields every reader
 * binds to, plus the snake_case copies it still writes beside them.
 */
interface CDRRecord {
  id: string;
  callUuid?: string;
  callerNumber?: string;
  destinationNumber?: string;
  callerId?: string;
  from_number?: string;
  to_number?: string;
  direction?: string;
  callType?: string;
  overallCallStatus?: string;
  call_status?: string;
  hangupCause?: string;
  hangupStatus?: string;
  durationSec?: number;
  conversationDurationSec?: number;
  billableDurationSec?: number;
  duration_seconds?: number | string;
  createdAt?: number;
  timestamp?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const ITEMS_PER_PAGE = 100;
const DATE_STYLE: React.CSSProperties = { width: 170 };

const CallHistoryPage: React.FC<PageProps> = ({ signOut, user, embedded = false }) => {
  const [records, setRecords] = useState<CDRRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [direction, setDirection] = useState<'all' | 'INBOUND' | 'OUTBOUND'>('all');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [page, setPage] = useState(1);
  const confirmDanger = useConfirmDanger();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '500' });
      if (startDate) params.set('startDate', String(Math.floor(new Date(startDate).getTime() / 1000)));
      if (endDate) params.set('endDate', String(Math.floor(new Date(endDate + 'T23:59:59').getTime() / 1000)));
      const response = await api.authFetch(`${API_BASE}/voice-cdr-read?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body?.error || `HTTP ${response.status}`);
      setRecords(body.records || []);
      setError('');
    } catch (err) {
      console.error('Call history load failed:', err);
      setError(err instanceof Error ? err.message : 'Unable to load call history');
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [query, direction, startDate, endDate]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return records.filter((row) => {
      const rowDirection = String(row.direction || '').toUpperCase();
      if (direction !== 'all' && rowDirection !== direction) return false;
      if (!q) return true;
      return [
        row.callUuid, row.callerId, row.callerNumber, row.destinationNumber,
        row.from_number, row.to_number, row.callType, row.overallCallStatus,
        row.call_status, row.hangupCause, row.hangupStatus,
      ].some((value) => String(value || '').toLowerCase().includes(q));
    });
  }, [records, query, direction]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));
  const rows = filtered.slice((page - 1) * ITEMS_PER_PAGE, page * ITEMS_PER_PAGE);

  const clearHistory = async () => {
    const ok = await confirmDanger('delete', 'This permanently clears all call history and cannot be undone.', {
      title: 'Clear all call history?',
      confirmInput: 'CLEAR',
      confirmText: 'Clear all',
    });
    if (!ok) return;
    setClearing(true);
    try {
      const response = await api.authFetch(`${API_BASE}/voice-cdr-read`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clearAll: true, hardDelete: true }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await load();
    } catch (err) {
      console.error('Call history clear failed:', err);
      setError('Unable to clear call history');
    } finally {
      setClearing(false);
    }
  };

  const content = (
    <div className="history-page">
      <div className="history-header">
        <div>
          <h2>Call History</h2>
          <p>Provider-neutral call detail records from the current voice stack.</p>
        </div>
        <div className="actions">
          <Button variant="secondary" onClick={load} loading={loading}>Refresh</Button>
          <Button variant="secondary" onClick={clearHistory} loading={clearing}>Clear</Button>
        </div>
      </div>

      <div className="filters">
        <input aria-label="Search call history" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search number, call ID, status..." />
        <select aria-label="Direction" value={direction} onChange={e => setDirection(e.target.value as 'all' | 'INBOUND' | 'OUTBOUND')}>
          <option value="all">All directions</option>
          <option value="INBOUND">Inbound</option>
          <option value="OUTBOUND">Outbound</option>
        </select>
        <DateField ariaLabel="Start date" value={startDate} onChange={setStartDate} style={DATE_STYLE} />
        <DateField ariaLabel="End date" value={endDate} onChange={setEndDate} style={DATE_STYLE} />
      </div>

      {error && <div className="error">{error}</div>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Direction</th><th>From</th><th>To</th><th>Type</th><th>Duration</th><th>Status</th><th>Hangup</th></tr></thead>
          <tbody>
            {loading && <tr><td colSpan={8}>Loading...</td></tr>}
            {!loading && rows.map(row => {
              const when = row.createdAt;
              const duration = row.billableDurationSec ?? row.conversationDurationSec ?? row.durationSec ?? row.duration_seconds ?? 0;
              const status = row.overallCallStatus || row.call_status || '-';
              return <tr key={row.id || row.callUuid}>
                <td>{when ? new Date(Number(when) * 1000).toLocaleString('en-IN') : (row.timestamp || '-')}</td>
                <td>{row.direction || '-'}</td>
                <td>{row.callerNumber || row.from_number || '-'}</td>
                <td>{row.destinationNumber || row.to_number || '-'}</td>
                <td>{row.callType || '-'}</td>
                <td>{Math.round(Number(duration))}s</td>
                <td>{status}</td>
                <td>{row.hangupCause || row.hangupStatus || '-'}</td>
              </tr>;
            })}
            {!loading && rows.length === 0 && <tr><td colSpan={8}>No call records found.</td></tr>}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />}

      <style jsx>{`
        .history-page { padding: 20px; }
        .history-header { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }
        h2 { margin:0; color:#0f2a1d; }
        p { margin:4px 0 0; color:var(--text-muted); font-size:var(--text-sm); }
        .actions,.filters { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
        .filters { margin-bottom:14px; }
        .filters input,.filters select { padding:8px 10px; border:1px solid #d1d5db; border-radius:8px; background:#fff; }
        .filters input { min-width:260px; }
        .error { margin:10px 0; padding:10px; border:1px solid #fecaca; border-radius:8px; }
        .table-wrap { overflow:auto; border:1px solid var(--border); border-radius:10px; margin-bottom:12px; }
        table { width:100%; border-collapse:collapse; }
        th,td { padding:9px 10px; border-bottom:1px solid #f3f4f6; font-size:var(--text-xs); text-align:left; white-space:nowrap; }
        th { background:var(--bg-secondary); }
      `}</style>
    </div>
  );

  if (embedded) return content;
  return <Layout onSignOut={signOut} user={user}><SEO title="Call History" description="Voice call history" />{content}</Layout>;
};

export default CallHistoryPage;
