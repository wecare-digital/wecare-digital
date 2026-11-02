/**
 * Public compatibility API: six strictly typed status keys, backed by the
 * ONE shared ActionNotificationProvider state machine and floating host.
 * Never allow raw provider/API text or whatsappFailed into a transient toast.
 */
import React, { createContext, useCallback, useContext, useMemo } from 'react';
import { ActionNotificationProvider, useActionNotification } from '../../contexts/ActionNotificationProvider';
import type { ActionNotificationType } from '../../contexts/ActionNotificationProvider';
import { publicActionText } from '../../lib/publicActionNotices';
import type { PublicActionNoticeKind } from '../../lib/publicActionNotices';
import type { PublicNoticeTone } from './PublicNotice';

export interface PublicToastOptions {
  tone?: PublicNoticeTone;
  /** Zero keeps a processing state until the owner replaces/clears it. */
  durationMs?: number;
}

type PublicToastKind = Exclude<PublicActionNoticeKind, 'whatsappFailed'>;

interface PublicToastContextValue {
  showToast: (kind: PublicToastKind, options?: PublicToastOptions) => number;
  hideToast: (id?: number) => void;
}

const PublicContext = createContext<PublicToastContextValue | null>(null);

export function useOptionalPublicToast(): PublicToastContextValue | null {
  return useContext(PublicContext);
}

export function usePublicToast(): PublicToastContextValue {
  const value = useOptionalPublicToast();
  if (!value) throw new Error('usePublicToast requires PublicToastProvider');
  return value;
}

function PublicNotificationAdapter({ children }: { children: React.ReactNode }) {
  const actions = useActionNotification();
  const showToast = useCallback((
    kind: PublicToastKind, options: PublicToastOptions = {},
  ): number => {
    // An unsafe/unknown key, including an unconfirmed WhatsApp send, is NEVER
    // converted to a floating message even if called from plain JavaScript.
    if (kind === 'whatsappFailed') return 0;
    const message = publicActionText(kind);
    if (typeof message !== 'string' || !message) return 0;

    const type: ActionNotificationType =
      options.tone === 'error' ? 'error'
        : options.tone === 'success' ? 'success'
          : kind === 'success' || kind === 'whatsappAccepted' ? 'success'
            : kind === 'failure' || kind === 'blocked' ? 'error' : 'info';

    return actions.show(type, message, { durationMs: options.durationMs });
  }, [actions]);
  const hideToast = useCallback((id?: number) => actions.hide(id), [actions]);
  const value = useMemo(() => ({ showToast, hideToast }), [showToast, hideToast]);

  return <PublicContext.Provider value={value}>{children}</PublicContext.Provider>;
}

export default function PublicToastProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <ActionNotificationProvider scope="public">
      <PublicNotificationAdapter>{children}</PublicNotificationAdapter>
    </ActionNotificationProvider>
  );
}
