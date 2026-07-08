"""
Дайджест касаний: для каждого менеджера — открытые сделки с next_touch_at <= сегодня.
Шлёт письмо через настроенный Django email backend (Beget SMTP из .env).
"""
from __future__ import annotations

from collections import defaultdict

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Рассылает менеджерам напоминания о касаниях продлений на сегодня.'

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT a.email, a.full_name, s.full_name AS student, dir.name AS direction,
                       st.label AS stage, d.next_touch_at
                FROM renewal_deal d
                JOIN accounts a ON a.id = d.assignee_id
                JOIN students s ON s.id = d.student_id
                JOIN directions dir ON dir.id = d.direction_id
                JOIN renewal_stage st ON st.id = d.stage_id
                WHERE d.outcome_at IS NULL AND d.next_touch_at IS NOT NULL
                  AND d.next_touch_at <= now()::date
                  AND a.email IS NOT NULL AND a.email != ''
                ORDER BY a.email, d.next_touch_at
            """)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        by_email: dict[str, list] = defaultdict(list)
        for r in rows:
            by_email[r['email']].append(r)

        sent = 0
        for email, items in by_email.items():
            lines = [f"— {it['student']} · {it['direction']} · {it['stage']} "
                     f"(касание {it['next_touch_at']})" for it in items]
            send_mail(
                subject=f'Продления на сегодня: {len(items)}',
                message='Задачи по продлениям:\n' + '\n'.join(lines),
                from_email=None, recipient_list=[email], fail_silently=True)
            sent += 1
        self.stdout.write(self.style.SUCCESS(f'renewals: отправлено дайджестов: {sent}'))
