from django.urls import path
from . import views

app_name = "exam"

urlpatterns = [
    # General User Authentication
    path("", views.home, name="home"),
    # Admin routes
    path('seat-allocation/api/halls/<int:exam_id>/', views.get_exam_halls_api, name='get_exam_halls_api'),
    path("admin-login/", views.admin_login, name="admin_login"),
    path("admin-logout/", views.admin_logout, name="admin_logout"),
    # Teacher routes
    path("teacher-login/", views.teacher_login, name="teacher_login"),
    path("teacher-logout/", views.teacher_logout, name="teacher_logout"),
    # Student routes
    path("student-login/", views.student_login, name="student_login"),
    path("student-logout/", views.student_logout, name="student_logout"),

    # Admin Dashboard and Main Pages
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('teacher-dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('student-dashboard/', views.student_dashboard, name='student_dashboard'),

    # Admin Management: Halls
    path('admin-dashboard/halls/', views.manage_halls, name='manage_halls'),
    path('admin-dashboard/halls/edit/<int:hall_id>/', views.edit_hall, name='edit_hall'),
    path('admin-dashboard/halls/delete/<int:hall_id>/', views.delete_hall, name='delete_hall'),

    # Admin Management: Departments
    path('admin-dashboard/departments/', views.manage_departments, name='manage_departments'),
    path('admin-dashboard/departments/edit/<int:dept_id>/', views.edit_department, name='edit_department'),
    path('admin-dashboard/departments/delete/<int:dept_id>/', views.delete_department, name='delete_department'),

    # Admin Management: Students
    path('admin-dashboard/students/', views.manage_students, name='manage_students'),
    path('admin-dashboard/add-student/', views.add_student, name='add_student'),
    path('admin-dashboard/students/edit/<int:student_id>/', views.edit_student, name='edit_student'),
    path('admin-dashboard/students/delete/<int:student_id>/', views.delete_student, name='delete_student'),
    path('student-dashboard/', views.student_dashboard, name='student_dashboard'),

    # Admin Management: Teachers
    path('admin-dashboard/teachers/', views.manage_teachers, name='manage_teachers'),
    path('admin-dashboard/add-teacher/', views.add_teacher, name='add_teacher'),
    path('admin-dashboard/teachers/edit/<int:teacher_id>/', views.edit_teacher, name='edit_teacher'),
    path('admin-dashboard/teachers/delete/<int:teacher_id>/', views.delete_teacher, name='delete_teacher'),

    # Admin Management: Exams
    path('admin-dashboard/exams/', views.manage_exams, name='manage_exams'),
    path('admin-dashboard/exams/edit/<int:exam_id>/', views.edit_exam, name='edit_exam'),
    path('admin-dashboard/exams/delete/<int:exam_id>/', views.delete_exam, name='delete_exam'),

    # Seating Plan & Allocation Pages
    path('admin-dashboard/seating-plan-list/', views.seating_plan_list, name='seating_plan_list'),
    path('admin-dashboard/seating-plans/<int:exam_id>/', views.all_seating_plans, name='all_seating_plans'),
    path('admin-dashboard/seating-plans/<int:exam_id>/<int:hall_id>/', views.seating_plan_detail, name='seating_plan_detail'),
    path('admin-dashboard/seat-allocation/', views.seat_allocation, name='seat_allocation'),

    # Invigilator Assignment
    path('admin-dashboard/assign-invigilator/<int:exam_id>/', views.assign_invigilator, name='assign_invigilator'),
    path('admin-dashboard/delete-invigilator-assignment/<int:assignment_id>/', views.delete_invigilator_assignment, name='delete_invigilator_assignment'),
    path('ajax/get-student-count/', views.get_student_count, name='get_student_count'),


    path('attendance/mark/<int:exam_id>/<int:hall_id>/', 
         views.mark_attendance, name='mark_attendance'),

    # Path for Downloading Attendance Report
    path('attendance/download/<int:exam_id>/<int:hall_id>/', 
         views.download_attendance, name='download_attendance'),

    # Path for Student Count AJAX (If you implemented it)
    path('ajax/get-student-count/', 
         views.get_student_count, name='get_student_count'),
]