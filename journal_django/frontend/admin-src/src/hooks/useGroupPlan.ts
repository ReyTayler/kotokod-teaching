/**
 * Мутации операций плана (planned_lessons) — шаг 7 материализованных плановых
 * уроков (docs/lesson-scheduling.md). Стиль зеркалит useGroupSchedule.ts:
 * useMutation + invalidate (без optimistic-апдейтов — не нужны для admin-форм).
 *
 * Все эндпоинты — POST /api/admin/groups/<id>/plan/*, RBAC IsManagerOrAdmin,
 * X-CSRFToken ставит сам api() (см. lib/api.ts). Инвалидируем group-plan
 * (тот же ключ, что useGroupPlanCalendar → useGroupPlan использует для чтения)
 * и ['groups'] (слоты видны и в списке групп).
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { groupPlanKey } from './useGroupPlanCalendar';
import type { PlanRow } from './useGroupPlanCalendar';

function invalidatePlan(qc: ReturnType<typeof useQueryClient>, groupId: number) {
  qc.invalidateQueries({ queryKey: groupPlanKey(groupId) });
  // Слоты (recurrence-шаблон) меняются при permanent-change — видны в списке групп.
  qc.invalidateQueries({ queryKey: ['groups'] });
}

/** POST /plan/generate — сгенерировать план курса (идемпотентно, без тела). */
export function useGeneratePlan(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<PlanRow[]>('POST', `/api/admin/groups/${groupId}/plan/generate`),
    onSuccess: () => invalidatePlan(qc, groupId),
  });
}

export interface ReschedulePayload {
  new_date: string;
  new_time?: string | null;
  new_teacher_id?: number | null;
}

/** POST /plan/<lid>/reschedule — разовый перенос (+опц. время/преподаватель). */
export function useReschedule(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ lessonId, body }: { lessonId: number; body: ReschedulePayload }) =>
      api<PlanRow>('POST', `/api/admin/groups/${groupId}/plan/${lessonId}/reschedule`, body),
    onSuccess: () => invalidatePlan(qc, groupId),
  });
}

export interface PermanentChangePayload {
  from_seq: number;
  new_day_of_week: number; // Вс=0..Сб=6
  new_time?: string | null;
  new_teacher_id?: number | null;
}

/** POST /plan/permanent-change — перенос навсегда с позиции from_seq (effective_from сервер выводит сам). */
export function usePermanentChange(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PermanentChangePayload) =>
      api<PlanRow[]>('POST', `/api/admin/groups/${groupId}/plan/permanent-change`, body),
    onSuccess: () => invalidatePlan(qc, groupId),
  });
}

/** POST /plan/<lid>/change-teacher — разовая смена преподавателя одной строки. */
export function useChangeTeacher(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ lessonId, newTeacherId }: { lessonId: number; newTeacherId: number }) =>
      api<PlanRow>('POST', `/api/admin/groups/${groupId}/plan/${lessonId}/change-teacher`, {
        new_teacher_id: newTeacherId,
      }),
    onSuccess: () => invalidatePlan(qc, groupId),
  });
}

export interface ChangeTeacherPermanentPayload {
  from_seq: number;
  new_teacher_id: number;
}

/** POST /plan/change-teacher-permanent — смена преподавателя хвоста (seq>=from_seq). */
export function useChangeTeacherPermanent(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ChangeTeacherPermanentPayload) =>
      api<PlanRow[]>('POST', `/api/admin/groups/${groupId}/plan/change-teacher-permanent`, body),
    onSuccess: () => invalidatePlan(qc, groupId),
  });
}

/** POST /plan/<lid>/cancel — отмена со сдвигом хвоста на +7 дней (без тела). */
export function useCancelLesson(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (lessonId: number) =>
      api<PlanRow[]>('POST', `/api/admin/groups/${groupId}/plan/${lessonId}/cancel`),
    onSuccess: () => invalidatePlan(qc, groupId),
  });
}
