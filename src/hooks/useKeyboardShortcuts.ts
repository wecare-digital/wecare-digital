/**
 * Keyboard Shortcuts Hook
 * Global keyboard shortcuts for the app
 */

import { useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';

interface ShortcutConfig {
  key: string;
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  action: () => void;
  description: string;
}

// Global shortcuts registry
const globalShortcuts: ShortcutConfig[] = [];

export const useKeyboardShortcuts = (shortcuts: ShortcutConfig[] = []) => {
  const router = useRouter();

  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    // Don't trigger shortcuts when typing in inputs
    const target = event.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
      // Allow Escape and Ctrl+Enter in inputs
      if (event.key !== 'Escape' && !(event.ctrlKey && event.key === 'Enter')) {
        return;
      }
    }

    const allShortcuts = [...globalShortcuts, ...shortcuts];

    for (const shortcut of allShortcuts) {
      const keyMatch = event.key.toLowerCase() === shortcut.key.toLowerCase();
      const ctrlMatch = shortcut.ctrl ? (event.ctrlKey || event.metaKey) : !event.ctrlKey && !event.metaKey;
      const shiftMatch = shortcut.shift ? event.shiftKey : !event.shiftKey;
      const altMatch = shortcut.alt ? event.altKey : !event.altKey;

      if (keyMatch && ctrlMatch && shiftMatch && altMatch) {
        event.preventDefault();
        shortcut.action();
        return;
      }
    }
  }, [shortcuts]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return { shortcuts: [...globalShortcuts, ...shortcuts] };
};

// Navigation shortcuts hook

// Chat shortcuts hook

// Shortcut help modal data

export default useKeyboardShortcuts;
