-- 001_initial_schema.sql
-- Полная начальная схема journal-backend.

BEGIN;

-- ===== Справочники =====

CREATE TABLE teachers (
  id         serial PRIMARY KEY,
  name       text NOT NULL UNIQUE,
  email      text,
  phone      text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tokens (
  token      text PRIMARY KEY,
  teacher_id int NOT NULL REFERENCES teachers(id),
  active     bool NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE directions (
  id            serial PRIMARY KEY,
  name          text NOT NULL UNIQUE,
  sheet_name    text NOT NULL,
  is_individual bool NOT NULL
);

-- ===== Группы и состав =====

CREATE TABLE groups (
  id                      serial PRIMARY KEY,
  name                    text NOT NULL UNIQUE,
  direction_id            int NOT NULL REFERENCES directions(id),
  teacher_id              int NOT NULL REFERENCES teachers(id),
  is_individual           bool NOT NULL,
  lesson_duration_minutes int NOT NULL DEFAULT 90
                          CHECK (lesson_duration_minutes IN (45, 60, 90)),
  lessons_per_week        int NOT NULL DEFAULT 1
                          CHECK (lessons_per_week BETWEEN 1 AND 7),
  group_start_date        date,
  vk_chat                 text,
  created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE group_schedule_slots (
  id          serial PRIMARY KEY,
  group_id    int NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  day_of_week int NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
  start_time  time NOT NULL,
  UNIQUE (group_id, day_of_week, start_time)
);
CREATE INDEX group_schedule_slots_dow_time_idx
  ON group_schedule_slots(day_of_week, start_time);

CREATE TABLE students (
  id                  serial PRIMARY KEY,
  full_name           text NOT NULL,
  birth_date          date,
  phone               text,
  school_grade        int CHECK (school_grade BETWEEN 1 AND 11),
  platform_id         text,
  parent_name         text,
  first_purchase_date date,
  age                 int,
  pm                  text,
  enrollment_status   text NOT NULL DEFAULT 'enrolled'
                      CHECK (enrollment_status IN
                        ('enrolled','not_enrolled','frozen','declined')),
  frozen_until_month  int CHECK (frozen_until_month BETWEEN 1 AND 12),
  CHECK ((enrollment_status = 'frozen') = (frozen_until_month IS NOT NULL)),
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE group_memberships (
  id           serial PRIMARY KEY,
  group_id     int NOT NULL REFERENCES groups(id),
  student_id   int NOT NULL REFERENCES students(id),
  lessons_done numeric(6,1) NOT NULL DEFAULT 0,
  remaining    numeric(6,1) NOT NULL DEFAULT 0,
  start_date   date,
  sheet_row    int,
  active       bool NOT NULL DEFAULT true,
  UNIQUE (group_id, student_id)
);

-- ===== Транзакционные таблицы =====

CREATE TABLE lessons (
  id                      serial PRIMARY KEY,
  group_id                int NOT NULL REFERENCES groups(id),
  teacher_id              int NOT NULL REFERENCES teachers(id),
  original_teacher_id     int REFERENCES teachers(id),
  lesson_date             date NOT NULL,
  lesson_number           numeric(5,1) NOT NULL,
  lesson_duration_minutes int NOT NULL,
  lesson_type             text NOT NULL,
  record_url              text,
  submitted_at            timestamptz NOT NULL DEFAULT now(),
  submitted_by_token      text NOT NULL
);
CREATE INDEX lessons_group_date_idx   ON lessons(group_id, lesson_date);
CREATE INDEX lessons_teacher_date_idx ON lessons(teacher_id, lesson_date);

CREATE TABLE lesson_attendance (
  lesson_id  int NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  student_id int NOT NULL REFERENCES students(id),
  present    bool NOT NULL,
  PRIMARY KEY (lesson_id, student_id)
);

CREATE TABLE payroll (
  id             serial PRIMARY KEY,
  lesson_id      int NOT NULL UNIQUE REFERENCES lessons(id),
  teacher_id     int NOT NULL REFERENCES teachers(id),
  total_students int NOT NULL,
  present_count  int NOT NULL,
  payment        numeric(10,2) NOT NULL,
  penalty        numeric(10,2) NOT NULL DEFAULT 0
);
CREATE INDEX payroll_teacher_lesson_idx ON payroll(teacher_id, lesson_id);

-- ===== Инфраструктура =====

CREATE TABLE sync_failures (
  id            bigserial PRIMARY KEY,
  occurred_at   timestamptz NOT NULL DEFAULT now(),
  operation     text NOT NULL,
  payload       jsonb NOT NULL,
  error_message text NOT NULL,
  resolved_at   timestamptz
);

-- Таблицу schema_migrations создаёт db/migrate.js до запуска любой миграции

COMMIT;
