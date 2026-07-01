// Утилиты CSV-экспорта в браузере (без зависимостей).
//
// Формат заточен под Excel в RU-локали:
//   • разделитель `;`  (в RU Excel запятая = десятичный разделитель);
//   • UTF-8 BOM — иначе Excel ломает кириллицу;
//   • переводы строк CRLF (\r\n).

type Cell = string | number;

const BOM = String.fromCharCode(0xFEFF);

/** Экранирование одной ячейки: оборачиваем в кавычки, если есть `;`, `"` или перевод строки. */
function escapeCell(v: Cell): string {
  const s = String(v);
  return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Матрица строк → CSV-текст (без BOM). */
export function toCsv(rows: Cell[][]): string {
  return rows.map((r) => r.map(escapeCell).join(';')).join('\r\n');
}

/** Скачать CSV-текст файлом (добавляет UTF-8 BOM для Excel). */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([BOM + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
