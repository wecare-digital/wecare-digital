import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { listInboxMessagePage, type InboxMessagePage, type Message } from '../api/domains/messaging';
import { listContactsResult, type Contact } from '../api/domains/contacts';
import type { ApiFailure } from '../api/core';
import { displacedInboxRows, inboxConversationKey, inboxHeadMayHaveGap, mergeInboxMessages, refreshInboxHead } from '../lib/inbox-feed';

const REFRESH_MS = 30_000;
const SAMPLE_REFRESH_MS = 120_000;

interface RequestState {
  key: string;
  head: Message[];
  archive: Message[];
  next: string | null;
  historyNeedsReload: boolean;
  paged: boolean;
  legacy: boolean;
  sampled: boolean;
  lastHeadRead: number;
  headFailure: ApiFailure | null;
  olderFailure: ApiFailure | null;
  headUnavailable: string[];
  olderUnavailable: string[];
  ready: boolean;
  refreshing: boolean;
  loadingOlder: boolean;
}

function initial ( key: string ): RequestState {
  return {
    key, head: [], archive: [], next: null, historyNeedsReload: false, paged: false, legacy: false, sampled: false, lastHeadRead: 0,
    headFailure: null, olderFailure: null, headUnavailable: [], olderUnavailable: [],
    ready: false, refreshing: false, loadingOlder: false,
  };
}

/** Shared Recent Activity and saved-contact thread data for both Inbox screens. */
export function useInboxMessageFeed ( { contactId, channel, active = true }: {
  contactId?: string; channel?: string; active?: boolean;
} = {} ) {
  const scope = JSON.stringify( [ contactId || '', channel || 'ALL', active ] );
  const [ state, setState ] = useState<RequestState>( () => initial( scope ) );
  const current = useRef<RequestState | null>( null );
  const removed = useRef( new Set<string>() );

  const read = useCallback( async ( older = false ) => {
    const run = current.current;
    if ( !active || !run || run.key !== scope || run.refreshing || run.loadingOlder ) return false;
    if ( older && ( !run.next || run.historyNeedsReload ) ) return false;
    const commit = ( patch: Partial<RequestState> ) => {
      Object.assign( run, patch );
      setState( { ...run } );
    };
    commit( older ? { loadingOlder: true, olderFailure: null } : { refreshing: true, headFailure: null } );
    const result = await listInboxMessagePage( { contactId, channel, cursor: older ? run.next ?? undefined : undefined } );
    if ( current.current !== run ) return false;
    if ( !result.ok ) {
      const cursorRetired = older && ( result.failure.status === 400 || result.failure.status === 409 );
      commit( older ? { loadingOlder: false, olderFailure: result.failure,
        historyNeedsReload: run.historyNeedsReload || cursorRetired }
        : { refreshing: false, headFailure: result.failure, ready: true } );
      return false;
    }
    const data: InboxMessagePage = result.data;
    const rows = data.messages.filter( row => !removed.current.has( row.id ) );
    if ( older ) {
      commit( {
        archive: mergeInboxMessages( run.archive, rows ),
        next: data.nextCursor, legacy: data.legacy, paged: true,
        olderUnavailable: data.unavailableChannels, loadingOlder: false,
      } );
    } else {
      const limited = data.legacy || data.sampled;
      const archive = limited ? [] : run.paged
        ? mergeInboxMessages( run.archive, displacedInboxRows( run.head, rows, !contactId, !!data.nextCursor ) )
        : run.archive;
      const historyNeedsReload = !limited && ( run.historyNeedsReload
        || ( run.paged && !!data.nextCursor && inboxHeadMayHaveGap( run.head, rows, !contactId ) ) );
      commit( {
        head: refreshInboxHead( run.head, rows, data.unavailableChannels ), archive,
        historyNeedsReload, paged: !limited && run.paged, lastHeadRead: Date.now(),
        headUnavailable: data.unavailableChannels, ready: true, refreshing: false,
        legacy: data.legacy, sampled: data.sampled,
        next: limited ? null : run.paged ? run.next : data.nextCursor,
        ...( limited ? { olderFailure: null, olderUnavailable: [] } : {} ),
      } );
    }
    return true;
  }, [ active, channel, contactId, scope ] );

  useEffect( () => {
    const run = initial( scope );
    current.current = run;
    void read();
    const poll = () => {
      if ( document.hidden || ( run.sampled && Date.now() - run.lastHeadRead < SAMPLE_REFRESH_MS ) ) return;
      void read();
    };
    if ( !active ) return () => { if ( current.current === run ) current.current = null; };
    const timer = setInterval( poll, REFRESH_MS );
    return () => {
      clearInterval( timer );
      if ( current.current === run ) current.current = null;
    };
  }, [ active, scope, read ] );

  const removeMessage = useCallback( ( id: string ) => {
    removed.current.add( id );
    const run = current.current;
    if ( !run ) return;
    run.head = run.head.filter( row => row.id !== id );
    run.archive = run.archive.filter( row => row.id !== id );
    setState( { ...run } );
  }, [] );

  const removeConversation = useCallback( ( key: string ) => {
    const run = current.current;
    if ( !run ) return;
    const keep = ( row: Message ) => {
      if ( inboxConversationKey( row ) !== key ) return true;
      removed.current.add( row.id );
      return false;
    };
    run.head = run.head.filter( keep );
    run.archive = run.archive.filter( keep );
    setState( { ...run } );
  }, [] );

  const reloadHistory = useCallback( () => {
    const run = current.current;
    if ( !run || run.refreshing || run.loadingOlder ) return;
    Object.assign( run, {
      archive: [], next: null, paged: false,
      historyNeedsReload: false, olderFailure: null, olderUnavailable: [],
    } );
    setState( { ...run } );
    void read();
  }, [ read ] );

  const view = useMemo( () => state.key === scope ? state : initial( scope ), [ scope, state ] );
  const messages = useMemo( () => mergeInboxMessages( view.archive, view.head ), [ view.archive, view.head ] );
  return {
    messages,
    loading: active && !view.ready,
    loadingOlder: view.loadingOlder,
    refreshing: view.refreshing,
    failure: view.headFailure || view.olderFailure,
    unavailableChannels: [ ...new Set( [ ...view.headUnavailable, ...view.olderUnavailable ] ) ],
    legacy: view.legacy,
    sampled: view.sampled,
    hasOlder: !!view.next && !view.historyNeedsReload,
    historyNeedsReload: view.historyNeedsReload,
    reloadHistory,
    refresh: read,
    removeMessage,
    removeConversation,
  };
}

export function useInboxContactDirectory () {
  const [ contacts, setContacts ] = useState<Contact[]>( [] );
  const [ contactFailure, setContactFailure ] = useState<ApiFailure | null>( null );
  const inFlight = useRef(false);
  const refreshContacts = useCallback( async () => {
    if ( inFlight.current ) return;
    inFlight.current = true;
    try {
      const result = await listContactsResult();
      if ( result.ok ) {
        setContacts( result.data );
        setContactFailure( null );
      } else setContactFailure( result.failure );
    } finally {
      inFlight.current = false;
    }
  }, [] );
  const removeContact = useCallback( ( id: string ) => {
    setContacts( current => current.filter( contact => contact.contactId !== id ) );
  }, [] );
  useEffect( () => { void refreshContacts(); }, [ refreshContacts ] );
  return { contacts, contactFailure, refreshContacts, removeContact };
}
