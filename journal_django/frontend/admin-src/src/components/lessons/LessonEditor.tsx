import { useEffect, useRef, useState } from 'react';
import { useLessonFull, useLessonMutations } from '../../hooks/useLessons';
import { useMemberships } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';
import { DateInput } from '../form/DateInput';
import { Dialog } from '../ui/Dialog';
import { AssignExtraLessonModal } from './AssignExtraLessonModal';
import { fmtDate } from '../../lib/format';
import type { Group } from '../../lib/types';

function currentMonthLabel(): string {
  return new Date().toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow', month: 'long', year: 'numeric' });
}

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
  // Посещаемость, СОХРАНЁННАЯ на сервере (снимок при открытии редактора) — по
  // ней отличаем «переключили в этой сессии» от «уже было так». Нужна, чтобы
  // понять, является ли клик по карточке именно сгоранием урока задним числом
  // (см. burnConfirm ниже), а не обычной правкой ещё не сохранённого урока.
  const [savedPresent, setSavedPresent] = useState<Record<number, boolean>>({});
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [assigningExtra, setAssigningExtra] = useState(false);
  const [burnConfirmStudentId, setBurnConfirmStudentId] = useState<number | null>(null);

  useEffect(() => {
    if (lesson) {
      setDate(String(lesson.lesson_date).slice(0, 10));
      setUrl(lesson.record_url || '');
      const init: Record<number, boolean> = {};
      for (const a of lesson.attendance || []) init[a.student_id] = !!a.present;
      setPresent(init);
      setSavedPresent(init);
    } else if (lessonId === null) {
      setDate('');
      setUrl('');
      // Новый урок — по умолчанию все НЕ присутствовали; админ выставляет вручную.
      const init: Record<number, boolean> = {};
      for (const m of members) init[m.student_id] = false;
      setPresent(init);
      setSavedPresent({});
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
    const willBePresent = !present[sid];
    // Сгорание: у уже сохранённого урока переключаем ученика, отмеченного
    // отсутствующим на сервере, в присутствующего — именно этот переход
    // update_attendance_cell на бэке штампует burned_at (см. LessonEditor —
    // деньги за такой урок считаются в месяце ПРАВКИ, не в месяце урока).
    // Явно предупреждаем об этом, а не молча списываем урок с баланса.
    if (lesson && willBePresent && !savedPresent[sid]) {
      setBurnConfirmStudentId(sid);
      return;
    }
    setPresent((p) => ({ ...p, [sid]: !p[sid] }));
  };

  const confirmBurn = () => {
    if (burnConfirmStudentId === null) return;
    setPresent((p) => ({ ...p, [burnConfirmStudentId]: true }));
    setBurnConfirmStudentId(null);
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
      {burnConfirmStudentId !== null && lesson && (
        <Dialog
          open
          onOpenChange={(o) => !o && setBurnConfirmStudentId(null)}
          title="Отметить урок сгоревшим?"
          footer={
            <>
              <button type="button" className="btn-secondary" onClick={() => setBurnConfirmStudentId(null)}>
                Отмена
              </button>
              <button type="button" className="btn-save" onClick={confirmBurn}>
                Да, сгорел
              </button>
            </>
          }
        >
          <p>
            Урок состоялся {fmtDate(lesson.lesson_date)}, и{' '}
            <strong>{members.find((m) => m.student_id === burnConfirmStudentId)?.student_name || 'ученик'}</strong>{' '}
            был отмечен отсутствующим.
          </p>
          <p>
            Если отметить его присутствующим сейчас — урок спишется с баланса ученика,
            а деньги будут учтены в отчётности за <strong>{currentMonthLabel()}</strong>,
            а не за месяц самого урока.
          </p>
          <p>Если ученик просто был на уроке и это ошибка учителя — отменяйте без опасений, это не «сгорание».</p>
        </Dialog>
      )}
    </div>
  );
}
