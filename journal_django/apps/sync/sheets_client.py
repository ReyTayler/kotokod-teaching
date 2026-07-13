"""Тонкий клиент Google Sheets (только чтение) — порт read-функций services/sheets.js.

Не переносим write-функции (appendToJournal/updateStudentCell/batchUpdateCounters) —
их звал только старый Express teacher-report flow, backfill-скрипты их не
используют. Тот же service-account-key.json и те же переменные
STUDENTS_SPREADSHEET_ID/JOURNAL_SPREADSHEET_ID из .env, что и у Node-версии.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build

_SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
_KEY_PATH = Path(settings.REPO_ROOT) / 'service-account-key.json'

_service = None


def _sheets_service():
    """Ленивая инициализация клиента — не дёргаем Google API при импорте модуля."""
    global _service
    if _service is None:
        creds = service_account.Credentials.from_service_account_file(str(_KEY_PATH), scopes=_SCOPES)
        _service = build('sheets', 'v4', credentials=creds)
    return _service


def _read_range(spreadsheet_id: str, sheet_name: str, cell_range: str) -> list[list]:
    result = _sheets_service().spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f'{sheet_name}!{cell_range}',
    ).execute()
    return result.get('values', [])


def read_students_range(sheet_name: str, cell_range: str) -> list[list]:
    """Чтение диапазона из таблицы учеников (STUDENTS_SPREADSHEET_ID)."""
    return _read_range(os.environ['STUDENTS_SPREADSHEET_ID'], sheet_name, cell_range)


def read_journal_range(sheet_name: str, cell_range: str) -> list[list]:
    """Чтение диапазона из таблицы журнала (JOURNAL_SPREADSHEET_ID)."""
    return _read_range(os.environ['JOURNAL_SPREADSHEET_ID'], sheet_name, cell_range)
