import { useMemo, useState } from 'react';
import { Modal } from '../ui/Modal';
import { Field } from '@shared/components/form/Field';
import { DateInput } from '@shared/components/form/DateInput';
import { TextInput } from '@shared/components/form/TextInput';
import { ApiError } from '@shared/lib/api';
import { useToast } from '@shared/components/ui/Toast';
import { useSubmitLesson } from '../../hooks/useSubmitLesson';
import { useGroupDirections } from '../../hooks/useGroupDirections';
import { isoDate, todayMsk } from '../../lib/dates';
import { calcPayment, fmtNum, getCourseLimit, isHalfLesson, lessonNumber, rub } from '../../lib/teacher-calc';
import type { GroupData, SubmitPayload, SubmitResult } from '../../lib/types';

type LessonType = 'regular' | 'reschedule';

/**
 * Форма записи проведённого урока (submitLesson). Клиентские расчёты (выплата,
 * номер урока, лимит курса) — только превью; сервер авторитетен и может
 * посчитать иначе (штраф, округления). См. teacher-calc.ts.
 */
export function LessonForm({
  group,
  groupData,
  isSubstitution,
  originalTeacher,
  onClose,
}: {
  group: string;
  groupData: GroupData;
  isSubstitution?: boolean;
  originalTeacher?: string;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const submitLesson = useSubmitLesson();

  const todayIso = useMemo(() => isoDate(todayMsk()), []);
  const [lessonType, setLessonType] = useState<LessonType>('regular');
  const [date, setDate] = useState(todayIso);
  const [recordUrl, setRecordUrl] = useState('');
  const [present, setPresent] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(groupData.students.map((s) => [s.name, true])),
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
  const allPresent = total > 0 && presentCount === total;

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

  const remaining = groupData.students[0]?.remaining ?? 0;
  const debtWarning = remaining <= 0;
  const penaltyWarning = date !== todayIso;

  const toggleAll = () => {
    const nextVal = !allPresent;
    setPresent(Object.fromEntries(groupData.students.map((s) => [s.name, nextVal])));
  };

  const handleSubmit = () => {
    if (limitExceeded || submitLesson.isPending) return;
    setSubmitError(null);

    const payload: SubmitPayload = {
      group,
      date,
      students: groupData.students.map((s) => ({ name: s.name, present: !!present[s.name] })),
      lessonType,
      ...(recordUrl.trim() ? { recordUrl: recordUrl.trim() } : {}),
      ...(isSubstitution ? { isSubstitution: true, originalTeacher } : {}),
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
      subtitle={isSubstitution ? `Замена · за ${originalTeacher}` : 'Запись урока'}
      onClose={onClose}
    >
      <div className="seg">
        <button
          type="button"
          className={`seg-btn${lessonType === 'regular' ? ' active' : ''}`}
          onClick={() => setLessonType('regular')}
        >
          По расписанию
        </button>
        <button
          type="button"
          className={`seg-btn${lessonType === 'reschedule' ? ' active' : ''}`}
          onClick={() => setLessonType('reschedule')}
        >
          Перенос
        </button>
      </div>

      <Field label="Дата урока">
        <DateInput value={date} onChange={(e) => setDate(e.target.value)} />
      </Field>

      {penaltyWarning && (
        <div className="lf-warn">
          Урок не за сегодня — при сохранении будет удержан штраф 40 ₽ за просрочку отчёта.
        </div>
      )}

      <div>
        <div className="lf-students-hdr">
          <span className="t-sec-label">Посещаемость · {total}</span>
          <button type="button" className="lf-toggle-all" onClick={toggleAll}>
            {allPresent ? 'Снять всех' : 'Отметить всех'}
          </button>
        </div>
        <div className="lf-students">
          {groupData.students.map((s) => (
            <button
              type="button"
              key={s.name}
              className={`lf-student${present[s.name] ? ' is-present' : ''}`}
              onClick={() => setPresent((p) => ({ ...p, [s.name]: !p[s.name] }))}
              aria-pressed={!!present[s.name]}
            >
              <span className="lf-student-name">{s.name}</span>
              <span className="lf-student-state">{present[s.name] ? 'Пришёл' : 'Не пришёл'}</span>
            </button>
          ))}
        </div>
      </div>

      {debtWarning && (
        <div className="lf-warn">
          Оплаченные уроки закончились (остаток: {remaining}).
          {groupData.pm ? ` Сообщите менеджеру ${groupData.pm}.` : ' Сообщите менеджеру.'}
        </div>
      )}

      {limitExceeded && limitMessage && (
        <div className="lf-error">
          <strong>Лимит курса исчерпан.</strong> {limitMessage}
        </div>
      )}

      <Field label="Ссылка на запись (необязательно)">
        <TextInput value={recordUrl} onChange={(e) => setRecordUrl(e.target.value)} placeholder="https://..." />
      </Field>

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
