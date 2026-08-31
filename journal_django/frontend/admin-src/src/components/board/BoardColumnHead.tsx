import type { ReactNode } from 'react';
import { stageTone } from '../../lib/stage-tone';

interface Props {
  label: string;
  count: number;
  /** Цвет стадии из справочника. Пусто — тон выведется из названия. */
  color?: string | null;
  /** Служебная пометка рядом с названием (например «авто» в «Продлениях»). */
  badge?: ReactNode;
  /** Кнопки справа от счётчика: поиск, меню. */
  actions?: ReactNode;
}

/**
 * Шапка колонки доски — сплошная плашка цветом стадии.
 *
 * Общая для «Задач» и «Продлений» по прямому требованию заказчика: шапка стадии
 * должна выглядеть одинаково во всей системе. Специфика разделов сюда не
 * переезжает — она приходит слотами `badge` и `actions`.
 *
 * Цвет подписи считает stageTone(): цвет стадии выбирает человек, и на светлой
 * заливке белый текст нечитаем.
 */
export function BoardColumnHead({ label, count, color, badge, actions }: Props) {
  const tone = stageTone(color, label);
  return (
    <div
      className="board-col-head"
      style={{ background: tone.bg, color: tone.ink }}
    >
      <span className="board-col-head__label" title={label}>{label}</span>
      {badge}
      <span className="board-col-head__count">{count}</span>
      {actions && <span className="board-col-head__actions">{actions}</span>}
    </div>
  );
}
