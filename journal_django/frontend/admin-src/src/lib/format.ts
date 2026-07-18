/**
 * Сегодняшняя дата по МСК в формате 'YYYY-MM-DD'.
 * Intl.DateTimeFormat с явным timeZone игнорирует часовой пояс ОС/браузера —
 * в отличие от ручной арифметики с getTimezoneOffset(), которая давала
 * двойной сдвиг на машинах с локальным поясом Europe/Moscow.
 */
export function todayMSK(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Moscow',
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date());
}

export function fmtDate(s: string | Date | null | undefined): string {
  if (!s) return '—';
  const str = String(s);
  if (/^\d{4}-\d{2}-\d{2}$/.test(str)) {
    const [y, m, d] = str.split('-');
    return `${d}.${m}.${y}`;
  }
  const d = new Date(str);
  if (!isNaN(d.getTime())) {
    return d.toLocaleDateString('ru-RU', {
      timeZone: 'Europe/Moscow',
      day: '2-digit', month: '2-digit', year: 'numeric',
    });
  }
  return str;
}

/** Дата-время по МСК с секундами (журналы ИБ/изменений). */
export function fmtDateTime(s: string | null | undefined): string {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString('ru-RU', {
    timeZone:  'Europe/Moscow',
    day:       '2-digit',
    month:     '2-digit',
    year:      'numeric',
    hour:      '2-digit',
    minute:    '2-digit',
    second:    '2-digit',
  });
}

/** Компактное дата-время по МСК для лент: '06.07 11:11'. */
export function fmtDateTimeShort(s: string | null | undefined): string {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const dm = d.toLocaleDateString('ru-RU', {
    timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit',
  });
  const hm = d.toLocaleTimeString('ru-RU', {
    timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit',
  });
  return `${dm} ${hm}`;
}

export function escapeHtml(s: unknown): string {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));
}

export function fmtRub(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  // 7 250 ₽ / 7 250,50 ₽
  const rounded = Math.round(n * 100) / 100;
  const intPart = Math.floor(Math.abs(rounded)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  const fracCents = Math.round((Math.abs(rounded) - Math.floor(Math.abs(rounded))) * 100);
  const sign = rounded < 0 ? '−' : '';
  const fracPart = fracCents ? `,${String(fracCents).padStart(2, '0')}` : '';
  return `${sign}${intPart}${fracPart} ₽`;
}

export function fmtLessons(value: number): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '0';
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(1).replace('.', ',');
}
