/**
 * One Copy success/failure owner for public pages and Workspace.
 *
 * Clipboard writes are awaited. There is no independent Copied label, local
 * timer, second live region, fallback success claim or unhandled Promise.
 * Select-and-keyboard-copy recovery remains in order-specific call sites that
 * provide a visible selectable identifier.
 */
import { useCallback } from 'react';
import { useOptionalPublicToast } from '../components/public/PublicToastProvider';
import { useOptionalToastContext } from '../contexts/ToastContext';
import { publicActionText } from '../lib/publicActionNotices';

export function useActionCopy(): (value: string) => Promise<boolean> {
  const publicToast = useOptionalPublicToast();
  const workspaceToast = useOptionalToastContext();

  return useCallback(async (value: string): Promise<boolean> => {
    try {
      if (typeof value !== 'string' || !value.trim()
        || typeof navigator === 'undefined'
        || typeof navigator.clipboard?.writeText !== 'function') {
        throw new Error('Clipboard unavailable');
      }
      await navigator.clipboard.writeText(value);
      if (publicToast) publicToast.showToast('success');
      else workspaceToast?.success(publicActionText('success'));
      return true;
    } catch {
      if (publicToast) publicToast.showToast('failure');
      else workspaceToast?.error(publicActionText('failure'));
      return false;
    }
  }, [publicToast, workspaceToast]);
}
