import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@shared/lib/api';

/**
 * GET /api/extra-lessons/:id и POST /api/extra-lessons/:id/record (role=teacher,
 * см. apps/extra_lessons/views.py::TeacherExtraLessonDetailView/
 * TeacherExtraLessonRecordView). Используется ExtraLessonRecordModal —
 * фиксация проведения доп.урока. Одна резолюция = один ученик (пер-ученик
 * модель AbsenceResolution), поэтому present — единый флаг, а не список.
 */

export interface ExtraLessonDetail {
  id: number;
  status: 'pending' | 'makeup_scheduled' | 'makeup_done';
  scheduled_date: string;
  scheduled_time: string;
  duration_minutes: number;
  missed_lesson_group_name: string;
  missed_lesson_date: string;
  student_id: number;
  student_name: string;
}

export function useExtraLesson(id: number | null) {
  return useQuery({
    queryKey: ['extra-lesson', id],
    queryFn: () => api<ExtraLessonDetail>('GET', `/api/extra-lessons/${id}`),
    enabled: id != null,
    staleTime: 30_000,
  });
}

export function useRecordExtraLesson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: {
      id: number;
      body: { record_url?: string; present: boolean };
    }) => api<{ lesson_id: number; payment: number; penalty: number }>(
      'POST', `/api/extra-lessons/${id}/record`, body,
    ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['calendar'] });
      qc.invalidateQueries({ queryKey: ['extra-lesson', vars.id] });
    },
  });
}
