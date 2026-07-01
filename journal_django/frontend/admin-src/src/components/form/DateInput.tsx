import { useEffect, useMemo, useRef, useState } from 'react';
import type { InputHTMLAttributes } from 'react';
import { MONTHS_RU } from '../../lib/slots';

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'value'> {
  value?: string; // 'YYYY-MM-DD' or ''
  onChange?: (e: { target: { value: string } }) => void;
  placeholder?: string;
}

// Дни недели сверху grid'а — начинаем с понедельника (русская конвенция).
const DOW_HEAD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

function todayMSK(): { y: number; m: number; d: number } {
  const now = new Date();
  const msk = new Date(now.getTime() + (3 * 60 - now.getTimezoneOffset()) * 60_000);
  return { y: msk.getUTCFullYear(), m: msk.getUTCMonth(), d: msk.getUTCDate() };
}

function parseISO(s: string | undefined): { y: number; m: number; d: number } | null {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s.slice(0, 10));
  if (!m) return null;
  return { y: Number(m[1]), m: Number(m[2]) - 1, d: Number(m[3]) };
}

function fmtISO(y: number, m: number, d: number): string {
  return `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

function fmtDisplay(s: string | undefined): string {
  const p = parseISO(s);
  if (!p) return '';
  return `${String(p.d).padStart(2, '0')}.${String(p.m + 1).padStart(2, '0')}.${p.y}`;
}

// Возвращает массив 42 ячеек (6 рядов × 7 дней) для месяца,
// с обернутыми сюда дрейфующими днями prev/next месяца.
function buildMonthGrid(y: number, m: number): Array<{ y: number; m: number; d: number; inMonth: boolean }> {
  const firstDow = new Date(Date.UTC(y, m, 1)).getUTCDay(); // 0..6, Sunday=0
  // Сдвигаем чтобы понедельник был index 0: (firstDow + 6) % 7
  const leading = (firstDow + 6) % 7;
  const daysInMonth = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const grid: Array<{ y: number; m: number; d: number; inMonth: boolean }> = [];
  // prev month tail
  if (leading > 0) {
    const daysInPrev = new Date(Date.UTC(y, m, 0)).getUTCDate();
    for (let i = leading; i > 0; i--) {
      const d = daysInPrev - i + 1;
      const pmy = m === 0 ? y - 1 : y;
      const pmm = m === 0 ? 11 : m - 1;
      grid.push({ y: pmy, m: pmm, d, inMonth: false });
    }
  }
  // current month
  for (let d = 1; d <= daysInMonth; d++) {
    grid.push({ y, m, d, inMonth: true });
  }
  // next month head
  while (grid.length < 42) {
    const idx = grid.length - leading - daysInMonth + 1;
    const nmy = m === 11 ? y + 1 : y;
    const nmm = m === 11 ? 0 : m + 1;
    grid.push({ y: nmy, m: nmm, d: idx, inMonth: false });
  }
  return grid;
}

export function DateInput({ value, onChange, placeholder, disabled, className, ...rest }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const valuePart = useMemo(() => parseISO(value), [value]);
  const today = useMemo(() => todayMSK(), []);

  // Какой месяц показываем в календаре. Инициализируется текущим значением или сегодня.
  const [viewYM, setViewYM] = useState<{ y: number; m: number }>(() => {
    if (valuePart) return { y: valuePart.y, m: valuePart.m };
    return { y: today.y, m: today.m };
  });

  // При открытии — синхронизировать view с value/today.
  useEffect(() => {
    if (open) {
      if (valuePart) setViewYM({ y: valuePart.y, m: valuePart.m });
      else setViewYM({ y: today.y, m: today.m });
    }
  }, [open, valuePart, today.y, today.m]);

  // Click outside.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const emit = (val: string) => {
    onChange?.({ target: { value: val } });
    setOpen(false);
    triggerRef.current?.focus();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (disabled) return;
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen((o) => !o); }
    else if (e.key === 'Escape') setOpen(false);
  };

  const grid = useMemo(() => buildMonthGrid(viewYM.y, viewYM.m), [viewYM]);

  const stepMonth = (delta: number) => {
    setViewYM(({ y, m }) => {
      const total = y * 12 + m + delta;
      return { y: Math.floor(total / 12), m: ((total % 12) + 12) % 12 };
    });
  };

  const display = fmtDisplay(value);

  return (
    <div className={`date-input ${open ? 'is-open' : ''} ${className || ''}`} ref={containerRef}>
      <button
        type="button"
        ref={triggerRef}
        className="date-input__trigger"
        onClick={() => !disabled && setOpen((o) => !o)}
        onKeyDown={onKey}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <span className={`date-input__value ${display ? '' : 'is-placeholder'}`}>
          {display || (placeholder || 'дд.мм.гггг')}
        </span>
        <svg className="date-input__icon" width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="2" y="3" width="10" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.2"/>
          <path d="M2 5.5h10M5 1.5v2M9 1.5v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
        </svg>
      </button>
      {open && (
        <div className="date-input__popover" role="dialog" aria-label="Выбор даты">
          <div className="date-input__head">
            <button type="button" className="date-input__nav" onClick={() => stepMonth(-1)} aria-label="Прошлый месяц">‹</button>
            <span className="date-input__title">{MONTHS_RU[viewYM.m]} {viewYM.y}</span>
            <button type="button" className="date-input__nav" onClick={() => stepMonth(1)} aria-label="Следующий месяц">›</button>
          </div>
          <div className="date-input__dow">
            {DOW_HEAD.map((d) => <span key={d}>{d}</span>)}
          </div>
          <div className="date-input__grid">
            {grid.map((c, i) => {
              const isToday = c.y === today.y && c.m === today.m && c.d === today.d;
              const isSelected = valuePart && c.y === valuePart.y && c.m === valuePart.m && c.d === valuePart.d;
              const cls = [
                'date-input__day',
                !c.inMonth && 'is-muted',
                isToday && 'is-today',
                isSelected && 'is-selected',
              ].filter(Boolean).join(' ');
              return (
                <button
                  type="button"
                  key={i}
                  className={cls}
                  onMouseDown={(e) => { e.preventDefault(); emit(fmtISO(c.y, c.m, c.d)); }}
                >{c.d}</button>
              );
            })}
          </div>
          <div className="date-input__footer">
            <button
              type="button"
              className="date-input__action"
              onClick={() => emit(fmtISO(today.y, today.m, today.d))}
            >Сегодня</button>
            {value && (
              <button
                type="button"
                className="date-input__action date-input__action--muted"
                onClick={() => emit('')}
              >Очистить</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
