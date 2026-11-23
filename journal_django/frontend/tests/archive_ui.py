"""Archive frontend acceptance. All API responses are synthetic; no real records are read."""
import json
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect
from schedule_ui import Fixture, OUT, vite_servers

class ArchiveFixture(Fixture):
    def __init__(self):
        super().__init__(role='superadmin')
        self.requests = []
        self.fail = False
        self.rows = [dict(id=i, entity_type='group', name=f'Группа {i:03}', description='Python · Тестовый преподаватель') for i in range(1, 602)]
        self.rows += [dict(id=9001, entity_type='teacher', name='Общий преподаватель', description='archive@example.invalid +79990001234'), dict(id=9002, entity_type='group', name='Общий архив группы', description='Длинное название направления · Тестовый преподаватель'), dict(id=9003, entity_type='direction', name='Общий курс', description='')]

    def route(self, route):
        parsed = urlparse(route.request.url)
        if parsed.path != '/api/admin/archive': return super().route(route)
        self.requests.append(route.request.url)
        assert route.request.method == 'GET'
        if self.fail:
            route.fulfill(status=503, json={'error': 'Тестовая ошибка'}); return
        params = parse_qs(parsed.query)
        query = params.get('q', [''])[0].casefold()
        kind = params.get('entity_type', ['all'])[0]
        page, size = int(params.get('page', ['1'])[0]), int(params.get('page_size', ['50'])[0])
        matched = [r for r in self.rows if all(word in (r['name'] + ' ' + r['description'] + ' #' + str(r['id'])).casefold() for word in query.split())]
        types = ['teacher', 'group', 'direction']
        counts = {key: sum(r['entity_type'] == key for r in matched) for key in types}
        total_counts = {key: sum(r['entity_type'] == key for r in self.rows) for key in types}
        rows = sorted([r for r in matched if kind == 'all' or r['entity_type'] == kind], key=lambda r: (r['name'], r['entity_type'], r['id']))
        route.fulfill(json={'rows': rows[(page-1)*size:page*size], 'total': len(rows), 'page': page, 'page_size': size, 'counts': counts, 'archive_counts': total_counts})


def open_archive(browser, fixture, mobile=False):
    ctx = browser.new_context(viewport={'width': 390 if mobile else 1440, 'height': 844 if mobile else 1000}, is_mobile=mobile, has_touch=mobile)
    ctx.route('**/api/**', fixture.route)
    page = ctx.new_page()
    page.set_default_timeout(10000)
    page.errors = []
    page.on('pageerror', lambda e: page.errors.append(str(e)))
    page.goto('http://127.0.0.1:5273/admin/archive')
    expect(page.get_by_role('heading', name='Архив', exact=True)).to_be_visible()
    return ctx, page


