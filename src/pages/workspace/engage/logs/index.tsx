/**
 * Message Logs — ONE view over the canonical MessagesTable, for every channel.
 *
 * WHY THIS FILE ABSORBED THREE OTHERS
 * -----------------------------------
 * There were four logs pages totalling 971 lines, and all four called the same
 * `api.listMessages` against the same single table. They differed only in a
 * channel filter string and a column set:
 *
 *   dm/logs          319  all channels, filters + summary cards
 *   dm/ses/logs      268  channel EMAIL, plus a delete action
 *   dm/whatsapp/logs 265  channel WHATSAPP, plus error decoding, CSV, pagination
 *   dm/rcs/logs      119  channel RCS, nothing unique
 *
 * `messages-read/handler.py` calls MessagesTable "the single source the inbox
 * reads" and the legacy per-channel dual-writes were already stopped, so there
 * was never a data reason for four pages - only a UI one.
 *
 * Every capability from all four is kept, none dropped:
 *   - channel / direction / status filters, and the summary cards (from dm/logs)
 *   - contact-name resolution, failure-reason breakdown, CSV export, pagination
 *     and WhatsApp error decoding (from dm/whatsapp/logs)
 *   - row delete (from dm/ses/logs)
 *
 * THE `channel` PROP is what replaces the three files. A hub embeds this with its
 * own channel and the filter is preset and hidden, because a channel selector
 * inside a page already titled "RCS" is a control that can only ever be wrong.
 * `?channel=` is accepted too, so a link or a Ctrl+K result can deep-link.
 *
 * WhatsApp error decoding stays WhatsApp-only. `describeWaError` maps Meta's
 * numeric codes; showing a Meta explanation next to an SES bounce would invent a
 * cause. Other channels show their raw `errorDetails` and nothing more.
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import Button from '../../../../components/ui/Button';
import Pagination from '../../../../components/ui/Pagination';
import InfoTooltip from '../../../../components/ui/InfoTooltip';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import { describeWaError } from '../../../../lib/wa-errors';
import { useToastContext } from '../../../../contexts/ToastContext';
import * as api from '../../../../api/client';

export type LogChannel = 'whatsapp' | 'sms' | 'email' | 'voice' | 'rcs';

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
  /** Preset and lock the channel. Used by the per-channel hubs. */
  channel?: LogChannel;
}

interface MessageLog {
  id: string;
  channel: LogChannel;
  direction: 'INBOUND' | 'OUTBOUND';
  contactId: string;
  contactName?: string;
  content: string;
  status: string;
  createdAt: string;
  messageType?: string;
  errorCode?: number;
  errorDetails?: string;
}

const LOGS_PER_PAGE = 50;

const CHANNEL_BADGES: Record<string, { bg: string; color: string; label: string }> = {
  whatsapp: { bg: '#f0fdf4', color: '#15803d', label: 'WhatsApp' },
  sms: { bg: '#eff6ff', color: '#1d4ed8', label: 'SMS' },
  email: { bg: '#fffbeb', color: '#b45309', label: 'Email' },
  voice: { bg: '#f5f3ff', color: '#6d28d9', label: 'Voice' },
  rcs: { bg: '#f0fdfa', color: '#0f766e', label: 'RCS' },
};

const STATUS_BADGES: Record<string, { bg: string; color: string; label: string }> = {
  pending: { bg: '#fffbeb', color: '#b45309', label: 'Pending' },
  queued: { bg: '#f9fafb', color: 'rgba(0,0,0,.54)', label: 'Queued' },
  sent: { bg: '#eff6ff', color: '#1d4ed8', label: 'Sent' },
  delivered: { bg: '#f0fdfa', color: '#0f766e', label: 'Delivered' },
  read: { bg: '#f0fdf4', color: '#15803d', label: 'Read' },
  received: { bg: '#f0fdf4', color: '#15803d', label: 'Received' },
  failed: { bg: '#fef2f2', color: '#b91c1c', label: 'Failed' },
  undelivered: { bg: '#fef2f2', color: '#b91c1c', label: 'Undelivered' },
};

const FAILED_STATUSES = [ 'failed', 'undelivered' ];

/*
 * The three filter option lists, hoisted so they are not rebuilt per render. Each one holds
 * exactly the <option> rows it replaced, in the same order and with the same values - the
 * filters read 'all', not '', so none of these has a placeholder row.
 */
