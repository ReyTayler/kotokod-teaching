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
