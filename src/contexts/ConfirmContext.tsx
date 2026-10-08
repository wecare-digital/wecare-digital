/**
 * Confirm Dialog Context
 * Unified confirm dialog for the entire app.
 * Site theme: Lime #d1f470 + Dark #1a3a2a.
 *
 * Usage:
 *   const confirm = useConfirm();
 *   if (await confirm('Delete 25 contacts?')) { ... }
 *   if (await confirm({ title: 'Hard Delete', message: <p>Gone forever</p>, confirmInput: 'DELETE', danger: true })) { ... }
 *
 *   const prompt = usePromptDialog();
 *   const reason = await prompt({ label: 'Why is this being withdrawn?', minLength: 10, multiline: true });
 *   if (reason === null) return;   // cancelled, Escape, or backdrop
 *
 * WHY THE PROMPT LIVES HERE RATHER THAN IN A PROVIDER OF ITS OWN. The dialog shell, the
 * Escape/Enter handling, the backdrop click, the type-to-confirm field and the autoFocus
 * behaviour all already exist in this file. A second modal implementation is a second thing
 * to keep in step, and the two would drift the first time one of them was fixed.
 */

import React, { createContext, useContext, useState, useCallback, useRef, useEffect, ReactNode } from 'react';

interface ConfirmOptions {
  title?: string;
  message: ReactNode;
  confirmText?: string;
  cancelText?: string;
  confirmInput?: string;   // If set, user must type this exact string to enable confirm
  danger?: boolean;        // Red-tinted destructive action styling
}

/**
 * Options for the free-text prompt — the one thing neither existing system could do.
 *
 * `message` is OPTIONAL and both live call sites omit it. A `window.prompt` carries exactly
 * one string, so making `message` required would force a choice between rendering that
 * sentence twice (once as body copy, once as the field label) and inventing body copy.
 * `label` carries the sentence verbatim instead, and `helper` states the constraint the
 * component enforces rather than restating the question.
 */
export type PromptOptions = {
  title?: string;
  message?: ReactNode;
  label: string;           // Visible <label> for the field. Required.
  placeholder?: string;
  initialValue?: string;
  required?: boolean;      // Default true: an empty value disables confirm
  minLength?: number;      // Default 0: confirm disabled until value.trim().length >= minLength
  maxLength?: number;      // Default 500
  helper?: ReactNode;      // Rendered under the field; defaults to the minLength hint
  confirmText?: string;
  cancelText?: string;
  multiline?: boolean;     // Default false -> <input>; true -> <textarea rows=3>
};

type ConfirmFn = (messageOrOptions: string | ConfirmOptions) => Promise<boolean>;
type PromptFn = (options: PromptOptions) => Promise<string | null>;

/**
 * The context value is an OBJECT of two functions, not a bare ConfirmFn: a second hook cannot
 * reach a second function through a value that is one function. ConfirmFn's own
 * Promise<boolean> signature is deliberately unchanged — it has roughly forty call sites and
 * widening it to carry a value would touch every one of them for the sake of two consumers.
 * A caller wanting a boolean should not have to read a union.
 */
const ConfirmContext = createContext<{ confirm: ConfirmFn; prompt: PromptFn } | undefined>(undefined);

interface DialogState {
  isOpen: boolean;
  title: string;
  message: ReactNode;
  confirmText: string;
  cancelText: string;
  confirmInput?: string;
  danger: boolean;
  prompt?: PromptOptions;
}

const PROMPT_FIELD_ID = 'confirm-prompt-input';
const PROMPT_HELPER_ID = 'confirm-prompt-helper';

