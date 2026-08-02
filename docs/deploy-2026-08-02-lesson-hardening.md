# Выкат: закрытие дублей записи урока (Фазы 1–3)

**Дата подготовки:** 2026-08-02
**Что выкатываем:** 19 коммитов — защита от дублей записи урока, обратная связь при
отправке, производительность и настройки сервера.
**Сервер:** `kotokod-vps` (217.12.37.200), домен `develop-kotokod.ru`.

---

## Состояние на момент подготовки

| Что | Состояние |
|---|---|
| Ревизия на сервере | `f75dd3f` — новых коммитов нет |
| Ревизия локально | 19 коммитов поверх `f75dd3f`, **не запушены** |
| `sites-available/journal-kotokod` | **уже дописаны** TLS-сессии и таймауты прокси, `nginx -t` пройден, **nginx НЕ перезагружен** |
| `snippets/journal-static.conf` | не тронут, кеш статики не применён |
| Бэкап конфигов | `/root/nginx-backup-20260802/` |
| Сайт | работает на старом конфиге, пользователи не затронуты |

**Железо (замерено 2026-08-02):** 4 ядра, 5921 МБ RAM, свободно 4342 МБ, swap нет.
Воркер gunicorn весит ~200 МБ, девять уложатся в ~1.8 ГБ. PostgreSQL:
`max_connections=100`, занято 8.

---

## ⚠️ Ловушка, о которой надо знать до начала

**Боевой `journal-kotokod.conf` отличается от репозиторного только доменом и путями
к сертификатам.** Копировать файл из репозитория напрямую НЕЛЬЗЯ — затрёт
`develop-kotokod.ru` плейсхолдером `example.kotokod.ru` и сломает TLS. Если когда-то
понадобится перелить его целиком:

```bash
sed 's/example\.kotokod\.ru/develop-kotokod.ru/g' \
  /opt/kotokod/journal-backend/deploy/nginx/journal-kotokod.conf \
  > /etc/nginx/sites-available/journal-kotokod
```

Сниппет `journal-static.conf` домена не содержит — его копировать можно как есть.

---

## Шаг 0. Бэкап базы

```bash
ssh kotokod-vps 'bash /opt/kotokod/journal-backend/deploy/scripts/backup-db.sh'
ssh kotokod-vps 'ls -lt /opt/kotokod/backups | head -3'
```

Ожидается свежий дамп с сегодняшней датой. **Без этого дальше не идти** — в выкате
есть миграция схемы.

---

## Шаг 1. Отправить изменения в GitHub (локально)

```bash
cd C:/Users/ilyap/TestKOTOKOD
git log --oneline origin/main..HEAD | wc -l    # ожидается 19
git push origin main
```

---

## Шаг 2. Забрать на сервер

Репозиторий принадлежит пользователю `kotokod` — git-команды выполнять от него,
иначе git ругается на «dubious ownership».

```bash
ssh kotokod-vps 'sudo -u kotokod git -C /opt/kotokod/journal-backend status --short'
```
Ожидается пустой вывод. Если что-то есть — разобраться до `pull`, иначе локальные
правки на сервере конфликтнут.

```bash
ssh kotokod-vps 'sudo -u kotokod git -C /opt/kotokod/journal-backend pull --ff-only origin main'
ssh kotokod-vps 'sudo -u kotokod git -C /opt/kotokod/journal-backend log --oneline -1'
```
Ожидается верхний коммит про кеш статики и воркеры.

**На этом шаге приложение ещё работает на старом коде** (gunicorn не перезапущен), но
nginx уже отдаёт НОВЫЕ бандлы фронта. Кратковременное расхождение допустимо: новый
фронт со старым бэкендом теряет только оформление ошибки повторной отправки
доп.урока. Не затягивайте паузу до следующего шага.

---

## Шаг 3. Миграция базы

