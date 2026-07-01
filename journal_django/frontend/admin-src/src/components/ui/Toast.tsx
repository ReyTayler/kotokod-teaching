import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

type ToastKind = 'ok' | 'error' | 'info';
interface ToastItem { id: number; message: string; kind: ToastKind; }

const ToastContext = createContext<{ toast: (msg: string, kind?: ToastKind) => void }>(null!);

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, kind: ToastKind = 'info') => {
    const id = nextId++;
    setItems((prev) => [...prev, { id, message, kind }]);
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 3000);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="toast-container">
        {items.map((t) => (
          <div key={t.id} className={`toast toast--${t.kind}`}>{t.message}</div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() { return useContext(ToastContext); }

export function showApiError(err: unknown, toast: (m: string, k?: ToastKind) => void) {
  if (typeof err === 'object' && err && 'message' in err) {
    toast(String((err as { message: unknown }).message), 'error');
  } else {
    toast('Ошибка', 'error');
  }
}
