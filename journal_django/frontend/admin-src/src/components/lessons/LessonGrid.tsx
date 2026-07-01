import { useMemo } from 'react';
import { useLessonsForGroup } from '../../hooks/useLessons';
import { useDirections } from '../../hooks/useDirections';
import { directionColor } from '../../lib/direction-color';
import type { Group, Lesson } from '../../lib/types';

interface Props {
  group: Group;
  selectedSlot: number | null;
  onSelectSlot: (slot: number, lessonId: number | null) => void;
}

export function LessonGrid({ group, selectedSlot, onSelectSlot }: Props) {
  const { data: lessons = [] } = useLessonsForGroup({ group_id: group.id });
  const { data: directions = [] } = useDirections(true);
  const direction = directions.find((d) => d.id === group.direction_id) || null;
  const color = directionColor(direction);

  const byNumber = useMemo(() => {
    const map = new Map<number, Lesson>();
    let max = 0;
    for (const l of lessons) {
      const slot = Math.ceil(Number(l.lesson_number));
      if (!map.has(slot)) map.set(slot, l);
      if (slot > max) max = slot;
    }
    return { map, max };
  }, [lessons]);

  const totalSlots = direction?.total_lessons != null ? Number(direction.total_lessons) : null;
  const slotCount = totalSlots ? Math.max(totalSlots, byNumber.max) : Math.max(byNumber.max, 12);

  return (
    <div className="lesson-grid">
      {Array.from({ length: slotCount }, (_, i) => {
        const num = i + 1;
        const lesson = byNumber.map.get(num);
        const filled = !!lesson;
        const isSelected = selectedSlot === num;
        return (
          <button
            key={num}
            type="button"
            className={`lesson-square${filled ? ' is-filled' : ''}${isSelected ? ' is-selected' : ''}`}
            style={{ ['--dir-color' as string]: color }}
            aria-label={`Урок №${num}${filled ? '' : ' (не проведён)'}`}
            data-tip={`Урок №${num}`}
            onClick={() => onSelectSlot(num, lesson ? lesson.id : null)}
          >
            <span className="lesson-square__num">{num}</span>
          </button>
        );
      })}
    </div>
  );
}
