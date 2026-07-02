import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

/**
 * Лёгкая модалка на токенах (портал в #modal-host). Esc и клик по фону —
 * закрытие. Для read-only деталей и форм teacher SPA.
 */
export function Modal({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const host = document.getElementById('modal-host') || document.body;

  return createPortal(
    <div className="t-modal-overlay" onClick={onClose}>
      <div className="t-modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="t-modal-head">
          <div>
            <div className="t-modal-title">{title}</div>
            {subtitle != null && <div className="t-modal-sub">{subtitle}</div>}
          </div>
          <button type="button" className="t-modal-close" onClick={onClose} aria-label="Закрыть">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="t-modal-body">{children}</div>
      </div>
    </div>,
    host,
  );
}
