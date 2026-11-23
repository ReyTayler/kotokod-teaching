import { type ReactNode } from 'react';
import { HelpPopover } from '../ui/HelpPopover';

interface Props {
  label: string;
  required?: boolean;
  error?: string;
  help?: ReactNode;
  /** Растянуть поле на всю ширину в 2-колоночной сетке формы (.modal-form). */
  full?: boolean;
  children: ReactNode;
}

export function Field({ label, required, error, help, full, children }: Props) {
  return (
    <div className={`field${full ? ' field--full' : ''}`}>
      <div className="field__label-row">
        <label>{label}{required && <span style={{ color: 'var(--red)' }}> *</span>}</label>
        {help && <HelpPopover label={label ? `Подсказка: ${label}` : 'Подсказка'}>{help}</HelpPopover>}
      </div>
      {children}
      {error && (
        <div className="field-error" style={{ color: 'var(--red)', fontSize: 13, marginTop: 4 }}>
          {error}
        </div>
      )}
    </div>
  );
}
