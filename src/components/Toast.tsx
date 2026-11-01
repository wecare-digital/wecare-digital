/**
 * Toast Notification Component
 * Unified toast notifications for the entire app
 */

import React, { useEffect, useState } from 'react';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface ToastMessage {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

interface ToastProps {
  toasts: ToastMessage[];
  onRemove: (id: string) => void;
}

const Toast: React.FC<ToastProps> = ({ toasts, onRemove }) => {
  return (
    <div className="toast-container wc-action-toast-host wc-action-toast-host--workspace">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onRemove={onRemove} />
      ))}
    </div>
  );
};

/**
 * How long a toast stays before it starts leaving. A time, not a motion: it is how long a reader
 * is given to read the message, so it is unaffected by prefers-reduced-motion.
 */
const HOLD_MS = 5500;

const ToastItem: React.FC<{ toast: ToastMessage; onRemove: (id: string) => void }> = ({ toast, onRemove }) => {
  const [isExiting, setIsExiting] = useState(false);

  /**
   * THE HOLD IS A TIMER. THE EXIT IS NOT.
   *
   * This used to be a timer inside a timer: after the hold it set the exit class and then called
   * `setTimeout(() => onRemove(id), 300)` to unmount once the animation had finished. The 300 was
   * a guess at the CSS duration, and it was the WRONG guess - `.toast-exit` in
   * styles/inner-ux.css animates for 0.2s, so the toast sat fully transparent for 100ms on every
   * dismissal, and the container held a dead node that still occupied its grid gap.
   *
   * Two numbers describing one duration in two languages will always drift; the only question is
   * how long before somebody notices. So the exit is now driven by `animationend` below. The
   * stylesheet owns how long leaving takes, and retiming the animation needs no change here.
   *
   * WHY THE HOLD STAYS IN JS: CSS cannot unmount a React node, and driving the whole lifecycle
   * from one long animation would put the READING TIME under prefers-reduced-motion too - a
   * reduced-motion reader would get a toast that vanished in 0.01ms. Reduce motion means do not
   * animate, not do not wait.
   */
  useEffect(() => {
    const timer = setTimeout(() => setIsExiting(true), toast.duration || HOLD_MS);
    return () => clearTimeout(timer);
  }, [toast.duration]);

  /**
   * Fires for the enter animation as well, so it is guarded on `isExiting` rather than on the
   * animation's name. Names are the more obvious check and the weaker one: they are a CSS
   * identifier that a future stylesheet rename or a minifier could change, and nothing would fail
   * loudly - toasts would simply stop being removed.
   */
  const handleAnimationEnd = () => {
    if (isExiting) onRemove(toast.id);
  };

  /**
   * A BACKSTOP, NOT A SECOND DURATION - and the distinction is the whole reason it is safe to have.
   *
   * `animationend` is what normally removes this, and the stylesheet owns how long leaving takes.
   * But an animation that never runs never ends: an element hidden before it started, a browser
   * that does not implement AnimationEvent, a stylesheet that failed to load. In any of those the
   * toast would sit in the corner permanently, which is a worse failure than a slightly early
   * unmount.
   *
   * That is not hypothetical. jsdom has no AnimationEvent at all - React does not even deliver
   * `animationend` there, verified by probing it directly - so under test this timer is the only
   * thing that removes a toast.
   *
   * One second is an UPPER BOUND rather than a matched value. It is far longer than any exit this
   * design would plausibly use (the current one is 0.2s), so it never pre-empts the animation, and
   * because it is not trying to equal the CSS it cannot drift out of step with it the way the old
   * 300ms did.
   */
  useEffect(() => {
    if (!isExiting) return;
    const backstop = setTimeout(() => onRemove(toast.id), 1000);
    return () => clearTimeout(backstop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isExiting, toast.id]);

  return (
    <div
      className={`toast wc-action-toast toast-${toast.type} ${isExiting ? 'toast-exit' : ''}`}
      role={toast.type === 'error' || toast.type === 'warning' ? 'alert' : 'status'}
      aria-atomic="true"
      onAnimationEnd={handleAnimationEnd}
    >
      {/* Severity remains available in the role and message, not a decorative icon. */}
      <span className="toast-message">{toast.message}</span>
      {/* Closing is immediate and does not wait for the exit animation: the reader has asked for
          it gone, and animating a dismissal they explicitly requested only delays it. */}
      <button className="toast-close" onClick={() => onRemove(toast.id)} aria-label="Dismiss notification">✕</button>
    </div>
  );
};

// Toast state has one owner: the Workspace ToastContext provider.
// Do not reintroduce a local useToast state/host alongside that provider.
export default Toast;
