(function () {
    "use strict";

    // ════════════════════════════════════════════════════════════
    // КОНСТАНТЫ (зеркало Config.gs — держать синхронно)
    // ════════════════════════════════════════════════════════════

    const COURSE_LIMITS = {
      python: 56, minecraft: 48, roblox: 40, blender: 16, scratch: 32, webdesign: 36, webdev: 36,
    };

    const PAY = { halfLesson: 250, smallFull: 500, smallPartial: 300, perStudent: 200 };

    const DAY_NAMES_RU = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
    const SCHED_DAY_ORDER = [1, 2, 3, 4, 5, 6, 0];

    const DAY_COLORS = [
      { a: "#a78bfa", b: "rgba(167,139,250,.08)" },
      { a: "#3b82f6", b: "rgba(59,130,246,.08)" },
      { a: "#8b5cf6", b: "rgba(139,92,246,.08)" },
      { a: "#06b6d4", b: "rgba(6,182,212,.08)" },
      { a: "#10b981", b: "rgba(16,185,129,.08)" },
      { a: "#f59e0b", b: "rgba(245,158,11,.08)" },
      { a: "#ef4444", b: "rgba(239,68,68,.08)" },
    ];

    // ════════════════════════════════════════════════════════════
    // СОСТОЯНИЕ ПРИЛОЖЕНИЯ
    // ════════════════════════════════════════════════════════════

    let state = {
      teacher: "",
      teacherData: {},  // группы текущего преподавателя
      allData: {},  // все группы (для замены)
      students: [],  // текущий список учеников с флагом present
      tab: "mine",        // "mine" | "sub"
      group: "",            // выбранная группа — источник истины
      isSub: false,
      origTeacher: "",
      lessonType: "schedule",    // "schedule" | "reschedule"
      page: "schedule",    // "journal" | "schedule"
      schedView: "week",
      schedLessons: [],
      schedNoTime: [],
      schedAll: [],
      cachedAt: null,
      schedLoaded: false,
      activeDayPick: -1,
      reportLoaded: false,
      reportData: null,
      reportFilter: { status: 'all', teacher: '' },
    };

    // ════════════════════════════════════════════════════════════
    // УТИЛИТЫ
    // ════════════════════════════════════════════════════════════

    const $ = id => document.getElementById(id);

    function esc(str) {
      if (!str) return "";
      return String(str)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function fmt(n) { return Number.isInteger(n) ? String(n) : n.toFixed(1); }

    function rub(amount) { return amount.toLocaleString("ru") + " ₽"; }

    function getCourseLimit(name) {
      const n = name.toLowerCase();
      if (/python/.test(n)) return COURSE_LIMITS.python;
      if (/minecraft/.test(n)) return COURSE_LIMITS.minecraft;
      if (/roblox/.test(n)) return COURSE_LIMITS.roblox;
      if (/blend|блендер/.test(n)) return COURSE_LIMITS.blender;
      if (/scratch/.test(n)) return COURSE_LIMITS.scratch;
      if (/веб.?диз|web.?диз|web.?des|веб.?des/i.test(n)) return COURSE_LIMITS.webdesign;
      if (/веб.?разр|web.?разр|web.?dev|веб.?dev/i.test(n)) return COURSE_LIMITS.webdev;
      return null;
    }

    function calcPayment(total, present, isHalf = false) {
      if (present === 0) return 0;
      if (isHalf) return PAY.halfLesson * present;
      if (total <= 2) return present === total ? PAY.smallFull : PAY.smallPartial;
      return PAY.perStudent * present;
    }

    function formatDateDisplay(iso) {
      if (!iso) return "";
      const [y, m, d] = iso.split("-").map(Number);
      const dd = String(d).padStart(2, "0"), mm = String(m).padStart(2, "0");
      const day = DAY_NAMES_RU[new Date(y, m - 1, d).getDay()];
      return window.innerWidth <= 600 ? `${dd}.${mm}.${y}\n${day}` : `${dd}.${mm}.${y} — ${day}`;
    }

    function todayIso() {
      const t = new Date();
      return [t.getFullYear(), String(t.getMonth() + 1).padStart(2, "0"), String(t.getDate()).padStart(2, "0")].join("-");
    }

    function pluralLesson(n) {
      if (n % 10 === 1 && n % 100 !== 11) return "";
      if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return "а";
      return "ов";
    }
    function pluralIndiv(n) {
      if (n % 10 === 1 && n % 100 !== 11) return "";
      if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return "а";
      return "ов";
    }

    // ════════════════════════════════════════════════════════════
    // ИНИЦИАЛИЗАЦИЯ
    // ════════════════════════════════════════════════════════════

    window.onload = function () {
      setTodayDate();
      loadSchedule();
      bootstrap();
      setInterval(loadSchedule, 5 * 60 * 1000);
      setInterval(function () { if (state.reportLoaded) loadReport(); }, 5 * 60 * 1000);
      setInterval(function () {
        if (!state.teacher) return;
        if (!$("stepStudents").classList.contains("hidden")) return;
        _bgRefreshJournal();
      }, 5 * 60 * 1000);
    };

    // ── Привязка статических обработчиков ────────────────────────
    // Раньше эти действия висели inline-атрибутами on*= в index.html, что
    // несовместимо с CSP `script-src 'self'`. Теперь навешиваем через
    // addEventListener. Группы (фильтры статуса, переключатель вида, кнопка
    // закрытия попапа) — через делегирование по data-атрибутам/классам.
    function wireStaticHandlers() {
      const on = (id, ev, fn) => { const el = $(id); if (el) el.addEventListener(ev, fn); };

      // Верхняя навигация
      on("btnJournal", "click", () => switchPage("journal"));
      on("btnNavSchedule", "click", () => switchPage("schedule"));
      on("btnNavReport", "click", () => switchPage("report"));

      // Журнал
      on("refreshBtn", "click", () => refreshData());
      on("tabMine", "click", () => switchTab("mine"));
      on("tabSub", "click", () => switchTab("sub"));
      on("groupSelect", "change", () => onGroupChange());
      on("btnLessonSchedule", "click", () => setLessonType("schedule"));
      on("btnLessonReschedule", "click", () => setLessonType("reschedule"));
      on("dateInput", "change", () => onDateChange());
      on("recordUrl", "input", () => onRecordInput());
      on("submitBtn", "click", () => submitForm());
      on("emptyLogoutBtn", "click", () => logout());
      on("newLessonBtn", "click", () => resetForm());

      // Отчёт
      on("reportRefreshBtn", "click", () => loadReport(true));
      const statusRow = $("rfStatusRow");
      if (statusRow) statusRow.addEventListener("click", e => {
        const chip = e.target.closest(".rf-chip");
        if (chip && chip.dataset.status) setReportStatusFilter(chip.dataset.status);
      });
      on("rfTeacherSelect", "change", e => setReportTeacherFilter(e.target.value));

      // Расписание: переключатель вида (делегирование по data-view)
      const viewTabs = document.querySelector(".view-tabs-sched");
      if (viewTabs) viewTabs.addEventListener("click", e => {
        const tab = e.target.closest(".view-tab-sched");
        if (tab && tab.dataset.view) setSchedView(tab.dataset.view);
      });
      on("schedRefreshBtn", "click", () => loadSchedule(true));

      // Попап урока: клик по фону закрывает; ✕ создаётся динамически → делегирование
      const overlay = $("schedOverlay");
      if (overlay) overlay.addEventListener("click", e => {
        if (e.target === e.currentTarget) { hideSchedPopup(); return; }
        if (e.target.closest(".popup-close")) hideSchedPopup();
      });
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", wireStaticHandlers);
    } else {
      wireStaticHandlers();
    }

    // ════════════════════════════════════════════════════════════
    // НАВИГАЦИЯ СТРАНИЦ
    // ════════════════════════════════════════════════════════════

    function switchPage(page) {
      if (state.page === page) return;
      state.page = page;

      const isJ = page === "journal";
      const isS = page === "schedule";
      const isR = page === "report";

      $("btnJournal").classList.toggle("active", isJ);
      $("btnNavSchedule").classList.toggle("active", isS);
      $("btnNavReport").classList.toggle("active", isR);

      const titles = { journal: "Журнал посещаемости", schedule: "Расписание индивов", report: "Сводный отчёт" };
      $("pageTitle").textContent = titles[page] || "";

      // wide — для расписания и отчёта, узко — только для журнала
      document.querySelector(".app").classList.toggle("wide", !isJ);

      $("journalWrapper").classList.toggle("hidden", !isJ);
      $("schedulePage").classList.toggle("hidden", !isS);
      $("reportPage").classList.toggle("hidden", !isR);

      if (isS && !state.schedLoaded) loadSchedule();
      if (isR && !state.reportLoaded) loadReport();
    }

    // ════════════════════════════════════════════════════════════
    // BOOTSTRAP ИЗ СЕССИИ
    // ════════════════════════════════════════════════════════════

    // ── CSRF: backend требует X-CSRFToken на мутациях (CookieJWTAuthentication).
    //    GET /api/auth/csrf выставляет csrftoken-cookie (@ensure_csrf_cookie);
    //    читаем её и шлём заголовком на всех POST.
    let _csrfToken = null;
    function _getCookie(name) {
      const m = document.cookie.match('(?:^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
      return m ? decodeURIComponent(m[1]) : null;
    }
    async function ensureCsrf() {
      _csrfToken = _getCookie('csrftoken');
      if (!_csrfToken) {
        try { await fetch('/api/auth/csrf', { credentials: 'include' }); } catch (e) {}
        _csrfToken = _getCookie('csrftoken');
      }
      return _csrfToken;
    }
    function _csrfHeaders(base) {
      const h = Object.assign({}, base || {});
      const t = _csrfToken || _getCookie('csrftoken');
      if (t) h['X-CSRFToken'] = t;
      return h;
    }

    // ── Тихий refresh access-токена (паритет с admin SPA lib/api.ts).
    //    Access-токен живёт 15 минут. При 401 один раз обновляем его из
    //    7-дневной refresh-cookie (POST /api/auth/refresh) и повторяем запрос —
    //    учителя не выбрасывает на /login, пока жив refresh.
    //    CSRF для refresh не нужен (RefreshView с authentication_classes=[]).
    //    In-flight промис мемоизируется: пачка параллельных 401 ждёт один refresh.
    const _REFRESH_PATH = '/api/auth/refresh';
    let _refreshInflight = null;
    function _refreshAccessToken() {
      if (!_refreshInflight) {
        _refreshInflight = fetch(_REFRESH_PATH, { method: 'POST', credentials: 'include' })
          .then(function (res) { return res.ok; })
          .catch(function () { return false; })
          .finally(function () { _refreshInflight = null; });
      }
      return _refreshInflight;
    }
    // Дроп-ин замена fetch для защищённых /api-эндпоинтов: при 401 пробует
    // обновить токен и повторяет тот же запрос ровно один раз. options
    // переиспользуется на повтор (body — строка, не stream, повтор безопасен).
    async function apiFetch(path, options) {
      let res = await fetch(path, options);
      if (res.status === 401 && path !== _REFRESH_PATH) {
        const ok = await _refreshAccessToken();
        if (ok) res = await fetch(path, options);
      }
      return res;
    }

    async function bootstrap() {
      _show("skeletonScreen");
      try {
        const t0 = Date.now();
        await ensureCsrf();
        const r = await apiFetch('/api/getData', {
          method: 'POST',
          credentials: 'include',
          headers: _csrfHeaders({ 'Content-Type': 'application/json' }),
          body: '{}'
        });
        if (r.status === 401 || r.status === 403) { window.location = '/login'; return; }
        const res = await r.json();
        if (res.error) { window.location = '/login'; return; }

        state.teacher = res.teacher;
        state.teacherData = res.data || {};
        _hide("skeletonScreen");
        $("teacherChipName").textContent = state.teacher;

        if (!Object.keys(state.teacherData).length) {
          showEmptyState();
          return;
        }

        showCacheBadge(Date.now() - t0 < 1500);
        populateGroups();
        _show("mainForm");

      } catch (e) {
        window.location = '/login';
      }
    }

    async function logout() {
      try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'include', headers: _csrfHeaders() }); } catch (e) {}
      window.location = '/login';
    }

    // ════════════════════════════════════════════════════════════
    // ВКЛАДКИ ЖУРНАЛА
    // ════════════════════════════════════════════════════════════

    function switchTab(tab) {
      state.tab = tab;
      const isSub = tab === "sub";
      $("tabMine").classList.toggle("active", !isSub);
      $("tabSub").classList.toggle("active", isSub);
      _resetGroupStep();

      if (isSub) {
        if (!Object.keys(state.allData).length) _loadAllData();
        else populateGroupsFrom(state.allData, true);
      } else {
        populateGroupsFrom(state.teacherData, false);
      }
    }

    async function _loadAllData() {
      _setRefreshSpinning(true);
      try {
        const response = await apiFetch('/api/getAllData', {
          method: 'POST',
          credentials: 'include',
          headers: _csrfHeaders({ 'Content-Type': 'application/json' }),
          body: '{}'
        });

        _setRefreshSpinning(false);

        if (response.status === 401 || response.status === 403) { window.location = '/login'; return; }
        const r = await response.json();
        if (r.error) {
          alert("Ошибка: " + r.error);
          return;
        }

        state.allData = r.data;
        populateGroupsFrom(state.allData, true);

      } catch (e) {
        _setRefreshSpinning(false);
        alert("Ошибка: " + e.message);
      }
    }

    function populateGroupsFrom(data, flat) {
      const sel = $("groupSelect");
      sel.innerHTML = '<option value="">— выберите —</option>';

      if (flat) {
        const entries = [];
        Object.keys(data).sort().forEach(t => {
          if (t === state.teacher) return;
          Object.keys(data[t]).sort().forEach(g => entries.push({ teacher: t, group: g }));
        });
        entries.forEach(e => {
          const opt = document.createElement("option");
          opt.value = e.group;
          opt.dataset.teacher = e.teacher;
          opt.textContent = e.teacher + " — " + e.group;
          sel.appendChild(opt);
        });
      } else {
        Object.keys(data).sort().forEach(g => {
          const opt = document.createElement("option");
          opt.value = g; opt.textContent = g;
          sel.appendChild(opt);
        });
      }
    }

    function populateGroups() {
      if (!Object.keys(state.teacherData).length) { showEmptyState(); return; }
      populateGroupsFrom(state.teacherData, false);
    }

    // ════════════════════════════════════════════════════════════
    // ОБНОВЛЕНИЕ ДАННЫХ
    // ════════════════════════════════════════════════════════════

    async function refreshData() {
      _setRefreshSpinning(true);
      try {
        const response = await apiFetch('/api/refreshData', {
          method: 'POST',
          credentials: 'include',
          headers: _csrfHeaders({ 'Content-Type': 'application/json' }),
          body: '{}'
        });

        _setRefreshSpinning(false);

        if (response.status === 401 || response.status === 403) { window.location = '/login'; return; }
        const r = await response.json();
        if (r.error) {
          alert("Ошибка: " + r.error);
          return;
        }

        state.teacherData = r.data;
        state.allData = {};
        _resetGroupStep();

        if (state.tab === "sub") _loadAllData();
        else populateGroups();

        showCacheBadge(false);

      } catch (e) {
        _setRefreshSpinning(false);
        alert("Ошибка: " + e.message);
      }
    }

    async function _bgRefreshJournal() {
      try {
        const response = await apiFetch('/api/getData', {
          method: 'POST',
          credentials: 'include',
          headers: _csrfHeaders({ 'Content-Type': 'application/json' }),
          body: '{}'
        });
        if (response.status === 401 || response.status === 403) { window.location = '/login'; return; }
        const r = await response.json();

        if (!r.error && r.data) {
          state.teacherData = r.data;
          if (state.tab === "sub") state.allData = {};
        }
      } catch (_) {
        // Тихое обновление — игнорируем ошибки
      }
    }

    // ════════════════════════════════════════════════════════════
    // ВЫБОР ГРУППЫ
    // ════════════════════════════════════════════════════════════

    function onGroupChange() {
      const sel = $("groupSelect");
      const group = sel.value;
      const opt = sel.options[sel.selectedIndex];

      _resetGroupStep();
      if (!group) return;

      state.isSub = state.tab === "sub";
      state.origTeacher = state.isSub ? (opt.dataset.teacher || "") : "";
      state.group = group;

      const src = state.isSub ? state.allData : state.teacherData;
      const gd = state.isSub ? src[state.origTeacher][group] : src[group];

      state.students = gd.students.map(s => ({ ...s, present: false }));
      const pm = gd.pm || "";

      const isHalf = /45\s*минут/i.test(group);
      const step = isHalf ? 0.5 : 1;
      // Для групп: номер урока = max пройденных + 1 (групповой счётчик)
      const done = state.students.length
        ? Math.max(...state.students.map(s => s.lessonsDone ?? 0))
        : 0;
      const next = Math.round((done + step) * 10) / 10;
      const nextDisp = fmt(next);

      $("lessonNumber").textContent = "№" + nextDisp;
      $("lessonTitle").textContent = "Урок " + nextDisp + (isHalf ? " (45 минут)" : "");
      $("lessonSubtitle").textContent = "Пройдено уроков: " + fmt(done);
      _show("lessonInfo");

      // Проверка лимита курса
      const limit = getCourseLimit(group);
      if (limit !== null && Math.ceil(next) > limit) {
        const rem = limit - done;
        const msg = rem > 0 && rem < step
          ? `По данному курсу максимум ${limit} уроков. Пройдено: ${fmt(done)}. Недостаточно для ${isHalf ? "полурока" : "урока"} (нужно ${step}, доступно ${rem.toFixed(1)}).`
          : `По данному курсу максимум ${limit} уроков. Пройдено: ${fmt(done)}. Заполнение заблокировано.`;
        $("courseLimitTitle").textContent = "Лимит курса исчерпан";
        $("courseLimitText").textContent = msg;
        _show("courseLimitBlock");
        _showSelectedGroup(group);
        return;
      }

      _showSelectedGroup(group);

      // Уроки в долг
      const remaining = state.students[0]?.remaining ?? 0;
      if (remaining <= 0) {
        $("debtText").textContent = `Оплаченные уроки закончились (остаток: ${remaining}).` +
          (pm ? ` Сообщите менеджеру ${pm}.` : " Сообщите менеджеру.");
        _show("debtWarning");
      }

      // Замена
      if (state.isSub) {
        $("subTeacherName").textContent = state.origTeacher;
        _show("subTeacherInfo");
      }

      renderStudents();
      _show("stepStudents");
    }

    function _showSelectedGroup(group) {
      const el = $("selectedGroup");
      el.textContent = group;
      _show(el);
      $("badge1").classList.add("done");
    }

    // ════════════════════════════════════════════════════════════
    // УЧЕНИКИ
    // ════════════════════════════════════════════════════════════

    function renderStudents() {
      const list = $("studentsList");
      list.innerHTML = "";
      state.students.forEach((s, i) => {
        const remColor = s.remaining <= 0 ? "color:var(--err)" : "color:var(--text-3)";
        const remText = s.remaining <= 0 ? `В долг (${s.remaining})` : `Осталось: ${s.remaining}`;
        const badge = state.isSub ? '<span class="sub-badge">ЗАМЕНА</span>' : "";
        const row = document.createElement("div");
        row.className = "student-row absent";
        row.id = "student_" + i;
        row.onclick = () => toggleStudent(i);
        row.innerHTML = `
      <div>
        <div class="student-name">${esc(s.name)}${badge}</div>
        <div class="student-lessons" style="display:flex;gap:12px;">
          <span>Пройдено: ${fmt(s.lessonsDone)}</span>
          <span style="${remColor}">${remText}</span>
        </div>
      </div>
      <button class="toggle-btn" id="btn_${i}">✗ Не пришёл</button>`;
        list.appendChild(row);
      });
      updateSummary();
    }

    function toggleStudent(i) {
      state.students[i].present = !state.students[i].present;
      const row = $("student_" + i);
      const btn = $("btn_" + i);
      const ok = state.students[i].present;
      row.className = "student-row " + (ok ? "present" : "absent");
      btn.textContent = ok ? "✓ Пришёл" : "✗ Не пришёл";
      updateSummary();
    }

    function updateSummary() {
      const total = state.students.length;
      const present = state.students.filter(s => s.present).length;
      const isHalf = /45\s*минут/i.test(state.group);
      $("summaryPresent").textContent = present;
      $("summaryAbsent").textContent = total - present;
      $("summaryPay").textContent = rub(calcPayment(total, present, isHalf));
      updateSubmitBtn();
    }

    // ════════════════════════════════════════════════════════════
    // ДАТА
    // ════════════════════════════════════════════════════════════

    function setTodayDate() {
      const iso = todayIso();
      $("dateInput").value = iso;
      _updateDateDisplay(iso);
    }

    function onDateChange() {
      _updateDateDisplay($("dateInput").value);
      updateSummary();
    }

    function _updateDateDisplay(iso) {
      const span = $("dateDisplayText");
      if (iso) {
        span.style.color = "var(--text)";
        span.textContent = formatDateDisplay(iso);
      } else {
        span.style.color = "var(--text-3)";
        span.textContent = "Выберите дату...";
      }
    }

    // ════════════════════════════════════════════════════════════
    // ТИП УРОКА
    // ════════════════════════════════════════════════════════════

    function setLessonType(type) {
      state.lessonType = type;
      $("btnLessonSchedule").className = "lesson-type-btn" + (type === "schedule" ? " active-schedule" : "");
      $("btnLessonReschedule").className = "lesson-type-btn" + (type === "reschedule" ? " active-reschedule" : "");
    }

    // ════════════════════════════════════════════════════════════
    // ОТПРАВКА ФОРМЫ
    // ════════════════════════════════════════════════════════════

    function onRecordInput() {
      $("recordUrl").classList.remove("field-error");
      updateSubmitBtn();
    }

    function updateSubmitBtn() {
      $("submitBtn").disabled = !$("dateInput").value || !$("recordUrl").value.trim();
    }

    async function submitForm() {
      const date = $("dateInput").value;
      const recordUrl = $("recordUrl").value.trim();
      const group = state.group;

      if (!date) { _showError("Укажите дату урока"); return; }
      if (!recordUrl) {
        $("recordUrl").classList.add("field-error");
        $("recordUrl").focus();
        _showError("Укажите ссылку на запись урока");
        return;
      }

      const btn = $("submitBtn");
      btn.disabled = true;
      btn.textContent = "Сохраняем...";

      try {
        const response = await apiFetch('/api/submitLesson', {
          method: 'POST',
          credentials: 'include',
          headers: _csrfHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            group: group,
            date: date,
            recordUrl: recordUrl,
            lessonType: state.lessonType,
            isSubstitution: state.isSub,
            originalTeacher: state.origTeacher,
            students: state.students.map(s => ({
              name: s.name,
              present: s.present
            }))
          })
        });

        if (response.status === 401 || response.status === 403) { window.location = '/login'; return; }
        const r = await response.json();

        if (r.success) {
          state.reportLoaded = false;
          _showSuccess(group, date, r.payment);
        } else {
          _showError("Ошибка сохранения: " + r.error);
          btn.disabled = false;
          btn.textContent = "Сохранить урок";
        }

      } catch (e) {
        _showError("Ошибка соединения: " + e.message);
        btn.disabled = false;
        btn.textContent = "Сохранить урок";
      }
    }

    // ════════════════════════════════════════════════════════════
    // ЭКРАНЫ
    // ════════════════════════════════════════════════════════════

    function _showSuccess(group, date, payment) {
      _hide("mainForm");
      $("successGroup").textContent = group;
      $("successDate").textContent = new Date(date).toLocaleDateString("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "numeric" });
      $("successPayment").textContent = rub(payment);
      _show("successScreen");
    }

    function showEmptyState() {
      $("emptyTeacherName").textContent = state.teacher;
      _show("emptyScreen");
    }

    function retryFromEmpty() {
      logout();
    }

    function resetForm() {
      _hide("successScreen");
      _show("mainForm");
      _resetGroupStep();
      $("recordUrl").value = "";
      $("recordUrl").classList.remove("field-error");
      $("submitBtn").textContent = "Сохранить урок";
      _hide("errorMsg");
      setLessonType("schedule");
      setTodayDate();
    }

    // ════════════════════════════════════════════════════════════
    // РАСПИСАНИЕ
    // ════════════════════════════════════════════════════════════

    async function loadSchedule(force) {
      state.schedLoaded = true;
      const btn = $("schedRefreshBtn");
      const hasData = state.schedLessons.length > 0 || state.schedNoTime.length > 0;

      btn.disabled = true;
      if (hasData) {
        _setSchedSubtitle(true);
      } else {
        btn.classList.add("spinning");
        _hide("schedContent");
        _hide("schedError");
        _show("schedSkeleton");
      }

      try {
        const url = force ? '/api/schedule?force=true' : '/api/schedule';
        const response = await apiFetch(url, { credentials: 'include' });
        const res = await response.json();

        btn.disabled = false;
        btn.classList.remove("spinning");
        _hide("schedSkeleton");

        if (res.error) {
          _showSchedError(res.error);
          return;
        }

        state.schedLessons = res.lessons || [];
        state.schedNoTime = res.noTime || [];
        state.cachedAt = res.cachedAt;

        state.schedAll = [];
        state.schedLessons.forEach((l, i) => { l.idx = i; state.schedAll.push(l); });
        state.schedNoTime.forEach((l, i) => { l.idx = state.schedLessons.length + i; state.schedAll.push(l); });

        _setSchedSubtitle(false);
        _updateSchedStats();
        renderSched();

      } catch (e) {
        btn.disabled = false;
        btn.classList.remove("spinning");
        _hide("schedSkeleton");
        _setSchedSubtitle(false);
        _showSchedError("Ошибка соединения: " + e.message);
      }
    }

    function _updateSchedStats() {
      const all = state.schedAll;
      const unique = new Set(all.map(l => l.group)).size;
      const teachers = new Set(all.map(l => l.teacher)).size;
      const noTime = new Set(state.schedNoTime.map(l => l.group)).size;
      const students = new Set();
      all.forEach(l => (l.students || []).forEach(s => students.add(s.name + "|||" + l.group)));

      $("sbTotal").textContent = unique;
      $("sbTeachers").textContent = teachers;
      $("sbNoTime").textContent = noTime;
      $("sbStudents").textContent = students.size;
      _show("schedStatBar");
    }

    function setSchedView(v) {
      state.schedView = v;
      document.querySelectorAll(".view-tab-sched").forEach((b, i) => {
        b.classList.toggle("active", ["week", "teacher", "day"][i] === v);
      });
      if (state.schedLessons.length || state.schedNoTime.length) renderSched();
    }

    function renderSched() {
      const el = $("schedContent");
      el.innerHTML = "";
      if (state.schedView === "week") _renderWeek(el);
      else if (state.schedView === "teacher") _renderByTeacher(el);
      else if (state.schedView === "day") _renderByDay(el);
      _show(el);
    }

    function _groupByDay() {
      const m = {};
      SCHED_DAY_ORDER.forEach(d => { m[d] = []; });
      state.schedLessons.forEach(l => { if (m[l.day] !== undefined) m[l.day].push(l); });
      return m;
    }

    function _makeLessonCard(lesson, showDay) {
      const dc = lesson.day != null ? DAY_COLORS[lesson.day] : null;
      const ac = dc ? dc.a : "var(--accent)";

      const card = document.createElement("div");
      card.className = "lesson-card";
      if (lesson.idx !== undefined) card.onclick = () => showSchedPopup(lesson.idx);

      const time = document.createElement("div");
      time.className = lesson.time ? "lc-time" : "lc-time no-time";
      time.textContent = lesson.time || "—";
      if (lesson.time) time.style.color = ac;
      card.appendChild(time);

      const info = document.createElement("div");
      info.className = "lc-info";

      const gname = document.createElement("div");
      gname.className = "lc-group";
      gname.textContent = lesson.groupDisplay || lesson.group;
      gname.title = lesson.group;
      info.appendChild(gname);

      const parts = [];
      if (showDay && lesson.dayName) parts.push(lesson.dayName);
      parts.push(lesson.teacher);
      if (lesson.pm) parts.push(lesson.pm);

      const meta = document.createElement("div");
      meta.className = "lc-meta";
      meta.textContent = parts.join(" • ");
      info.appendChild(meta);

      card.appendChild(info);
      return card;
    }

    function _appendNoTime(parent, items, showDay) {
      if (!items || !items.length) return;
      const sec = document.createElement("div");
      sec.className = "notime-sec";
      const uniq = new Set(items.map(l => l.group)).size;
      sec.innerHTML = `<div class="notime-hdr"><span class="notime-title">Без согласованного времени</span><span class="notime-badge">${uniq} занятие</span></div>`;
      const list = document.createElement("div");
      list.className = "list-cards";
      items.forEach(l => list.appendChild(_makeLessonCard(l, showDay)));
      sec.appendChild(list);
      parent.appendChild(sec);
    }

    // Вид: Неделя
    function _renderWeek(parent) {
      const today = new Date().getDay();
      const byDay = _groupByDay();

      SCHED_DAY_ORDER.forEach(dow => {
        const items = byDay[dow];
        const dc = DAY_COLORS[dow];

        const block = document.createElement("div");
        block.className = "week-day-block";
        block.style.cssText = `background:${dc.b};border:1px solid ${dc.a}30`;

        const hdr = document.createElement("div");
        hdr.className = "week-day-hdr";
        hdr.style.cssText = `border-left:3px solid ${dc.a};background:${dc.b};color:${dc.a}`;

        const name = document.createElement("span");
        name.className = "week-day-name";
        name.textContent = DAY_NAMES_RU[dow] + (dow === today ? " · Сегодня" : "");
        hdr.appendChild(name);

        if (items.length) {
          const cnt = document.createElement("span");
          cnt.className = "week-day-cnt";
          cnt.textContent = items.length + " урок" + pluralLesson(items.length);
          hdr.appendChild(cnt);
        }
        block.appendChild(hdr);

        if (!items.length) {
          const empty = document.createElement("div");
          empty.className = "week-day-empty";
          empty.textContent = "Уроков нет";
          block.appendChild(empty);
        } else {
          const list = document.createElement("div");
          list.className = "list-cards";
          list.style.cssText = "padding:8px 10px 10px;gap:6px;";
          items.forEach(l => list.appendChild(_makeLessonCard(l, false)));
          block.appendChild(list);
        }
        parent.appendChild(block);
      });

      _appendNoTime(parent, state.schedNoTime, false);
    }

    // Вид: По преподавателям
    function _renderByTeacher(parent) {
      const byT = {};
      state.schedLessons.forEach(l => {
        if (!byT[l.teacher]) byT[l.teacher] = [];
        byT[l.teacher].push(l);
      });

      Object.keys(byT).sort().forEach(teacher => {
        const items = byT[teacher];
        const row = document.createElement("div");
        row.className = "teacher-row";

        const hdr = document.createElement("div");
        hdr.className = "teacher-row-hdr";
        hdr.onclick = () => row.classList.toggle("open");

        const uniq = new Set(items.map(l => l.group)).size;
        hdr.innerHTML = `
      <div class="teacher-row-left">
        <span class="teacher-row-name">${esc(teacher)}</span>
        <span class="teacher-row-cnt">${uniq} группы/индива</span>
      </div>
      <span class="teacher-row-arrow">▾</span>`;

        const body = document.createElement("div");
        body.className = "teacher-row-body";
        const list = document.createElement("div");
        list.className = "list-cards";
        items.forEach(l => list.appendChild(_makeLessonCard(l, true)));
        body.appendChild(list);

        row.appendChild(hdr);
        row.appendChild(body);
        parent.appendChild(row);
      });

      if (state.schedNoTime.length) {
        const flat = [];
        const byTNT = {};
        state.schedNoTime.forEach(l => { if (!byTNT[l.teacher]) byTNT[l.teacher] = []; byTNT[l.teacher].push(l); });
        Object.keys(byTNT).sort().forEach(t => flat.push(...byTNT[t]));
        _appendNoTime(parent, flat, false);
      }
    }

    // Вид: По дням
    function _renderByDay(parent) {
      const today = new Date().getDay();
      const byDay = _groupByDay();
      state.activeDayPick = today;

      const picker = document.createElement("div");
      picker.className = "day-picker";
      picker.id = "dayPicker";

      SCHED_DAY_ORDER.forEach(dow => {
        const dc = DAY_COLORS[dow];
        const cnt = byDay[dow].length;
        const btn = document.createElement("button");
        btn.className = "day-pick-btn" + (dow === today ? " today-day" : "");
        btn.id = "dayPickBtn_" + dow;
        btn.style.cssText = `border-color:${dc.a}60;color:${dow === today ? "#fff" : dc.a};background:${dow === today ? dc.a : dc.b}`;
        btn.innerHTML = `<div>${DAY_NAMES_RU[dow]}</div><div class="day-pick-cnt">${cnt ? cnt + " ур." : "—"}</div>`;
        btn.onclick = () => _selectDay(dow);
        picker.appendChild(btn);
      });

      parent.appendChild(picker);

      const dayContent = document.createElement("div");
      dayContent.id = "dayContent";
      parent.appendChild(dayContent);

      _appendNoTime(parent, state.schedNoTime, false);
      _renderDayContent(byDay, today);
    }

    function _selectDay(dow) {
      state.activeDayPick = dow;
      const byDay = _groupByDay();
      SCHED_DAY_ORDER.forEach(d => {
        const btn = $("dayPickBtn_" + d);
        if (!btn) return;
        const dc = DAY_COLORS[d];
        const on = d === dow;
        btn.style.color = on ? "#fff" : dc.a;
        btn.style.background = on ? dc.a : dc.b;
      });
      _renderDayContent(byDay, dow);
    }

    function _renderDayContent(byDay, dow) {
      const cont = $("dayContent");
      if (!cont) return;
      cont.innerHTML = "";
      const items = byDay[dow] || [];
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "week-day-empty";
        empty.style.cssText = "padding:20px 0;text-align:center;";
        empty.textContent = "В этот день уроков нет";
        cont.appendChild(empty);
      } else {
        const list = document.createElement("div");
        list.className = "list-cards";
        items.forEach(l => list.appendChild(_makeLessonCard(l, false)));
        cont.appendChild(list);
      }
    }

    // ════════════════════════════════════════════════════════════
    // ПОПАП ДЕТАЛЕЙ УРОКА
    // ════════════════════════════════════════════════════════════

    function showSchedPopup(idx) {
      const lesson = state.schedAll[idx];
      if (!lesson) return;
      const dc = lesson.day != null ? DAY_COLORS[lesson.day] : { a: "var(--accent)" };
      const sts = lesson.students || [];

      let timeDisp;
      if (lesson.allTimes && lesson.allTimes.length > 1) {
        timeDisp = lesson.allTimes.join(" · ");
      } else {
        timeDisp = lesson.dayName
          ? lesson.dayName + (lesson.time ? ", " + lesson.time + " МСК" : "")
          : "Время не согласовано";
      }

      // ── Шапка ──
      let html = `
    <div class="popup-head">
      <div>
        <div class="popup-title">${esc(lesson.group)}</div>
        <div style="font-size:12px;color:${dc.a};margin-top:2px;">${esc(timeDisp)}</div>
      </div>
      <button class="popup-close">✕</button>
    </div>`;

      // ── Участники (имя + возраст + прогресс каждого) ──
      html += `<div class="popup-sec"><div class="popup-sec-label">Участники</div>`;
      if (sts.length) {
        sts.forEach(st => {
          const ageBadge = st.age
            ? `<span class="p-badge p-badge-age">🎂 ${esc(st.age)} лет</span>`
            : "";
          const hasProg = st.lessonsDone !== undefined && st.remaining !== undefined;
          const remClass = (st.remaining <= 0) ? "p-badge-rem-debt" : "p-badge-rem-ok";
          const remIcon = (st.remaining <= 0) ? "⚠" : "✓";
          const doneBadge = hasProg
            ? `<span class="p-badge p-badge-done">📖 ${fmt(st.lessonsDone)} пройдено</span>`
            : "";
          const remBadge = hasProg
            ? `<span class="p-badge ${remClass}">${remIcon} ${st.remaining} оплачено</span>`
            : "";
          html += `<div class="participant-row">
        <div class="participant-name">👤 ${esc(st.name)}</div>
        <div class="participant-badges">${ageBadge}${doneBadge}${remBadge}</div>
      </div>`;
        });
      } else {
        html += `<div class="popup-row"><span class="popup-ico">👤</span><span class="popup-val" style="color:var(--text-2)">Нет данных</span></div>`;
      }
      html += `</div>`;

      // ── Преподаватель и менеджер ──
      html += `
    <div class="popup-sec">
      <div class="popup-sec-label">Преподаватель и менеджер</div>
      <div class="popup-row"><span class="popup-ico">🎓</span><span class="popup-val">${esc(lesson.teacher)}</span></div>
      ${lesson.pm ? `<div class="popup-row"><span class="popup-ico">🗂</span><span class="popup-val">${esc(lesson.pm)}</span></div>` : ""}
    </div>`;

      // ── Доп. информация: ВКонтакте и дата старта ──
      const hasVk = !!lesson.vkChat;
      const hasStart = !!lesson.startDate;
      if (hasVk || hasStart) {
        html += `<div class="popup-sec"><div class="popup-sec-label">Дополнительно</div>`;
        if (hasVk) {
          html += `<div class="popup-row">
        <span class="popup-ico">💬</span>
        <span class="popup-val">
          <a href="${esc(lesson.vkChat)}" target="_blank"
             style="color:var(--accent);text-decoration:none;word-break:break-all;">
            Чат ВКонтакте
          </a>
        </span>
      </div>`;
        }
        if (hasStart) {
          html += `<div class="popup-row"><span class="popup-ico">📅</span><span class="popup-val">Старт: ${esc(lesson.startDate)}</span></div>`;
        }
        html += `</div>`;
      }

      $("schedPopup").innerHTML = html;
      $("schedOverlay").classList.add("show");
      document.body.style.overflow = "hidden";
    }

    function hideSchedPopup() {
      $("schedOverlay").classList.remove("show");
      document.body.style.overflow = "";
    }

    document.addEventListener("keydown", e => { if (e.key === "Escape") hideSchedPopup(); });

    // ════════════════════════════════════════════════════════════
    // ВСПОМОГАТЕЛЬНЫЕ UI-ФУНКЦИИ
    // ════════════════════════════════════════════════════════════

    function _show(el) { (typeof el === "string" ? $(el) : el)?.classList.remove("hidden"); }
    function _hide(el) { (typeof el === "string" ? $(el) : el)?.classList.add("hidden"); }

    function _showEl(id, text) { const el = $(id); el.textContent = text; _show(el); }

    function _showError(msg) {
      _hide("skeletonScreen"); _show("mainForm");
      _showEl("errorMsg", msg);
    }

    function _showJournalError(msg) {
      _hide("skeletonScreen"); _show("mainForm");
      _showEl("errorMsg", msg);
    }

    function _setRefreshSpinning(on) {
      const btn = $("refreshBtn");
      btn.disabled = on;
      btn.classList.toggle("spinning", on);
    }

    function showCacheBadge(isHit) {
      const badge = $("cacheBadge"), text = $("cacheBadgeText");
      badge.className = "cache-badge " + (isHit ? "hit" : "miss");
      text.textContent = isHit ? "данные из кэша" : "данные обновлены";
      _show(badge);
      setTimeout(() => _hide(badge), 4000);
    }

    function _setSchedSubtitle(loading) {
      const sub = $("schedSubtitle");
      if (!sub) return;
      sub.innerHTML = loading
        ? '<span class="live-spin">⟳</span><span>обновляется...</span>'
        : `<span class="live-dot"></span><span>Live · обновлено в ${state.cachedAt || "—"} МСК</span>`;
      _show(sub);
    }

    function _showSchedError(msg) {
      const el = $("schedError");
      el.textContent = "Ошибка: " + msg;
      _show(el);
    }

    function _resetGroupStep() {
      const ids = ["stepStudents", "selectedGroup", "lessonInfo", "debtWarning",
        "courseLimitBlock", "subTeacherInfo"];
      ids.forEach(_hide);
      $("badge1").classList.remove("done");
      $("badge2").classList.remove("done");
      $("groupSelect").value = "";
      state.students = [];
      state.isSub = false;
      state.origTeacher = "";
      state.group = "";
      state.lessonType = "schedule";
      setLessonType("schedule");
    }

    // ════════════════════════════════════════════════════════════
    // СВОДНЫЙ ОТЧЁТ
    // ════════════════════════════════════════════════════════════

    const REPORT_DAY_COLORS = DAY_COLORS; // используем те же цвета что и в расписании

    async function loadReport(force) {
      state.reportLoaded = true;
      const btn = $("reportRefreshBtn");
      btn.disabled = true;
      btn.classList.add("spinning");

      if (!force && state.reportData) {
        btn.disabled = false;
        btn.classList.remove("spinning");
        _renderReport(state.reportData);
        return;
      }

      _hide("reportContent");
      _hide("reportError");
      _show("reportSkeleton");

      try {
        const url = force ? '/api/report?force=true' : '/api/report';
        const response = await apiFetch(url, { credentials: 'include' });
        const res = await response.json();

        btn.disabled = false;
        btn.classList.remove("spinning");
        _hide("reportSkeleton");

        if (res.error) {
          _showReportError(res.error);
          return;
        }

        state.reportData = res;
        _renderReport(res);

      } catch (e) {
        btn.disabled = false;
        btn.classList.remove("spinning");
        _hide("reportSkeleton");
        _showReportError("Ошибка соединения: " + e.message);
      }
    }

    function _renderReport(res) {
      const el = $("reportContent");
      el.innerHTML = "";

      const lessons = res.lessons || [];
      const noTime = res.noTime || [];
      const now = new Date();

      // ── Пересчёт статусов pending/overdue на клиенте ──
      lessons.forEach(l => {
        if (l.status === "done") return;
        if (l.day === null || l.day === undefined) return;
        const lessonDT = _reportLessonDT(res.weekStart, l.day, l.time);
        if (!lessonDT) return;
        l.status = now < lessonDT ? "pending" : "overdue";
        l.label = now < lessonDT ? "Пока урока не было" : "Надо заполнить";
      });

      // ── Статистика по всем данным (до фильтрации) ──
      const done = lessons.filter(l => l.status === "done").length;
      const overdue = lessons.filter(l => l.status === "overdue").length;
      const pending = lessons.filter(l => l.status === "pending").length;
      $("rsbDone").textContent = done;
      $("rsbOverdue").textContent = overdue;
      $("rsbPending").textContent = pending;
      _show("reportStatBar");

      // ── Подпись недели ──
      if (res.weekStart) {
        const [y, m, d] = res.weekStart.split('-').map(Number);
        const wStart = new Date(y, m - 1, d);      // ПОНЕДЕЛЬНИК
        const wEnd = new Date(y, m - 1, d + 6);    // ВОСКРЕСЕНЬЕ (+6 дней)

        const fmtD = dt => String(dt.getDate()).padStart(2, '0') + "." + String(dt.getMonth() + 1).padStart(2, '0');
        $("reportWeekLabel").textContent = "Неделя " + fmtD(wStart) + "–" + fmtD(wEnd) + "." + wEnd.getFullYear();
      }
      _show("reportLiveDot");

      // ── Наполняем select преподавателей (один раз при первом рендере) ──
      _populateTeacherFilter(lessons, noTime);
      _show("reportFilters");

      // ── Применяем фильтры ──
      _applyReportFilters(lessons, noTime, res.weekStart);
    }

    /** Строит список уникальных преподавателей и заполняет <select> */
    function _populateTeacherFilter(lessons, noTime) {
      const sel = $("rfTeacherSelect");
      const currentVal = sel.value;

      const teachers = new Set();
      [...lessons, ...noTime].forEach(l => { if (l.teacher) teachers.add(l.teacher); });

      // Перестраиваем только если набор изменился
      const sorted = [...teachers].sort();
      const existing = [...sel.options].slice(1).map(o => o.value);
      if (JSON.stringify(sorted) === JSON.stringify(existing)) return;

      // Сохраняем и восстанавливаем выбор
      sel.innerHTML = '<option value="">Все преподаватели</option>';
      sorted.forEach(t => {
        const opt = document.createElement("option");
        opt.value = t; opt.textContent = t;
        sel.appendChild(opt);
      });
      sel.value = sorted.includes(currentVal) ? currentVal : "";
      state.reportFilter.teacher = sel.value;
    }

    /** Основная функция фильтрации и рендера с учётом активных фильтров */
    function _applyReportFilters(lessons, noTime, weekStart) {
      const el = $("reportContent");
      el.innerHTML = "";
      const today = new Date().getDay();
      const sf = state.reportFilter.status;
      const tf = state.reportFilter.teacher;

      // Фильтруем
      const showNoTime = sf === "all" || sf === "notime";
      const filteredLessons = lessons.filter(l => {
        if (tf && l.teacher !== tf) return false;
        if (sf !== "all" && l.status !== sf) return false;
        return true;
      });
      const filteredNoTime = showNoTime
        ? noTime.filter(l => !tf || l.teacher === tf)
        : [];

      // Пустой результат
      if (!filteredLessons.length && !filteredNoTime.length) {
        el.innerHTML = '<div class="report-empty">Нет индивов, соответствующих фильтрам</div>';
        _show(el);
        return;
      }

      // Группируем по дням
      const byDay = {};
      SCHED_DAY_ORDER.forEach(d => { byDay[d] = []; });
      filteredLessons.forEach(l => { if (byDay[l.day] !== undefined) byDay[l.day].push(l); });

      SCHED_DAY_ORDER.forEach(dow => {
        const items = byDay[dow];
        if (!items.length) return;

        const dc = REPORT_DAY_COLORS[dow];
        const block = document.createElement("div");
        block.className = "report-day-block";
        block.style.cssText = "background:" + dc.b + ";border:1px solid " + dc.a + "30";

        const hdr = document.createElement("div");
        hdr.className = "report-day-hdr";
        hdr.style.cssText = "border-left:3px solid " + dc.a + ";background:" + dc.b + ";color:" + dc.a;
        hdr.innerHTML = '<span>' + DAY_NAMES_RU[dow] + (dow === today ? " · Сегодня" : "") + '</span>'
          + '<span class="report-day-cnt">' + items.length + ' урок' + pluralLesson(items.length) + '</span>';
        block.appendChild(hdr);

        items.forEach(l => block.appendChild(_makeReportRow(l, dc)));
        el.appendChild(block);
      });

      // Блок «Без времени»
      if (filteredNoTime.length) {
        const sec = document.createElement("div");
        sec.className = "report-notime-sec";
        sec.innerHTML = '<div class="report-notime-hdr">'
          + '<span class="report-notime-title">Без согласованного времени</span>'
          + '<span class="report-notime-badge">' + filteredNoTime.length + ' индив' + pluralIndiv(filteredNoTime.length) + '</span>'
          + '</div>';
        filteredNoTime.forEach(l => {
          const row = document.createElement("div");
          row.className = "report-row";
          row.style.background = "rgba(0,0,0,.10)";
          row.innerHTML = '<div class="report-timeslot" style="color:var(--text-3)"><div class="rts-day">—</div><div class="rts-time" style="font-size:13px">Нет</div></div>'
            + '<div class="report-info"><div class="report-group">' + esc(l.group) + '</div>'
            + '<div class="report-meta"><span class="report-teacher">' + esc(l.teacher) + '</span>'
            + (l.pm ? '<span class="report-pm">' + esc(l.pm) + '</span>' : '') + '</div></div>'
            + '<div class="report-status rs-notime">Время не указано</div>';
          sec.appendChild(row);
        });
        el.appendChild(sec);
      }

      _show(el);
    }

    /** Переключение фильтра по статусу */
    function setReportStatusFilter(status) {
      state.reportFilter.status = status;

      // Обновляем активный чип
      $("rfStatusRow").querySelectorAll(".rf-chip").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.status === status);
      });

      // Перерисовываем без запроса на сервер
      if (state.reportData) {
        _applyReportFilters(
          state.reportData.lessons || [],
          state.reportData.noTime || [],
          state.reportData.weekStart
        );
      }
    }

    /** Переключение фильтра по преподавателю */
    function setReportTeacherFilter(teacher) {
      state.reportFilter.teacher = teacher;
      const sel = $("rfTeacherSelect");
      sel.classList.toggle("active", !!teacher);

      if (state.reportData) {
        _applyReportFilters(
          state.reportData.lessons || [],
          state.reportData.noTime || [],
          state.reportData.weekStart
        );
      }
    }

    function _makeReportRow(l, dc) {
      const row = document.createElement("div");
      row.className = "report-row";

      // Время слева
      const timeEl = document.createElement("div");
      timeEl.className = "report-timeslot";
      timeEl.style.color = dc.a;
      timeEl.innerHTML = '<div class="rts-day">' + esc(l.dayShort || "") + '</div>'
        + '<div class="rts-time">' + esc(l.time || "—") + '</div>';

      // Название + препод
      const info = document.createElement("div");
      info.className = "report-info";
      info.innerHTML = '<div class="report-group">' + esc(l.groupDisplay || l.group) + '</div>'
        + '<div class="report-meta">'
        + '<span class="report-teacher">' + esc(l.teacher) + '</span>'
        + (l.pm ? '<span class="report-pm">' + esc(l.pm) + '</span>' : '')
        + '</div>';

      // Статус
      const sc = { pending: "rs-pending", overdue: "rs-overdue", done: "rs-done", notime: "rs-notime" };
      const ico = { pending: "○", overdue: "⚠", done: "✓", notime: "—" };
      const st = document.createElement("div");
      st.className = "report-status " + (sc[l.status] || "rs-pending");
      st.textContent = (ico[l.status] || "") + " " + (l.label || "");

      row.appendChild(timeEl);
      row.appendChild(info);
      row.appendChild(st);
      return row;
    }

    /** Вычисляет Date урока из weekStart (yyyy-MM-dd), dayNum и time (чч:мм) */
    function _reportLessonDT(weekStartStr, dayNum, timeStr) {
      if (!weekStartStr || dayNum === null || !timeStr) return null;
      const [y, m, d] = weekStartStr.split("-").map(Number);
      const offset = dayNum === 0 ? 6 : dayNum - 1; // пн=0 … вс=6
      const lessonD = new Date(y, m - 1, d + offset);
      const [hh, mm] = timeStr.split(":").map(Number);
      lessonD.setHours(hh, mm, 0, 0);
      return lessonD;
    }

    function _showReportError(msg) {
      const el = $("reportError");
      el.textContent = "Ошибка: " + msg;
      _show(el);
    }
})();

