import { publicActionText } from './publicActionNotices';

/** Protocol statuses select approved copy; arbitrary API text cannot become UI copy. */
export function authStepFeedback ( message: unknown, outcome?: unknown ): { tone: 'info' | 'error'; message: string } | null {
  if ( outcome === 'code_sent' ) return { tone: 'info', message: publicActionText( 'whatsappAccepted' ) };
  if ( outcome === 'retry_code' ) return { tone: 'info', message: publicActionText( 'success' ) };
  return message || outcome ? { tone: 'error', message: publicActionText( 'failure' ) } : null;
}
