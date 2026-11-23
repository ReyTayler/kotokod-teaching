"""Browser acceptance of the shared schedule editor, with synthetic API data only.
Run: python journal_django/frontend/tests/schedule_ui.py (starts/stops local Vite).
Requires Playwright Python and installed Edge. Never contacts a real API.
"""
import copy
from contextlib import contextmanager
import datetime as dt
import json
import subprocess
import shutil
import time
import urllib.request
from pathlib import Path
import tempfile
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect

TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())
OUT = Path(tempfile.mkdtemp(prefix='kotokod-schedule-qa-'))

class Fixture:
    def __init__(self, role='manager', active=True, empty=False):
        self.role, self.active = role, active
        self.days = {str(i): [] if empty else [['10:00', '14:00']] for i in range(7)}
        self.overrides = {} if empty else {(MONDAY + dt.timedelta(days=7)).isoformat(): [['12:00', '18:00']]}
        self.writes, self.unhandled = [], []
        self.fail_save, self.fail_lessons = False, False

    def route(self, route):
        req = route.request
        u = urlparse(req.url)
        p, qs = u.path, parse_qs(u.query)
        data, status = {}, 200
        if p == '/api/auth/me':
            data = dict(account_id=1, email='qa@example.invalid', role=self.role, teacher_id=1 if self.role == 'teacher' else None, name='Тестовый сотрудник', twofa_enabled=True)
        elif p == '/api/auth/csrf':
            route.fulfill(status=200, json={}, headers={'Set-Cookie': 'csrftoken=qa; Path=/'}); return
        elif 'work-schedule' in p:
            tail = p.split('work-schedule')[1]
            if req.method != 'GET':
                body = req.post_data_json
                self.writes.append((req.method, tail, copy.deepcopy(body)))
                if self.fail_save:
                    route.fulfill(status=400, json={'error': 'Validation failed', 'details': {'non_field_errors': ['Тестовая ошибка сохранения']}}); return
                if tail == '/template': self.days = body['days']
                elif tail == '/week':
                    for date, ivs in body['days'].items():
                        dow = (dt.date.fromisoformat(date).weekday() + 1) % 7
                        if ivs == self.days[str(dow)]: self.overrides.pop(date, None)
                        else: self.overrides[date] = ivs
                else: raise AssertionError(f'Unexpected mutation: {req.method} {p}')
            elif tail == '/template':
                data = {'days': self.days, 'upcoming_overrides': [{'date': date, 'intervals': ivs} for date, ivs in self.overrides.items() if date >= TODAY.isoformat()]}
            else:
                start, end = dt.date.fromisoformat(qs['from'][0]), dt.date.fromisoformat(qs['to'][0])
                windows = {}
                while start <= end:
                    date = start.isoformat()
                    windows[date] = self.overrides.get(date, self.days[str((start.weekday() + 1) % 7)])
                    start += dt.timedelta(days=1)
                data = {'has_schedule': bool(self.overrides or any(self.days.values())), 'windows': windows, 'override_dates': [date for date in windows if date in self.overrides]}
        elif p in ('/api/admin/calendar', '/api/calendar'):
            if self.fail_lessons:
                route.fulfill(status=503, json={'error': ['Тестовая ошибка загрузки занятий']}); return
            date = qs['from'][0]
            data = {'occurrences': [dict(date=date, time='09:00', durationMinutes=60, status='pending', groupDisplay='Тестовая группа')], 'unscheduled': [], 'window': {'from': date, 'to': qs['to'][0]}}
        elif p == '/api/admin/teachers/1':
            data = dict(id=1, name='Тестовый преподаватель', active=self.active, email='', phone='', created_at='2026-01-01', telegram=None)
        elif p.endswith('/stats'):
            data = dict(month='2026-11', year=2026, last_lesson_date=None, total=dict(sessions=0, minutes=0, substitutions=0), by_direction=[], by_duration=[], monthly=[], group_progress=[], attendance=dict(present=0, counted=0, pct=None), weekday_load=[], unfilled=dict(count=0, oldest_date=None), absences=dict(registered=0, makeup_done=0, makeup_scheduled=0, burned=0, pending_now=0))
        elif p == '/api/admin/groups': data = {'rows': [], 'total': 0, 'page': 1, 'page_size': 50}
        elif 'telegram' in p: data = []
        elif 'notifications' in p or 'tasks' in p: data = {'count': 0, 'results': [], 'unread': 0}
        else:
            self.unhandled.append(p)
            data = []
        route.fulfill(status=status, json=data)


