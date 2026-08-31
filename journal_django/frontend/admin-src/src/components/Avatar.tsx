import { hueOfName } from '../lib/direction-color';

interface Props { name: string; size?: number; }

/** Инициалы имени: первые буквы двух первых слов, а у односложного — две
 *  первые буквы. Вынесено из компонента и экспортировано — тем же правилом
 *  полоса воронок задач сокращает названия («Тестовая доска» → «ТД»). */
export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/);
  return (parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
}

export function Avatar({ name, size = 32 }: Props) {
  const initials = initialsOf(name);
  const hue = hueOfName(name);
  return (
    <div
      className="avatar"
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.38),
        background: `hsl(${hue},55%,92%)`,
        border: `2px solid hsl(${hue},50%,80%)`,
        color: `hsl(${hue},55%,35%)`,
      }}
    >
      {initials}
    </div>
  );
}
