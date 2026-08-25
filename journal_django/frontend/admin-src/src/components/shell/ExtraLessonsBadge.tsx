import { usePendingExtraLessonsCount } from '../../hooks/useExtraLessons';

/** Красный бейдж с числом необработанных пропусков на кнопке «Доп.уроки». */
export function ExtraLessonsBadge() {
  const { data } = usePendingExtraLessonsCount();
  const count = data?.count ?? 0;
  if (count <= 0) return null;
  return (
    <span className="nav-badge" title={`Необработанных пропусков: ${count}`}>
      {count > 99 ? '99+' : count}
    </span>
  );
}
