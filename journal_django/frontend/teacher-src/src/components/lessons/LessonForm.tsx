import { useMemo, useState } from 'react';
import { Modal } from '../ui/Modal';
import { Field } from '@shared/components/form/Field';
import { DateInput } from '@shared/components/form/DateInput';
import { ApiError } from '@shared/lib/api';
import { useToast } from '@shared/components/ui/Toast';
import { useSubmitLesson } from '../../hooks/useSubmitLesson';
import { useGroupDirections } from '../../hooks/useGroupDirections';
import { isoDate, todayMsk } from '../../lib/dates';
import { calcPayment, fmtNum, getCourseLimit, isHalfLesson, lessonNumber, rub } from '../../lib/teacher-calc';
import type { GroupData, SubmitPayload, SubmitResult } from '../../lib/types';

/** Похожа ли строка на http(s)-ссылку — только мягкая подсказка, не блокирует сохранение. */
function looksLikeUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

/** Ученик исчерпал оплаченные уроки (remaining<=0) — отмечать присутствие нельзя (см. submit_lesson на бэке). */
function isBlocked(s: { remaining: number }): boolean {
  return s.remaining <= 0;
}

/**
 * Форма записи проведённого урока (submitLesson). Клиентские расчёты (выплата,
 * номер урока, лимит курса) — только превью; сервер авторитетен и может
 * посчитать иначе (штраф, округления). См. teacher-calc.ts.
 *
 * isSubstitution — ТОЛЬКО отображение (подзаголовок «Замена»): сервер выводит
 * замену сам из planned_lessons (назначение «Сменить преподавателя» в admin),
 * клиентские isSubstitution/originalTeacher в payload не отправляются (API — 400).
 * Тип урока (перенос) сервер тоже выводит сам — из moved_from_date плановой
 * строки, поэтому выбора «По расписанию / Перенос» в форме больше нет.
 */