def open_page(browser, fixture, teacher=False, mobile=False):
    ctx = browser.new_context(viewport={'width': 390 if mobile else 1440, 'height': 844 if mobile else 1000}, timezone_id='Europe/Moscow', is_mobile=mobile, has_touch=mobile)
    ctx.route('**/api/**', fixture.route)
    page = ctx.new_page()
    page.set_default_timeout(10000)
    page.errors = []
    page.on('pageerror', lambda e: page.errors.append(str(e)))
    page.goto('http://127.0.0.1:5274/teacher/schedule' if teacher else 'http://127.0.0.1:5273/admin/teachers/1?tab=schedule')
    expect(page.get_by_role('heading', name='Рабочие часы', exact=True)).to_be_visible()
    return ctx, page


def btn(page, name): return page.get_by_role('button', name=name, exact=True)

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        fixture = Fixture()
        ctx, page = open_page(browser, fixture)
        # Roving focus + keyboard editing; no mutation before Save.
        cell = page.locator('[data-col="0"][data-slot="18"]')
        cell.focus(); page.keyboard.press('Space')
        expect(cell).to_have_attribute('aria-pressed', 'true')
        page.keyboard.press('ArrowRight')
        expect(page.locator('[data-col="1"][data-slot="18"]')).to_be_focused()
        assert page.locator('.sched-cell[tabindex="0"]').count() == 1
        assert not fixture.writes
        # Mouse drag paints intermediate slots even with sparse pointer events.
        start = page.locator('[data-col="2"][data-slot="16"]').bounding_box()
        end_box = page.locator('[data-col="2"][data-slot="19"]').bounding_box()
        page.mouse.move(start['x'] + 10, start['y'] + 10)
        page.mouse.down()
        page.mouse.move(end_box['x'] + 10, end_box['y'] + 10, steps=1)
        page.mouse.up()
        for slot in range(16, 20):
            expect(page.locator(f'[data-col="2"][data-slot="{slot}"]')).to_have_attribute('aria-pressed', 'true')
        # Changing the teacher tab must keep the draft until an explicit decision.
        page.get_by_role('tab', name='Группы', exact=True).click()
        expect(page.get_by_role('dialog')).to_be_visible()
        btn(page, 'Остаться').click()
        expect(cell).to_have_attribute('aria-pressed', 'true')
        # Failed save-and-leave retains both draft and target; retry succeeds.
        fixture.fail_save = True
        page.get_by_role('tab', name='Группы', exact=True).click()
        btn(page, 'Сохранить и перейти').click()
        expect(page.get_by_role('dialog').get_by_text('Тестовая ошибка сохранения')).to_be_visible()
        fixture.fail_save = False
        btn(page, 'Сохранить и перейти').click()
        expect(page.get_by_role('tab', name='Группы', exact=True)).to_have_attribute('aria-selected', 'true')
        page.get_by_role('tab', name='График работы', exact=True).click()
        expect(page.get_by_role('heading', name='Рабочие часы', exact=True)).to_be_visible()
        print('PASS: keyboard, tab guard, save failure and retry', flush=True)
        # Exact selectors support 24:00 and normalize neighbouring intervals.
        end = page.get_by_role('button', name='Пн, интервал 1, конец', exact=True)
        end.click(); page.get_by_role('option', name='24:00', exact=True).click()
        expect(end).to_have_text('24:00')
        # Copy only selected days, then discard the whole operation.
        page.locator('.sched-day').first.get_by_role('button', name='Копировать день').click()
        page.get_by_role('dialog').get_by_text('Вт', exact=True).click()
        expect(page.get_by_role('checkbox', name='Вт', exact=True)).to_be_checked()
        btn(page, 'Применить к выбранным дням').click()
        expect(page.get_by_role('button', name='Вт, интервал 1, конец', exact=True)).to_have_text('24:00')
        btn(page, 'Отменить изменения').click()
        print('PASS: precise intervals, 24:00 and copy', flush=True)
        # Reset a future exception is a draft operation and saves only that day.
        btn(page, 'Изменения по датам').click(); btn(page, 'Следующая неделя').click()
        reset = page.get_by_role('button', name='Вернуть день', exact=False)
        expect(reset).to_have_count(1)
        before = len(fixture.writes)
        reset.click()
        expect(btn(page, 'Сохранить изменения недели')).to_be_visible()
        assert len(fixture.writes) == before
        btn(page, 'Сохранить изменения недели').click()
        expect(page.get_by_text('График сохранён', exact=True)).to_be_visible()
        assert list(fixture.writes[-1][2]['days']) == [(MONDAY + dt.timedelta(days=7)).isoformat()]
        assert fixture.writes[-1][0] == 'PUT'
        print('PASS: deferred reset and changed-day payload', flush=True)
        # Past dates are visible but not editable; load error is explicit.
        btn(page, 'Предыдущая неделя').click()
        btn(page, 'Предыдущая неделя').click()
        expect(page.get_by_text('Прошедшая неделя · только просмотр')).to_be_visible()
        assert page.locator('.sched-cell[aria-disabled="true"]').count() == 336
        assert page.locator('.sched-day-add').count() == 0
        fixture.fail_lessons = True
        btn(page, 'Следующая неделя').click()
        btn(page, 'Следующая неделя').click()
        # A different uncached week ensures we exercise a fresh calendar request.
        btn(page, 'Следующая неделя').click()
        expect(btn(page, 'Повторить загрузку занятий')).to_be_visible(timeout=15000)
        fixture.fail_lessons = False
        btn(page, 'Повторить загрузку занятий').click()
        expect(btn(page, 'Повторить загрузку занятий')).to_have_count(0)
        print('PASS: past dates and lessons error recovery', flush=True)
        # Expanded layout and both themes.
        btn(page, 'Развернуть график').click()
        expect(page.locator('.sched--expanded')).to_be_visible()
        page.screenshot(path=str(OUT / 'desktop-light.png'))
        page.evaluate("document.documentElement.setAttribute('data-theme','dark')")
        trigger = page.locator('.sched-interval .select-input__trigger').first
        expected_bg = page.locator('.sched-summary').evaluate('(el) => getComputedStyle(el).backgroundColor')
        expect(trigger).to_have_css('background-color', expected_bg)
        page.screenshot(path=str(OUT / 'desktop-dark.png'), animations='disabled')
        trigger = page.locator('.sched-interval .select-input__trigger').first
        colors = trigger.evaluate('(el) => ({background: getComputedStyle(el).backgroundColor, text: getComputedStyle(el).color})')
        assert colors['background'] != 'rgb(255, 255, 255)', colors
        assert colors['background'] != colors['text'], colors
        btn(page, 'Свернуть график').click()
        assert not page.errors, page.errors
        ctx.close()
        # Mobile editing without the cramped seven-column grid.
        fixture = Fixture(empty=True)
        ctx, page = open_page(browser, fixture, mobile=True)
        expect(page.locator('.sched-grid-panel')).to_be_hidden()
        page.locator('.sched-day').first.get_by_role('button', name='+ Добавить интервал').click()
        btn(page, 'Сохранить обычный график').click()
        expect(page.get_by_text('График сохранён', exact=True)).to_be_visible()
        assert fixture.days['1'] == [['09:00', '11:00']]
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        bar = page.locator('.sched-savebar').bounding_box()
        assert bar['y'] + bar['height'] <= 845, bar
        page.screenshot(path=str(OUT / 'mobile.png'), full_page=True)
        assert not page.errors, page.errors
        ctx.close()
        # Archive has a specific explanation and cannot edit intervals.
        ctx, page = open_page(browser, Fixture(active=False))
        expect(page.get_by_text('Преподаватель в архиве.', exact=False)).to_be_visible()
        assert page.locator('.sched-day-add').count() == 0
        assert not page.errors, page.errors
        ctx.close()
        # Teacher SPA shares the same editor and router navigation protection.
        ctx, page = open_page(browser, Fixture(role='teacher'), teacher=True)
        page.locator('.sched-day').first.get_by_role('button', name='Нерабочий день', exact=True).click()
        btn(page, 'Изменения по датам').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        btn(page, 'Уйти без сохранения').click()
        expect(btn(page, 'Изменения по датам')).to_have_attribute('aria-pressed', 'true')
        page.locator('.sched-day').last.get_by_role('button', name='Нерабочий день', exact=True).click()
        page.get_by_role('link', name='Календарь', exact=True).first.click()
        expect(page.get_by_role('dialog')).to_be_visible()
        btn(page, 'Остаться').click()
        assert not page.errors, page.errors
        ctx.close(); browser.close()
    print(json.dumps({'result': 'PASS', 'screenshots': str(OUT)}, ensure_ascii=False))

@contextmanager
def vite_servers():
    servers = []
    try:
        for name, port in [('admin-src', 5273), ('teacher-src', 5274)]:
            cwd = Path(__file__).resolve().parents[1] / name
            servers.append(subprocess.Popen([shutil.which('node'), str(cwd / 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0))
            for attempt in range(80):
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{port}/' + ('admin/' if name == 'admin-src' else 'teacher/'), timeout=1)
                    break
                except Exception:
                    if servers[-1].poll() is not None: raise RuntimeError(f'Vite {name} exited')
                    time.sleep(.25)
            else: raise RuntimeError(f'Vite {name} did not start')
        yield
    finally:
        for server in servers:
            server.terminate()
            server.wait(timeout=10)


if __name__ == '__main__':
    with vite_servers():
        run()
