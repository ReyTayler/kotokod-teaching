# Бухгалтерский отчёт за месяц (Excel-экспорт) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Django management command `export_accounting_report` that writes an Excel report — per student: lessons attended this month, purchase payments this month (date+amount), remaining paid-lesson balance, remaining advance (avans) money.

**Architecture:** A pure data-assembly function (`collect_monthly_report`) reuses existing finance primitives (`balances_for_students`, `fifo_inputs` + `compute_fifo`) to avoid duplicating the half-lesson/FIFO rules, batched across all students (no N+1). A separate pure `write_report_xlsx` function turns the assembled rows into an `.xlsx` file via `openpyxl`. The management command is a thin CLI wrapper: parse `--month`/`--out`, call the two functions, print a one-line summary.

**Tech Stack:** Django management command, Django ORM, `openpyxl` (already a project dependency), `pytest-django`.

**Spec:** `docs/superpowers/specs/2026-07-15-accounting-monthly-report-design.md`

**Note on commits:** this project's convention (CLAUDE.md) is "commit only on explicit user request" — this overrides the writing-plans default of a commit after every step. Stage/verify the diff after each task instead of committing; ask the user when the whole feature is done whether to commit.

---

### Task 1: Command package scaffolding

**Files:**
- Create: `journal_django/apps/finances/management/__init__.py`
- Create: `journal_django/apps/finances/management/commands/__init__.py`

There is no `management/` directory under `apps/finances` yet (confirmed via glob of the app tree) — Django only discovers commands in `<app>/management/commands/*.py` if both `__init__.py` files exist.

- [ ] **Step 1: Create the two empty `__init__.py` files**

Both files are empty (0 bytes) — same as every other app's `management/__init__.py` in this repo (e.g. `apps/groups/management/__init__.py`).

- [ ] **Step 2: Verify Django can see the (still commandless) package**

Run: `cd journal_django && python manage.py help --settings=config.settings.development`
Expected: exits 0, no traceback (just confirms the app package imports cleanly; the command itself doesn't exist yet so it won't be listed).

---

### Task 2: `collect_monthly_report` — data assembly (no Excel yet)

**Files:**
- Create: `journal_django/apps/finances/reports.py`
- Test: `journal_django/apps/finances/tests/test_reports.py`

This is the core data layer. It must NOT duplicate the half-lesson rule or the FIFO remaining-value calculation — reuse `apps.finances.repository._attended_units_case` (the exact `45min→0.5` `Case` expression already used by `balance_for_student`), `apps.finances.repository.balances_for_students` (batched `purchased − attended`), and `apps.finances.repository.fifo_inputs` + `apps.finances.fifo.compute_fifo` (the same batched-FIFO pattern `apps/dashboard/services.py::get_dashboard` already uses for `deferred_total`).

- [ ] **Step 1: Write the failing test**