const CHANNEL_FILTER_OPTIONS: SelectOption[] = [
  { value: 'all', label: 'All channels' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'sms', label: 'SMS' },
  { value: 'email', label: 'Email' },
  { value: 'voice', label: 'Voice' },
  { value: 'rcs', label: 'RCS' },
];

const DIRECTION_FILTER_OPTIONS: SelectOption[] = [
  { value: 'all', label: 'All' },
  { value: 'INBOUND', label: 'Inbound' },
  { value: 'OUTBOUND', label: 'Outbound' },
];

const STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: 'all', label: 'All statuses' },
  { value: 'sent', label: 'Sent' },
  { value: 'delivered', label: 'Delivered' },
  { value: 'read', label: 'Read' },
  { value: 'received', label: 'Received' },
  { value: 'failed', label: 'Failed' },
];

/*
 * LAYOUT ONLY - the box is drawn by .ui-select-trigger. One width for all three filters,
 * because the trigger shows the SELECTED label while a native control sizes itself to its
 * WIDEST option: without a width the row would re-flow every time a filter was used.
 */
const FILTER_STYLE: React.CSSProperties = { width: 170 };

const chBadge = ( c: string ) =>
  CHANNEL_BADGES[ c ] || { bg: '#f9fafb', color: 'rgba(0,0,0,.54)', label: c || 'Unknown' };
const stBadge = ( s: string ) =>
  STATUS_BADGES[ s ] || { bg: '#f9fafb', color: 'rgba(0,0,0,.54)', label: s || 'unknown' };

