import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { GroupScheduleData, ScheduleException, ScheduleExceptionKind } from '../lib/types';

const KEY = (groupId: number) => ['group-schedule', groupId] as const;

export function useGroupSchedule(groupId: number) {
  return useQuery({
    queryKey: KEY(groupId),
    queryFn: () => api<GroupScheduleData>('GET', `/api/admin/groups/${groupId}/schedule`),
    enabled: Number.isFinite(groupId) && groupId > 0,
  });
}

export interface ScheduleChangePayload {
  effective_from: string;
  slots: { day_of_week: number; start_time: string }[];
}

export function useScheduleChange(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ScheduleChangePayload) =>
      api<GroupScheduleData>('POST', `/api/admin/groups/${groupId}/schedule-change`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY(groupId) });
      // Слоты группы видны и в списке групп (GroupsListPage/GroupFormModal) — сбрасываем тоже.
      qc.invalidateQueries({ queryKey: ['groups'] });
    },
  });
}

export interface ExceptionPayload {
  kind: ScheduleExceptionKind;
  original_date?: string | null;
  original_time?: string | null;
  new_date?: string | null;
  new_start_time?: string | null;
  new_teacher_id?: number | null;
  note?: string | null;
}

export function useCreateException(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ExceptionPayload) =>
      api<ScheduleException>('POST', `/api/admin/groups/${groupId}/exceptions`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY(groupId) }),
  });
}

export function useDeleteException(groupId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (exceptionId: number) =>
      api<void>('DELETE', `/api/admin/groups/${groupId}/exceptions/${exceptionId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY(groupId) }),
  });
}
