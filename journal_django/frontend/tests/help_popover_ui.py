"""Acceptance for click-to-open help across real admin pages. All API data is synthetic."""
import json
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from schedule_ui import Fixture, OUT, open_page, btn, vite_servers

class HelpFixture(Fixture):
    def route(self, route):
        p = urlparse(route.request.url).path
        if p == '/api/admin/registry/summary':
            route.fulfill(json={'generated_at': '2026-11-21T10:00:00Z', 'kpis': {'active_students': 0, 'renewal_upsell': 0, 'idle': 0, 'avg_progress': 0, 'lessons_ahead': 0, 'cancellations': 0}, 'today_stream': [], 'signals': {key: {'count': 0} for key in ['ending', 'closed', 'idle', 'no_plan']}})
        elif p == '/api/admin/registry/students':
            route.fulfill(json={'rows': [], 'total': 0, 'page': 1, 'page_size': 30})
        else:
            super().route(route)


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        fixture = HelpFixture(role='superadmin')
        ctx, page = open_page(browser, fixture)
        icon = btn(page, 'Как работать с графиком')
        expect(page.get_by_text('График показывает доступность преподавателя', exact=False)).to_have_count(0)
        icon.hover()
        expect(page.locator('.help-popover__panel')).to_have_count(0)
        icon.click()
        panel = page.get_by_role('dialog', name='Как работать с графиком', exact=True)
        expect(panel).to_be_visible()
        expect(icon).to_have_attribute('aria-expanded', 'true')
        expect(panel.get_by_text('График показывает доступность преподавателя', exact=False)).to_be_visible()
        bounds = panel.bounding_box(); anchor = icon.bounding_box()
        assert abs(bounds['x'] - anchor['x']) < 30, (bounds, anchor)
        page.screenshot(path=str(OUT / 'help-schedule.png'))
        page.keyboard.press('Escape')
        expect(panel).to_have_count(0); expect(icon).to_be_focused()
        page.keyboard.press('Enter'); expect(panel).to_be_visible()
        btn(page, 'Закрыть подсказку').click(); expect(icon).to_be_focused()
        icon.click(); page.locator('.sched-timezone').click(); expect(panel).to_have_count(0)
        icon.click(); icon.click(); expect(panel).to_have_count(0)
        # Help stays operable in the expanded editor; Escape closes only the help.
        btn(page, 'Развернуть график').click()
        icon.click(); expect(panel).to_be_visible()
        page.keyboard.press('Escape')
        expect(panel).to_have_count(0)
        expect(page.locator('.sched--expanded')).to_be_visible()
        btn(page, 'Свернуть график').click()
        # A panel inside a Radix modal must not close its parent or lose focus.
        page.goto('http://127.0.0.1:5273/admin/groups')
        btn(page, '+ Новая').click()
        modal = page.get_by_role('dialog', name='Новая группа', exact=True)
        expect(modal).to_be_visible()
        field_help = modal.get_by_role('button', name='Подсказка: Уроков в группе', exact=True)
        field_help.click()
        help_panel = page.get_by_role('dialog', name='Подсказка: Уроков в группе', exact=True)
        expect(help_panel).to_be_visible()
        expect(help_panel.get_by_text('Сколько уроков курса', exact=False)).to_be_visible()
        assert help_panel.evaluate('(el) => !!el.parentElement.closest("[role=dialog]")')
        page.keyboard.press('Escape')
        expect(help_panel).to_have_count(0); expect(modal).to_be_visible(); expect(field_help).to_be_focused()
        field_help.click(); btn(page, 'Закрыть подсказку').click(); expect(modal).to_be_visible()
        page.screenshot(path=str(OUT / 'help-modal.png'))
        modal.get_by_role('button', name='Закрыть', exact=True).click()
        # The question icon on a KPI must not activate the card filter.
        page.goto('http://127.0.0.1:5273/admin/dashboard')
        kpi_help = btn(page, 'Подсказка: Простой')
        expect(kpi_help).to_be_visible()
        url = page.url
        kpi_help.click()
        expect(page.get_by_role('dialog', name='Подсказка: Простой', exact=True)).to_be_visible()
        assert page.url == url
        page.keyboard.press('Escape')
        btn(page, 'Простой: 0').click()
        expect(page).to_have_url(__import__('re').compile('seg=idle'))
        assert page.locator('button button').count() == 0
        assert not page.errors, page.errors
        assert not fixture.writes
        ctx.close()
        # Touch opening, viewport collision handling, and both color themes.
        ctx, page = open_page(browser, HelpFixture(), mobile=True)
        icon = btn(page, 'Как работать с графиком')
        icon.tap()
        panel = page.get_by_role('dialog', name='Как работать с графиком', exact=True)
        expect(panel).to_be_visible()
        bounds = panel.bounding_box()
        assert 0 <= bounds['x'] and bounds['x'] + bounds['width'] <= 390, bounds
        assert bounds['height'] <= 360, bounds
        page.screenshot(path=str(OUT / 'help-mobile.png'))
        page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
        page.screenshot(path=str(OUT / 'help-dark.png'), animations='disabled')
        btn(page, 'Закрыть подсказку').tap()
        expect(panel).to_have_count(0)
        assert not page.errors, page.errors
        ctx.close(); browser.close()
    print(json.dumps({'result': 'PASS', 'screenshots': str(OUT)}, ensure_ascii=False))

if __name__ == '__main__':
    with vite_servers():
        run()
