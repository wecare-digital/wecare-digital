/**
 * Copy-to-clipboard controls for WhatsApp/Meta diagnostics.
 * One global action notice (no separate "✓ Copied" label or local timer).
 * The fbtrace_id never appears in a notification or a backend request.
 */
import React from 'react';
import { useActionCopy } from '../../hooks/useActionCopy';

export const CopyToClipboardButton: React.FC<{
  text: string; label?: string; size?: 'sm' | 'md';
}> = ({ text, label = 'Copy', size = 'sm' }) => {
  const copy = useActionCopy();
  return (
    <button type="button" onClick={() => { void copy(text); }} style={{
      border: '1px solid #d0d0d0', background: '#fff', color: '#333',
      borderRadius: 6, cursor: 'pointer', fontWeight: 600,
      fontSize: size === 'sm' ? 11 : 13,
      padding: size === 'sm' ? '2px 8px' : '6px 12px',
    }}>
      {label}
    </button>
  );
};

// Meta error trace IDs may be copied to a support ticket; never toast the ID.
export const FbTraceIdCopy: React.FC<{ traceId?: string }> = ({ traceId }) => {
  if (!traceId) return null;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#666' }}>
      <span>fbtrace_id:</span>
      <code style={{ background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>{traceId}</code>
      <CopyToClipboardButton text={traceId} label="Copy" />
    </div>
  );
};