Миграция `lessons/0009_lesson_submission_key`: добавляет колонку `submission_key`,
частичный уникальный индекс и пересоздаёт триггеры журнала изменений (pghistory).

```bash
ssh kotokod-vps 'cd /opt/kotokod/journal-backend/journal_django && \
  sudo -u kotokod DJANGO_SETTINGS_MODULE=config.settings.production \
  .venv/bin/python manage.py migrate lessons'
```

Ожидается `Applying lessons.0009_lesson_submission_key... OK`.

**Конфликта уникальности быть не может:** колонка новая, у всех существующих строк
она `NULL`, а индекс частичный (`WHERE submission_key IS NOT NULL`) и такие строки не
покрывает.

Проверка, что индекс создан:
```bash
ssh kotokod-vps 'sudo -u postgres psql -d journal -tAc \
  "SELECT indexname FROM pg_indexes WHERE tablename='"'"'lessons'"'"' ORDER BY 1"'
```
Ожидается в списке `lessons_submission_key_unique` **и** сохранившийся
`lessons_natural_key`.

**Откат шага:** миграция обратима (`migrate lessons 0008`), но откатывать её нужно
только вместе с откатом кода — новый код без колонки не запустится.

---

## Шаг 4. Перезапуск приложения

Здесь вступают в силу: девять воркеров вместо трёх и переиспользование соединений с
БД (`CONN_MAX_AGE=60`).

```bash
ssh kotokod-vps 'systemctl restart journal-django && sleep 5 && systemctl is-active journal-django'
```
Ожидается `active`.

```bash
ssh kotokod-vps 'pgrep -c -f gunicorn'
```
Ожидается **10** (девять воркеров + мастер). Было 4.

```bash
ssh kotokod-vps 'free -m; ps -eo rss,comm --sort=-rss | head -12'
```
Смотреть: `available` должно остаться выше ~2000 МБ. Если ушло ниже — снизить
`workers` в `deploy/gunicorn.conf.py` и перезапустить.

Celery тоже читает настройки Django — перезапустить, чтобы подхватил `CONN_MAX_AGE`:
```bash
ssh kotokod-vps 'systemctl restart journal-celery-worker journal-celery-beat'
```

Соединения к базе после прогрева:
```bash
ssh kotokod-vps 'sudo -u postgres psql -tAc "SELECT count(*) FROM pg_stat_activity"'
```
Ожидается порядка 20–25 из 100. Если приблизилось к 100 — снизить `workers`.

**Откат шага:** `sudo -u kotokod git -C /opt/kotokod/journal-backend checkout f75dd3f`
и `systemctl restart journal-django`.

---

## Шаг 5. nginx: кеш статики и уже подготовленные правки

Сниппет копируется из репозитория как есть (домена не содержит):

```bash
ssh kotokod-vps 'cp /opt/kotokod/journal-backend/deploy/nginx/snippets/journal-static.conf \
  /etc/nginx/snippets/journal-static.conf'
```

Site-конфиг **уже содержит** TLS-сессии и таймауты — их дописали 2026-08-02, но
nginx с тех пор не перезагружался. Проверить, что всё на месте:

```bash
ssh kotokod-vps 'grep -c "ssl_session_cache\|proxy_read_timeout" /etc/nginx/sites-available/journal-kotokod'
```
Ожидается `2` и больше.

```bash
ssh kotokod-vps 'nginx -t'
```
**Только при `test is successful`** идти дальше:

```bash
ssh kotokod-vps 'systemctl reload nginx'
```

**Откат шага:**
```bash
ssh kotokod-vps 'cp /root/nginx-backup-20260802/journal-kotokod /etc/nginx/sites-available/ && \
  cp /root/nginx-backup-20260802/journal-static.conf /etc/nginx/snippets/ && \
  nginx -t && systemctl reload nginx'
```

---

## Шаг 6. Выравнивание плана и факта (условие из коммита 2485444)

