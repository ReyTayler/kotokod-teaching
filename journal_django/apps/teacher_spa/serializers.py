"""
Serializers for teacher_spa.

Порт submitLessonSchema из shared/schemas.js (lines 263-274).
date-поле — DateStringField (YYYY-MM-DD, без timezone drift).
"""
from __future__ import annotations

from rest_framework import serializers

from apps.core.fields import DateStringField
from apps.directions.models import Direction
from apps.payroll.models import Payroll

# Поля, которые клиент больше не выбирает — их выводит сервер из planned_lessons
# (см. services.submit_lesson): замена — из назначения «Сменить преподавателя»,
# перенос — из moved_from_date плановой строки.
_SERVER_DERIVED_FIELDS = {
    'isSubstitution': 'Поле не принимается: замена назначается администратором.',
    'originalTeacher': 'Поле не принимается: замена назначается администратором.',
    'lessonType': 'Поле не принимается: тип урока выводится из плана занятий.',
}


class StudentAttendanceSerializer(serializers.Serializer):
    """Элемент списка студентов в submitLesson: {name, present, is_free?}.

    is_free — исход «бесплатное занятие» (опц., по умолчанию False). См.
    lesson-outcomes-spec."""

    name = serializers.CharField()
    present = serializers.BooleanField()
    is_free = serializers.BooleanField(required=False, default=False)


class SubmitLessonSerializer(serializers.Serializer):
    """
    Порт submitLessonSchema из shared/schemas.js.

    Обязательные: group, date, students. Необязательные: recordUrl.

    isSubstitution/originalTeacher/lessonType клиентом больше НЕ принимаются
    (400): тип урока выводит сервер из planned_lessons — замена из назначения
    «Сменить преподавателя», перенос из moved_from_date (см. services.submit_lesson).
    """

    # Zod: z.string().optional() — null НЕ принимается (Express 400).
    # Пустую строку z.string() принимает → allow_blank=True. z.string() не триммит →
    # trim_whitespace=False.
    group = serializers.CharField()
    date = DateStringField()
    recordUrl = serializers.CharField(
        allow_blank=True, required=False, trim_whitespace=False
    )
    students = StudentAttendanceSerializer(many=True)

    def validate(self, attrs):
        forbidden = set(_SERVER_DERIVED_FIELDS) & set(self.initial_data or {})
        if forbidden:
            raise serializers.ValidationError({
                key: _SERVER_DERIVED_FIELDS[key] for key in sorted(forbidden)
            })
        return attrs


class MyLessonSerializer(serializers.Serializer):
    """
    Read-only элемент истории «Мои уроки» (GET /api/lessons).

    Payroll (1:1) может отсутствовать у исторических записей → все производные
    от него поля отдаются как None. Decimal-поля рендерятся строкой с масштабом
    (DateSafeJSONRenderer) — фронт приводит Number().
    """

    id = serializers.IntegerField()
    date = serializers.DateField(source='lesson_date')
    group = serializers.CharField(source='group.name')
    lessonNumber = serializers.DecimalField(
        source='lesson_number', max_digits=5, decimal_places=1
    )
    lessonType = serializers.CharField(source='lesson_type')
    isSubstitution = serializers.SerializerMethodField()
    originalTeacher = serializers.SerializerMethodField()
    recordUrl = serializers.CharField(source='record_url', allow_null=True)
    submittedAt = serializers.DateTimeField(source='submitted_at')
    direction = serializers.SerializerMethodField()
    directionColor = serializers.SerializerMethodField()
    presentCount = serializers.SerializerMethodField()
    totalCount = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    penalty = serializers.SerializerMethodField()

    def _payroll(self, obj):
        try:
            return obj.payroll
        except Payroll.DoesNotExist:
            return None

    def _direction(self, obj):
        try:
            return obj.group.direction
        except Direction.DoesNotExist:
            return None

    def get_direction(self, obj):
        d = self._direction(obj)
        return d.name if d else None

    def get_directionColor(self, obj):
        d = self._direction(obj)
        return d.color if d else None

    def get_isSubstitution(self, obj) -> bool:
        return obj.lesson_type == 'substitution'

    def get_originalTeacher(self, obj):
        return obj.original_teacher.name if obj.original_teacher_id else None

    def get_presentCount(self, obj):
        pr = self._payroll(obj)
        return pr.present_count if pr else None

    def get_totalCount(self, obj):
        pr = self._payroll(obj)
        return pr.total_students if pr else None

    def get_payment(self, obj):
        pr = self._payroll(obj)
        return str(pr.payment) if pr else None

    def get_penalty(self, obj):
        pr = self._payroll(obj)
        return str(pr.penalty) if pr else None
