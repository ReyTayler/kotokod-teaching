// Комментарии к сущности карточки (ученик, преподаватель). Бэкенд:
// /api/admin/<students|teachers>/:id/comments — одинаковый контракт у обоих.

/** Сущности, у которых в карточке есть вкладка «Комментарии». */
export type CommentEntity = 'students' | 'teachers';

export interface EntityComment {
  id: number;
  body: string;
  created_at: string;
  author_id: number | null;
  author_name: string | null;
}
