import { useEffect, useRef, useState } from 'react';
import { useLessonFull, useLessonMutations } from '../../hooks/useLessons';
import { useMemberships } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';
import { DateInput } from '../form/DateInput';
import { AssignExtraLessonModal } from './AssignExtraLessonModal';
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
  const [assigningExtra, setAssigningExtra] = useState(false);

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

  const togglePresent = (sid: number) => {
    setPresent((p) => ({ ...p, [sid]: !p[sid] }));
  };

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
        await muts.update.mutateAsync({
          id: lesson.id,
          body: { lesson_date: date, record_url: url },
        });
        await Promise.all(attendance.map((a) =>
          muts.toggleAttendance.mutateAsync({
            lessonId: lesson.id, studentId: a.student_id, present: a.present,
          }),
        ));
        toast('Сохранено', 'ok');
      } else {
        await muts.create.mutateAsync({
          lesson_date: date,
          group_id: group.id,
          teacher_id: group.teacher_id,
          lesson_number: slot,
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
          Посещаемость <span className="lesson-editor__hint">(клик по карточке — переключение)</span>
        </label>
        <div className="attendance-grid">
          {members.length ? members.map((m) => {
            const isPresent = !!present[m.student_id];
            return (
              <button
                key={m.student_id}
                type="button"
                className={`attendance-card ${isPresent ? 'is-present' : 'is-absent'}`}
                onClick={() => togglePresent(m.student_id)}
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
        {lesson && Object.values(present).some((p) => !p) && (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setAssigningExtra(true)}
          >
            Назначить доп.урок
          </button>
        )}
        <button
          type="button"
          className="btn-save"
          style={{ marginLeft: 'auto' }}
          onClick={() => { void handleSave(); }}
          disabled={muts.create.isPending || muts.update.isPending || muts.toggleAttendance.isPending || muts.remove.isPending}
        >{lesson ? 'Сохранить' : 'Создать урок'}</button>
      </div>
      {assigningExtra && lesson && (
        <AssignExtraLessonModal
          missedLessonId={lesson.id}
          candidates={members
            .filter((m) => !present[m.student_id])
            .map((m) => ({ student_id: m.student_id, student_name: m.student_name || `#${m.student_id}` }))}
          defaultTeacherId={lesson.teacher_id}
          onClose={() => setAssigningExtra(false)}
        />
      )}
    </div>
  );
}