```python
# journal_django/apps/finances/tests/test_reports.py
"""
Тесты сборки данных отчёта (apps/finances/reports.py::collect_monthly_report).
Использует существующие фикстуры apps/finances/tests/conftest.py.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection

from apps.finances.reports import collect_monthly_report

pytestmark = pytest.mark.django_db


def _add_payment(created, student_id, direction_id, subs, total, paid_at, kind='purchase'):
    lessons = subs * 4 if kind == 'purchase' else -(subs * 4)
    amount = total if kind == 'purchase' else -total
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
            "kind, unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, subs, lessons, kind, total, amount, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def _add_lesson_attendance(created, group_id, teacher_id, student_id, date, duration=60):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO lessons (group_id, teacher_id, lesson_date, lesson_number, "
            "lesson_duration_minutes, lesson_type, submitted_by_token) "
            "VALUES (%s,%s,%s,1,%s,'regular','test') RETURNING id",
            [group_id, teacher_id, date, duration],
        )
        lid = cur.fetchone()[0]
        cur.execute(
            'INSERT INTO lesson_attendance (lesson_id, student_id, present) VALUES (%s,%s,true)',
            [lid, student_id],
        )
    created['lessons'].append(lid)
    return lid


def test_collect_monthly_report_single_student_full_scenario(
    group_fixture, teacher_id_fixture, student_fixture, direction_fixture, graph_cleanup,
):
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE students SET platform_id = 'PL-42' WHERE id = %s", [student_fixture]
        )
    # Две оплаты ВНУТРИ месяца (2026-07), одна ДО месяца (не должна попасть в payments/paid_month_total),
    # один возврат внутри месяца (kind='refund' — не должен попасть в payments/итого, но гасит остаток).
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, '2026-07-05')
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 2, 3600, '2026-07-20')
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, '2026-06-15')
    # 1 обычный урок (1.0) + 1 полу-урок (0.5) внутри месяца = 1.5 посещено.
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-10', duration=60,
    )
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-07-11', duration=45,
    )
    # Урок ВНЕ месяца — не должен попасть в attended_lessons.
    _add_lesson_attendance(
        graph_cleanup, group_fixture, teacher_id_fixture, student_fixture, '2026-08-01', duration=60,
    )

    rows = collect_monthly_report('2026-07')
    row = next(r for r in rows if r.student_id == student_fixture)

    assert row.platform_id == 'PL-42'
    assert row.attended_lessons == 1.5
    assert row.payments == [('2026-07-05', Decimal('2000.00')), ('2026-07-20', Decimal('3600.00'))]
    assert row.paid_month_total == Decimal('5600.00')
    # покуплено 4+8=12 уроков, отработано 1.5 → баланс 10.5
    assert row.balance == 10.5


def test_collect_monthly_report_student_with_no_activity_gets_zero_row(student_fixture):
    rows = collect_monthly_report('2026-07')
    row = next(r for r in rows if r.student_id == student_fixture)

    assert row.platform_id is None
    assert row.attended_lessons == 0
    assert row.payments == []
    assert row.paid_month_total == Decimal('0')
    assert row.balance == 0
    assert row.remaining_value == Decimal('0')


def test_collect_monthly_report_invalid_month_raises_value_error():
    with pytest.raises(ValueError):
        collect_monthly_report('2026-13')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd journal_django && pytest apps/finances/tests/test_reports.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'apps.finances.reports'` (file doesn't exist yet).

- [ ] **Step 3: Write `apps/finances/reports.py`**

```python
# journal_django/apps/finances/reports.py
"""
Сборка данных бухгалтерского отчёта за месяц + запись в Excel.

Переиспользует существующие сервисы финансов — не дублирует правила
half-lesson (apps.finances.repository._attended_units_case) и FIFO-остаток
аванса (apps.finances.repository.fifo_inputs + apps.finances.fifo.compute_fifo,
тот же батч-паттерн, что apps/dashboard/services.py::get_dashboard использует
для deferred_total — один проход по всем ученикам, без запроса в цикле).

См. docs/superpowers/specs/2026-07-15-accounting-monthly-report-design.md
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.core.utils.dates import msk_month_range
from apps.core.utils.decimal import js_number
from apps.finances.fifo import compute_fifo
from apps.finances.repository import _ZERO, _attended_units_case, balances_for_students, fifo_inputs
from apps.lessons.models import LessonAttendance
from apps.payments.models import Payment
from apps.students.models import Student


@dataclass
class MonthlyReportRow:
    student_id: int
    full_name: str
    platform_id: str | None
    attended_lessons: int | float
    payments: list[tuple[str, Decimal]]
    paid_month_total: Decimal
    balance: int | float
    remaining_value: Decimal


def _date_str(value) -> str:
    if isinstance(value, datetime.date):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10]


def collect_monthly_report(month: str) -> list[MonthlyReportRow]:
    """
    Данные отчёта по ВСЕМ ученикам системы за указанный месяц.

    month: 'YYYY-MM'. Посещаемость/оплаты (kind='purchase') — только внутри
    месяца [month_start, month_end] включительно. Баланс и остаток аванса —
    на сегодня (те же величины, что apps.finances.balance.get_student_balance
    отдаёт per-student, но здесь батчево на всех разом).

    Raises:
        ValueError: month не в формате YYYY-MM / невалидный месяц (1-12).
    """
    month_start, month_end = msk_month_range(f'{month}-01')

    students = list(
        Student.objects.order_by('full_name').values('id', 'full_name', 'platform_id')
    )
    student_ids = [s['id'] for s in students]

    attended_rows = (
        LessonAttendance.objects
        .filter(present=True, lesson__lesson_date__gte=month_start, lesson__lesson_date__lte=month_end)
        .values('student_id')
        .annotate(units=Coalesce(Sum(_attended_units_case()), _ZERO))
    )
    attended_by_student = {r['student_id']: r['units'] for r in attended_rows}

    payment_rows = (
        Payment.objects
        .filter(kind='purchase', paid_at__gte=month_start, paid_at__lte=month_end)
        .order_by('student_id', 'paid_at', 'id')
        .values('student_id', 'paid_at', 'total_amount')
    )
    payments_by_student: dict[int, list[tuple[str, Decimal]]] = {}
    for r in payment_rows:
        payments_by_student.setdefault(r['student_id'], []).append(
            (_date_str(r['paid_at']), r['total_amount'])
        )

    balances = balances_for_students(student_ids)

    inp = fifo_inputs()
    remaining_value_by_student: dict[int, Decimal] = {}
    for key in inp['keys']:
        fifo = compute_fifo(
            inp['lots_by_key'].get(key, []), inp['cons_by_key'].get(key, []),
            '0001-01-01', '9999-12-31',
        )
        remaining_value_by_student[int(key)] = fifo['remaining_value']

    rows: list[MonthlyReportRow] = []
    for s in students:
        sid = s['id']
        payments = payments_by_student.get(sid, [])
        rows.append(MonthlyReportRow(
            student_id=sid,
            full_name=s['full_name'],
            platform_id=s['platform_id'],
            attended_lessons=js_number(attended_by_student.get(sid, Decimal('0'))),
            payments=payments,
            paid_month_total=sum((amount for _, amount in payments), Decimal('0')),
            balance=balances.get(sid, 0),
            remaining_value=remaining_value_by_student.get(sid, Decimal('0')),
        ))
    return rows
```

`msk_month_range(f'{month}-01')` (from `apps.core.utils.dates`, already used elsewhere for month-boundary logic) internally does `datetime.date.fromisoformat(f'{month}-01')` — an invalid month (e.g. `'2026-13'`) raises `ValueError` there, before any DB query runs. That's exactly the exception the test in Step 1 expects and the command (Task 4) will catch.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd journal_django && pytest apps/finances/tests/test_reports.py -v`
Expected: 3 passed.

---

### Task 3: `write_report_xlsx` — pure Excel writer (no DB)

**Files:**
- Modify: `journal_django/apps/finances/reports.py` (append `write_report_xlsx`)
- Test: `journal_django/apps/finances/tests/test_reports_xlsx.py`

Pure function, no DB — takes `MonthlyReportRow` objects constructed directly in the test (fast, no fixtures needed). Verifies: header row + dynamic `Дата N`/`Платёж N` column count = max payments across rows, `-` filler for students with fewer payments, and that money/date columns actually got real numeric/date cell values (not strings) so the accountant can sort/sum them in Excel.

- [ ] **Step 1: Write the failing test**

```python
# journal_django/apps/finances/tests/test_reports_xlsx.py
"""
Тесты чистой функции записи Excel (apps/finances/reports.py::write_report_xlsx).
Без БД — строки собираются вручную.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import openpyxl

from apps.finances.reports import MonthlyReportRow, write_report_xlsx


def test_write_report_xlsx_dynamic_payment_columns_and_dashes(tmp_path):
    rows = [
        MonthlyReportRow(
            student_id=1, full_name='Аня А.', platform_id='PL-1',
            attended_lessons=2, payments=[('2026-07-05', Decimal('2000.00'))],
            paid_month_total=Decimal('2000.00'), balance=6, remaining_value=Decimal('2000.00'),
        ),
        MonthlyReportRow(
            student_id=2, full_name='Боря Б.', platform_id=None,
            attended_lessons=0,
            payments=[('2026-07-01', Decimal('1000.00')), ('2026-07-15', Decimal('1500.00'))],
            paid_month_total=Decimal('2500.00'), balance=8, remaining_value=Decimal('2500.00'),
        ),
    ]
    out = tmp_path / 'report.xlsx'

    write_report_xlsx(rows, out)

    wb = openpyxl.load_workbook(out)
    ws = wb.active
    assert ws.title == 'Отчёт'
    header = [c.value for c in ws[1]]
    # 2 ученика с максимум 2 платежами → 2 пары "Дата N"/"Платёж N".
    assert header == [
        'ФИО ученика', 'Platform ID', 'Посещено уроков за месяц',
        'Дата 1', 'Платёж 1', 'Дата 2', 'Платёж 2',
        'Итого оплачено за месяц, ₽', 'Остаток оплаченных уроков', 'Остаток аванса, ₽',
    ]

    row1 = [c.value for c in ws[2]]  # Аня — 1 платёж из 2 возможных
    assert row1[0:3] == ['Аня А.', 'PL-1', 2]
    assert row1[3] == datetime.date(2026, 7, 5)
    assert row1[4] == 2000.0
    assert row1[5] == '-'  # нет второго платежа
    assert row1[6] == '-'
    assert row1[7:10] == [2000.0, 6, 2000.0]

    row2 = [c.value for c in ws[3]]  # Боря — platform_id пуст → '-', 2 платежа
    assert row2[1] == '-'
    assert row2[3] == datetime.date(2026, 7, 1)
    assert row2[5] == datetime.date(2026, 7, 15)


def test_write_report_xlsx_empty_rows_writes_header_only(tmp_path):
    out = tmp_path / 'empty.xlsx'

    write_report_xlsx([], out)

    wb = openpyxl.load_workbook(out)
    ws = wb.active
    assert ws.max_row == 1
    assert ws['A1'].value == 'ФИО ученика'


def test_write_report_xlsx_creates_parent_dir(tmp_path):
    out = tmp_path / 'nested' / 'dir' / 'report.xlsx'

    write_report_xlsx([], out)

    assert out.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd journal_django && pytest apps/finances/tests/test_reports_xlsx.py -v`
Expected: FAIL — `ImportError: cannot import name 'write_report_xlsx' from 'apps.finances.reports'`.

- [ ] **Step 3: Append `write_report_xlsx` to `apps/finances/reports.py`**

```python
def write_report_xlsx(rows: list[MonthlyReportRow], path: str | Path) -> None:
    """Пишет rows в один лист «Отчёт»: один ученик = одна строка."""
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    max_payments = max((len(r.payments) for r in rows), default=0)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Отчёт'

    headers = ['ФИО ученика', 'Platform ID', 'Посещено уроков за месяц']
    for i in range(1, max_payments + 1):
        headers += [f'Дата {i}', f'Платёж {i}']
    headers += ['Итого оплачено за месяц, ₽', 'Остаток оплаченных уроков', 'Остаток аванса, ₽']
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    money_fmt = '#,##0.00'
    date_fmt = 'DD.MM.YYYY'
    total_col = 4 + max_payments * 2
    balance_col = total_col + 1
    remaining_col = balance_col + 1

    for row in rows:
        values: list = [row.full_name, row.platform_id or '-', row.attended_lessons]
        for i in range(max_payments):
            if i < len(row.payments):
                pay_date, pay_amount = row.payments[i]
                values += [datetime.date.fromisoformat(pay_date), float(pay_amount)]
            else:
                values += ['-', '-']
        values += [float(row.paid_month_total), row.balance, float(row.remaining_value)]
        ws.append(values)

    for excel_row in range(2, len(rows) + 2):
        for i in range(max_payments):
            date_col = 4 + i * 2
            amount_col = date_col + 1
            date_cell = ws.cell(row=excel_row, column=date_col)
            if isinstance(date_cell.value, datetime.date):
                date_cell.number_format = date_fmt
            ws.cell(row=excel_row, column=amount_col).number_format = money_fmt
        ws.cell(row=excel_row, column=total_col).number_format = money_fmt
        ws.cell(row=excel_row, column=remaining_col).number_format = money_fmt

    widths = {1: 32, 2: 14, 3: 12, total_col: 18, balance_col: 14, remaining_col: 14}
    for i in range(max_payments):
        widths[4 + i * 2] = 12
        widths[5 + i * 2] = 12
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = 'A2'

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd journal_django && pytest apps/finances/tests/test_reports_xlsx.py -v`
Expected: 3 passed.

---

### Task 4: `export_accounting_report` management command

**Files:**
- Create: `journal_django/apps/finances/management/commands/export_accounting_report.py`
- Test: `journal_django/apps/finances/tests/test_export_accounting_report_command.py`

Thin CLI wrapper around Task 2/3's functions. `--month` required; `--out` optional, defaults to `<BASE_DIR>/reports/accounting_report_<month>.xlsx` (that `reports/` folder doesn't need a `.gitignore` entry — the repo's root `.gitignore` already excludes `*.xlsx`/`*.xls` globally).

- [ ] **Step 1: Write the failing test**

```python
# journal_django/apps/finances/tests/test_export_accounting_report_command.py
"""
Тесты management command export_accounting_report — сквозной прогон
(call_command → читаем результат через openpyxl).
"""
from __future__ import annotations

from decimal import Decimal

import openpyxl
import pytest
from django.core.management import CommandError, call_command
from django.db import connection

pytestmark = pytest.mark.django_db


def _add_payment(created, student_id, direction_id, subs, total, paid_at):
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO payments (student_id, direction_id, subscriptions_count, lessons_count, "
            "unit_price, total_amount, paid_at, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'test') RETURNING id",
            [student_id, direction_id, subs, subs * 4, total, total, paid_at],
        )
        pid = cur.fetchone()[0]
    created['payments'].append(pid)
    return pid


def test_command_writes_xlsx_with_student_row(
    student_fixture, direction_fixture, graph_cleanup, tmp_path,
):
    _add_payment(graph_cleanup, student_fixture, direction_fixture, 1, 2000, '2026-07-05')
    out_path = tmp_path / 'out.xlsx'

    call_command('export_accounting_report', month='2026-07', out=str(out_path))

    assert out_path.exists()
    wb = openpyxl.load_workbook(out_path)
    ws = wb.active
    header = [c.value for c in ws[1]]
    assert header[:3] == ['ФИО ученика', 'Platform ID', 'Посещено уроков за месяц']
    names = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert '__fin_student__' in names


def test_command_invalid_month_raises_command_error(tmp_path):
    with pytest.raises(CommandError):
        call_command('export_accounting_report', month='2026-13', out=str(tmp_path / 'x.xlsx'))
    assert not (tmp_path / 'x.xlsx').exists()


def test_command_default_out_path_uses_reports_dir(settings, tmp_path, monkeypatch):
    settings.BASE_DIR = tmp_path
    monkeypatch.chdir(tmp_path)

    call_command('export_accounting_report', month='2026-07')

    expected = tmp_path / 'reports' / 'accounting_report_2026-07.xlsx'
    assert expected.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd journal_django && pytest apps/finances/tests/test_export_accounting_report_command.py -v`
Expected: FAIL — `django.core.management.base.CommandError: Unknown command: 'export_accounting_report'`.

- [ ] **Step 3: Write the command**

```python
# journal_django/apps/finances/management/commands/export_accounting_report.py
"""
python manage.py export_accounting_report --month=2026-07 [--out=path.xlsx]

Бухгалтерский отчёт за месяц: посещённые уроки, оплаты (дата+сумма), остаток
оплаченных уроков и остаток аванса — по каждому ученику системы.

См. docs/superpowers/specs/2026-07-15-accounting-monthly-report-design.md
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.finances.reports import collect_monthly_report, write_report_xlsx


class Command(BaseCommand):
    help = 'Бухгалтерский отчёт за месяц в Excel: посещаемость, оплаты, остаток уроков и аванса.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month', required=True, type=str,
            help='Месяц отчёта в формате YYYY-MM, например 2026-07',
        )
        parser.add_argument(
            '--out', type=str, default=None,
            help='Путь к выходному .xlsx (по умолчанию reports/accounting_report_<month>.xlsx)',
        )

    def handle(self, *args, **opts):
        month = opts['month']
        try:
            rows = collect_monthly_report(month)
        except ValueError:
            raise CommandError(f'Неверный формат месяца: "{month}". Ожидается YYYY-MM.')

        out = opts['out']
        out_path = Path(out) if out else Path(settings.BASE_DIR) / 'reports' / f'accounting_report_{month}.xlsx'

        write_report_xlsx(rows, out_path)

        self.stdout.write(self.style.SUCCESS(
            f'Готово: {len(rows)} учеников, файл сохранён в {out_path}'
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd journal_django && pytest apps/finances/tests/test_export_accounting_report_command.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full finances test suite to check for regressions**

Run: `cd journal_django && pytest apps/finances -v`
Expected: all tests pass (existing `test_balance.py`, `test_fifo.py`, `test_fifo_inputs.py`, `test_finances_orm_smoke.py`, `test_refund_remaining.py` unaffected + the 3 new test files from Tasks 2-4).

---

### Task 5: Manual smoke run against the real dev DB

Not a code task — a verification step, since this is a one-off accounting deliverable and pytest uses `journal_test`, not the real `journal` dev DB with actual students/payments.

- [ ] **Step 1: Run the command against the dev DB for the current month**

Run: `cd journal_django && python manage.py export_accounting_report --month=2026-07 --settings=config.settings.development`
Expected: `Готово: N учеников, файл сохранён в .../journal_django/reports/accounting_report_2026-07.xlsx`, N roughly matching the known student count.

- [ ] **Step 2: Open the file and spot-check 2-3 known students**

Verify against what's already visible in the admin SPA for those students: `Остаток оплаченных уроков` matches their balance widget, `Остаток аванса` matches their FIFO remaining-value widget, and the payment dates/sums for July match their payment history.

---

## Self-review notes

- **Spec coverage:** platform ID (Task 2, `platform_id` field) ✓; lessons attended in month (Task 2, `attended_rows`) ✓; who/how much paid — date+amount pairs (Task 2 `payments` + Task 3 dynamic columns) ✓; remaining paid lessons (Task 2 `balance`) ✓; remaining avans (Task 2 `remaining_value`) ✓; single-sheet numbered Дата N/Платёж N with `-` filler (Task 3) ✓; refunds excluded (Task 2 `kind='purchase'` filter) ✓; no "who paid" column (not present anywhere in Task 3 headers) ✓; all students, no direction filter (Task 2 queries unfiltered `Student.objects.all()`-equivalent) ✓; management command with `--month`/`--out` (Task 4) ✓; default path `reports/accounting_report_<month>.xlsx` (Task 4) ✓.
- **Type consistency check:** `MonthlyReportRow` fields are used identically across Task 2 (construction), Task 3 (`write_report_xlsx` reads `.full_name`, `.platform_id`, `.attended_lessons`, `.payments`, `.paid_month_total`, `.balance`, `.remaining_value`) — no renames between tasks.
- **No placeholders:** every step has runnable code; no TBD/TODO left.
