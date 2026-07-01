"""
Serializers for settings_app.

adminSettingsSchema из shared/schemas.js:
  z.object({}).passthrough()
  Произвольный JSON-объект. Бэк хранит как есть.

Валидация выполняется непосредственно во view (проверка isinstance dict),
т.к. DRF Serializer не поддерживает passthrough-объекты без определённых полей.
Этот файл существует для единообразия структуры модуля.
"""
# Сериализатор не нужен — валидация в views.py

