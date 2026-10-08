/**
 * Tasks — the work queue, built on data that actually exists.
 *
 * WHAT THIS REPLACED, AND WHY IT MATTERS
 * --------------------------------------
 * This route was a 33-line `ComingSoon` stub promising six features: create and
 * assign tasks, set priorities and deadlines, track progress, team collaboration,
 * task templates, automated reminders.
 *
 * There is **no tasks backend in this repository**. No `TasksTable`, no task API,
 * nothing. So five of those six promises had nothing behind them, and a screen built
 * to deliver them would have been fabrication — the same defect as the agent panel
 * advertising eighteen refused tools, the audit sink that never wrote a row, and the
 * `createInvoice` that returned success and wrote nothing.
 *
 * WHAT DOES EXIST is a real, already-written team-inbox model: `conversation-meta`,
 * with `status` (open / pending / resolved), `assignee`, `tags` and `notes`. The
 * unified inbox reads and writes it on every conversation. `GET /inbox/meta` returns
 * all of it. That is a work queue, so that is what this page is.
 *
 * HONEST ABOUT THE GAP. The model has no priority, no due date, no templates and no
 * reminders, and this page does not pretend otherwise — it says so, on screen,
 * rather than rendering an empty Priority column that implies the field exists and
 * is unset. An absent capability stated plainly is worth more than a column that
 * lies quietly.
 *
 * Every row links to the conversation it came from, because a task here is not an
 * abstraction over the conversation — it IS the conversation, seen from the queue.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import Button from '../../../components/ui/Button';
import Select, { type SelectOption } from '../../../components/ui/Select';
import { useToastContext } from '../../../contexts/ToastContext';
import * as api from '../../../api/client';

/* LAYOUT ONLY - `.tk-filters` is a flex row and `.tk-fg` a column, so the field needs a
   width of its own: the trigger shows the selected label while a native select sized itself
   to its widest option, and an assignee name is as wide as the longest person. */
const ASSIGNEE_SELECT_STYLE: React.CSSProperties = { width: 220 };

interface PageProps { signOut?: () => void; user?: any; }

type Status = 'open' | 'pending' | 'resolved';

const STATUSES: { id: Status; label: string; hint: string }[] = [
  { id: 'open', label: 'Open', hint: 'Nobody has picked this up yet' },
  { id: 'pending', label: 'Pending', hint: 'Waiting on someone or something' },
  { id: 'resolved', label: 'Resolved', hint: 'Done, kept for the record' },
];

const STATUS_PAINT: Record<Status, { bg: string; fg: string }> = {
  open: { bg: '#fffbeb', fg: '#b45309' },
  pending: { bg: '#eff6ff', fg: '#1d4ed8' },
  resolved: { bg: '#f0fdf4', fg: '#15803d' },
};

const UNASSIGNED = '__unassigned__';

