import { useEffect, useRef, useState } from 'react';
import { useLessonFull, useLessonMutations } from '../../hooks/useLessons';
import { useMemberships } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';
import { DateInput } from '../form/DateInput';
import type { Group } from '../../lib/types';

interface Props {
  group: Group;
  slot: number;
  lessonId: number | null;
  color: string;
  onClose: () => void;
}

export function LessonEditor({ group, slot, lessonId, color, onClose }: Props) {
  const { data: lesson, isLoading: lessonLoading } = useLessonFull(lessonId);
  const { data: members = [], isLoading: membersLoading } = useMemberships({ group_id: group.id });
  const muts = useLessonMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const editorRef = useRef<HTMLDivElement | null>(null);
  const isFirstOpenRef = useRef(true);

  const [date, setDate] = useState('');
  const [url, setUrl] = useState('');
  const [present, setPresent] = useState<Record<number, boolean>>({});
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  useEffect(() => {
    if (lesson) {
      setDate(String(lesson.lesson_date).slice(0, 10));
      setUrl(lesson.record_url || '');
      const init: Record<number, boolean> = {};
      for (const a of lesson.attendance || []) init[a.student_id] = !!a.present;
      setPresent(init);
    } else if (lessonId === null) {
      setDate('');
      setUrl('');
      // Новый урок — по умолчанию все НЕ присутствовали; админ выставляет вручную.
      const init: Record<number, boolean> = {};
      for (const m of members) init[m.student_id] = false;
      setPresent(init);
    }
  }, [lesson, lessonId, members]);

  useEffect(() => {
    if (isFirstOpenRef.current && editorRef.current) {
      isFirstOpenRef.current = false;
      editorRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, []);

  if (lessonLoading || membersLoading) {
    return <div ref={editorRef} className="lesson-editor-host--loading" />;
  }

  // Посещаемость СОХРАНЁННОГО урока — свершившийся факт, грид read-only. Пропуск
  // закрывают только через раздел «Доп.уроки» (назначить доп.урок / сжечь);
  // ретроактивной правки посещаемости из редактора урока больше нет (раньше
  // absent→present штамповал «сгорание» — теперь это отдельная сущность).
  const locked = !!lesson;

  const handleSave = async () => {
    if (!date) { toast('Укажите дату', 'error'); return; }
    const attendance = members.map((m) => ({
      student_id: m.student_id,
      present: !!present[m.student_id],
    }));
    const presentCount = attendance.filter((a) => a.present).length;
    const totalStudents = attendance.length;

    if (totalStudents === 0) {
      toast('В группе нет учеников — урок зафиксировать нельзя', 'error');
      return;
    }
    if (presentCount === 0) {
      toast('Отметьте хотя бы одного присутствующего ученика', 'error');
      return;
    }

    try {
      if (lesson) {
        // Посещаемость завершённого урока не редактируется здесь — только дата/ссылка.
        await muts.update.mutateAsync({
          id: lesson.id,
          body: { lesson_date: date, record_url: url },
        });
        toast('Сохранено', 'ok');
      } else {
        // slot — порядковый номер ЯЧЕЙКИ грида (1,2,3…), не lesson_number: для
        // 45-мин групп каждая ячейка = полу-урок (step=0.5), поэтому пишем
        // slot*step (0.5, 1.0, 1.5…) — обратное преобразование к тому, что
        // LessonGrid делает при чтении (slot = round(lesson_number/step)).
        const step = group.lesson_duration_minutes === 45 ? 0.5 : 1;
        await muts.create.mutateAsync({
          lesson_date: date,
          group_id: group.id,
          teacher_id: group.teacher_id,
          lesson_number: slot * step,
          lesson_duration_minutes: group.lesson_duration_minutes,
          lesson_type: 'regular',
          record_url: url,
          submitted_by_token: 'admin-imported',
          attendance,
        });
        toast('Урок создан', 'ok');
      }
      onClose();
    } catch (err) { showError(err); }
  };

  const handleDelete = async () => {
    if (!lesson) return;
    if (!confirmingDelete) { setConfirmingDelete(true); return; }
    try {
      await muts.remove.mutateAsync(lesson.id);
      toast('Урок удалён', 'ok');
      onClose();
    } catch (err) { showError(err); }
  };

  return (
    <div ref={editorRef} className="lesson-editor" style={{ ['--dir-color' as string]: color }}>
      <div className="lesson-editor__header">
        <h4>Урок №{slot}{lesson ? '' : ' · новый'}</h4>
        <button type="button" className="btn-secondary" onClick={onClose}>Закрыть</button>
      </div>
      <div className="lesson-editor__row">
        <label>Дата проведения</label>
        <DateInput value={date} onChange={(e) => setDate(e.target.value)} />
      </div>
      <div className="lesson-editor__row">
        <label>Ссылка на запись урока</label>
        <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
      </div>
      <div className="lesson-editor__row">
        <label>
          Посещаемость {!locked && <span className="lesson-editor__hint">(клик по карточке — переключение)</span>}
        </label>
        <div className="attendance-grid">
          {members.length ? members.map((m) => {
            const isPresent = !!present[m.student_id];
            return (
              <button
                key={m.student_id}
                type="button"
                className={`attendance-card ${isPresent ? 'is-present' : 'is-absent'}${locked ? ' is-locked' : ''}`}
                onClick={locked ? undefined : () => setPresent((p) => ({ ...p, [m.student_id]: !p[m.student_id] }))}
                disabled={locked}
                aria-disabled={locked}
              >
                <span className="attendance-card__icon" aria-hidden>{isPresent ? '✓' : '✕'}</span>
                <span className="attendance-card__name">{m.student_name || `#${m.student_id}`}</span>
              </button>
            );
          }) : (
            <div className="memberships__empty">В группе нет учеников</div>
          )}
        </div>
      </div>
      <div className="lesson-editor__footer">
        {lesson && (
          <button
            type="button"
            className={`btn-delete${confirmingDelete ? ' is-confirming' : ''}`}
            onClick={() => { void handleDelete(); }}
          >{confirmingDelete ? 'Точно удалить?' : 'Удалить урок'}</button>
        )}
        <button
          type="button"
          className="btn-save"
          style={{ marginLeft: 'auto' }}
          onClick={() => { void handleSave(); }}
          disabled={muts.create.isPending || muts.update.isPending || muts.remove.isPending}
        >{lesson ? 'Сохранить' : 'Создать урок'}</button>
      </div>
    </div>
  );
}
