"""
test_teacher_spa_api.py — e2e тесты для teacher SPA эндпоинтов.

Фаза 4: аутентификация через JWT (access-cookie), не HMAC session-cookie.
_client(role, account_id) создаёт JWT-клиент для реального аккаунта из БД.

Покрытие:
  Auth:
    - нет cookie → 401
    - role=manager/admin → 403 (teacher-only)
    - role=teacher, account_id не существует → 401 (token_version mismatch)
    - role=teacher, account привязан → 200

  submitLesson, report, schedule, refresh, refreshData — без изменений по смыслу.
"""
from __future__ import annotations

import pytest
from django.conf import settings
from django.db import connection
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db

_ACCESS_COOKIE = settings.SIMPLE_JWT.get('AUTH_COOKIE', 'access')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client(role: str | None, account_id: int | None = None) -> APIClient:
    """
    Создать APIClient.
    - role=None → анонимный клиент (401)
    - role + account_id из БД → JWT access-cookie для реального аккаунта
    - role + несуществующий account_id → JWT с несовпадающей token_version → 401
    """
    c = APIClient()
    if role is None:
        return c

    if account_id is not None:
        from apps.accounts.models import Account
        try:
            user = Account.objects.get(pk=account_id)
            refresh = RefreshToken.for_user(user)
            refresh['token_version'] = user.token_version
            c.cookies[_ACCESS_COOKIE] = str(refresh.access_token)
        except Account.DoesNotExist:
            # Несуществующий аккаунт: выдаём JWT с выдуманным user_id →
            # simplejwt не найдёт пользователя → AuthenticationFailed → 401
            from rest_framework_simplejwt.tokens import AccessToken
            token = AccessToken()
            token['user_id'] = account_id
            token['token_version'] = 0
            c.cookies[_ACCESS_COOKIE] = str(token)
    return c


def _cleanup_lesson(lesson_id: int) -> None:
    """Чистим урок и связанные записи (FK-безопасный порядок)."""
    with connection.cursor() as cur:
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lesson_attendance WHERE lesson_id = %s', [lesson_id])
        cur.execute('DELETE FROM lessons WHERE id = %s', [lesson_id])


def _get_lesson_id(group_id: int, token: str) -> int | None:
    """Найти последний урок по group_id и submitted_by_token."""
    with connection.cursor() as cur:
        cur.execute(
            'SELECT id FROM lessons WHERE group_id = %s AND submitted_by_token = %s '
            'ORDER BY id DESC LIMIT 1',
            [group_id, token],
        )
        row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Auth — общие для всех POST и GET эндпоинтов
# ---------------------------------------------------------------------------

class TestAuthRequirements:

    def test_get_data_no_cookie_401(self):
        resp = _client(None).post('/api/getData', {}, format='json')
        assert resp.status_code == 401

    def test_get_data_manager_403(self, manager_client):
        resp = manager_client.post('/api/getData', {}, format='json')
        assert resp.status_code == 403

    def test_get_data_admin_403(self, admin_client):
        resp = admin_client.post('/api/getData', {}, format='json')
        assert resp.status_code == 403

    def test_submit_lesson_no_cookie_401(self):
        resp = _client(None).post('/api/submitLesson', {}, format='json')
        assert resp.status_code == 401

    def test_report_no_cookie_401(self):
        resp = _client(None).get('/api/report')
        assert resp.status_code == 401

    def test_report_manager_403(self, manager_client):
        resp = manager_client.get('/api/report')
        assert resp.status_code == 403

    def test_schedule_no_cookie_401(self):
        resp = _client(None).get('/api/schedule')
        assert resp.status_code == 401

    def test_refresh_data_no_cookie_401(self):
        resp = _client(None).post('/api/refreshData', {}, format='json')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Auth — teacher с несуществующим account_id
#
# После перехода на JWT: несуществующий user_id в токене →
# simplejwt не найдёт пользователя в БД → AuthenticationFailed → 401.
# ---------------------------------------------------------------------------

class TestUnlinkedTeacherAccount:

    def test_get_data_invalid_account_id_401(self):
        """
        account_id=999999 (не существует в БД) → JWT создаётся с выдуманным user_id
        → simplejwt не найдёт пользователя → 401 Unauthorized.
        """
        resp = _client('teacher', 999999).post('/api/getData', {}, format='json')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# getData / getAllData — teacher linked
# ---------------------------------------------------------------------------

