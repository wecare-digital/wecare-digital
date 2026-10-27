/**
 * Reusable Modal Component
 * Focus trap, ARIA roles, keyboard navigation
 */

import React, { useEffect, useCallback, useRef } from 'react';
import { lockScroll, unlockScroll } from '../../lib/scrollLock';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  closeOnOverlay?: boolean;
  closeOnEsc?: boolean;
  showCloseButton?: boolean;
}

const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  children,
  footer,
  size = 'md',
  closeOnOverlay = true,
  closeOnEsc = true,
  showCloseButton = true,
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const handleEsc = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape' && closeOnEsc) onClose();
  }, [onClose, closeOnEsc]);

  // Focus trap
  useEffect(() => {
    if (!isOpen) return;

    previousFocusRef.current = document.activeElement as HTMLElement;
    document.addEventListener('keydown', handleEsc);
    // See src/lib/scrollLock.ts. The page scrolls inside the DOCUMENT, not inside body,
    // so locking body alone would let the page move behind the modal.
    lockScroll();

    // Focus first focusable element
    const timer = setTimeout(() => {
      const modal = modalRef.current;
      if (!modal) return;
      const focusable = modal.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length > 0) focusable[0].focus();
    }, 50);

    return () => {
      clearTimeout(timer);
      document.removeEventListener('keydown', handleEsc);
      unlockScroll();
      previousFocusRef.current?.focus();
    };
  }, [isOpen, handleEsc]);

  // Tab trap
  useEffect(() => {
    if (!isOpen) return;
    const trap = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const modal = modalRef.current;
      if (!modal) return;
      const focusable = modal.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', trap);
    return () => document.removeEventListener('keydown', trap);
  }, [isOpen]);

  if (!isOpen) return null;

  const sizeStyles = { sm: '400px', md: '500px', lg: '700px', xl: '900px' };

  return (
    <div className="ui-modal-overlay" style={overlayStyle} onClick={closeOnOverlay ? onClose : undefined}>
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className="ui-modal-panel"
        style={{ ...modalStyle, maxWidth: sizeStyles[size] }}
        onClick={e => e.stopPropagation()}
      >
        <div style={headerStyle}>
          <h2 id="modal-title" style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>{title}</h2>
          {showCloseButton && <button className="ui-modal-close" onClick={onClose} style={closeButtonStyle} aria-label="Close modal">×</button>}
        </div>
        <div style={bodyStyle}>{children}</div>
        {footer && <div className="ui-modal-footer" style={footerStyle}>{footer}</div>}
      </div>
      <style jsx global>{`
        @media(max-width:768px){
          .ui-modal-overlay{
            align-items:flex-end !important;
            padding:
              max(12px,env(safe-area-inset-top,0px))
              max(12px,env(safe-area-inset-right,0px))
              max(12px,env(safe-area-inset-bottom,0px))
              max(12px,env(safe-area-inset-left,0px)) !important;
          }
          .ui-modal-panel{
            max-width:100% !important;
            max-height:calc(100dvh - 24px - env(safe-area-inset-top,0px) - env(safe-area-inset-bottom,0px)) !important;
            border-radius:16px 16px 0 0 !important;
          }
          .ui-modal-footer{
            flex-wrap:wrap;
          }
          .ui-modal-footer > button,
          .ui-modal-footer > .btn{
            flex:1 1 140px;
          }
        }
        @media(max-width:360px){
          .ui-modal-overlay{padding-inline:8px !important}
          .ui-modal-footer{gap:8px !important;padding-inline:14px !important}
          .ui-modal-footer > button,
          .ui-modal-footer > .btn{flex-basis:100%}
        }
      `}</style>
    </div>
  );
};

const overlayStyle: React.CSSProperties = {
  position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
  background: 'rgba(0,0,0,0.5)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 1000,
  padding: '20px',
};

const modalStyle: React.CSSProperties = {
  background: '#fff', borderRadius: '16px', width: '100%',
  maxHeight: '90dvh', overflow: 'hidden', display: 'flex',
  flexDirection: 'column', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)',
};

const headerStyle: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '16px 20px', borderBottom: '1px solid #e5e7eb',
};

const closeButtonStyle: React.CSSProperties = {
  background: 'none', border: 'none', fontSize: '24px',
  cursor: 'pointer', color: '#6b7280', padding: 0,
  width: '44px', height: '44px', minWidth: '44px', minHeight: '44px',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  lineHeight: 1,
};

const bodyStyle: React.CSSProperties = {
  padding: '20px', flex: 1, overflowY: 'auto',
};

const footerStyle: React.CSSProperties = {
  display: 'flex', justifyContent: 'flex-end', gap: '12px',
  padding: '16px 20px', borderTop: '1px solid #e5e7eb',
};

export default Modal;
