from unittest.mock import MagicMock, patch

from apps.sync import sheets_client


def test_read_students_range_uses_students_spreadsheet_id(monkeypatch):
    monkeypatch.setenv('STUDENTS_SPREADSHEET_ID', 'STU123')
    fake_service = MagicMock()
    fake_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        'values': [['a', 'b']],
    }

    with patch.object(sheets_client, '_sheets_service', return_value=fake_service):
        rows = sheets_client.read_students_range('Список всех детей', 'A3:S')

    assert rows == [['a', 'b']]
    fake_service.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
        spreadsheetId='STU123', range='Список всех детей!A3:S',
    )


def test_read_journal_range_uses_journal_spreadsheet_id(monkeypatch):
    monkeypatch.setenv('JOURNAL_SPREADSHEET_ID', 'JRN456')
    fake_service = MagicMock()
    fake_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        'values': [],
    }

    with patch.object(sheets_client, '_sheets_service', return_value=fake_service):
        rows = sheets_client.read_journal_range('Токены', 'A:F')

    assert rows == []
    fake_service.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
        spreadsheetId='JRN456', range='Токены!A:F',
    )


def test_read_range_returns_empty_list_when_no_values(monkeypatch):
    monkeypatch.setenv('STUDENTS_SPREADSHEET_ID', 'STU123')
    fake_service = MagicMock()
    fake_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {}

    with patch.object(sheets_client, '_sheets_service', return_value=fake_service):
        rows = sheets_client.read_students_range('X', 'A1:A1')

    assert rows == []