class TestGetData:

    def test_get_data_returns_teacher_and_data(
        self, teacher_fixture, account_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """Привязанный teacher → {teacher, data}."""
        _, teacher_name = teacher_fixture
        resp = _client('teacher', account_fixture).post('/api/getData', {}, format='json')
        assert resp.status_code == 200
        body = resp.json()
        assert body['teacher'] == teacher_name
        assert isinstance(body['data'], dict)

    def test_get_all_data_returns_all(
        self, teacher_fixture, account_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """getAllData → {teacher, data}."""
        _, teacher_name = teacher_fixture
        resp = _client('teacher', account_fixture).post('/api/getAllData', {}, format='json')
        assert resp.status_code == 200
        body = resp.json()
        assert body['teacher'] == teacher_name
        assert isinstance(body['data'], dict)
        assert teacher_name in body['data']


# ---------------------------------------------------------------------------
# submitLesson
# ---------------------------------------------------------------------------

class TestSubmitLesson:

    def _submit(self, account_id: int, payload: dict):
        return _client('teacher', account_id).post('/api/submitLesson', payload, format='json')

    def test_group_not_found(self, teacher_fixture, account_fixture):
        """Несуществующая группа → 200 {success:false, error:'Группа не найдена'}."""
        _, teacher_name = teacher_fixture
        resp = self._submit(account_fixture, {
            'group': '__nonexistent_group__',
            'date': '2026-06-10',
            'students': [],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is False
        assert 'Группа не найдена' in body['error']

    def test_future_date_rejected(self, teacher_fixture, account_fixture):
        """Дата урока в будущем (позже сегодняшней МСК) → 200 {success:false}, без побочных эффектов."""
        resp = self._submit(account_fixture, {
            'group': '__nonexistent_group__',
            'date': '2099-01-01',
            'students': [],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is False
        assert 'наступил' in body['error']

    def test_valid_submit_creates_records(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
        lessons_done,
    ):
        """Валидный запрос → lesson + attendance + payroll, lessonsDone инкрементирован."""
        _, teacher_name = teacher_fixture
        student_name = '__spa_test_student__'
        group_name = '__spa_test_group__ пн 10:00'
        token = f'acct:{account_fixture}'

        resp = self._submit(account_fixture, {
            'group': group_name,
            'date': '2026-06-10',
            'students': [{'name': student_name, 'present': True}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is True
        assert 'payment' in body
        assert 'penalty' in body
        assert 'lessonNumber' in body

        lesson_id = _get_lesson_id(group_fixture, token)
        assert lesson_id is not None

        try:
            with connection.cursor() as cur:
                cur.execute(
                    'SELECT present FROM lesson_attendance '
                    'WHERE lesson_id = %s AND student_id = %s',
                    [lesson_id, student_fixture],
                )
                row = cur.fetchone()
            assert row is not None
            assert row[0] is True

            with connection.cursor() as cur:
                cur.execute(
                    'SELECT payment FROM payroll WHERE lesson_id = %s', [lesson_id]
                )
                pay_row = cur.fetchone()
            assert pay_row is not None

            done = lessons_done(group_fixture, student_fixture)
            assert done == 1.0
        finally:
            _cleanup_lesson(lesson_id)
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                    [membership_fixture],
                )

    def test_half_lesson_step(
        self,
        teacher_fixture, account_fixture,
        half_group_fixture, student_fixture, half_membership_fixture,
        lessons_done,
    ):
        """Группа с '45 минут' в названии → step=0.5, lessonNumber=0.5."""
        group_name = '__spa_half_group__ 45 минут вт 11:00'
        student_name = '__spa_test_student__'
        token = f'acct:{account_fixture}'

        resp = self._submit(account_fixture, {
            'group': group_name,
            'date': '2026-06-10',
            'students': [{'name': student_name, 'present': True}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is True
        assert body['lessonNumber'] == 0.5

        lesson_id = _get_lesson_id(half_group_fixture, token)
        assert lesson_id is not None
        try:
            done = lessons_done(half_group_fixture, student_fixture)
            assert done == 0.5
        finally:
            _cleanup_lesson(lesson_id)
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                    [half_membership_fixture],
                )

    def test_half_lesson_determined_by_duration_not_name(
        self, teacher_fixture, account_fixture, student_fixture,
    ):
        """Ф4: half-lesson по lesson_duration_minutes==45, даже если в имени НЕТ '45 минут'."""
        teacher_id, _ = teacher_fixture
        group_name = '__f4_group__ пн 10:00'  # имя без '45 минут'
        lid = None
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO directions (name,total_lessons,active) "
                "VALUES ('__f4_dir__',8,true) RETURNING id"
            )
            did = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO groups (name,direction_id,teacher_id,is_individual,"
                "lesson_duration_minutes,active,lesson_number_offset) VALUES (%s,%s,%s,false,45,true,0) RETURNING id",
                [group_name, did, teacher_id],
            )
            gid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO group_memberships (group_id,student_id,lessons_done,active) "
                "VALUES (%s,%s,0,true) RETURNING id",
                [gid, student_fixture],
            )
            mid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
                "unit_price, total_amount, paid_at, created_by) "
                "VALUES (%s, %s, 1, 4, 1000, 4000, '2026-06-01', 'test') RETURNING id",
                [student_fixture, did],
            )
            pid = cur.fetchone()[0]
        token = f'acct:{account_fixture}'
        try:
            resp = _client('teacher', account_fixture).post('/api/submitLesson', {
                'group': group_name, 'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            }, format='json')
            assert resp.status_code == 200
            body = resp.json()
            assert body['success'] is True
            assert body['lessonNumber'] == 0.5  # half по duration=45, а не по имени
            lid = _get_lesson_id(gid, token)
        finally:
            if lid:
                _cleanup_lesson(lid)
            with connection.cursor() as cur:
                cur.execute('DELETE FROM group_memberships WHERE id = %s', [mid])
                cur.execute('DELETE FROM payments WHERE id = %s', [pid])
                cur.execute('DELETE FROM groups WHERE id = %s', [gid])
                cur.execute('DELETE FROM directions WHERE id = %s', [did])

    def test_all_absent_blocked(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Урок без единого присутствующего (все «Не пришёл») → success:false,
        ничего не пишется. Блокер «пустого» урока (нет посещаемости — нет урока)."""
        group_name = '__spa_test_group__ пн 10:00'
        student_name = '__spa_test_student__'
        token = f'acct:{account_fixture}'

        resp = self._submit(account_fixture, {
            'group': group_name,
            'date': '2026-06-10',
            'students': [{'name': student_name, 'present': False}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is False
        assert 'присутств' in body['error']

        assert _get_lesson_id(group_fixture, token) is None

    def test_present_blocked_when_no_paid_balance(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture,
    ):
        """
        Ученик без оплаченных уроков (remaining<=0, membership без payments) +
        present:true → success:false, урок/attendance/payroll не создаются.
        """
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO group_memberships (group_id, student_id, lessons_done, active) '
                'VALUES (%s, %s, 0, true) RETURNING id',
                [group_fixture, student_fixture],
            )
            membership_id = cur.fetchone()[0]

        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body['success'] is False
            assert '__spa_test_student__' in body['error']

            token = f'acct:{account_fixture}'
            assert _get_lesson_id(group_fixture, token) is None
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM group_memberships WHERE id = %s', [membership_id])

    def test_empty_students_list_blocked(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Пустой список students (нет ни одного присутствующего) → success:false,
        ничего не пишется — тот же блокер «пустого» урока, что и all-absent."""
        token = f'acct:{account_fixture}'
        resp = self._submit(account_fixture, {
            'group': '__spa_test_group__ пн 10:00',
            'date': '2026-06-10',
            'students': [],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is False
        assert 'присутств' in body['error']
        assert _get_lesson_id(group_fixture, token) is None

    def test_payment_calculation_small_group(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Малая группа (1 ученик, пришёл) → payment=500."""
        group_name = '__spa_test_group__ пн 10:00'
        student_name = '__spa_test_student__'
        token = f'acct:{account_fixture}'

        resp = self._submit(account_fixture, {
            'group': group_name,
            'date': '2026-06-10',
            'students': [{'name': student_name, 'present': True}],
        })
        body = resp.json()
        assert body['success'] is True
        assert body['payment'] == 500

        lesson_id = _get_lesson_id(group_fixture, token)
        if lesson_id:
            _cleanup_lesson(lesson_id)
        with connection.cursor() as cur:
            cur.execute(
                'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                [membership_fixture],
            )

    def test_substitution_derived_from_assigned_planned_lesson(
        self,
        teacher_fixture, account_fixture,
        sub_teacher_fixture, sub_account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """
        Замена выводится сервером: чужая группа + плановое занятие, назначенное
        заменщику админом («Сменить преподавателя»), → lesson_type='substitution',
        teacher_id=заменщик, original_teacher_id=владелец группы.
        """
        owner_id, _ = teacher_fixture
        sub_id, _ = sub_teacher_fixture
        group_name = '__spa_test_group__ пн 10:00'
        student_name = '__spa_test_student__'
        token = f'acct:{sub_account_fixture}'

        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW()) RETURNING id",
                [group_fixture, sub_id],
            )
            planned_id = cur.fetchone()[0]

        try:
            resp = self._submit(sub_account_fixture, {
                'group': group_name,
                'date': '2026-06-10',
                'students': [{'name': student_name, 'present': True}],
            })
            assert resp.status_code == 200
            assert resp.json()['success'] is True

            lesson_id = _get_lesson_id(group_fixture, token)
            assert lesson_id is not None
            try:
                with connection.cursor() as cur:
                    cur.execute(
                        'SELECT lesson_type, teacher_id, original_teacher_id FROM lessons WHERE id = %s',
                        [lesson_id],
                    )
                    lt, tid, orig = cur.fetchone()
                assert lt == 'substitution'
                assert tid == sub_id
                assert orig == owner_id
            finally:
                _cleanup_lesson(lesson_id)
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                        [membership_fixture],
                    )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE id = %s', [planned_id])

    def test_foreign_group_without_assignment_403(
        self,
        teacher_fixture, account_fixture,
        sub_teacher_fixture, sub_account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Чужая группа БЕЗ назначенного планового занятия → 403, урок не создан."""
        resp = self._submit(sub_account_fixture, {
            'group': '__spa_test_group__ пн 10:00',
            'date': '2026-06-10',
            'students': [{'name': '__spa_test_student__', 'present': True}],
        })
        assert resp.status_code == 403
        assert _get_lesson_id(group_fixture, f'acct:{sub_account_fixture}') is None

    def test_client_substitution_fields_rejected_400(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Клиентские isSubstitution/originalTeacher/lessonType больше не принимаются → 400."""
        _, teacher_name = teacher_fixture
        base = {
            'group': '__spa_test_group__ пн 10:00',
            'date': '2026-06-10',
            'students': [{'name': '__spa_test_student__', 'present': True}],
        }
        assert self._submit(account_fixture, {**base, 'isSubstitution': True}).status_code == 400
        assert self._submit(account_fixture, {**base, 'isSubstitution': False}).status_code == 400
        assert self._submit(account_fixture, {**base, 'originalTeacher': teacher_name}).status_code == 400
        assert self._submit(account_fixture, {**base, 'lessonType': 'reschedule'}).status_code == 400
        assert self._submit(account_fixture, {**base, 'lessonType': 'regular'}).status_code == 400
        assert _get_lesson_id(group_fixture, f'acct:{account_fixture}') is None

    def test_reschedule_derived_from_moved_planned_lesson(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """
        Плановая строка своей группы перенесена НА дату отметки (moved_from_date
        задан) → сервер пишет lesson_type='reschedule' без клиентского флага.
        """
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'

        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, moved_from_date, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-10', '10:00', %s, 'pending', '2026-06-08', NOW(), NOW()) "
                'RETURNING id',
                [group_fixture, teacher_id],
            )
            planned_id = cur.fetchone()[0]

        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.status_code == 200
            assert resp.json()['success'] is True

            lesson_id = _get_lesson_id(group_fixture, token)
            assert lesson_id is not None
            try:
                with connection.cursor() as cur:
                    cur.execute('SELECT lesson_type FROM lessons WHERE id = %s', [lesson_id])
                    assert cur.fetchone()[0] == 'reschedule'
            finally:
                _cleanup_lesson(lesson_id)
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                        [membership_fixture],
                    )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE id = %s', [planned_id])

    def test_submit_lesson_links_fact_to_planned_lesson(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """
        submitLesson должен сам привязывать факт к плановой строке (fact_lesson_id +
        status='done'), иначе занятие остаётся «не проведено» в расписании/календаре,
        пока кто-то вручную не прогонит backfill_planned_lessons.
        """
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'

        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW()) "
                'RETURNING id',
                [group_fixture, teacher_id],
            )
            planned_id = cur.fetchone()[0]

        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.status_code == 200
            assert resp.json()['success'] is True

            lesson_id = _get_lesson_id(group_fixture, token)
            assert lesson_id is not None
            try:
                with connection.cursor() as cur:
                    cur.execute(
                        'SELECT fact_lesson_id, status FROM planned_lessons WHERE id = %s',
                        [planned_id],
                    )
                    fact_lesson_id, status = cur.fetchone()
                assert fact_lesson_id == lesson_id
                assert status == 'done'
            finally:
                _cleanup_lesson(lesson_id)
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                        [membership_fixture],
                    )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE id = %s', [planned_id])

    def test_blocked_when_earlier_lesson_unfilled(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Незакрытое занятие прошлой недели → отказ, урок не создаётся."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-03', '10:00', %s, 'pending', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body['success'] is False
            assert body['error'] == (
                'Есть не отмеченные занятия. Обратитесь к менеджеру или '
                'администратору за правкой расписания.'
            )
            assert _get_lesson_id(group_fixture, token) is None
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_not_blocked_when_earlier_lesson_cancelled(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Отменённое занятие долгом не считается — урок записывается."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-03', '10:00', %s, 'cancelled', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.json()['success'] is True
            lesson_id = _get_lesson_id(group_fixture, token)
            try:
                assert lesson_id is not None
            finally:
                if lesson_id is not None:
                    _cleanup_lesson(lesson_id)
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                        [membership_fixture],
                    )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_not_blocked_when_earlier_lesson_done(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Проведённое занятие долгом не считается — урок записывается."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-03', '10:00', %s, 'done', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.json()['success'] is True
            lesson_id = _get_lesson_id(group_fixture, token)
            try:
                assert lesson_id is not None
            finally:
                if lesson_id is not None:
                    _cleanup_lesson(lesson_id)
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                        [membership_fixture],
                    )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_not_blocked_by_non_course_row(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Строка без seq (маркер/разовое занятие) блокером не является."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, NULL, NULL, '2026-06-03', '10:00', %s, 'pending', NOW(), NOW()), "
                "       (%s, 1, 1, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.json()['success'] is True
            lesson_id = _get_lesson_id(group_fixture, token)
            try:
                assert lesson_id is not None
            finally:
                if lesson_id is not None:
                    _cleanup_lesson(lesson_id)
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                        [membership_fixture],
                    )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_not_blocked_by_later_unfilled_lesson(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Незакрытое занятие ПОЗЖЕ отмечаемой даты не мешает ретро-отметке."""
        teacher_id, _ = teacher_fixture
        token = f'acct:{account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-17', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, teacher_id],
            )
        try:
            resp = self._submit(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.json()['success'] is True
            lesson_id = _get_lesson_id(group_fixture, token)
            try:
                assert lesson_id is not None
            finally:
                if lesson_id is not None:
                    _cleanup_lesson(lesson_id)
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                        [membership_fixture],
                    )
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])

    def test_transaction_rollback_on_payroll_failure(
        self, monkeypatch,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
        lessons_done,
    ):
        """Ошибка в payroll → полный rollback."""
        from apps.lessons import repository as lessons_repository
        from apps.teacher_spa import services

        def _boom(*args, **kwargs):
            raise RuntimeError('payroll insert failed')

        # submit_lesson теперь делегирует запись в apps.lessons.services.record_lesson,
        # которое зовёт apps.lessons.repository.insert_payroll (единое ядро — см.
        # docs/superpowers/specs/2026-07-14-unify-lesson-recording-design.md).
        monkeypatch.setattr(lessons_repository, 'insert_payroll', _boom)

        with pytest.raises(RuntimeError):
            services.submit_lesson(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })

        token = f'acct:{account_fixture}'
        assert _get_lesson_id(group_fixture, token) is None
        with connection.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM lesson_attendance la JOIN lessons l ON l.id=la.lesson_id '
                'WHERE l.group_id = %s', [group_fixture],
            )
            assert cur.fetchone()[0] == 0
        assert lessons_done(group_fixture, student_fixture) == 0.0

    def test_invalid_body_400(self, teacher_fixture, account_fixture):
        """Тело без обязательных полей → 400."""
        resp = self._submit(account_fixture, {'group': 'test'})
        assert resp.status_code == 400

    def test_substitute_teacher_is_blocked_too(
        self,
        teacher_fixture, account_fixture,
        sub_teacher_fixture, sub_account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Подменяющий преподаватель блокируется так же: долг группы важнее того,
        кто именно отмечает. Закрыть чужой долг он не вправе — текст отправляет
        его к менеджеру.

        Схема — как в test_substitution_derived_from_assigned_planned_lesson:
        group_fixture принадлежит teacher_fixture (владелец), sub_account_fixture —
        заменщик с плановым занятием, назначенным на дату отметки (иначе 403
        «занятие не назначено» вместо блокера). Плюс незакрытое занятие ГРУППЫ на
        более раннюю дату (назначено владельцу) — has_unfilled_before считает по
        group_id, не по teacher_id, поэтому чужой долг блокирует и заменщика.
        """
        teacher_id, _ = teacher_fixture
        sub_id, _ = sub_teacher_fixture
        token = f'acct:{sub_account_fixture}'
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-03', '10:00', %s, 'pending', NOW(), NOW()), "
                "       (%s, 2, 2, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW())",
                [group_fixture, teacher_id, group_fixture, sub_id],
            )
        try:
            resp = self._submit(sub_account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'students': [{'name': '__spa_test_student__', 'present': True}],
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body['success'] is False
            assert body['error'] == (
                'Есть не отмеченные занятия. Обратитесь к менеджеру или '
                'администратору за правкой расписания.'
            )
            assert _get_lesson_id(group_fixture, token) is None
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE group_id = %s', [group_fixture])


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

class TestReport:

    def test_report_structure(self, teacher_fixture, account_fixture):
        """GET /api/report → {lessons, noTime, weekStart, cachedAt}."""
        resp = _client('teacher', account_fixture).get('/api/report')
        assert resp.status_code == 200
        body = resp.json()
        assert 'lessons' in body
        assert 'noTime' in body
        assert 'weekStart' in body
        assert 'cachedAt' in body
        week_start = body['weekStart']
        assert len(week_start) == 10
        assert week_start[4] == '-' and week_start[7] == '-'

    def test_report_week_start_is_monday(self, teacher_fixture, account_fixture):
        """weekStart — это понедельник."""
        import datetime
        resp = _client('teacher', account_fixture).get('/api/report')
        body = resp.json()
        d = datetime.date.fromisoformat(body['weekStart'])
        assert d.weekday() == 0

    def test_report_group_with_time_in_lessons(
        self, teacher_fixture, account_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """Группа с временем в названии попадает в lessons."""
        resp = _client('teacher', account_fixture).get('/api/report')
        body = resp.json()
        group_names_in_lessons = [item['group'] for item in body['lessons']]
        assert '__spa_test_group__ пн 10:00' in group_names_in_lessons

    def test_report_week_param_valid_monday(self, teacher_fixture, account_fixture):
        """?week=<понедельник> → weekStart совпадает с переданным (навигация по неделям)."""
        resp = _client('teacher', account_fixture).get('/api/report?week=2026-06-01')
        assert resp.status_code == 200
        assert resp.json()['weekStart'] == '2026-06-01'  # 2026-06-01 — понедельник

    def test_report_week_param_non_monday_400(self, teacher_fixture, account_fixture):
        """?week=<не понедельник> → 400."""
        resp = _client('teacher', account_fixture).get('/api/report?week=2026-06-03')
        assert resp.status_code == 400

    def test_report_week_param_invalid_format_400(self, teacher_fixture, account_fixture):
        """?week=<мусор> → 400."""
        resp = _client('teacher', account_fixture).get('/api/report?week=not-a-date')
        assert resp.status_code == 400

    def test_report_no_week_param_defaults_to_current(self, teacher_fixture, account_fixture):
        """Без ?week — weekStart остаётся текущим понедельником (parity)."""
        import datetime
        resp = _client('teacher', account_fixture).get('/api/report')
        assert resp.status_code == 200
        d = datetime.date.fromisoformat(resp.json()['weekStart'])
        assert d.weekday() == 0

    def test_report_mine_scopes_to_own_teacher(
        self, teacher_fixture, account_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """?mine=true → в ответе ТОЛЬКО уроки текущего преподавателя (серверный скоуп)."""
        _, teacher_name = teacher_fixture
        resp = _client('teacher', account_fixture).get('/api/report?mine=true')
        assert resp.status_code == 200
        body = resp.json()
        for item in body['lessons'] + body['noTime']:
            assert item['teacher'] == teacher_name
        assert '__spa_test_group__ пн 10:00' in [i['group'] for i in body['lessons']]


# ---------------------------------------------------------------------------
# schedule
# ---------------------------------------------------------------------------

class TestSchedule:

    def test_schedule_structure(self, teacher_fixture, account_fixture):
        """GET /api/schedule → {lessons, noTime, cachedAt}."""
        resp = _client('teacher', account_fixture).get('/api/schedule')
        assert resp.status_code == 200
        body = resp.json()
        assert 'lessons' in body
        assert 'noTime' in body
        assert 'cachedAt' in body
        assert 'weekStart' not in body

    def test_schedule_students_have_full_info(
        self, teacher_fixture, account_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """В schedule students содержат {name, lessonsDone, remaining, birthDate}."""
        resp = _client('teacher', account_fixture).get('/api/schedule')
        body = resp.json()
        group_lessons = [
            item for item in body['lessons']
            if item.get('group') == '__spa_test_group__ пн 10:00'
        ]
        assert len(group_lessons) >= 1
        stu_list = group_lessons[0]['students']
        assert len(stu_list) >= 1
        stu = stu_list[0]
        assert 'name' in stu
        assert 'lessonsDone' in stu
        assert 'remaining' in stu
        assert 'birthDate' in stu

    def test_schedule_no_time_sort_key(self, teacher_fixture, account_fixture):
        """noTime items имеют sortKey=99999."""
        resp = _client('teacher', account_fixture).get('/api/schedule')
        body = resp.json()
        for item in body['noTime']:
            assert item.get('sortKey') == 99999

    def test_schedule_has_all_times(
        self, teacher_fixture, account_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """lessons items содержат allTimes (список строк)."""
        resp = _client('teacher', account_fixture).get('/api/schedule')
        body = resp.json()
        lesson_items = [
            item for item in body['lessons']
            if item.get('group') == '__spa_test_group__ пн 10:00'
        ]
        assert len(lesson_items) >= 1
        assert 'allTimes' in lesson_items[0]
        assert isinstance(lesson_items[0]['allTimes'], list)


# ---------------------------------------------------------------------------
# refresh redirects
# ---------------------------------------------------------------------------

class TestRefreshRedirects:

    def test_report_refresh_302(self, teacher_fixture, account_fixture):
        """GET /api/report/refresh → 302 → /api/report."""
        resp = _client('teacher', account_fixture).get(
            '/api/report/refresh', follow=False
        )
        assert resp.status_code == 302
        assert resp['Location'] == '/api/report'

    def test_schedule_refresh_302(self, teacher_fixture, account_fixture):
        """GET /api/schedule/refresh → 302 → /api/schedule."""
        resp = _client('teacher', account_fixture).get(
            '/api/schedule/refresh', follow=False
        )
        assert resp.status_code == 302
        assert resp['Location'] == '/api/schedule'


# ---------------------------------------------------------------------------
# refreshData
# ---------------------------------------------------------------------------

class TestRefreshData:

    def test_refresh_data_success(self, teacher_fixture, account_fixture):
        """POST /api/refreshData → {success:true}."""
        resp = _client('teacher', account_fixture).post(
            '/api/refreshData', {}, format='json'
        )
        assert resp.status_code == 200
        assert resp.json() == {'success': True}


# ---------------------------------------------------------------------------
# GET /api/lessons — история «Мои уроки»
# ---------------------------------------------------------------------------

class TestMyLessons:

    def test_no_cookie_401(self):
        assert _client(None).get('/api/lessons').status_code == 401

    def test_manager_403(self, manager_client):
        assert manager_client.get('/api/lessons').status_code == 403

    def test_envelope_shape(self, teacher_fixture, account_fixture):
        """GET /api/lessons → {rows, total, page, page_size}."""
        resp = _client('teacher', account_fixture).get('/api/lessons')
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body['rows'], list)
        assert 'total' in body and 'page' in body and 'page_size' in body

    def test_returns_own_submitted_lesson(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """После submitLesson урок появляется в /api/lessons со скоупом по учителю."""
        group_name = '__spa_test_group__ пн 10:00'
        token = f'acct:{account_fixture}'

        submit = _client('teacher', account_fixture).post('/api/submitLesson', {
            'group': group_name, 'date': '2026-06-10',
            'students': [{'name': '__spa_test_student__', 'present': True}],
        }, format='json')
        assert submit.status_code == 200 and submit.json()['success'] is True

        lesson_id = _get_lesson_id(group_fixture, token)
        try:
            resp = _client('teacher', account_fixture).get('/api/lessons')
            assert resp.status_code == 200
            rows = resp.json()['rows']
            mine = [r for r in rows if r['group'] == group_name and r['date'] == '2026-06-10']
            assert len(mine) >= 1
            row = mine[0]
            assert row['presentCount'] == 1
            assert row['totalCount'] == 1
            assert row['payment'] is not None
            assert row['isSubstitution'] is False
            # Точный источник предмета: ключи присутствуют (значение может быть None,
            # если у тестовой группы нет направления/цвета).
            assert 'direction' in row
            assert 'directionColor' in row
        finally:
            _cleanup_lesson(lesson_id)
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                    [membership_fixture],
                )


# ---------------------------------------------------------------------------
# GET /api/group-directions — карта групп→направление (точный источник предмета)
# ---------------------------------------------------------------------------

class TestGroupDirections:

    def test_no_cookie_401(self):
        assert _client(None).get('/api/group-directions').status_code == 401

    def test_manager_403(self, manager_client):
        assert manager_client.get('/api/group-directions').status_code == 403

    def test_returns_groups_map(
        self, teacher_fixture, account_fixture, group_fixture, student_fixture, membership_fixture
    ):
        """teacher → {groups: {<name>: {direction, color, isIndividual}}}."""
        resp = _client('teacher', account_fixture).get('/api/group-directions')
        assert resp.status_code == 200
        groups = resp.json()['groups']
        assert isinstance(groups, dict)
        entry = groups.get('__spa_test_group__ пн 10:00')
        assert entry is not None
        assert 'direction' in entry and 'color' in entry and 'isIndividual' in entry
        # Ф4: продолжительность + длина курса для half-lesson/лимита без regex
        assert entry['lessonDurationMinutes'] == 60
        assert entry['totalLessons'] == 8


# ---------------------------------------------------------------------------
# GET /api/group-progress — матрица посещаемости группы (страница группы)
# ---------------------------------------------------------------------------

_GROUP_NAME = '__spa_test_group__ пн 10:00'


class TestGroupProgress:

    @staticmethod
    def _url(name: str = _GROUP_NAME) -> str:
        from urllib.parse import quote
        return f'/api/group-progress?group={quote(name)}'

    def test_no_cookie_401(self):
        assert _client(None).get(self._url()).status_code == 401

    def test_manager_403(self, manager_client):
        assert manager_client.get(self._url()).status_code == 403

    def test_missing_param_400(self, teacher_fixture, account_fixture):
        assert _client('teacher', account_fixture).get('/api/group-progress').status_code == 400

    def test_unknown_group_404(self, teacher_fixture, account_fixture):
        assert _client('teacher', account_fixture).get(
            self._url('__nonexistent_group__'),
        ).status_code == 404

    def test_owner_200_contract(
        self, teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Владелец группы → 200, контракт admin-прогресса (students/slots/…)."""
        resp = _client('teacher', account_fixture).get(self._url())
        assert resp.status_code == 200
        body = resp.json()
        assert 'students' in body and 'slots' in body
        assert 'total_slots' in body and 'held_slots' in body
        names = [s['name'] for s in body['students']]
        assert '__spa_test_student__' in names

    def test_foreign_teacher_403(
        self, teacher_fixture, account_fixture,
        sub_teacher_fixture, sub_account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Чужая группа без назначенных занятий → 403."""
        assert _client('teacher', sub_account_fixture).get(self._url()).status_code == 403

    def test_assigned_substitute_200(
        self, teacher_fixture, account_fixture,
        sub_teacher_fixture, sub_account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """Заменщик с назначенным плановым занятием группы → 200."""
        sub_id, _ = sub_teacher_fixture
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO planned_lessons (group_id, seq, lesson_number, scheduled_date, '
                'scheduled_time, teacher_id, status, created_at, updated_at) '
                "VALUES (%s, 1, 1, '2026-06-10', '10:00', %s, 'pending', NOW(), NOW()) RETURNING id",
                [group_fixture, sub_id],
            )
            planned_id = cur.fetchone()[0]
        try:
            assert _client('teacher', sub_account_fixture).get(self._url()).status_code == 200
        finally:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM planned_lessons WHERE id = %s', [planned_id])
