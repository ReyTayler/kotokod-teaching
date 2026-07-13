"""
URL-конфиг teacher SPA.

Пути монтируются под /api (НЕ /api/admin).
APPEND_SLASH=False — без trailing slash (как Express).

Порядок: report/refresh и schedule/refresh ПЕРЕД report/schedule,
чтобы /report/refresh не поглотилось /report<pk>.
"""
from django.urls import path

from apps.teacher_spa import views

urlpatterns = [
    path('/getData', views.GetDataView.as_view(), name='teacher-get-data'),
    path('/getAllData', views.GetAllDataView.as_view(), name='teacher-get-all-data'),
    path('/submitLesson', views.SubmitLessonView.as_view(), name='teacher-submit-lesson'),
    # refresh перед базовыми маршрутами
    path('/report/refresh', views.ReportRefreshView.as_view(), name='teacher-report-refresh'),
    path('/schedule/refresh', views.ScheduleRefreshView.as_view(), name='teacher-schedule-refresh'),
    path('/report', views.ReportView.as_view(), name='teacher-report'),
    path('/schedule', views.ScheduleView.as_view(), name='teacher-schedule'),
    path('/refreshData', views.RefreshDataView.as_view(), name='teacher-refresh-data'),
    path('/lessons', views.MyLessonsView.as_view(), name='teacher-my-lessons'),
    path('/group-directions', views.GroupDirectionsView.as_view(), name='teacher-group-directions'),
    path('/group-progress', views.GroupProgressView.as_view(), name='teacher-group-progress'),
]
