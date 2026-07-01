const { google } = require('googleapis');
const path = require('path');

// Инициализация Google Sheets API
const auth = new google.auth.GoogleAuth({
    keyFile: path.join(__dirname, '..', 'service-account-key.json'),
    scopes: ['https://www.googleapis.com/auth/spreadsheets'],
});

const sheets = google.sheets({ version: 'v4', auth });

// ДВА ID таблиц
const STUDENTS_SPREADSHEET_ID = process.env.STUDENTS_SPREADSHEET_ID;
const JOURNAL_SPREADSHEET_ID = process.env.JOURNAL_SPREADSHEET_ID;

/**
 * Чтение диапазона из таблицы учеников
 */
async function readStudentsRange(sheetName, range) {
    try {
        const response = await sheets.spreadsheets.values.get({
            spreadsheetId: STUDENTS_SPREADSHEET_ID,
            range: `${sheetName}!${range}`,
        });
        return response.data.values || [];
    } catch (error) {
        console.error('Ошибка чтения (students):', error.message);
        throw error;
    }
}

/**
 * Чтение диапазона из таблицы журнала
 */
async function readJournalRange(sheetName, range) {
    try {
        const response = await sheets.spreadsheets.values.get({
            spreadsheetId: JOURNAL_SPREADSHEET_ID,
            range: `${sheetName}!${range}`,
        });
        return response.data.values || [];
    } catch (error) {
        console.error('Ошибка чтения (journal):', error.message);
        throw error;
    }
}

/**
 * Запись данных в таблицу журнала — с автоматическим расширением листа
 */
async function appendToJournal(sheetName, rows) {
    try {
        console.log(`📝 Запись в лист "${sheetName}"...`);

        // 1. Получаем ID листа
        const sheetInfo = await sheets.spreadsheets.get({
            spreadsheetId: JOURNAL_SPREADSHEET_ID,
            fields: 'sheets.properties',
        });

        const sheet = sheetInfo.data.sheets.find(
            s => s.properties.title === sheetName
        );

        if (!sheet) {
            throw new Error(`Лист "${sheetName}" не найден`);
        }

        const sheetId = sheet.properties.sheetId;
        const currentRows = sheet.properties.gridProperties.rowCount || 1000;

        console.log(`  → В листе сейчас ${currentRows} строк`);

        // 2. Читаем столбец A, чтобы найти последнюю заполненную строку
        const response = await sheets.spreadsheets.values.get({
            spreadsheetId: JOURNAL_SPREADSHEET_ID,
            range: `${sheetName}!A:A`,
        });

        const values = response.data.values || [];

        // 3. Находим последнюю НЕпустую строку
        let lastDataRow = 0;
        for (let i = 0; i < values.length; i++) {
            const cell = values[i];
            if (cell && cell.length > 0 && cell[0] && String(cell[0]).trim() !== '') {
                lastDataRow = i + 1;
            }
        }

        // 4. Целевая строка = следующая после последней заполненной
        let targetRow = lastDataRow + 1;

        console.log(`  → Последняя заполненная строка: ${lastDataRow}`);
        console.log(`  → Целевая строка: ${targetRow}`);

        // 5. Если целевая строка больше текущего количества строк — расширяем лист
        if (targetRow > currentRows) {
            const rowsToAdd = targetRow - currentRows + 10; // +10 с запасом
            console.log(`  ⚠️ Расширяем лист на ${rowsToAdd} строк...`);

            await sheets.spreadsheets.batchUpdate({
                spreadsheetId: JOURNAL_SPREADSHEET_ID,
                requestBody: {
                    requests: [{
                        appendDimension: {
                            sheetId: sheetId,
                            dimension: 'ROWS',
                            length: rowsToAdd
                        }
                    }]
                }
            });

            console.log(`  ✅ Лист расширен`);
        }

        // 6. Записываем данные
        const range = `${sheetName}!A${targetRow}`;
        await sheets.spreadsheets.values.update({
            spreadsheetId: JOURNAL_SPREADSHEET_ID,
            range: range,
            valueInputOption: 'USER_ENTERED',
            requestBody: { values: rows },
        });

        console.log(`  ✅ Данные записаны в ${range}`);
        return { row: targetRow };

    } catch (error) {
        console.error('  ❌ Ошибка записи в журнал:', error.message);
        throw error;
    }
}

