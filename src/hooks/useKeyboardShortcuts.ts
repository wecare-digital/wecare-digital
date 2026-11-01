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
export const useNavigationShortcuts = () => {
  const router = useRouter();

  const shortcuts: ShortcutConfig[] = [
    { key: 'd', ctrl: true, action: () => router.push('/workspace/communications?view=inbox'), description: 'Go to Messages' },
    { key: 'm', ctrl: true, action: () => router.push('/workspace/communications?view=inbox&channel=whatsapp'), description: 'Go to Messages' },
    { key: 'c', ctrl: true, shift: true, action: () => router.push('/workspace/customers'), description: 'Go to Contacts' },
    { key: 'b', ctrl: true, action: () => router.push('/workspace/communications?view=manage&section=whatsapp&tool=campaign'), description: 'Go to Campaign' },
    { key: 'p', ctrl: true, shift: true, action: () => router.push('/workspace/payments?view=collect'), description: 'Go to Pay' },
  ];

  useKeyboardShortcuts(shortcuts);
  return shortcuts;
};

// Chat shortcuts hook
export const useChatShortcuts = (callbacks: {
  onSend?: () => void;
  onNewLine?: () => void;
  onEscape?: () => void;
  onSearch?: () => void;
  onTemplate?: () => void;
  onInteractive?: () => void;
}) => {
  const shortcuts: ShortcutConfig[] = [
    ...(callbacks.onSend ? [{ key: 'Enter', ctrl: true, action: callbacks.onSend, description: 'Send message' }] : []),
    ...(callbacks.onEscape ? [{ key: 'Escape', action: callbacks.onEscape, description: 'Close/Cancel' }] : []),
    ...(callbacks.onSearch ? [{ key: 'f', ctrl: true, action: callbacks.onSearch, description: 'Search messages' }] : []),
    ...(callbacks.onTemplate ? [{ key: 't', ctrl: true, shift: true, action: callbacks.onTemplate, description: 'Open templates' }] : []),
    ...(callbacks.onInteractive ? [{ key: 'i', ctrl: true, shift: true, action: callbacks.onInteractive, description: 'Interactive message' }] : []),
  ];

  useKeyboardShortcuts(shortcuts);
  return shortcuts;
};

// Shortcut help modal data
export const getShortcutGroups = () => [
  {
    title: 'Navigation',
    shortcuts: [
      { keys: ['Ctrl', 'D'], description: 'Messages' },
      { keys: ['Ctrl', 'M'], description: 'Messages' },
      { keys: ['Ctrl', 'Shift', 'C'], description: 'Contacts' },
      { keys: ['Ctrl', 'B'], description: 'Campaign' },
      { keys: ['Ctrl', 'Shift', 'P'], description: 'Pay' },
    ],
  },
  {
    title: 'Chat',
    shortcuts: [
      { keys: ['Ctrl', 'Enter'], description: 'Send message' },
      { keys: ['Ctrl', 'F'], description: 'Search messages' },
      { keys: ['Ctrl', 'Shift', 'T'], description: 'Open templates' },
      { keys: ['Ctrl', 'Shift', 'I'], description: 'Interactive message' },
      { keys: ['Esc'], description: 'Close/Cancel' },
    ],
  },
  {
    title: 'General',
    shortcuts: [
      { keys: ['?'], description: 'Show shortcuts' },
      { keys: ['Ctrl', 'K'], description: 'Quick search' },
      { keys: ['Ctrl', 'R'], description: 'Refresh data' },
    ],
  },
];

export default useKeyboardShortcuts;
