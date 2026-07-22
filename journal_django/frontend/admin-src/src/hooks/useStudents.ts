import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Student, Paginated } from '../lib/types';

interface StudentStats {
  overall: {
    lessons_recorded: number;
    attended_count: number;
    attendance_pct: number | null;
    denominator: number;
    this_month: { lessons_recorded: number; attended_count: number; attendance_pct: number | null };
  };
  directions: Array<{
    direction_id: number;
    direction_name: string;
    direction_color: string | null;
    course_total_lessons: number | null;
    lessons_recorded: number;
    attended_count: number;
    attendance_pct: number | null;
    denominator: number;
    last_attended: string | null;
    this_month: { lessons_recorded: number; attended_count: number; attendance_pct: number | null };
    groups: Array<{
      group_id: number;
      group_name: string;
      membership_active: boolean;
      lessons_recorded: number;
      attended_count: number;
      attendance_pct: number | null;
    }>;
  }>;
}

const KEY = ['students'] as const;

// ──────────────────────────────────────────────────────
// Для PaymentModal и других мест, где нужен ВЕСЬ список учеников (autocomplete).
// Бэк теперь всегда отдаёт Paginated — распаковываем .rows здесь, page_size 2000 хватит.
// ──────────────────────────────────────────────────────
export function useStudentsAll() {
  return useQuery({
    queryKey: [...KEY, 'all'],
    queryFn: async () => {
      const res = await api<Paginated<Student>>(
        'GET',
        '/api/admin/students?page=1&page_size=2000&sort_by=full_name&sort_dir=asc',
      );
      return res.rows;
    },
    staleTime: 60_000,
  });
}

// ──────────────────────────────────────────────────────
// Для StudentsListPage (server-side pagination).
// ──────────────────────────────────────────────────────
export interface StudentsListParams {
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  filters: Record<string, string>;
}

function buildStudentsQuery(p: StudentsListParams): string {
  const qs = new URLSearchParams();
  qs.set('page', String(p.page));
  qs.set('page_size', String(p.page_size));
  qs.set('sort_by', p.sort_by);
  qs.set('sort_dir', p.sort_dir);
  for (const [k, v] of Object.entries(p.filters)) {
    if (v) qs.set(`filter[${k}]`, v);
  }
  return qs.toString();
}

export function useStudents(params: StudentsListParams) {
  return useQuery({
    queryKey: [...KEY, 'list', params],
    queryFn: () => api<Paginated<Student>>('GET', `/api/admin/students?${buildStudentsQuery(params)}`),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useStudent(id: number) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api<Student>('GET', `/api/admin/students/${id}`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useStudentStats(id: number) {
  return useQuery({
    queryKey: [...KEY, id, 'stats'],
    queryFn: () => api<StudentStats>('GET', `/api/admin/students/${id}/stats`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useStudentMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['students'] });
    qc.invalidateQueries({ queryKey: ['archive'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: Partial<Student>) => api<Student>('POST', '/api/admin/students', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<Student> }) =>
        api<Student>('PATCH', `/api/admin/students/${id}`, body),
      onSuccess: invalidate,
    }),
    setManager: useMutation({
      mutationFn: ({ id, managerId }: { id: number; managerId: number | null }) =>
        api<Student>('PATCH', `/api/admin/students/${id}/manager`, { manager_id: managerId }),
      onSuccess: () => {
        invalidate();
        qc.invalidateQueries({ queryKey: ['renewals'] });
      },
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/students/${id}`),
      onSuccess: invalidate,
    }),
  };
}
