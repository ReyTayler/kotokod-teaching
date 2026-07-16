import { useEffect, useState } from 'react';
import { Modal } from '../ui/Modal';
import { ApiError } from '@shared/lib/api';
import { useToast } from '@shared/components/ui/Toast';
import { useExtraLesson, useRecordExtraLesson } from '../../hooks/useExtraLesson';

/** Похожа ли строка на http(s)-ссылку — только мягкая подсказка, не блокирует сохранение. */
function looksLikeUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * Фиксация проведения доп.урока (ExtraLessonAssignment) — посещаемость
 * только по назначенным участникам (не по всей группе, в отличие от
 * LessonForm). См. apps/extra_lessons/views.py::TeacherExtraLessonRecordView,
 * apps/extra_lessons/services.py::record. Переиспользует lf-* стили из
 * groups.css (тот же визуальный язык, что LessonForm), чтобы не заводить
 * новые ad-hoc классы.
 */
export function ExtraLessonRecordModal({ assignmentId, onClose }: { assignmentId: number; onClose: () => void }) {
  const { toast } = useToast();
  const { data, isLoading, isError } = useExtraLesson(assignmentId);
  const record = useRecordExtraLesson();
  const [recordUrl, setRecordUrl] = useState('');
  const [present, setPresent] = useState<Record<number, boolean>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setPresent(Object.fromEntries(data.participants.map((p) => [p.student_id, true])));
  }, [data]);

  if (isLoading || !data) {
    return (
      <Modal title="Доп.урок" onClose={onClose}>
        {isError
          ? <div className="cal-error">Не удалось загрузить доп.урок. Попробуйте ещё раз.</div>
          : <div className="cal-empty">Загрузка…</div>}
      </Modal>
    );
  }

  const total = data.participants.length;
  const presentCount = data.participants.reduce((n, p) => n + (present[p.student_id] ? 1 : 0), 0);
  const absentCount = total - presentCount;
  const allPresent = total > 0 && data.participants.every((p) => present[p.student_id]);

  const toggleAll = () => {
    const nextVal = !allPresent;
    setPresent(Object.fromEntries(data.participants.map((p) => [p.student_id, nextVal])));
  };

  const handleSubmit = () => {
    if (record.isPending) return;
    setSubmitError(null);
    const attendance = data.participants.map((p) => ({
      student_id: p.student_id,
      present: !!present[p.student_id],
    }));
    record.mutate(
      { id: assignmentId, body: { record_url: recordUrl.trim() || undefined, attendance } },
      {
        onSuccess: (result) => {
          toast(`Доп.урок записан · ${result.payment} ₽`, 'ok');
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
            setSubmitError('Сессия истекла или доп.урок принадлежит другому преподавателю.');
          } else if (err instanceof ApiError) {
            setSubmitError(err.message);
          } else {
            setSubmitError('Не удалось сохранить доп.урок. Проверьте соединение и попробуйте ещё раз.');
          }
        },
      },
    );
  };

  return (
    <Modal
      title={`Доп.урок за ${data.missed_lesson_date}`}
      subtitle={`${data.missed_lesson_group_name} · ${data.scheduled_date} ${data.scheduled_time.slice(0, 5)}`}
      onClose={onClose}
    >
      <div>
        <div className="lf-students-hdr">
          <span className="t-sec-label">Посещаемость · {total}</span>
          <button type="button" className="lf-toggle-all" onClick={toggleAll} disabled={total === 0}>
            {allPresent ? 'Снять всех' : 'Отметить всех'}
          </button>
        </div>
        <div className="lf-students">
          {data.participants.map((p) => (
            <button
              type="button"
              key={p.student_id}
              className={`lf-student${present[p.student_id] ? ' is-present' : ''}`}
              onClick={() => setPresent((prev) => ({ ...prev, [p.student_id]: !prev[p.student_id] }))}
              aria-pressed={!!present[p.student_id]}
            >
              <span className="lf-student-name">{p.student_name}</span>
              <span className="lf-student-state">{present[p.student_id] ? 'Пришёл' : 'Не пришёл'}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="lf-record">
        <div className="lf-record-head">
          <span className="t-sec-label">Запись урока</span>
          <span className="lf-record-optional">необязательно</span>
        </div>
        <div className={`lf-record-box${recordUrl.trim() ? (looksLikeUrl(recordUrl.trim()) ? ' is-valid' : ' is-suspect') : ''}`}>
          <svg className="lf-record-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
          <input
            className="lf-record-input"
            type="url"
            inputMode="url"
            value={recordUrl}
            onChange={(e) => setRecordUrl(e.target.value)}
            placeholder="Вставьте ссылку на запись занятия…"
            aria-label="Ссылка на запись урока"
          />
          {recordUrl && (
            <button
              type="button"
              className="lf-record-clear"
              onClick={() => setRecordUrl('')}
              aria-label="Очистить ссылку"
              title="Очистить"
            >
              ×
            </button>
          )}
        </div>
      </div>

      <div className="lf-preview">
        <div className="lf-preview-row">
          <span>Пришли {presentCount} / Не пришли {absentCount}</span>
        </div>
      </div>

      {submitError && <div className="lf-error">{submitError}</div>}

      <div className="lf-actions">
        <button type="button" className="btn-cancel" onClick={onClose}>Отмена</button>
        <button
          type="button"
          className="btn-save"
          disabled={record.isPending}
          onClick={handleSubmit}
        >
          {record.isPending ? 'Сохранение…' : 'Сохранить доп.урок'}
        </button>
      </div>
    </Modal>
  );
}