const MessageLogsPage: React.FC<PageProps> = ( { signOut, user, embedded, channel } ) => {
  const router = useRouter();
  const [ logs, setLogs ] = useState<MessageLog[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ channelFilter, setChannelFilter ] = useState<string>( 'all' );
  const [ directionFilter, setDirectionFilter ] = useState<string>( 'all' );
  const [ statusFilter, setStatusFilter ] = useState<string>( 'all' );
  const [ page, setPage ] = useState( 1 );
  const [ deletingId, setDeletingId ] = useState<string | null>( null );
  const toast = useToastContext();

  // A prop beats a query param beats "all". The prop is a hub presetting its own
  // channel, so it must not be overridden by a stale URL.
  const lockedChannel: LogChannel | undefined = useMemo( () => {
    if ( channel ) return channel;
    const q = String( router.query.channel || '' ).toLowerCase();
    return ( q in CHANNEL_BADGES ) ? ( q as LogChannel ) : undefined;
  }, [ channel, router.query.channel ] );

  const effectiveChannel = lockedChannel ?? ( channelFilter === 'all' ? undefined : channelFilter );

  const load = useCallback( async () => {
    setLoading( true );
    try
    {
      // Contacts are fetched so a row can show a name instead of a raw id. This
      // came from the WhatsApp page; the other three showed the bare contactId,
      // which is unreadable.
      const [ messages, contacts ] = await Promise.all( [
        api.listMessages( undefined, lockedChannel ? lockedChannel.toUpperCase() : undefined, 2000 ),
        api.listContacts().catch( () => [] as api.Contact[] ),
      ] );
      const names: Record<string, string> = {};
      ( contacts || [] ).forEach( ( c ) => {
        names[ c.contactId ] = c.name || c.phone || c.email || c.contactId;
      } );
      setLogs( ( messages || [] ).map( ( m ) => ( {
        id: m.messageId,
        channel: ( m.channel?.toLowerCase() || 'whatsapp' ) as LogChannel,
        direction: ( String( m.direction || '' ).toUpperCase() === 'INBOUND'
          ? 'INBOUND' : 'OUTBOUND' ) as MessageLog[ 'direction' ],
        contactId: m.contactId,
        contactName: names[ m.contactId ],
        content: m.content || '',
        status: ( m.status || 'unknown' ).toLowerCase(),
        createdAt: m.timestamp,
        messageType: m.messageType,
        errorCode: m.errorCode,
        errorDetails: m.errorDetails,
      } ) ) );
    } catch
    {
      toast.error( 'Failed to load message logs' );
    } finally
    {
      setLoading( false );
    }
  }, [ lockedChannel, toast ] );

  useEffect( () => { load(); }, [ load ] );
  useEffect( () => { setPage( 1 ); }, [ channelFilter, directionFilter, statusFilter ] );

  const filtered = useMemo( () => logs.filter( ( l ) => {
    if ( effectiveChannel && l.channel !== effectiveChannel ) return false;
    if ( directionFilter !== 'all' && l.direction !== directionFilter ) return false;
    if ( statusFilter !== 'all' && l.status !== statusFilter ) return false;
    return true;
  } ), [ logs, effectiveChannel, directionFilter, statusFilter ] );

  const totals = useMemo( () => {
    const failed = filtered.filter( ( l ) => FAILED_STATUSES.includes( l.status ) );
    // Failure-reason breakdown, from the WhatsApp page. The single most useful
    // thing on a logs screen and it existed on only one of the four.
    const reasons: Record<string, number> = {};
    failed.forEach( ( l ) => {
      const info = l.channel === 'whatsapp'
        ? describeWaError( l.errorCode, l.errorDetails ) : null;
      const key = l.errorCode
        ? `${l.errorCode} · ${info?.title || 'Error'}`
        : ( info?.title || l.errorDetails || 'Unknown reason' );
      reasons[ key ] = ( reasons[ key ] || 0 ) + 1;
    } );
    return {
      total: filtered.length,
      out: filtered.filter( ( l ) => l.direction === 'OUTBOUND' ).length,
      in: filtered.filter( ( l ) => l.direction === 'INBOUND' ).length,
      failed: failed.length,
      topReasons: Object.entries( reasons ).sort( ( a, b ) => b[ 1 ] - a[ 1 ] ).slice( 0, 6 ),
    };
  }, [ filtered ] );

  const totalPages = Math.max( 1, Math.ceil( filtered.length / LOGS_PER_PAGE ) );
  const pageRows = filtered.slice( ( page - 1 ) * LOGS_PER_PAGE, page * LOGS_PER_PAGE );

  const exportCsv = useCallback( () => {
    const rows: string[][] = [ [ 'time', 'channel', 'direction', 'contact', 'type',
      'status', 'errorCode', 'reason', 'content' ] ];
    filtered.forEach( ( l ) => {
      const info = FAILED_STATUSES.includes( l.status ) && l.channel === 'whatsapp'
        ? describeWaError( l.errorCode, l.errorDetails ) : null;
      rows.push( [
        new Date( l.createdAt ).toISOString(), l.channel, l.direction,
        l.contactName || l.contactId, l.messageType || 'text', l.status,
        l.errorCode ? String( l.errorCode ) : '',
        info ? info.reason : ( l.errorDetails || '' ), l.content,
      ] );
    } );
    const csv = rows.map( ( r ) =>
      r.map( ( cell ) => `"${String( cell ).replace( /"/g, '""' )}"` ).join( ',' )
    ).join( '\n' );
    const url = URL.createObjectURL( new Blob( [ csv ], { type: 'text/csv' } ) );
    const a = document.createElement( 'a' );
    a.href = url;
    a.download = `message-logs-${effectiveChannel || 'all'}-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL( url );
  }, [ filtered, effectiveChannel ] );

  const remove = useCallback( async ( row: MessageLog ) => {
    if ( deletingId ) return;
    setDeletingId( row.id );
    try
    {
      const ok = await api.deleteMessage( row.id, row.direction );
      if ( ok )
      {
        setLogs( ( prev ) => prev.filter( ( l ) => l.id !== row.id ) );
        toast.success( 'Message deleted' );
      } else toast.error( 'Delete failed' );
    } catch { toast.error( 'Delete failed' ); }
    finally { setDeletingId( null ); }
  }, [ deletingId, toast ] );

  const fmt = ( s: string ) => {
    const d = new Date( s );
    return Number.isNaN( d.getTime() ) ? '—' : d.toLocaleDateString( 'en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    } );
  };

  const title = lockedChannel ? `${chBadge( lockedChannel ).label} Logs` : 'Message Logs';

  const content = (
    <>
      <div className="logs-page">
        { !embedded && (
          <PageHeader
            title={ title }
            subtitle={ lockedChannel
              ? `Every ${chBadge( lockedChannel ).label} message, from the canonical message store`
              : 'Every message across WhatsApp, SMS, Email, Voice and RCS' }
            icon="logs"
          />
        ) }

        <div className="filters">
          { /* The channel selector is hidden when a hub has preset one: a channel
               dropdown inside a page titled "RCS" can only ever be wrong. */ }
          { !lockedChannel && (
            <div className="filter-group">
              { /*
                 * SHAPE (a) - all three filters. Each one had an external label bound to the
                 * control by id; those labels are GONE and Select owns the pair instead. The
                 * trigger is a button, and per HTML-AAM a button takes its accessible name
                 * from its CONTENTS, so an external label bound by id is not a name source
                 * for it the way it is for a native control. Keeping them would have left
                 * these three announcing only "WhatsApp", "All" and "All statuses". Select
                 * renders the visible span and the aria-labelledby wiring itself, so one
                 * component owns the association instead of two lines that have to agree.
                 */ }
              <Select label="Channel" value={ channelFilter }
                onChange={ ( v ) => setChannelFilter( v ) }
                options={ CHANNEL_FILTER_OPTIONS } style={ FILTER_STYLE } />
            </div>
          ) }
          <div className="filter-group">
            <Select label="Direction" value={ directionFilter }
              onChange={ ( v ) => setDirectionFilter( v ) }
              options={ DIRECTION_FILTER_OPTIONS } style={ FILTER_STYLE } />
          </div>
          <div className="filter-group">
            <Select label="Status" value={ statusFilter }
              onChange={ ( v ) => setStatusFilter( v ) }
              options={ STATUS_FILTER_OPTIONS } style={ FILTER_STYLE } />
          </div>
          <div className="filter-actions">
            <Button variant="secondary" icon="refresh" onClick={ load }
              disabled={ loading } loading={ loading }>Refresh</Button>
            <Button variant="secondary" onClick={ exportCsv }
              disabled={ !filtered.length }>Export CSV</Button>
          </div>
        </div>

        <div className="summary-cards">
          <div className="summary-card">
            <span className="card-value">{ totals.total }</span>
            <span className="card-label">Total</span>
          </div>
          <div className="summary-card">
            <span className="card-value">{ totals.out }</span>
            <span className="card-label">Outbound</span>
          </div>
          <div className="summary-card">
            <span className="card-value">{ totals.in }</span>
            <span className="card-label">Inbound</span>
          </div>
          <div className="summary-card">
            <span className="card-value card-value-bad">{ totals.failed }</span>
            <span className="card-label">Failed</span>
          </div>
        </div>

        { totals.topReasons.length > 0 && (
          <div className="reasons">
            <span className="reasons-title">Why they failed</span>
            <ul className="reasons-list">
              { totals.topReasons.map( ( [ reason, count ] ) => (
                <li key={ reason }><strong>{ count }</strong> · { reason }</li>
              ) ) }
            </ul>
          </div>
        ) }

        <div className="table-container">
          <table className="logs-table">
            <thead>
              <tr>
                { !lockedChannel && <th>Channel</th> }
                <th>Dir</th>
                <th>Contact</th>
                <th>Content</th>
                <th>Status</th>
                <th>When</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              { loading ? (
                <tr><td colSpan={ 7 } className="state-cell">Loading…</td></tr>
              ) : pageRows.length === 0 ? (
                <tr><td colSpan={ 7 } className="state-cell">No messages found</td></tr>
              ) : pageRows.map( ( row ) => {
                const cb = chBadge( row.channel );
                const sb = stBadge( row.status );
                const waInfo = row.channel === 'whatsapp'
                  && FAILED_STATUSES.includes( row.status )
                  ? describeWaError( row.errorCode, row.errorDetails ) : null;
                return (
                  <tr key={ row.id }>
                    { !lockedChannel && (
                      <td>
                        <span className="badge"
                          style={ { background: cb.bg, color: cb.color } }>{ cb.label }</span>
                      </td>
                    ) }
                    <td><span className="dir">{ row.direction === 'INBOUND' ? 'In' : 'Out' }</span></td>
                    <td className="mono">{ row.contactName || row.contactId }</td>
                    <td className="content" title={ row.content }>
                      { row.content.length > 60 ? `${row.content.slice( 0, 60 )}…` : row.content }
                    </td>
                    <td>
                      <span className="badge"
                        style={ { background: sb.bg, color: sb.color } }>{ sb.label }</span>
                      { waInfo && (
                        <InfoTooltip content={ `${waInfo.title} — ${waInfo.reason}` }>
                          <span className="why">why?</span>
                        </InfoTooltip>
                      ) }
                      { !waInfo && row.errorDetails && FAILED_STATUSES.includes( row.status ) && (
                        <span className="raw-err" title={ row.errorDetails }>detail</span>
                      ) }
                    </td>
                    <td className="when">{ fmt( row.createdAt ) }</td>
                    <td>
                      <Button variant="secondary" size="sm" onClick={ () => remove( row ) }
                        disabled={ deletingId === row.id }
                        loading={ deletingId === row.id }>Delete</Button>
                    </td>
                  </tr>
                );
              } ) }
            </tbody>
          </table>
        </div>

        { totalPages > 1 && (
          <Pagination currentPage={ page } totalPages={ totalPages } onPageChange={ setPage } />
        ) }
      </div>

      <style jsx>{ `
        .logs-page{max-width:1300px;margin:0 auto;padding:20px}
        .filters{display:flex;gap:16px;margin:0 0 20px;align-items:flex-end;flex-wrap:wrap}
        .filter-group{display:flex;flex-direction:column;gap:6px}
        .filter-group label{font-size:14px;color:rgba(0,0,0,.54)}
        .filter-group select{
          font-family:inherit;font-size:15px;color:rgba(0,0,0,.898);background:#fff;
          border:2px solid #e5e7eb;border-radius:13px;padding:9px 12px;min-height:0;
        }
        .filter-group select:focus{outline:none;border-color:#d1f470}
        .filter-actions{display:flex;gap:10px;margin-left:auto}

        .summary-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:0 0 20px}
        .summary-card{
          display:flex;flex-direction:column;gap:2px;background:#fff;
          border:1px solid #e5e7eb;border-radius:13px;padding:16px 18px;
        }
        .card-value{font-size:24px;font-weight:700;color:#000;line-height:1.2}
        .card-value-bad{color:#b91c1c}
        .card-label{font-size:14px;color:rgba(0,0,0,.54)}

        .reasons{
          background:#fffbeb;border:1px solid #b45309;border-radius:13px;
          padding:14px 18px;margin:0 0 20px;
        }
        .reasons-title{font-size:15px;font-weight:600;color:#b45309}
        .reasons-list{margin:8px 0 0;padding-left:18px}
        .reasons-list li{font-size:14px;color:rgba(0,0,0,.898);line-height:1.6}

        .table-container{
          background:#fff;border:1px solid #e5e7eb;border-radius:13px;overflow:hidden;
          margin:0 0 16px;
        }
        .logs-table{width:100%;border-collapse:collapse}
        .logs-table th{
          background:#fafafa;padding:11px 16px;text-align:left;font-size:14px;
          font-weight:600;color:rgba(0,0,0,.54);border-bottom:1px solid #e5e7eb;
        }
        .logs-table td{
          padding:11px 16px;border-bottom:1px solid #e5e7eb;font-size:14px;
          color:rgba(0,0,0,.898);
        }
        .logs-table tr:last-child td{border-bottom:none}

        .badge{
          display:inline-flex;align-items:center;padding:4px 10px;border-radius:50px;
          font-size:13px;font-weight:600;
        }
        .dir{font-size:13px;color:rgba(0,0,0,.54)}
        .mono{font-family:'SF Mono',Monaco,Consolas,monospace;font-size:13px}
        .content{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .when{color:rgba(0,0,0,.54);font-size:13px;white-space:nowrap}
        .why,.raw-err{
          margin-left:8px;font-size:13px;color:#b91c1c;text-decoration:underline;
          cursor:help;
        }
        .state-cell{text-align:center;padding:40px;color:rgba(0,0,0,.54)}

        @media(max-width:800px){
          .summary-cards{grid-template-columns:repeat(2,1fr)}
          .filters{flex-direction:column;align-items:stretch}
          .filter-actions{margin-left:0}
          .table-container{overflow-x:auto}
        }
      `}</style>
    </>
  );

  if ( embedded ) return content;

  return (
    <Layout user={ user } onSignOut={ signOut }>
      { content }
    </Layout>
  );
};

export default MessageLogsPage;
