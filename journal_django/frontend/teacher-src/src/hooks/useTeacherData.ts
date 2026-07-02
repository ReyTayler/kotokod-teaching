import { useQuery } from '@tanstack/react-query';
import { api } from '@shared/lib/api';
import type { GetDataResponse, GetAllDataResponse } from '../lib/types';

/**
 * POST /api/getData — группы ТОЛЬКО текущего преподавателя (для «Мои занятия»).
 * staleTime покрупнее, чем у отчёта: справочник групп/учеников/остатков меняется
 * реже, чем недельное расписание, и после submitLesson инвалидируется явно.
 */
export function useTeacherData() {
  return useQuery<GetDataResponse>({
    queryKey: ['teacherData'],
    queryFn: () => api<GetDataResponse>('POST', '/api/getData'),
    staleTime: 5 * 60_000,
  });
}

/**
 * POST /api/getAllData — вложено по преподавателю (для вкладки «Замена»).
 * enabled=false, пока пользователь не открыл вкладку — не тянем чужие данные зря.
 */
export function useAllData(enabled: boolean) {
  return useQuery<GetAllDataResponse>({
    queryKey: ['allData'],
    queryFn: () => api<GetAllDataResponse>('POST', '/api/getAllData'),
    enabled,
    staleTime: 5 * 60_000,
  });
}