/**
 * Обновление ячейки в таблице учеников (для счетчиков уроков)
 */
async function updateStudentCell(sheetName, cell, value) {
    try {
        await sheets.spreadsheets.values.update({
            spreadsheetId: STUDENTS_SPREADSHEET_ID,
            range: `${sheetName}!${cell}`,
            valueInputOption: 'USER_ENTERED',
            requestBody: { values: [[value]] },
        });
    } catch (error) {
        console.error('Ошибка обновления ячейки ученика:', error.message);
        throw error;
    }
}

/**
 * Массовое обновление счётчиков уроков (ОДНИМ запросом)
 * @param {Array} updates - массив объектов { sheetName, cell, value }
 */
async function batchUpdateCounters(updates) {
    if (!updates.length) return;

    console.log(`📊 Batch-обновление ${updates.length} счётчиков одним запросом...`);

    const data = updates.map(u => ({
        range: `${u.sheetName}!${u.cell}`,
        values: [[u.value]]
    }));

    try {
        await sheets.spreadsheets.values.batchUpdate({
            spreadsheetId: STUDENTS_SPREADSHEET_ID,
            requestBody: {
                data: data,
                valueInputOption: 'USER_ENTERED'
            }
        });

        console.log(`  ✅ Все ${updates.length} счётчиков обновлены`);
    } catch (error) {
        console.error('  ❌ Ошибка batch-обновления:', error.message);
        throw error;
    }
}

/**
 * Чтение ВСЕХ данных из листа "Список всех детей" (из таблицы учеников)
 */
async function readAllStudents() {
    console.log('📚 Читаем учеников из таблицы:', process.env.STUDENTS_SPREADSHEET_ID);

    const rows = await readStudentsRange('Список всех детей', 'A1:S');
    console.log('📄 Получено строк из таблицы:', rows.length);

    const data = {};
    const index = {};

    // Пропускаем заголовки (первые 2 строки)
    for (let i = 2; i < rows.length; i++) {
        const row = rows[i];

        const student = String(row[0] || '').trim();  // A - ФИ ребёнка
        const age = String(row[2] || '').trim();  // C - Возраст
        const pm = String(row[9] || '').trim();  // J - ПМ
        const teacher = String(row[11] || '').trim();  // L - Препод
        const group = String(row[12] || '').trim();  // M - Текущая группа
        const rawStart = row[13];                        // N - Дата старта
        const sheetRow = parseInt(row[14]) || 0;        // O - Index строки
        const vkChat = String(row[15] || '').trim();  // P - Ссылка ВК
        const done = Math.round((parseFloat(row[16]) || 0) * 10) / 10; // Q - Прошло уроков
        const rem = parseInt(row[17]) || 0;        // R - Осталось
        const direction = String(row[18] || '').trim();  // S - Направление

        // Пропускаем пустые строки и "ученика нет"
        if (!student || !teacher || !group) continue;
        if (group.includes('УЧЕНИКА НЕТ') || teacher.includes('УЧЕНИКА НЕТ')) continue;
        if (direction.includes('УЧЕНИКА НЕТ')) continue;

        // Определяем лист направления
        const isGroup = !direction.includes('ИНДИВ');
        const sheetName = isGroup
            ? direction.replace(/\s+ИНДИВ$/i, '').trim()
            : 'Индивидуальные';

        // Форматируем дату старта
        const startDate = rawStart instanceof Date
            ? rawStart.toLocaleDateString('ru-RU')
            : String(rawStart || '').trim();

        // 🔧 ВАЖНО: Создаём структуру данных
        if (!data[teacher]) {
            data[teacher] = {};
        }

        if (!data[teacher][group]) {
            data[teacher][group] = {
                students: [],
                lessonsDone: done,
                pm: pm,
                vkChat: vkChat,
                startDate: startDate,
                isGroup: isGroup,
            };
        }

        // Добавляем ученика
        data[teacher][group].students.push({
            name: student,
            lessonsDone: done,
            remaining: rem,
            age: age,
            sheetName: sheetName,
            sheetRow: sheetRow,
        });

        // Индекс для обновления счётчика
        if (sheetRow) {
            index[student + '|||' + group] = { sheetName, sheetRow };
        }
    }

    console.log('📊 Всего преподавателей:', Object.keys(data).length);
    console.log('📊 Всего групп:', Object.values(data).reduce((acc, t) => acc + Object.keys(t).length, 0));

    return { data, index };
}

