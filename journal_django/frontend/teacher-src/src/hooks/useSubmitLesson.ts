import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@shared/lib/api';
import type { SubmitPayload, SubmitResult } from '../lib/types';

/**
 * POST /api/submitLesson. retry:0 — ОБЯЗАТЕЛЬНО: сервер инкрементирует счётчики
 * уроков/выплаты не идемпотентно, повторная отправка того же запроса задвоит
 * начисления. При сетевой ошибке даём пользователю нажать «Сохранить» ещё раз
 * вручную — никакого авто-resubmit.
 */
export function useSubmitLesson() {
  const qc = useQueryClient();
  return useMutation<SubmitResult, unknown, SubmitPayload>({
    mutationFn: (payload) => api<SubmitResult>('POST', '/api/submitLesson', payload),
    retry: 0,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['report'] });
      qc.invalidateQueries({ queryKey: ['teacherData'] });
      qc.invalidateQueries({ queryKey: ['allData'] });
      qc.invalidateQueries({ queryKey: ['schedule'] });
    },
  });
}
