import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated } from '../lib/shared-types';
import type { StudentComment } from '../lib/student-comments';

const KEY = ['students', 'comments'] as const;

export function useStudentComments(studentId: number | null, page: number, pageSize: number) {
  return useQuery({
    queryKey: [...KEY, studentId, page, pageSize],
    queryFn: () => api<Paginated<StudentComment>>(
      'GET',
      `/api/admin/students/${studentId}/comments?page=${page}&page_size=${pageSize}`,
    ),
    enabled: !!studentId,
    placeholderData: keepPreviousData,
  });
}

export function useStudentCommentMutations(studentId: number | null) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: [...KEY, studentId] });
  return {
    add: useMutation({
      mutationFn: (body: string) =>
        api<StudentComment>('POST', `/api/admin/students/${studentId}/comments`, { body }),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (commentId: number) =>
        api('DELETE', `/api/admin/students/${studentId}/comments/${commentId}`),
      onSuccess: invalidate,
    }),
  };
}
