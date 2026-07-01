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

    def test_absent_student_not_incremented(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
        lessons_done,
    ):
        """Ученик absent → lessons_done НЕ инкрементируется."""
        group_name = '__spa_test_group__ пн 10:00'
        student_name = '__spa_test_student__'
        token = f'acct:{account_fixture}'

        resp = self._submit(account_fixture, {
            'group': group_name,
            'date': '2026-06-10',
            'students': [{'name': student_name, 'present': False}],
        })
        assert resp.status_code == 200
        assert resp.json()['success'] is True

        lesson_id = _get_lesson_id(group_fixture, token)
        assert lesson_id is not None
        try:
            done = lessons_done(group_fixture, student_fixture)
            assert done == 0.0
        finally:
            _cleanup_lesson(lesson_id)

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

    def test_substitution_branch(
        self,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
    ):
        """isSubstitution=true → lesson_type='substitution'."""
        _, teacher_name = teacher_fixture
        group_name = '__spa_test_group__ пн 10:00'
        student_name = '__spa_test_student__'
        token = f'acct:{account_fixture}'

        resp = self._submit(account_fixture, {
            'group': group_name,
            'date': '2026-06-10',
            'isSubstitution': True,
            'originalTeacher': teacher_name,
            'students': [{'name': student_name, 'present': True}],
        })
        assert resp.status_code == 200
        assert resp.json()['success'] is True

        lesson_id = _get_lesson_id(group_fixture, token)
        assert lesson_id is not None
        try:
            with connection.cursor() as cur:
                cur.execute(
                    'SELECT lesson_type, original_teacher_id FROM lessons WHERE id = %s',
                    [lesson_id],
                )
                lt, orig = cur.fetchone()
            assert lt == 'substitution'
            assert orig is not None
        finally:
            _cleanup_lesson(lesson_id)
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE group_memberships SET lessons_done = 0 WHERE id = %s',
                    [membership_fixture],
                )

    def test_transaction_rollback_on_payroll_failure(
        self, monkeypatch,
        teacher_fixture, account_fixture,
        group_fixture, student_fixture, membership_fixture,
        lessons_done,
    ):
        """Ошибка в payroll → полный rollback."""
        from apps.teacher_spa import repository, services

        def _boom(*args, **kwargs):
            raise RuntimeError('payroll insert failed')

        monkeypatch.setattr(repository, 'insert_payroll', _boom)

        with pytest.raises(RuntimeError):
            services.submit_lesson(account_fixture, {
                'group': '__spa_test_group__ пн 10:00',
                'date': '2026-06-10',
                'isSubstitution': False,
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
        """В schedule students содержат {name, lessonsDone, remaining, age}."""
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
        assert 'age' in stu

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
