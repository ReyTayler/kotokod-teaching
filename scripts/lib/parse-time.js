const DAY_MAP = {
  'воскресенье': 0, 'вс': 0,
  'понедельник': 1, 'пн': 1,
  'вторник':     2, 'вт': 2,
  'среда':       3, 'ср': 3,
  'четверг':     4, 'чт': 4,
  'пятница':     5, 'пт': 5,
  'суббота':     6, 'сб': 6,
};

const DAY_PATTERN = '(воскресенье|понедельник|вторник|среда|четверг|пятница|суббота|вс|пн|вт|ср|чт|пт|сб)';

function parseTimeSlots(groupName) {
  if (!groupName) return [];
  const re = new RegExp(`${DAY_PATTERN}[^0-9]*?(\\d{1,2})[:.\\-](\\d{2})`, 'gi');
  const slots = [];
  for (const m of String(groupName).matchAll(re)) {
    const day = DAY_MAP[m[1].toLowerCase()];
    if (day === undefined) continue;
    const hh = String(m[2]).padStart(2, '0');
    const mm = m[3];
    slots.push({ day_of_week: day, start_time: `${hh}:${mm}:00` });
  }
  return slots;
}

function parseLessonDuration(groupName) {
  return /\b45\s*минут/i.test(String(groupName || '')) ? 45 : 90;
}

module.exports = { parseTimeSlots, parseLessonDuration };
