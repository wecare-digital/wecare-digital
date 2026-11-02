/**
 * ONE action-notification state machine and ONE floating host per mounted route.
 *
 * Public and Workspace keep compatibility hooks, but neither creates another
 * timer, queue, visible toast or independent renderer. Contextual validation,
 * uncertain payments/WhatsApp, OTP and Vault access stay inline in their pages.
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import { useRouter } from 'next/router';
import { publicActionText } from '../lib/publicActionNotices';

export type ActionNotificationType = 'success' | 'error' | 'warning' | 'info';
export type ActionNotificationScope = 'public' | 'workspace';

export interface ActionNotificationOptions {
  /** Zero pins a contextual action until replaced, cleared or route changed. */
  durationMs?: number;
  /** Do not let an old async result replace a newer action or new page. */
  ownerId?: number;
}

interface ActiveNotification {
  id: number;
  type: ActionNotificationType;
  message: string;
}

interface ActionNotificationAPI {
  show: (type: ActionNotificationType, message: unknown, options?: ActionNotificationOptions) => number;
  hide: (ownerId?: number) => void;
}

const ActionContext = createContext<ActionNotificationAPI | null>(null);

const INVALID_MESSAGES = new Set(['undefined', 'null', 'nan', '[object object]']);
const FALLBACK: Record<Exclude<ActionNotificationType, 'success'>, string> = {
  error: publicActionText('failure'),
  warning: publicActionText('blocked'),
  info: publicActionText('processing'),
};

/**
 * Avoid showing undefined, objects, stack traces, HTML error pages, tokens or
 * enormous backend error payloads as customer/staff feedback.
 *
 * An invalid SUCCESS is suppressed rather than changed into "Done.": that
 * would falsely claim an operation completed. Errors get approved safe copy.
 */
export function normalizeActionNotification(
  message: unknown, type: ActionNotificationType,
): string | null {
  const text = typeof message === 'string'
    ? message.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim()
    : '';
  const invalid = !text || INVALID_MESSAGES.has(text.toLowerCase())
    || text.length > 320
    || /<\/?(?:html|script|body)[\s>]|<!doctype|\bBearer\s+[A-Za-z0-9_-]{10,}|Traceback \(most recent call last\)|(?:secret|api[_-]?key|access[_-]?token)\s*[:=]/i.test(text);
  if (invalid) return type === 'success' ? null : FALLBACK[type];
  return text;
}

export function useActionNotification(): ActionNotificationAPI {
  const value = useContext(ActionContext);
  if (!value) throw new Error('ActionNotificationProvider is required');
  return value;
}

export function ActionNotificationProvider({
  children, scope,
}: { children: React.ReactNode; scope: ActionNotificationScope }): React.ReactElement {
  const router = useRouter();
  const [active, setActive] = useState<ActiveNotification | null>(null);
  const nextId = useRef(0);
  const activeId = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopTimer = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const hide = useCallback((ownerId?: number) => {
    // A completed old request must not dismiss a newer action's result.
    if (ownerId !== undefined && ownerId !== activeId.current) return;
    stopTimer();
    activeId.current = 0;
    setActive(null);
  }, [stopTimer]);

  const show = useCallback((
    type: ActionNotificationType, message: unknown,
    options: ActionNotificationOptions = {},
  ): number => {
    const normalized = normalizeActionNotification(message, type);
    if (!normalized) return 0;
    if (options.ownerId !== undefined && options.ownerId !== activeId.current) return 0;
    stopTimer();
    const id = ++nextId.current;
    activeId.current = id;
    setActive({ id, type, message: normalized });

    // Public errors are persistent. Workspace errors and warnings also stay
    // readable until dismissed/replaced. Ordinary success/info lasts 5 seconds.
    const requested = options.durationMs;
    const duration = typeof requested === 'number' && Number.isFinite(requested)
      ? Math.min(60000, Math.max(0, requested))
      : (type === 'error' || type === 'warning') ? 0 : 5000;
    if (duration > 0) {
      timer.current = setTimeout(() => {
        if (activeId.current !== id) return;
        activeId.current = 0;
        timer.current = null;
        setActive(current => current?.id === id ? null : current);
      }, duration);
    }
    return id;
  }, [stopTimer]);

  // Never carry "Done." or a pending state across an unrelated route.
  useEffect(() => {
    const onChange = () => hide();
    router.events.on('routeChangeStart', onChange);
    return () => router.events.off('routeChangeStart', onChange);
  }, [router.events, hide]);
  useEffect(() => () => stopTimer(), [stopTimer]);

  const api = useMemo(() => ({ show, hide }), [show, hide]);
  const isWorkspace = scope === 'workspace';

  return (
    <ActionContext.Provider value={api}>
      {children}
      <div
        className={`wc-action-toast-host${isWorkspace ? ' wc-action-toast-host--workspace' : ' wc-public-toast-host'}`}
        data-wc-public-toast-host={isWorkspace ? undefined : 'true'}
        data-wc-unified-action-notice-host="true"
      >
        {active && (
          <div
            key={active.id}
            className={`wc-action-toast${isWorkspace ? ' toast' : ' wc-public-notice is-toast'}`}
            role={active.type === 'error' || active.type === 'warning' ? 'alert' : 'status'}
            aria-live={active.type === 'error' || active.type === 'warning' ? 'assertive' : 'polite'}
            aria-atomic="true"
          >
            <span className="toast-message">{active.message}</span>
            {isWorkspace && (
              <button type="button" className="toast-close"
                aria-label="Dismiss notification" onClick={() => hide(active.id)}>✕</button>
            )}
          </div>
        )}
      </div>
    </ActionContext.Provider>
  );
}
