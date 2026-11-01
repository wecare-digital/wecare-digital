/**
 * Toast Context - Global Toast Management
 * Provides one action toast at a time across the authenticated Workspace
 */

import React, { createContext, useContext, useState, useCallback, useRef, ReactNode } from 'react';
import Toast, { ToastMessage, ToastType } from '../components/Toast';

interface ToastContextType {
  success: (message: string) => void;
  error: (message: string) => void;
  warning: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const nextToastId = useRef(0);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = String(++nextToastId.current);
    // Show the latest action, never stack competing notifications.
    setToasts([{ id, type, message }]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const value: ToastContextType = {
    success: (message: string) => addToast('success', message),
    error: (message: string) => addToast('error', message),
    warning: (message: string) => addToast('warning', message),
    info: (message: string) => addToast('info', message),
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <Toast toasts={toasts} onRemove={removeToast} />
    </ToastContext.Provider>
  );
};

/** Optional consumer for shared components also rendered outside Workspace. */
export const useOptionalToastContext = (): ToastContextType | null =>
  useContext(ToastContext) ?? null;

export const useToastContext = (): ToastContextType => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToastContext must be used within a ToastProvider');
  }
  return context;
};

export default ToastContext;
