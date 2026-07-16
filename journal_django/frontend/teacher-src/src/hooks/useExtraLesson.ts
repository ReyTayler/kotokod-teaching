import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@shared/lib/api';

/**
 * GET /api/extra-lessons/:id и POST /api/extra-lessons/:id/record (role=teacher,
 * см. apps/extra_lessons/views.py::TeacherExtraLessonDetailView/
 * TeacherExtraLessonRecordView). Используется ExtraLessonRecordModal —
 * фиксация проведения доп.урока (посещаемость только по назначенным
 * участникам, см. apps/extra_lessons/services.py::record).
 */

export interface ExtraLessonParticipant {
  student_id: number;
  student_name: string;
}

export interface ExtraLessonDetail {
  id: number;
  status: 'scheduled' | 'done' | 'cancelled';
  scheduled_date: string;
  scheduled_time: string;
  duration_minutes: number;
  missed_lesson_group_name: string;
  missed_lesson_date: string;
  participants: ExtraLessonParticipant[];
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
      body: { record_url?: string; attendance: { student_id: number; present: boolean }[] };
    }) => api<{ lesson_id: number; payment: number; penalty: number }>(
      'POST', `/api/extra-lessons/${id}/record`, body,
    ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['calendar'] });
      qc.invalidateQueries({ queryKey: ['extra-lesson', vars.id] });
    },
  });
}
