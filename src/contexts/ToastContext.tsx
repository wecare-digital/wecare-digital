/**
 * Workspace compatibility hooks.
 *
 * The authenticated Workspace and public pages now use exactly the SAME
 * action notification state machine, host and lifecycle implementation.
 * Staff-specific wording remains allowed after runtime message validation.
 * Keep this interface stable for existing Workspace consumers.
 */
import React, { createContext, useCallback, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import {
  ActionNotificationProvider, useActionNotification,
} from './ActionNotificationProvider';
import type { ActionNotificationType } from './ActionNotificationProvider';

interface ToastContextType {
  success: (message: string) => void;
  error: (message: string) => void;
  warning: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

function WorkspaceNotificationAdapter({ children }: { children: ReactNode }) {
  const actions = useActionNotification();
  const send = useCallback((type: ActionNotificationType, message: string) => {
    // Do not stringify an arbitrary object/undefined returned by an API.
    // Shared engine suppresses invalid success and maps unsafe errors to safe copy.
    actions.show(type, message);
  }, [actions]);

  const success = useCallback((message: string) => send('success', message), [send]);
  const error = useCallback((message: string) => send('error', message), [send]);
  const warning = useCallback((message: string) => send('warning', message), [send]);
  const info = useCallback((message: string) => send('info', message), [send]);
  const value = useMemo(() => ({ success, error, warning, info }),
    [success, error, warning, info]);

  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => (
  <ActionNotificationProvider scope="workspace">
    <WorkspaceNotificationAdapter>{children}</WorkspaceNotificationAdapter>
  </ActionNotificationProvider>
);

export const useOptionalToastContext = (): ToastContextType | null =>
  useContext(ToastContext) ?? null;

export const useToastContext = (): ToastContextType => {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToastContext must be used within a ToastProvider');
  return context;
};

export default ToastContext;