Это условие поставлено ещё при прошлом выкате и **не выполнено**. Без него новые
уроки пойдут по позициям плана, а старые останутся со съехавшими номерами.

Сначала найти группы с дрейфом:
```bash
ssh kotokod-vps 'sudo -u postgres psql -d journal -tAc "
SELECT p.group_id, count(*) FROM planned_lessons p
JOIN lessons l ON l.id = p.fact_lesson_id
WHERE p.seq IS NOT NULL AND p.lesson_number IS DISTINCT FROM l.lesson_number
GROUP BY 1 ORDER BY 2 DESC"'
```

По каждой группе — **сухой прогон**, посмотреть, что предлагается:
```bash
ssh kotokod-vps 'cd /opt/kotokod/journal-backend/journal_django && \
  sudo -u kotokod DJANGO_SETTINGS_MODULE=config.settings.production \
  .venv/bin/python manage.py resync_plan_facts --group <ID>'
```

И только осознав вывод — применить:
```bash
... manage.py resync_plan_facts --group <ID> --apply
```

---

## Шаг 7. Проверка снаружи

**Кеш статики** (взять актуальное имя файла из `/teacher/index.html`):
```bash
curl -sI https://develop-kotokod.ru/teacher/assets/<файл>.js | grep -i "cache-control\|expires"
```
Ожидается `Cache-Control: max-age=31536000`. Раньше заголовка не было вовсе.

**Заголовки безопасности на ассетах не пропали** — это главная проверка правильности
подхода с `expires` вместо `add_header`:
```bash
curl -sI https://develop-kotokod.ru/teacher/assets/<файл>.js | grep -ci "strict-transport-security\|x-content-type-options"
```
Ожидается `2`. **Если 0 — откатить шаг 5 немедленно**: значит наследование заголовков
всё-таки сломано.

**Переиспользование TLS-сессий:**
```bash
echo | openssl s_client -connect develop-kotokod.ru:443 -reconnect 2>/dev/null | grep -c "Reused"
```
Ожидается больше нуля. До выката было `0`.

**Живость приложения:**
```bash
curl -sS -o /dev/null -w "код=%{http_code} ttfb=%{time_starttransfer}s\n" https://develop-kotokod.ru/health
```

**Логи на ошибки за первые минуты:**
```bash
ssh kotokod-vps 'journalctl -u journal-django --since "10 min ago" -p err --no-pager | tail -20'
ssh kotokod-vps 'tail -30 /var/log/nginx/error.log'
```

---

## Шаг 8. Ручная проверка в браузере

Автотестов на фронтенде в проекте нет — эти сценарии проверяются только руками.

1. **Кабинет преподавателя → «Зарплата»** — открывается, суммы и расшифровки на месте,
   переключение месяцев работает.
2. **Отметка урока из «Моих уроков»** — записывается, номер совпадает с планом.
3. **Повторная отправка того же занятия** — спокойное «уже записано», не красная ошибка.
4. **Закрытие формы во время отправки** — Esc, клик по фону, крестик и «Отмена» не
   работают, пока идёт сохранение.
5. **Мультислотовая группа** (два занятия в один день) — записываются оба.
6. **Доп.урок из «Моих уроков»** — открывается модалка доп.урока, а не форма обычного.

---

## Что этот выкат НЕ закрывает

**Дубли уроков, записанных ДО выката, ключом не ловятся.** У старых строк
`submission_key` пустой, они ничего не сторожат. Защита работает для новых записей;
старые прикрыты только захватом позиции плана.

**Группа без плана занятий с двумя занятиями в один день** получит отказ на втором.
Осознанный размен: отказ громкий и понятный, прежнее поведение молча создавало дубль
с деньгами. Правильное решение — завести такой группе план.

**Кеш статики не даёт `immutable`.** Использован `expires`, потому что `add_header`
внутри location выключил бы заголовки безопасности. Браузер будет изредка слать
условный запрос вместо полного молчания — незначительно.