export function LessonForm({
  group,
  groupData,
  initialDate,
  isSubstitution,
  onClose,
}: {
  group: string;
  groupData: GroupData;
  /** Предзаполнение даты (клик по занятию в календаре); по умолчанию — сегодня МСК. */
  initialDate?: string;
  isSubstitution?: boolean;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const submitLesson = useSubmitLesson();

  const todayIso = useMemo(() => isoDate(todayMsk()), []);
  const [date, setDate] = useState(initialDate ?? todayIso);
  const [recordUrl, setRecordUrl] = useState('');
  const [present, setPresent] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(groupData.students.map((s) => [s.name, !isBlocked(s)])),
  );
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Первичный источник half-lesson/лимита курса — карта /api/group-directions
  // (кэш общий с GroupsPage/MyLessonsPage). Regex-эвристика — только фолбэк
  // на случай, если карта ещё не загрузилась или группы в ней нет.
  const { data: dirData } = useGroupDirections();
  const dir = dirData?.groups[group];
  const isHalf = dir ? dir.lessonDurationMinutes === 45 : isHalfLesson(group);
  const { done, step, next } = lessonNumber(groupData.students, isHalf);
  const limit = dir ? dir.totalLessons : getCourseLimit(group);
  const total = groupData.students.length;
  const presentCount = groupData.students.reduce((n, s) => n + (present[s.name] ? 1 : 0), 0);
  const absentCount = total - presentCount;
  const payment = calcPayment(total, presentCount, isHalf);
  const eligibleStudents = groupData.students.filter((s) => !isBlocked(s));
  const allPresent = eligibleStudents.length > 0 && eligibleStudents.every((s) => present[s.name]);

  const limitExceeded = limit !== null && Math.ceil(next) > limit;
  const limitMessage = useMemo(() => {
    if (limit === null) return null;
    const prefix = `По данному курсу максимум ${limit} уроков. Пройдено: ${done}.`;
    const remainingSteps = limit - done;
    if (remainingSteps > 0 && remainingSteps < step) {
      return `${prefix} Недостаточно для ${isHalf ? 'полурока' : 'урока'} (нужно ${step}, доступно ${remainingSteps.toFixed(1)}).`;
    }
    return `${prefix} Заполнение заблокировано.`;
  }, [limit, done, step, isHalf]);

  const blockedStudents = groupData.students.filter((s) => isBlocked(s));
  const penaltyWarning = date !== todayIso;

  const toggleAll = () => {
    const nextVal = !allPresent;
    setPresent(Object.fromEntries(
      groupData.students.map((s) => [s.name, isBlocked(s) ? false : nextVal]),
    ));
  };

  const handleSubmit = () => {
    if (limitExceeded || submitLesson.isPending) return;
    setSubmitError(null);

    const payload: SubmitPayload = {
      group,
      date,
      students: groupData.students.map((s) => ({ name: s.name, present: !!present[s.name] })),
      ...(recordUrl.trim() ? { recordUrl: recordUrl.trim() } : {}),
    };

    submitLesson.mutate(payload, {
      // result.success === true (не просто `if (result.success)`): при
      // strictNullChecks:false (см. tsconfig.json — общая настройка проекта)
      // TS не narrow-ит union по boolean-дискриминанту через truthy-проверку.
      onSuccess: (result: SubmitResult) => {
        if (result.success === true) {
          toast(`Урок записан · ${rub(result.payment)}`, 'ok');
          onClose();
        } else {
          setSubmitError(result.error);
        }
      },
      onError: (err) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setSubmitError('Сессия истекла. Обновите страницу и войдите заново.');
        } else if (err instanceof ApiError) {
          setSubmitError(err.message);
        } else {
          setSubmitError('Не удалось сохранить урок. Проверьте соединение и попробуйте ещё раз.');
        }
      },
    });
  };

  return (
    <Modal
      title={group}
      subtitle={isSubstitution ? 'Запись урока · замена' : 'Запись урока'}
      onClose={onClose}
    >
      {/* Дата урока = дата занятия по расписанию, менять руками нельзя (иначе штраф за просрочку можно обойти). */}
      <Field label="Дата урока">
        <DateInput value={date} onChange={(e) => setDate(e.target.value)} disabled />
      </Field>

      {penaltyWarning && (
        <div className="lf-warn">
          Внимание, заполнение отчёта за урок просрочено.
        </div>
      )}

      <div>
        <div className="lf-students-hdr">
          <span className="t-sec-label">Посещаемость · {total}</span>
          <button
            type="button"
            className="lf-toggle-all"
            onClick={toggleAll}
            disabled={eligibleStudents.length === 0}
          >
            {allPresent ? 'Снять всех' : 'Отметить всех'}
          </button>
        </div>
        <div className="lf-students">
          {groupData.students.map((s) => {
            const blocked = isBlocked(s);
            return (
              <button
                type="button"
                key={s.name}
                className={`lf-student${present[s.name] ? ' is-present' : ''}${blocked ? ' is-blocked' : ''}`}
                onClick={() => {
                  if (blocked) return;
                  setPresent((p) => ({ ...p, [s.name]: !p[s.name] }));
                }}
                aria-pressed={!!present[s.name]}
                disabled={blocked}
                title={blocked ? 'Нет оплаченных уроков — отметить нельзя' : undefined}
              >
                <span className="lf-student-name">{s.name}</span>
                <span className="lf-student-state">
                  {blocked ? 'Нет оплаты' : present[s.name] ? 'Пришёл' : 'Не пришёл'}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {blockedStudents.length > 0 && (
        <div className="lf-warn">
          Нет оплаченных уроков: {blockedStudents.map((s) => s.name).join(', ')}. Отметить их нельзя
          {groupData.pm ? ` — сообщите менеджеру ${groupData.pm}.` : ' — сообщите менеджеру.'}
        </div>
      )}

      {limitExceeded && limitMessage && (
        <div className="lf-error">
          <strong>Лимит курса исчерпан.</strong> {limitMessage}
        </div>
      )}

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
        {recordUrl.trim() !== '' && !looksLikeUrl(recordUrl.trim()) && (
          <span className="lf-record-hint">Похоже, это не ссылка — проверьте, что скопировали адрес целиком.</span>
        )}
      </div>

      <div className="lf-preview">
        <div className="lf-preview-row">
          <span>Пришли {presentCount} / Не пришли {absentCount}</span>
          <span className="lf-preview-money">Выплата {rub(payment)}</span>
        </div>
        <div className="lf-preview-num">
          №{fmtNum(next)}{isHalf ? ' (45 минут)' : ''}
        </div>
      </div>

      {submitError && <div className="lf-error">{submitError}</div>}

      <div className="lf-actions">
        <button type="button" className="btn-cancel" onClick={onClose}>Отмена</button>
        <button
          type="button"
          className="btn-save"
          disabled={limitExceeded || submitLesson.isPending}
          onClick={handleSubmit}
        >
          {submitLesson.isPending ? 'Сохранение…' : 'Сохранить урок'}
        </button>
      </div>
    </Modal>
  );
}
