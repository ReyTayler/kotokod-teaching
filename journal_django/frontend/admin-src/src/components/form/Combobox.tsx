import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';

interface Option {
  value: string;
  label: string;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: Option[];
  placeholder?: string;
  /** Сколько строк помещается в выпадашке. Остальное прокручивается. По умолчанию 10. */
  maxVisible?: number;
}

const ITEM_HEIGHT = 36;

export function Combobox({ value, onChange, options, placeholder, maxVisible = 10 }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selected = useMemo(() => options.find((o) => o.value === value), [options, value]);

  const filtered = useMemo(() => {
    if (!open || !query.trim()) return options;
    const q = query.toLowerCase();
    return options.filter((o) => o.label.toLowerCase().includes(q));
  }, [options, query, open]);

  // Click outside → close.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery('');
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  // Скролл подсвеченного пункта в зону видимости (для клавиатурной навигации).
  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.children[highlight] as HTMLElement | undefined;
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [highlight, open]);

  const choose = (opt: Option) => {
    onChange(opt.value);
    setOpen(false);
    setQuery('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      setHighlight((h) => Math.min(filtered.length - 1, h + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
    } else if (e.key === 'Enter') {
      if (open && filtered[highlight]) { e.preventDefault(); choose(filtered[highlight]); }
    } else if (e.key === 'Escape') {
      setOpen(false);
      setQuery('');
    }
  };

  // displayValue: при открытом списке показываем query (видимый ввод поиска),
  // при закрытом — label выбранного.
  const displayValue = open ? query : (selected?.label || '');

  return (
    <div className="combobox" ref={containerRef}>
      <input
        type="text"
        className="combobox__input"
        value={displayValue}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setHighlight(0); }}
        onFocus={() => { setOpen(true); setQuery(''); setHighlight(0); }}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {open && (
        <ul
          ref={listRef}
          className="combobox__list"
          style={{ maxHeight: `${maxVisible * ITEM_HEIGHT}px` }}
          role="listbox"
        >
          {filtered.length === 0 ? (
            <li className="combobox__empty">Ничего не найдено</li>
          ) : (
            filtered.map((opt, i) => (
              <li
                key={opt.value}
                role="option"
                aria-selected={opt.value === value}
                className={
                  `combobox__item${i === highlight ? ' is-highlighted' : ''}` +
                  `${opt.value === value ? ' is-selected' : ''}`
                }
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => { e.preventDefault(); choose(opt); }}
              >
                {opt.label}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
