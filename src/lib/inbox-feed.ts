import type { Message } from '../api/domains/messaging';

export function inboxConversationKey ( message: Message ): string {
  return message.contactId || message.senderPhone || message.receivingPhone || 'unknown';
}

export function mergeInboxMessages ( ...groups: ReadonlyArray<ReadonlyArray<Message>> ): Message[] {
  const rows = new Map<string, Message>();
  for ( const group of groups ) {
    for ( const message of group ) {
      const id = message.id || message.messageId;
      if ( id ) rows.set( id, message );
    }
  }
  return Array.from( rows.values() ).sort( ( a, b ) =>
    Date.parse( b.timestamp ) - Date.parse( a.timestamp ) || a.id.localeCompare( b.id ) );
}

/** Keep stale previews only for channels the new read explicitly failed to query. */
export function refreshInboxHead ( previous: Message[], recent: Message[], unavailableChannels: string[] ): Message[] {
  const unavailable = new Set( unavailableChannels.map( channel => channel.toLowerCase() ) );
  return mergeInboxMessages( previous.filter( row => unavailable.has( row.channel.toLowerCase() ) ), recent );
}

/** Keep rows that slid out of a refreshed head if the user already opened older pages. */
export function displacedInboxRows ( previous: Message[], recent: Message[] ): Message[] {
  const cutoff = new Map<string, number>();
  for ( const row of recent ) {
    const ts = Date.parse( row.timestamp );
    if ( Number.isFinite( ts ) ) cutoff.set( row.channel, Math.min( cutoff.get( row.channel ) ?? ts, ts ) );
  }
  return previous.filter( row => Date.parse( row.timestamp ) < ( cutoff.get( row.channel ) ?? -Infinity ) );
}

/** A refreshed head without shared IDs may have overtaken a previously paged cursor. */
export function inboxHeadMayHaveGap ( previous: Message[], recent: Message[], partitionedByChannel: boolean ): boolean {
  const groupKey = ( row: Message ) => partitionedByChannel ? row.channel : '*';
  const oldGroups = new Map<string, { ids: Set<string>; newest: number }>();
  for ( const row of previous ) {
    const group = groupKey( row );
    const old = oldGroups.get( group ) ?? { ids: new Set<string>(), newest: -Infinity };
    old.ids.add( row.id );
    old.newest = Math.max( old.newest, Date.parse( row.timestamp ) || 0 );
    oldGroups.set( group, old );
  }
  const freshGroups = new Map<string, { overlaps: boolean; newest: number }>();
  for ( const row of recent ) {
    const group = groupKey( row );
    const fresh = freshGroups.get( group ) ?? { overlaps: false, newest: -Infinity };
    fresh.overlaps ||= oldGroups.get( group )?.ids.has( row.id ) ?? false;
    fresh.newest = Math.max( fresh.newest, Date.parse( row.timestamp ) || 0 );
    freshGroups.set( group, fresh );
  }
  return Array.from( freshGroups ).some( ( [ group, fresh ] ) => {
    const old = oldGroups.get( group );
    return old && !fresh.overlaps && fresh.newest >= old.newest;
  } );
}
