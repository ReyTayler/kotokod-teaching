import { directionColor } from '../../lib/direction-color';
import type { Direction } from '../../lib/types';

interface Props { name?: string | null; direction?: Direction | null; }

export function DirTag({ name, direction }: Props) {
  const label = direction?.name || name || '';
  if (!label) return null;
  const color = directionColor(direction || label);
  return (
    <span className="dir-tag" style={{ color, borderColor: `${color}55`, background: `${color}14` }}>
      {label}
    </span>
  );
}
