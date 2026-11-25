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