def apply_query(page, text):
    page.get_by_role('button', name='Поиск', exact=True).click()
    field = page.get_by_role('textbox', name='Поиск по всему архиву')
    field.fill(text)
    field.press('Enter')
    expect(page.get_by_role('dialog', name='Поиск по архиву', exact=True)).to_have_count(0)


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        fixture = ArchiveFixture()
        ctx, page = open_archive(browser, fixture)
        expect(page.get_by_role('status').filter(has_text='Найдено: 604')).to_be_visible()
        assert page.get_by_role('button', name='Обновить', exact=False).count() == 0
        assert page.locator('.archive-row').count() == 50
        page.get_by_role('button', name='Поиск', exact=True).click(trial=True)
        page.screenshot(path=str(OUT / 'archive-desktop.png'), animations='disabled')
        assert page.get_by_role('textbox', name='Поиск по всему архиву').count() == 0
        page.get_by_role('button', name='Поиск', exact=True).click()
        field = page.get_by_role('textbox', name='Поиск по всему архиву')
        request_count = len(fixture.requests)
        field.fill('Черновик без применения')
        assert len(fixture.requests) == request_count
        page.screenshot(path=str(OUT / 'archive-search-panel.png'), animations='disabled')
        page.get_by_role('button', name='Подсказка: Поиск по всему архиву', exact=True).click()
        expect(page.get_by_role('dialog', name='Подсказка: Поиск по всему архиву', exact=True)).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog', name='Поиск по архиву', exact=True)).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog', name='Поиск по архиву', exact=True)).to_have_count(0)
        assert len(fixture.requests) == request_count
        first = page.locator('.archive-row').first.get_attribute('href')
        page.get_by_role('button', name='Следующая страница', exact=True).click()
        expect(page).to_have_url(__import__('re').compile('page=2'))
        expect(page.locator('.archive-row').first).not_to_have_attribute('href', first)
        page.get_by_role('button', name='Группы', exact=False).filter(has=page.locator('.archive-type__name')).click()
        expect(page).not_to_have_url(__import__('re').compile('page=2'))
        apply_query(page, 'Общий')
        expect(page.get_by_role('status').filter(has_text='Найдено: 3')).to_be_visible()
        expect(page.locator('.archive-row')).to_have_count(3)
        expect(page.locator('.archive-type').first).to_have_attribute('aria-pressed', 'true')
        assert {page.locator('.archive-row__type').nth(i).inner_text() for i in range(3)} == {'Преподаватель', 'Группа', 'Направление'}
        expect(page.locator('.archive-row').filter(has_text='Общий курс')).to_have_attribute('href', '/admin/directions/9003')
        page.screenshot(path=str(OUT / 'archive-search.png'))
        page.reload()
        expect(page.locator('.archive-query')).to_have_text('Общий')
        expect(page.locator('.archive-row')).to_have_count(3)
        apply_query(page, 'Группа 601')
        expect(page.get_by_role('status').filter(has_text='Найдено: 1')).to_be_visible()
        expect(page.locator('.archive-row')).to_have_attribute('href', '/admin/groups/601')
        apply_query(page, 'archive@example.invalid')
        expect(page.locator('.archive-row')).to_have_attribute('href', '/admin/teachers/9001')
        apply_query(page, 'НичегоНеНайдено')
        expect(page.get_by_text('По вашему запросу ничего не найдено')).to_be_visible()
        page.get_by_role('button', name='Сбросить поиск и фильтр').click()
        expect(page.locator('.archive-query')).to_have_count(0)
        expect(page.locator('.archive-row')).to_have_count(50)
        fixture.fail = True
        page.reload()
        expect(page.get_by_role('alert')).to_contain_text('Не удалось загрузить архив', timeout=15000)
        fixture.fail = False
        page.get_by_role('button', name='Повторить загрузку').click()
        expect(page.locator('.archive-row')).to_have_count(50)
        assert not page.errors, page.errors
        assert all('/api/admin/archive' in url for url in fixture.requests)
        ctx.close()
        ctx, page = open_archive(browser, ArchiveFixture(), mobile=True)
        apply_query(page, 'Общий')
        expect(page.locator('.archive-row')).to_have_count(3)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUT / 'archive-mobile.png'), full_page=True)
        page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
        page.screenshot(path=str(OUT / 'archive-dark.png'), full_page=True, animations='disabled')
        assert not page.errors, page.errors
        page.get_by_role('button', name='Сбросить', exact=True).click()
        expect(page.locator('.archive-query')).to_have_count(0)
        expect(page.locator('.archive-row')).to_have_count(50)
        ctx.close()
        fixture = ArchiveFixture(); fixture.rows = []
        ctx, page = open_archive(browser, fixture)
        expect(page.get_by_text('Архив пока пуст', exact=True)).to_be_visible()
        assert not page.errors, page.errors
        ctx.close(); browser.close()
    print(json.dumps({'result': 'PASS', 'screenshots': str(OUT)}, ensure_ascii=False))

if __name__ == '__main__':
    with vite_servers(): run()