export const ConfirmProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [dialog, setDialog] = useState<DialogState>({
    isOpen: false, title: 'Confirm', message: '', confirmText: 'Confirm', cancelText: 'Cancel', danger: false,
  });
  const [inputValue, setInputValue] = useState('');
  const resolveRef = useRef<((value: boolean | string | null) => void) | null>(null);
  /**
   * The element that opened the dialog, so focus can go back to it on close.
   *
   * Focus was never restored before. With a text field that gap becomes visible: a keyboard
   * operator who types a reason and then cancels is dropped at the top of the document with
   * no idea where they were. Fixing it here benefits all ~40 existing useConfirm sites too.
   */
  const openerRef = useRef<HTMLElement | null>(null);

  // Reset input when dialog closes
  useEffect(() => {
    if (!dialog.isOpen) setInputValue('');
  }, [dialog.isOpen]);

  const captureOpener = useCallback(() => {
    const active = typeof document === 'undefined' ? null : document.activeElement;
    openerRef.current = active instanceof HTMLElement ? active : null;
  }, []);

  const confirm: ConfirmFn = useCallback((messageOrOptions) => {
    const opts: ConfirmOptions = typeof messageOrOptions === 'string'
      ? { message: messageOrOptions } : messageOrOptions;

    const msgStr = typeof opts.message === 'string' ? opts.message.toLowerCase() : '';
    const isDestructive = opts.danger || ['delete', 'remove', 'clear', 'cancel', 'reset'].some(k => msgStr.includes(k));

    captureOpener();
    setDialog({
      isOpen: true,
      title: opts.title || (isDestructive ? 'Are you sure?' : 'Confirm'),
      message: opts.message,
      confirmText: opts.confirmText || (isDestructive ? 'Yes, proceed' : 'Confirm'),
      cancelText: opts.cancelText || 'Cancel',
      confirmInput: opts.confirmInput,
      danger: opts.danger || false,
      prompt: undefined,
    });

    // The ref is widened to carry a string for the prompt, so the stored resolver narrows
    // back here rather than being assigned directly — assigning a (boolean) => void to a
    // (boolean | string | null) => void slot does not type-check, and casting would hide a
    // real mismatch if handleClose ever changed.
    return new Promise<boolean>((resolve) => {
      resolveRef.current = value => resolve(value === true);
    });
  }, [captureOpener]);

  const prompt: PromptFn = useCallback((options) => {
    captureOpener();
    setInputValue(options.initialValue ?? '');
    setDialog({
      isOpen: true,
      title: options.title || 'Confirm',
      message: options.message,
      confirmText: options.confirmText || 'Confirm',
      cancelText: options.cancelText || 'Cancel',
      confirmInput: undefined,
      danger: false,
      prompt: options,
    });

    return new Promise<string | null>((resolve) => {
      resolveRef.current = value => resolve(typeof value === 'boolean' ? null : value);
    });
  }, [captureOpener]);

  const handleClose = useCallback((result: boolean) => {
    setDialog(prev => ({ ...prev, isOpen: false }));
    const resolve = resolveRef.current;
    resolveRef.current = null;

    const opener = openerRef.current;
    openerRef.current = null;
    if (opener && document.contains(opener)) opener.focus();

    // handleClose keeps its boolean signature. A prompt resolves the TRIMMED value on
    // confirm and null on cancel; everything else resolves the boolean unchanged.
    resolve?.(dialog.prompt ? (result ? inputValue.trim() : null) : result);
  }, [dialog.prompt, inputValue]);

  const promptOpts = dialog.prompt;
  const trimmedInput = inputValue.trim();
  const minLength = promptOpts?.minLength ?? 0;
  const typedToConfirm = !dialog.confirmInput || inputValue === dialog.confirmInput;
  const promptSatisfied = !promptOpts
    || (trimmedInput.length >= minLength
      && (promptOpts.required ?? true ? trimmedInput.length > 0 : true));
  const canConfirm = typedToConfirm && promptSatisfied;

  /**
   * aria-describedby is set ONLY when there is a message. :83 used to hardcode it and the
   * #confirm-msg node used to open unconditionally, so a prompt with no message pointed a
   * screen reader at an empty element — an announced dialog followed by nothing, which is
   * worse than no attribute at all. For a prompt the description the user needs is the
   * field's own label and helper, carried by aria-describedby on the input.
   */
  const hasMessage = dialog.message !== undefined && dialog.message !== null
    && dialog.message !== '' && dialog.message !== false;

  const promptHelper = promptOpts
    ? (promptOpts.helper ?? (minLength > 0 ? `At least ${minLength} characters` : undefined))
    : undefined;

  const contextValue = React.useMemo(() => ({ confirm, prompt }), [confirm, prompt]);

  return (
    <ConfirmContext.Provider value={contextValue}>
      {children}
      {dialog.isOpen && (
        <div
          role="dialog" aria-modal="true"
          aria-labelledby="confirm-title" aria-describedby={hasMessage ? 'confirm-msg' : undefined}
          onKeyDown={e => {
            if (e.key === 'Escape') handleClose(false);
            if (e.key === 'Enter' && canConfirm) {
              // This handler sits on the backdrop, so it sees Enter from anywhere inside the
              // dialog. With multiline: true that would turn the newline key into a submit.
              const target = e.target as HTMLElement | null;
              const inTextarea = (target?.tagName || '').toLowerCase() === 'textarea';
              if (inTextarea || e.shiftKey) return;
              handleClose(true);
            }
          }}
          onClick={() => handleClose(false)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 10000, padding: '20px', backdropFilter: 'blur(2px)',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#fff', borderRadius: '13px', width: '100%', maxWidth: '420px',
              boxShadow: '0 8px 30px rgba(0,0,0,0.12)', overflow: 'hidden',
              animation: 'confirmIn 0.15s ease-out',
              border: '1.5px solid #d1f470',
            }}
          >
            {/* Accent bar */}
            <div style={{ height: '6px', background: dialog.danger ? '#dc2626' : '#d1f470' }} />

            <div style={{ padding: '20px 20px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                <div style={{
                  width: '32px', height: '32px', borderRadius: '50%',
                  background: dialog.danger ? '#fef2f2' : '#f9fafb',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}>
                  {dialog.danger ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1a3a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>
                    </svg>
                  )}
                </div>
                <h3 id="confirm-title" style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: '#1a1a1a' }}>
                  {dialog.title}
                </h3>
              </div>
              {hasMessage && (
                <div id="confirm-msg" style={{
                  margin: '0 0 16px', fontSize: '13px', lineHeight: 1.5, color: 'rgba(0, 0, 0, 0.54)', paddingLeft: '42px',
                }}>
                  {dialog.message}
                </div>
              )}

              {/* Free-text prompt field */}
              {promptOpts && (
                <div style={{ paddingLeft: '42px', marginBottom: '16px' }}>
                  <label htmlFor={PROMPT_FIELD_ID} style={{ display: 'block', fontSize: '12px', color: '#6b7280', marginBottom: '6px', fontWeight: 500 }}>
                    {promptOpts.label}
                  </label>
                  {promptOpts.multiline ? (
                    <textarea
                      id={PROMPT_FIELD_ID}
                      rows={3}
                      value={inputValue}
                      onChange={e => setInputValue(e.target.value)}
                      placeholder={promptOpts.placeholder}
                      maxLength={promptOpts.maxLength ?? 500}
                      aria-describedby={promptHelper ? PROMPT_HELPER_ID : undefined}
                      autoFocus
                      style={{
                        width: '100%', padding: '8px 12px', border: '1.5px solid #d1f470',
                        borderRadius: '13px', fontSize: '13px', outline: 'none',
                        boxSizing: 'border-box', fontFamily: 'inherit', resize: 'vertical',
                      }}
                      onFocus={e => { e.target.style.borderColor = '#1a3a2a'; e.target.style.boxShadow = '0 0 0 3px rgba(209,244,112,0.3)'; }}
                      onBlur={e => { e.target.style.borderColor = '#d1f470'; e.target.style.boxShadow = 'none'; }}
                    />
                  ) : (
                    <input
                      id={PROMPT_FIELD_ID}
                      type="text"
                      value={inputValue}
                      onChange={e => setInputValue(e.target.value)}
                      placeholder={promptOpts.placeholder}
                      maxLength={promptOpts.maxLength ?? 500}
                      aria-describedby={promptHelper ? PROMPT_HELPER_ID : undefined}
                      autoFocus
                      style={{
                        width: '100%', padding: '8px 12px', border: '1.5px solid #d1f470',
                        borderRadius: '13px', fontSize: '13px', outline: 'none',
                        boxSizing: 'border-box',
                      }}
                      onFocus={e => { e.target.style.borderColor = '#1a3a2a'; e.target.style.boxShadow = '0 0 0 3px rgba(209,244,112,0.3)'; }}
                      onBlur={e => { e.target.style.borderColor = '#d1f470'; e.target.style.boxShadow = 'none'; }}
                    />
                  )}
                  {promptHelper && (
                    <div id={PROMPT_HELPER_ID} style={{ marginTop: '6px', fontSize: '11px', color: '#6b7280' }}>
                      {promptHelper}
                    </div>
                  )}
                </div>
              )}

              {/* Type-to-confirm input */}
              {dialog.confirmInput && (
                <div style={{ paddingLeft: '42px', marginBottom: '16px' }}>
                  <label style={{ display: 'block', fontSize: '12px', color: '#6b7280', marginBottom: '6px', fontWeight: 500 }}>
                    Type &quot;{dialog.confirmInput}&quot; to confirm:
                  </label>
                  <input
                    type="text"
                    value={inputValue}
                    onChange={e => setInputValue(e.target.value)}
                    placeholder={dialog.confirmInput}
                    autoFocus
                    style={{
                      width: '100%', padding: '8px 12px', border: '1.5px solid #d1f470',
                      borderRadius: '13px', fontSize: '13px', outline: 'none',
                      boxSizing: 'border-box',
                    }}
                    onFocus={e => { e.target.style.borderColor = dialog.danger ? '#dc2626' : '#1a3a2a'; e.target.style.boxShadow = '0 0 0 3px rgba(209,244,112,0.3)'; }}
                    onBlur={e => { e.target.style.borderColor = '#d1f470'; e.target.style.boxShadow = 'none'; }}
                  />
                </div>
              )}
            </div>

            <div style={{
              display: 'flex', justifyContent: 'flex-end', gap: '8px',
              padding: '12px 20px', background: '#f9fafb', borderTop: '1px solid #f3f4f6',
            }}>
              <button
                onClick={() => handleClose(false)}
                autoFocus={!dialog.confirmInput && !promptOpts}
                style={{
                  padding: '7px 16px', border: '1.5px solid #d1f470', borderRadius: '13px',
                  background: '#fff', color: '#374151', fontSize: '13px', fontWeight: 500,
                  cursor: 'pointer',
                }}
              >
                {dialog.cancelText}
              </button>
              <button
                onClick={() => handleClose(true)}
                disabled={!canConfirm}
                style={{
                  padding: '7px 16px', border: 'none', borderRadius: '13px',
                  background: !canConfirm ? '#d1d5db' : (dialog.danger ? '#dc2626' : '#d1f470'),
                  color: dialog.danger ? '#fff' : '#1a3a2a', fontSize: '13px', fontWeight: 500,
                  cursor: canConfirm ? 'pointer' : 'not-allowed',
                  opacity: canConfirm ? 1 : 0.6,
                }}
              >
                {dialog.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}
      <style>{`@keyframes confirmIn { from { opacity:0; transform:scale(.96) translateY(-8px); } to { opacity:1; transform:scale(1) translateY(0); } }`}</style>
    </ConfirmContext.Provider>
  );
};

export const useConfirm = (): ConfirmFn => {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error('useConfirm must be used within a ConfirmProvider');
  return context.confirm;
};

export const usePromptDialog = (): PromptFn => {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error('usePromptDialog must be used within a ConfirmProvider');
  return context.prompt;
};

// Kept so the module's public surface does not shrink under anyone. Measured: no file
// imports it — all consumers import { useConfirm } / { usePromptDialog } / { ConfirmProvider }
// by name.
export default ConfirmContext;
