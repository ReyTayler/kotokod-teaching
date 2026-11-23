"""Настройка групповых ставок: браузерная проверка на синтетическом API."""
import copy
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect
from schedule_ui import Fixture, TODAY, vite_servers

OUT = Path(__file__).resolve().parents[3] / 'artifacts' / 'motivation-ux-research'
OUT.mkdir(parents=True, exist_ok=True)
URL = '/api/admin/payroll/group-rate-versions'


class GroupFixture(Fixture):
    def __init__(self, role='superadmin'):
        super().__init__(role=role)
        self.versions = []
        self.fail_save = False

    def route(self, route):
        req = route.request
        path = urlparse(req.url).path
        if path == URL + '/preview':
            body = req.post_data_json
            if not body['small_full_rate'] or float(body['small_full_rate']) < 0:
                route.fulfill(status=400, json={'error': 'Ошибка', 'details': {'small_full_rate': ['Сумма не может быть отрицательной.']}})
            else:
                route.fulfill(json={'results': [
                    dict(total=2, present=2, minutes=60, payment='500', rule_note='Тестовый пример'),
                    dict(total=2, present=1, minutes=60, payment='300', rule_note='Тестовый пример'),
                    dict(total=4, present=3, minutes=60, payment='600', rule_note='Тестовый пример'),
                    dict(total=3, present=1, minutes=45, payment=body['half_lesson_rate'], rule_note='Тестовый пример'),
                    dict(total=3, present=0, minutes=60, payment='0', rule_note='Тестовый пример'),
                ]})
            return
        if path.startswith(URL):
            if req.method == 'GET':
                route.fulfill(json={'results': self.versions}); return
            self.writes.append((req.method, copy.deepcopy(req.post_data_json)))
            if self.fail_save:
                route.fulfill(status=400, json={'error': 'Ошибка', 'details': {
                    'effective_from': ['Версия ставок с этой даты уже есть — выберите другую дату.']}}); return
            body = copy.deepcopy(req.post_data_json)
            assert not (set(body) & {'id', 'is_current', 'editable', 'created_at', 'created_by_name'}), body
            body.update(id=1, is_current=True, editable=True, created_by_name='Тестовый администратор', created_at='2026-11-22T10:00:00Z')
            self.versions = [body]
            route.fulfill(status=201, json={**body, 'recalculated': 2}); return
        if path == '/api/admin/payroll/rate-versions':
            route.fulfill(json={'results': [], 'directions': [], 'engine_lessons': {'lessons': 0, 'latest': None}}); return
        if path == '/api/admin/payroll/personal-rates':
            route.fulfill(json={'rows': [], 'total': 0, 'page': 1, 'page_size': 50}); return
        if path == '/api/admin/teachers':
            route.fulfill(json=[]); return
        if path == '/api/admin/groups':
            route.fulfill(json={'rows': [], 'total': 0, 'page': 1, 'page_size': 50}); return
        super().route(route)


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        for mobile in (False, True):
            fixture = GroupFixture()
            ctx = browser.new_context(viewport={'width': 390 if mobile else 1440, 'height': 844 if mobile else 1000},
                                      timezone_id='Europe/Moscow', is_mobile=mobile, has_touch=mobile)
            ctx.route('**/api/**', fixture.route)
            page = ctx.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto('http://127.0.0.1:5273/admin/settings')
            section = page.get_by_role('region', name='Групповые занятия', exact=True)
            expect(section).to_be_visible()
            expect(page.get_by_role('heading', name='Персональные ставки', exact=True)).to_have_count(0)
            expect(page.get_by_role('tab', name='Групповые занятия', exact=True)).to_have_attribute('aria-selected', 'true')
            section.get_by_role('button', name='Настроить ставки', exact=True).click()
            dialog = page.get_by_role('dialog', name='Групповые ставки с даты', exact=True)
            expect(dialog).to_be_visible()
            save = dialog.get_by_role('button', name='Сохранить', exact=True)
            expect(save).to_be_enabled()
            rate = dialog.get_by_role('spinbutton', name='Урок 45 минут, ₽ за присутствующего', exact=True)
            rate.fill('310.25')
            expect(dialog.get_by_label('Проверка новых условий').get_by_text('310,25 ₽', exact=True).first).to_be_visible()
            expect(dialog.get_by_role('heading', name='Что изменится', exact=True)).to_be_visible()
            expect(save).to_be_enabled()
            page.screenshot(path=str(OUT / ('mobile-form.png' if mobile else 'desktop-form.png')))
            # Server error stays in the form; retry preserves the draft.
            fixture.fail_save = True
            save.click()
            expect(dialog.get_by_text('Версия ставок с этой даты уже есть — выберите другую дату.', exact=True)).to_be_visible()
            expect(rate).to_have_value('310.25')
            if mobile:
                box = rate.bounding_box()
                assert box['width'] >= 100 and box['x'] + box['width'] < 375, box
            page.screenshot(path=str(OUT / ('mobile-error.png' if mobile else 'desktop-error.png')))
            fixture.fail_save = False
            save.click()
            expect(dialog).to_have_count(0)
            expect(section.get_by_text('Действует с', exact=False).first).to_be_visible()
            assert fixture.writes[-1][1]['half_lesson_rate'] == '310.25'
            assert len(fixture.writes) == 2  # preview is read-only
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.reload()
            expect(section.get_by_text('Действует с', exact=False).first).to_be_visible()
            page.screenshot(path=str(OUT / ('mobile-section.png' if mobile else 'desktop-section.png')), full_page=True)
            # Past versions remain visible, with no edit/delete menu.
            fixture.versions[0].update(effective_from=(TODAY - dt.timedelta(days=1)).isoformat(), editable=False)
            page.reload()
            expect(section.get_by_text('Действует с', exact=False).first).to_be_visible()
            section.get_by_text('История и будущие изменения', exact=True).click()
            section.locator('.motivation-history__entry > summary').click()
            expect(section.get_by_role('button', name='Исправить версию')).to_have_count(0)
            expect(section.get_by_role('button', name='Удалить версию')).to_have_count(0)
            section.get_by_role('button', name='Создать на основе этой версии').click()
            expect(dialog).to_be_visible()
            expect(rate).to_have_value('310.25')
            expect(save).to_be_enabled()
            page.keyboard.press('Escape')
            expect(dialog).to_have_count(0)
            page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
            section.get_by_role('button', name='Изменить с даты…').click()
            expect(dialog).to_be_visible()
            expect(rate).to_have_value('310.25')
            expect(save).to_be_enabled()
            page.screenshot(path=str(OUT / ('mobile-dark.png' if mobile else 'desktop-dark.png')))
            page.keyboard.press('Escape')
            expect(dialog).to_have_count(0)
            page.get_by_role('tab', name='Индивидуальные занятия', exact=True).click()
            expect(page.get_by_role('heading', name='Индивидуальные занятия', exact=False)).to_be_visible()
            assert 'motivation=individual' in page.url
            page.get_by_role('tab', name='Персональные ставки', exact=True).click()
            expect(page.get_by_role('heading', name='Персональные ставки', exact=False)).to_be_visible()
            page.get_by_role('tab', name='Групповые занятия', exact=True).click()
            expect(section).to_be_visible()
            assert 'motivation=' not in page.url
            assert not errors, errors
            ctx.close()
        browser.close()
    print(json.dumps({'result': 'PASS', 'screenshots': str(OUT)}, ensure_ascii=False))


if __name__ == '__main__':
    with vite_servers():
        run()