const TasksPage: React.FC<PageProps> = ( { signOut, user } ) => {
  const toast = useToastContext();
  const [ rows, setRows ] = useState<api.ConversationMeta[]>( [] );
  const [ names, setNames ] = useState<Record<string, string>>( {} );
  const [ loading, setLoading ] = useState( true );
  const [ statusFilter, setStatusFilter ] = useState<string>( 'all' );
  const [ assigneeFilter, setAssigneeFilter ] = useState<string>( 'all' );
  const [ savingId, setSavingId ] = useState<string | null>( null );

  const load = useCallback( async () => {
    setLoading( true );
    try
    {
      // Contacts resolve a conversationId into a person's name. Without it every
      // row reads as an opaque id, which is what made the old logs pages unusable.
      const [ meta, contacts ] = await Promise.all( [
        api.listConversationMeta(),
        api.listContacts().catch( () => [] as api.Contact[] ),
      ] );
      const byId: Record<string, string> = {};
      ( contacts || [] ).forEach( ( c ) => {
        byId[ c.contactId ] = c.name || c.phone || c.email || c.contactId;
      } );
      setNames( byId );
      setRows( meta || [] );
    } catch
    {
      toast.error( 'Could not load the work queue' );
    } finally
    {
      setLoading( false );
    }
  }, [ toast ] );

  useEffect( () => { load(); }, [ load ] );

  const assignees = useMemo( () => {
    const set = new Set<string>();
    rows.forEach( ( r ) => set.add( r.assignee?.trim() || UNASSIGNED ) );
    return Array.from( set ).sort();
  }, [ rows ] );

  /* The derived list, memoised. 'all' is the filter's own sentinel and was its first
     <option>, so it stays first and keeps its value and its text. */
  const assigneeOptions: SelectOption[] = useMemo(
    () => [
      { value: 'all', label: 'Everyone' },
      ...assignees.map( a => ( { value: a, label: a === UNASSIGNED ? 'Unassigned' : a } ) ),
    ],
    [ assignees ]
  );

  const filtered = useMemo( () => rows.filter( ( r ) => {
    if ( statusFilter !== 'all' && r.status !== statusFilter ) return false;
    if ( assigneeFilter !== 'all' )
    {
      const who = r.assignee?.trim() || UNASSIGNED;
      if ( who !== assigneeFilter ) return false;
    }
    return true;
  } ), [ rows, statusFilter, assigneeFilter ] );

  const counts = useMemo( () => {
    const out: Record<string, number> = { open: 0, pending: 0, resolved: 0 };
    rows.forEach( ( r ) => { out[ r.status ] = ( out[ r.status ] || 0 ) + 1; } );
    return out;
  }, [ rows ] );

  const move = useCallback( async ( row: api.ConversationMeta, status: Status ) => {
    if ( savingId ) return;
    setSavingId( row.conversationId );
    try
    {
      const updated = await api.updateConversationMeta( row.conversationId, { status } );
      if ( updated )
      {
        // Patch in place rather than refetching: the list is a scan, and a full
        // reload to change one field makes the queue feel broken under load.
        setRows( ( prev ) => prev.map( ( r ) =>
          r.conversationId === row.conversationId ? { ...r, status } : r ) );
        toast.success( `Moved to ${status}` );
      } else toast.error( 'Could not update' );
    } catch { toast.error( 'Could not update' ); }
    finally { setSavingId( null ); }
  }, [ savingId, toast ] );

  const label = ( id: string ) => names[ id ] || id;
  const when = ( ts?: number ) => ts
    ? new Date( ts ).toLocaleDateString( 'en-IN', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' } )
    : '—';

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO
        title="Tasks"
        description="The team work queue: conversations by status and assignee."
        noindex
      />
      <div className="tk-page">
        <div className="tk-inner">
          <header className="tk-head">
            <h1 className="tk-h1">Tasks</h1>
            <p className="tk-sub">
              Conversations that need someone, by status and assignee. Updating a
              task here is the same record the inbox shows.
            </p>
          </header>

          <div className="tk-cards">
            { STATUSES.map( ( s ) => (
              <button
                key={ s.id }
                type="button"
                className={ statusFilter === s.id ? 'tk-card tk-card-on' : 'tk-card' }
                onClick={ () => setStatusFilter( statusFilter === s.id ? 'all' : s.id ) }
              >
                <span className="tk-card-n">{ counts[ s.id ] ?? 0 }</span>
                <span className="tk-card-l">{ s.label }</span>
                <span className="tk-card-h">{ s.hint }</span>
              </button>
            ) ) }
          </div>

          <div className="tk-filters">
            <div className="tk-fg">
              { /*
                 * SHAPE (a), design 5.2 and 1.7(b). The external <label> bound by id is GONE,
                 * along with the id itself, and Select renders the visible span and the
                 * aria-labelledby wiring instead. Keeping them would have left this control
                 * announcing only "Everyone" or a person's name: the trigger is a <button>,
                 * and per HTML-AAM a button takes its accessible name from its CONTENTS, so an
                 * external label bound by id is not a name source for it the way it is for a
                 * native control. One component now owns the association instead of two lines
                 * that have to agree.
                 */ }
              <Select label="Assignee" value={ assigneeFilter }
                onChange={ v => setAssigneeFilter( v ) }
                options={ assigneeOptions } style={ ASSIGNEE_SELECT_STYLE } />
            </div>
            { statusFilter !== 'all' && (
              <Button variant="secondary" onClick={ () => setStatusFilter( 'all' ) }>
                Clear status filter
              </Button>
            ) }
            <div className="tk-actions">
              <Button variant="secondary" icon="refresh" onClick={ load }
                disabled={ loading } loading={ loading }>Refresh</Button>
            </div>
          </div>

          <div className="tk-table-wrap">
            <table className="tk-table">
              <thead>
                <tr>
                  <th>Conversation</th>
                  <th>Status</th>
                  <th>Assignee</th>
                  <th>Tags</th>
                  <th>Notes</th>
                  <th>Updated</th>
                  <th aria-label="Move" />
                </tr>
              </thead>
              <tbody>
                { loading ? (
                  <tr><td colSpan={ 7 } className="tk-state">Loading…</td></tr>
                ) : filtered.length === 0 ? (
                  <tr>
                    <td colSpan={ 7 } className="tk-state">
                      { rows.length === 0
                        ? 'No conversations have a status or assignee yet. Set one from the inbox and it appears here.'
                        : 'Nothing matches these filters.' }
                    </td>
                  </tr>
                ) : filtered.map( ( r ) => {
                  const paint = STATUS_PAINT[ r.status ] || STATUS_PAINT.open;
                  return (
                    <tr key={ r.conversationId }>
                      <td>
                        <Link href={ `/workspace/engage/inbox?contact=${encodeURIComponent( r.conversationId )}` }
                          className="tk-link">{ label( r.conversationId ) }</Link>
                      </td>
                      <td>
                        <span className="tk-badge"
                          style={ { background: paint.bg, color: paint.fg } }>
                          { r.status }
                        </span>
                      </td>
                      <td className="tk-who">
                        { r.assignee?.trim() || <span className="tk-muted">Unassigned</span> }
                      </td>
                      <td>
                        { r.tags?.length
                          ? r.tags.map( ( t ) => <span key={ t } className="tk-tag">{ t }</span> )
                          : <span className="tk-muted">—</span> }
                      </td>
                      <td className="tk-muted">{ r.notes?.length || 0 }</td>
                      <td className="tk-when">{ when( r.updatedAt ) }</td>
                      <td>
                        <div className="tk-move">
                          { STATUSES.filter( ( s ) => s.id !== r.status ).map( ( s ) => (
                            <button key={ s.id } type="button" className="tk-move-btn"
                              disabled={ savingId === r.conversationId }
                              onClick={ () => move( r, s.id ) }>
                              { s.label }
                            </button>
                          ) ) }
                        </div>
                      </td>
                    </tr>
                  );
                } ) }
              </tbody>
            </table>
          </div>

          {/* Stated, not stubbed. The old ComingSoon promised priorities, deadlines,
              templates and reminders; none of them exist in conversation-meta, and
              rendering an empty Priority column would imply the field is there and
              merely unset. */ }
          <p className="tk-gap">
            This queue is the conversation-meta record: status, assignee, tags and
            notes. Priorities, due dates, templates and reminders are not stored
            anywhere yet, so they are absent rather than empty.
          </p>
        </div>

        <style jsx>{ `
          .tk-page{
            font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
            background:#fafafa;min-height:100%;padding:40px 0;box-sizing:border-box;
          }
          .tk-inner{max-width:1300px;margin:0 auto;padding:0 24px;box-sizing:border-box}
          .tk-head{margin:0 0 28px}
          .tk-h1{
            font-size:clamp(32px,4.2vw,54px);font-weight:700;line-height:1.04;
            letter-spacing:-1.875px;color:rgba(0,0,0,.95);margin:0 0 14px;
          }
          .tk-sub{
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);margin:0;max-width:620px;
          }

          .tk-cards{
            display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:0 0 22px;
          }
          /* 2px because each card has a hover that swaps to lime - the contract's
             hairline rule. They are filters, so they are genuinely interactive. */
          .tk-card{
            display:flex;flex-direction:column;gap:2px;text-align:left;
            font-family:inherit;background:#fff;border:2px solid #e5e7eb;
            border-radius:13px;padding:16px 18px;cursor:pointer;transition:all .2s ease;
          }
          .tk-card:hover{border-color:#d1f470}
          /* Selected is one of our own states: lime fill, dark-green type. */
          .tk-card-on{background:#d1f470;border-color:#d1f470}
          .tk-card-on .tk-card-l,.tk-card-on .tk-card-n{color:#1a3a2a}
          .tk-card-on .tk-card-h{color:#1a3a2a}
          .tk-card-n{font-size:24px;font-weight:700;color:#000;line-height:1.2}
          .tk-card-l{font-size:17px;font-weight:600;color:rgba(0,0,0,.898)}
          .tk-card-h{font-size:14px;color:rgba(0,0,0,.54)}

          .tk-filters{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;margin:0 0 20px}
          .tk-fg{display:flex;flex-direction:column;gap:6px}
          /* These three now match no element: the one select in this file became a
             ui/Select, whose own box comes from form-controls.css, and its label is a
             <span class="ui-field-label"> rather than a <label>. Left in place, harmless,
             rather than deleted in a batch that is only supposed to move controls. The
             label's type therefore moves from 14px to .ui-field-label's own, which is a
             deliberate and recorded appearance change. */
          .tk-fg label{font-size:14px;color:rgba(0,0,0,.54)}
          .tk-fg select{
            font-family:inherit;font-size:15px;color:rgba(0,0,0,.898);background:#fff;
            border:2px solid #e5e7eb;border-radius:13px;padding:9px 12px;min-height:0;
          }
          .tk-fg select:focus{outline:none;border-color:#d1f470}
          .tk-actions{margin-left:auto}

          .tk-table-wrap{
            background:#fff;border:1px solid #e5e7eb;border-radius:13px;
            overflow:hidden;margin:0 0 18px;
          }
          .tk-table{width:100%;border-collapse:collapse}
          .tk-table th{
            background:#fafafa;padding:11px 16px;text-align:left;font-size:14px;
            font-weight:600;color:rgba(0,0,0,.54);border-bottom:1px solid #e5e7eb;
          }
          .tk-table td{
            padding:11px 16px;border-bottom:1px solid #e5e7eb;font-size:14px;
            color:rgba(0,0,0,.898);vertical-align:middle;
          }
          .tk-table tr:last-child td{border-bottom:none}

          .tk-link{color:#1a3a2a;text-decoration:underline}
          .tk-badge{
            display:inline-flex;align-items:center;padding:4px 12px;border-radius:50px;
            font-size:13px;font-weight:600;text-transform:capitalize;
          }
          .tk-tag{
            display:inline-flex;align-items:center;padding:3px 9px;margin:0 4px 2px 0;
            border-radius:50px;font-size:13px;background:rgba(209,244,112,.22);
            color:#1a3a2a;
          }
          .tk-who{font-size:14px}
          .tk-muted{color:rgba(0,0,0,.54)}
          .tk-when{color:rgba(0,0,0,.54);font-size:13px;white-space:nowrap}
          .tk-state{text-align:center;padding:40px;color:rgba(0,0,0,.54)}

          .tk-move{display:flex;gap:6px}
          .tk-move-btn{
            font-family:inherit;font-size:13px;font-weight:500;
            color:rgba(0,0,0,.898);background:#fff;border:2px solid #e5e7eb;
            border-radius:50px;padding:6px 14px;cursor:pointer;transition:all .2s ease;
          }
          .tk-move-btn:hover:not(:disabled){border-color:#d1f470;color:#1a3a2a}
          .tk-move-btn:disabled{opacity:.5;cursor:not-allowed}

          .tk-gap{
            font-size:14px;line-height:1.5;color:rgba(0,0,0,.54);margin:0;
            max-width:720px;
          }

          @media(max-width:800px){
            .tk-cards{grid-template-columns:1fr}
            .tk-table-wrap{overflow-x:auto}
            .tk-sub{font-size:17px}
          }
          @media(prefers-reduced-motion:reduce){
            .tk-card,.tk-move-btn{transition:none}
          }
        `}</style>
      </div>
    </Layout>
  );
};

export default TasksPage;
