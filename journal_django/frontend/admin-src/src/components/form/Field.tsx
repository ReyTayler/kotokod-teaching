import { type ReactNode } from 'react';

interface Props {
  label: string;
  required?: boolean;
  error?: string;
  children: ReactNode;
}

export function Field({ label, required, error, children }: Props) {
  return (
    <div className="field">
      <label>{label}{required && <span style={{ color: 'var(--red)' }}> *</span>}</label>
      {children}
      {error && (
        <div className="field-error" style={{ color: 'var(--red)', fontSize: 13, marginTop: 4 }}>
          {error}
        </div>
      )}
    </div>
  );
}
