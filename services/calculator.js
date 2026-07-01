const COURSE_LIMITS = {
    python: 56, minecraft: 48, roblox: 40, blender: 16,
    scratch: 32, webdesign: 36, webdev: 36,
};

const PAY_RATES = {
    halfLesson: 250,
    smallGroup: 500,
    smallPartial: 300,
    perStudent: 200,
};

function getCourseLimit(groupName) {
    const n = groupName.toLowerCase();
    if (/python/.test(n)) return COURSE_LIMITS.python;
    if (/minecraft/.test(n)) return COURSE_LIMITS.minecraft;
    if (/roblox/.test(n)) return COURSE_LIMITS.roblox;
    if (/blend|блендер/.test(n)) return COURSE_LIMITS.blender;
    if (/scratch/.test(n)) return COURSE_LIMITS.scratch;
    if (/веб.?диз|web.?диз/i.test(n)) return COURSE_LIMITS.webdesign;
    if (/веб.?разр|web.?разр/i.test(n)) return COURSE_LIMITS.webdev;
    return null;
}

function calculatePayment(total, present, isHalf = false) {
    if (present === 0) return 0;
    if (isHalf) return PAY_RATES.halfLesson * present;
    if (total <= 2) {
        return present === total ? PAY_RATES.smallGroup : PAY_RATES.smallPartial;
    }
    return PAY_RATES.perStudent * present;
}

function calculatePenalty(lessonDate, submitDate) {
    // lessonDate и submitDate в формате YYYY-MM-DD
    if (lessonDate === submitDate) return 0;
    return 40; // CONFIG.penaltyAmount
}

function formatMskDate(date = new Date()) {
    return date.toLocaleDateString('ru-RU', {
        timeZone: 'Europe/Moscow',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    }).split('.').reverse().join('-');
}

function formatMskDateTime(date = new Date()) {
    return date.toLocaleString('ru-RU', {
        timeZone: 'Europe/Moscow',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function getWeekStartMsk(now = new Date()) {
    const mskStr = now.toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' });
    const [d, m, y] = mskStr.split('.');
    const dt = new Date(y, m - 1, d);
    const dow = dt.getDay();
    const diff = (dow === 0) ? -6 : 1 - dow;
    dt.setDate(dt.getDate() + diff);
    return dt;
}

function mskMonthRange(now = new Date()) {
    const today = formatMskDate(now); // 'YYYY-MM-DD' в МСК
    const [y, m] = today.split('-').map(Number);
    const month = `${y}-${String(m).padStart(2, '0')}`;
    const month_start = `${month}-01`;
    const ny = m === 12 ? y + 1 : y;
    const nm = m === 12 ? 1 : m + 1;
    const month_end = `${ny}-${String(nm).padStart(2, '0')}-01`;
    return { month, month_start, month_end };
}

module.exports = {
    getCourseLimit,
    calculatePayment,
    calculatePenalty,
    formatMskDate,
    formatMskDateTime,
    getWeekStartMsk,
    mskMonthRange,
};