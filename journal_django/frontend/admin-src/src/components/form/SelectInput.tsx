import { useEffect, useMemo, useRef, useState } from 'react';
import type { SelectHTMLAttributes } from 'react';

interface Option { value: string | number; label: string; }

// Сохраняем onChange-сигнатуру native, чтобы вызовы вида onChange={e => ...e.target.value} продолжали работать.
interface Props extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange'> {
  options: Option[];
  onChange?: (e: { target: { value: string } }) => void;
  placeholder?: string;
}

export function SelectInput({ options, value, onChange, placeholder, disabled, className, ...rest }: Props) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const currentValue = value !== undefined ? String(value) : '';
  const selected = useMemo(() => options.find((o) => String(o.value) === currentValue), [options, currentValue]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  // Reset highlight to currently selected when opening
  useEffect(() => {
    if (open) {
      const idx = options.findIndex((o) => String(o.value) === currentValue);
      setHighlight(idx >= 0 ? idx : 0);
    }
  }, [open, options, currentValue]);

  const choose = (opt: Option) => {
    onChange?.({ target: { value: String(opt.value) } });
    setOpen(false);
    triggerRef.current?.focus();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (disabled) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      setHighlight((h) => Math.min(options.length - 1, h + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (!open) setOpen(true);
      else if (options[highlight]) choose(options[highlight]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div className={`select-input ${open ? 'is-open' : ''} ${className || ''}`} ref={ref}>
      <button
        type="button"
        ref={triggerRef}
        className="select-input__trigger"
        onClick={() => !disabled && setOpen((o) => !o)}
        onKeyDown={onKey}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={`select-input__value ${selected ? '' : 'is-placeholder'}`}>
          {selected ? selected.label : (placeholder || 'Выберите...')}
        </span>
        <svg className="select-input__chevron" width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>
      {open && (
        <ul className="select-input__list" role="listbox">
          {options.length === 0 ? (
            <li className="select-input__empty">Нет вариантов</li>
          ) : options.map((opt, i) => (
            <li
              key={`${opt.value}-${i}`}
              role="option"
              aria-selected={String(opt.value) === currentValue}
              className={`select-input__item${i === highlight ? ' is-highlighted' : ''}${String(opt.value) === currentValue ? ' is-selected' : ''}`}
              onMouseEnter={() => setHighlight(i)}
              onMouseDown={(e) => { e.preventDefault(); choose(opt); }}
            >
              {opt.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