/**
 * Чтение токенов из листа "Токены" (из таблицы ЖУРНАЛА)
 */
async function readTokens() {
    const rows = await readJournalRange('Токены', 'A:F');
    const tokens = {};

    for (let i = 1; i < rows.length; i++) {
        const token = String(rows[i][4] || '').trim();
        const teacher = String(rows[i][5] || '').trim();
        if (token && teacher) tokens[token] = teacher;
    }

    return tokens;
}

/**
 * Чтение заполненных уроков за неделю (для отчета)
 */
async function readFilledLessons(weekStartStr) {
    console.log('📖 Читаем заполненные уроки за неделю:', weekStartStr);

    const weekEnd = new Date(weekStartStr);
    weekEnd.setDate(weekEnd.getDate() + 6);
    const weekEndStr = weekEnd.toISOString().split('T')[0];

    const map = {};

    // Читаем оба журнала
    const sheetsToRead = ['Журнал индивы', 'Журнал группы'];

    for (const sheetName of sheetsToRead) {
        try {
            const rows = await readJournalRange(sheetName, 'A2:G');

            for (const row of rows) {
                if (!row[0] || !row[2]) continue;

                const rawDate = row[0];  // A - дата
                const group = String(row[2]).trim(); // C - группа
                const rawFixed = row[6]; // G - время фиксации

                // Форматируем дату
                let dateStr;
                if (rawDate instanceof Date) {
                    dateStr = rawDate.toISOString().split('T')[0];
                } else if (typeof rawDate === 'string') {
                    // Пробуем распарсить строку даты
                    const parts = rawDate.split(/[.\-/]/);
                    if (parts.length === 3) {
                        // ДД.ММ.ГГГГ -> ГГГГ-ММ-ДД
                        dateStr = `${parts[2]}-${parts[1].padStart(2, '0')}-${parts[0].padStart(2, '0')}`;
                    } else {
                        dateStr = rawDate;
                    }
                } else {
                    continue;
                }

                // Проверяем, что дата в пределах недели
                if (dateStr < weekStartStr || dateStr > weekEndStr) continue;

                const key = group + '|||' + weekStartStr;

                if (!map[key]) {
                    let fixedAt = '';
                    if (rawFixed instanceof Date) {
                        fixedAt = rawFixed.toLocaleString('ru-RU', {
                            day: '2-digit',
                            month: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit'
                        }).replace(/\.\d{4}/, '');
                    } else if (rawFixed) {
                        fixedAt = String(rawFixed);
                    }
                    map[key] = fixedAt;
                }
            }

            console.log(`  ${sheetName}: найдено заполнений за неделю: ${Object.keys(map).length}`);

        } catch (e) {
            console.log(`  ${sheetName}: лист не найден или пуст`);
        }
    }

    return map;
}

module.exports = {
    readStudentsRange,
    readJournalRange,
    appendToJournal,
    updateStudentCell,
    readAllStudents,
    readTokens,
    readFilledLessons,
    batchUpdateCounters,
};