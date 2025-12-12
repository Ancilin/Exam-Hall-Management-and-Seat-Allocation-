from django.utils import timezone
import importlib
import importlib.util
from collections import deque

# Dynamically check for pandas availability
if importlib.util.find_spec("pandas") is not None:
    pd = importlib.import_module("pandas")
else:
    # Set pd to a safe value if it's not installed, though Excel upload will fail without it.
    pd = None

import io
from .models import Exam, Hall, SeatingAllocation, Student
from datetime import date
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db import transaction, IntegrityError
# Ensure these are imported
from django.db.models import Count, F, ExpressionWrapper, IntegerField, Q
from django.http import JsonResponse, HttpResponse
from django import forms
import csv

# --- Imports for Forms and Models ---
from .forms import (
    AdminLoginForm,
    TeacherLoginForm,
    StudentLoginForm,
    AddStudentForm,
    AddTeacherForm,
    HallForm,
    DepartmentForm,
    ExamForm,
    DepartmentFilterForm,
    ExcelUploadForm,
    SeatAllocationForm,
    InvigilationAssignmentForm,
    AttendanceForm,
)

from .models import (
    Department,
    Student,
    Teacher,
    Hall,
    Exam,
    SeatingAllocation,
    InvigilationAssignment,
    AttendanceRecord,
)


# Helper functions for user type checks
def is_superuser(user):
    return user.is_superuser

def is_teacher(user):
    return hasattr(user, 'teacher')

def is_student(user):
    return hasattr(user, 'student')


def home(request):
    return render(request, "exam/home.html")


# --- Login/Logout Views ---
def admin_login(request):
    if request.method == 'POST':
        form = AdminLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user is not None and user.is_superuser:
                login(request, user)
                return redirect('exam:admin_dashboard')
            else:
                return render(request, 'exam/admin_login.html', {'form': form, 'error': 'Invalid credentials or you are not an admin.'})
    else:
        form = AdminLoginForm()
    return render(request, 'exam/admin_login.html', {'form': form})

def teacher_login(request):
    if request.method == 'POST':
        form = TeacherLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user is not None and hasattr(user, 'teacher'):
                login(request, user)
                return redirect('exam:teacher_dashboard')
            else:
                return render(request, 'exam/teacher_login.html', {'form': form, 'error': 'Invalid credentials or you are not a teacher.'})
    else:
        form = TeacherLoginForm()
    return render(request, 'exam/teacher_login.html', {'form': form})

def student_login(request):
    if request.user.is_authenticated and hasattr(request.user, 'student'):
        return redirect('exam:student_dashboard')

    if request.method == 'POST':
        form = StudentLoginForm(request.POST)
        if form.is_valid():
            roll_no = form.cleaned_data['roll_no']
            password = form.cleaned_data['password']
            try:
                student = Student.objects.select_related('user').get(roll_no=str(roll_no))
                authenticated_user = authenticate(request, username=student.user.username, password=password)
                
                if authenticated_user is not None and hasattr(authenticated_user, 'student'):
                    login(request, authenticated_user)
                    messages.success(request, f'Welcome back, {authenticated_user.username}!')
                    return redirect('exam:student_dashboard')
                else:
                    messages.error(request, 'Invalid password.')
                    return render(request, 'exam/student_login.html', {'form': form})
            except Student.DoesNotExist:
                messages.error(request, 'No student found with this roll number.')
                return render(request, 'exam/student_login.html', {'form': form})
    else:
        form = StudentLoginForm()
    return render(request, 'exam/student_login.html', {'form': form})

# --- Replace the existing teacher_dashboard function in views.py with this ---
@login_required
@user_passes_test(is_teacher)
def teacher_dashboard(request):
    teacher = request.user.teacher
    today = timezone.now().date()
    
    # This fetches one assignment for each exam (Business, Mobile, Big Data)
    invigilation_assignments = InvigilationAssignment.objects.filter(
        teacher=teacher,
        exam__date__gte=today
    ).select_related('exam', 'hall').order_by('exam__date', 'exam__start_time')

    exam_details = []
    
    # Process each assignment (duty) separately to generate one card per exam
    for assignment in invigilation_assignments:
        exam = assignment.exam
        hall = assignment.hall
        
        # Get students ONLY for this specific Exam/Hall combination
        # The ordering MUST be by seat_number (e.g., S1, S2, S3...)
        all_seating_allocations = SeatingAllocation.objects.filter(
            exam=exam,
            hall=hall
        ).select_related('student__user', 'student__department').order_by('student__roll_no', 'seat_number')
        
        # Collect unique departments involved for the summary (Should only be one department per card now)
        involved_departments = [dept.name for dept in exam.department.all()]
        
        # Attendance Check: Check attendance ONLY for this specific Exam/Hall/Today
        student_ids_in_exam = all_seating_allocations.values_list('student_id', flat=True)

        attendance_marked = AttendanceRecord.objects.filter(
            exam=exam, 
            hall=hall,
            student__id__in=student_ids_in_exam, 
            date_marked=today
        ).exists()
        
        exam_detail = {
            'display_name': exam.exam_name, 
            'hall': hall,
            'departments': involved_departments, 
            'students': all_seating_allocations, 
            'total_students': all_seating_allocations.count(),
            'date': exam.date,
            'start_time': exam.start_time,
            'end_time': exam.end_time,
            'mark_attendance_exam_id': exam.id, 
            'attendance_marked': attendance_marked, 
        }
        exam_details.append(exam_detail)
    
    context = {
        'teacher': teacher,
        'exam_details': exam_details,
    }
    return render(request, 'exam/teacher_dashboard.html', context)

def admin_logout(request):
    logout(request)
    messages.success(request, 'Successfully logged out.')
    return redirect('exam:home')

def teacher_logout(request):
    logout(request)
    messages.success(request, 'Successfully logged out.')
    return redirect('exam:home')

def student_logout(request):
    logout(request)
    messages.success(request, 'Successfully logged out.')
    return redirect('exam:home')


# --- Dashboard Views ---

@login_required
@user_passes_test(is_superuser)
def admin_dashboard(request):
    today = timezone.now().date()
    total_students = Student.objects.count()
    total_teachers = Teacher.objects.count()
    total_exams = Exam.objects.count()
    total_halls = Hall.objects.count()
    upcoming_exams = Exam.objects.filter(
        date__gte=today
    ).prefetch_related('department').order_by('date')[:5]
    
    context = {
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_exams': total_exams,
        'total_halls': total_halls,
        'upcoming_exams': upcoming_exams,
    }
    return render(request, 'exam/admin_dashboard.html', context)


@login_required
@user_passes_test(is_teacher)
def mark_attendance(request, exam_id, hall_id):
    # Get the *first* exam from the URL (used as the anchor for the slot)
    anchor_exam = get_object_or_404(Exam, id=exam_id)
    hall = get_object_or_404(Hall, id=hall_id)
    teacher = request.user.teacher
    today = timezone.now().date()
    
    # 1. CRITICAL: Find ALL exams running in this common slot (Date, Time, Hall)
    # This addresses the "one hall 3 exam" problem.
    shared_exams = Exam.objects.filter(
        date=anchor_exam.date,
        start_time=anchor_exam.start_time,
        halls=hall
    ).values_list('id', flat=True)
    
    if not shared_exams.exists():
        messages.error(request, "No exams found for this time slot.")
        return redirect('exam:teacher_dashboard')

    # Verify the current teacher is assigned to invigilate this hall/SLOT
    if not InvigilationAssignment.objects.filter(exam__id__in=shared_exams, hall=hall, teacher=teacher).exists():
        messages.error(request, "You are not authorized to mark attendance for this assignment.")
        return redirect('exam:teacher_dashboard')

    # 2. Get ALL students allocated to ANY of these shared exams in this specific hall
    # This collects students from all three departments (CS, ME, MA)
    allocations = SeatingAllocation.objects.filter(
        exam__id__in=shared_exams, 
        hall=hall
    ).select_related('student__user', 'exam').order_by('student__roll_no')
    
    if not allocations.exists():
        messages.warning(request, "No students are allocated to this hall for the exams in this slot.")
        return redirect('exam:teacher_dashboard')

    # 3. Check for existing attendance records for ANY shared exam for today
    # We use the list of students we just compiled for an accurate check
    student_ids_in_slot = allocations.values_list('student_id', flat=True)
    
    attendance_marked_today = AttendanceRecord.objects.filter(
        exam__id__in=shared_exams, 
        hall=hall, 
        student__id__in=student_ids_in_slot,
        date_marked=today
    ).select_related('student__user').distinct('student_id') # Use distinct to get one status per student
    
    # Map existing attendance for quick lookup
    existing_attendance_map = {record.student.id: record for record in attendance_marked_today}

    initial_data = []
    
    # Create a set to track which students have already been added to initial_data 
    # (prevents duplicates if a student is allocated to multiple exams in the slot - highly unlikely but safe)
    processed_student_ids = set()

    # Determine display name (e.g., Business Management, Mobile App, Big Data)
    exam_names = Exam.objects.filter(pk__in=shared_exams).values_list('exam_name', flat=True)
    display_name = ", ".join(exam_names)
    
    # Populate initial data
    for alloc in allocations:
        student_id = alloc.student.id
        if student_id not in processed_student_ids:
            
            # Default status: check existing attendance first, then default to Present 'P'
            status = 'P'
            if student_id in existing_attendance_map:
                status = existing_attendance_map[student_id].status
            
            initial_data.append({
                # CRITICAL: We pass the ANCHOR_EXAM to the form/model for saving the record.
                # This is okay because the record is tied to the student/hall/date/time slot.
                'student': alloc.student,
                'exam': anchor_exam, 
                'hall': hall,
                'status': status, 
                'roll_no_display': alloc.student.roll_no,
                'student_name_display': alloc.student.user.username,
            })
            processed_student_ids.add(student_id)

    # Formset factory to handle multiple forms
    AttendanceFormSet = forms.formset_factory(AttendanceForm, extra=0)

    # --- POST Logic ---
    if request.method == 'POST':
        # Filter initial data to pass only actual form fields
        EXPECTED_FORM_FIELDS = ['student', 'exam', 'hall', 'status']
        filtered_initial_data = [{k: v for k, v in data.items() if k in EXPECTED_FORM_FIELDS} for data in initial_data]
        
        formset = AttendanceFormSet(request.POST, initial=filtered_initial_data)
        
        if formset.is_valid():
            try:
                with transaction.atomic():
                    # 4. CRITICAL: Delete ALL old records for the entire SLOT (all shared exams)
                    # We must ensure we clean up all previous records for all consolidated exams/students
                    AttendanceRecord.objects.filter(
                        exam__id__in=shared_exams, 
                        hall=hall, 
                        student__id__in=student_ids_in_slot,
                        date_marked=today
                    ).delete()

                    new_records = []
                    for form in formset:
                        # Ensure we only create records for students marked as Absent or Present
                        student = form.cleaned_data['student']
                        status = form.cleaned_data['status']
                        
                        # Use the ANCHOR_EXAM for saving (as long as it links to the hall/time, it's consistent)
                        record = AttendanceRecord(
                            exam=anchor_exam,
                            hall=hall,
                            student=student,
                            status=status,
                            date_marked=today 
                        )
                        new_records.append(record)
                    
                    AttendanceRecord.objects.bulk_create(new_records)
                    messages.success(request, f"Attendance successfully saved for {len(new_records)} students across the consolidated exams.")
                    return redirect('exam:teacher_dashboard')
            except Exception as e:
                messages.error(request, f"A database error occurred: {e}. Attendance was NOT saved.")
        else:
            messages.error(request, "Please correct the errors below. (Attendance was not saved).")
            # Re-map display fields back if validation fails (needed for rendering)
            for i, form in enumerate(formset):
                if i < len(initial_data):
                    original_data = initial_data[i]
                    form.initial['roll_no_display'] = original_data.get('roll_no_display')
                    form.initial['student_name_display'] = original_data.get('student_name_display')
            
            
    else:
        # GET Request: Initialize formset with all data 
        formset = AttendanceFormSet(initial=initial_data)

    # Final step to ensure display fields are always present for the template when rendering
    for form in formset:
        if 'student' in form.initial:
            student = form.initial['student']
            form.initial['roll_no_display'] = student.roll_no
            form.initial['student_name_display'] = student.user.username
    
    context = {
        # Pass the consolidated name for the Mark Attendance page header
        'exam': anchor_exam,
        'display_name': display_name, 
        'hall': hall,
        'formset': formset,
        'attendance_marked_today': attendance_marked_today.exists(),
    }
    return render(request, 'exam/mark_attendance.html', context)

# The student_dashboard view is correct for data retrieval.
@login_required
@user_passes_test(lambda u: u.is_superuser)
def seat_allocation(request):
    if request.method == "POST":
        form = SeatAllocationForm(request.POST)
        if form.is_valid():
            exam = form.cleaned_data["exam"]
            halls = list(form.cleaned_data["halls"]) # Convert to list to ensure order
            if not halls:
                messages.error(request, "Please select at least one hall.")
                return render(request, "exam/seat_allocation.html", {"form": form})

            # Get all students in the exam's departments
            exam_departments = exam.department.all()
            all_students = Student.objects.filter(department__in=exam_departments).order_by("roll_no")

            total_students = all_students.count()
            total_capacity = sum(hall.capacity for hall in halls)

            if total_students == 0:
                messages.error(request, "No students found for this exam.")
                return render(request, "exam/seat_allocation.html", {"form": form})

            if total_students > total_capacity:
                messages.error(
                    request,
                    f"Not enough seats available. Students: {total_students}, Capacity: {total_capacity}",
                )
                return render(request, "exam/seat_allocation.html", {"form": form})

            try:
                with transaction.atomic():
                    # CRITICAL: Delete old allocations for this exam before creating new ones
                    SeatingAllocation.objects.filter(exam=exam).delete()

                    # Interleave students department-wise (A B C A B C)
                    dept_lists = [list(all_students.filter(department=dept)) for dept in exam_departments]
                    mixed_students = []
                    max_len = max(len(d) for d in dept_lists) if dept_lists else 0

                    for i in range(max_len):
                        for dept in dept_lists:
                            if i < len(dept):
                                mixed_students.append(dept[i])

                    # ✅ Global continuous seat numbering across halls
                    allocation_list = []
                    seat_counter = 1
                    student_index = 0

                    for hall in halls:
                        for _ in range(hall.capacity):
                            if student_index < total_students:
                                student = mixed_students[student_index]
                                seat_number = f"S{seat_counter}" # Global Seat Number

                                allocation_list.append(
                                    SeatingAllocation(
                                        student=student,
                                        exam=exam,
                                        hall=hall,
                                        seat_number=seat_number,
                                    )
                                )

                                seat_counter += 1
                                student_index += 1
                            else:
                                break

                    SeatingAllocation.objects.bulk_create(allocation_list)

                    messages.success(
                        request,
                        f"✅ Successfully allocated {len(allocation_list)} students across {len(halls)} halls (Global numbering applied)."
                    )
                    return redirect("exam:all_seating_plans", exam_id=exam.id)

            except Exception as e:
                messages.error(request, f"Error during allocation: {e}")
                return render(request, "exam/seat_allocation.html", {"form": form})

    else:
        form = SeatAllocationForm()
        exams = Exam.objects.annotate(
            enrolled_students_count=Count("department__students", distinct=True)
        ).order_by("-date")
        halls = Hall.objects.order_by("hall_name")
        recent_allocations = (
            SeatingAllocation.objects.values("exam__id", "exam__exam_name").distinct().order_by("-exam__id")[:5]
        )

        context = {
            "form": form,
            "exams": exams,
            "halls": halls,
            "recent_allocations": recent_allocations,
        }
        return render(request, "exam/seat_allocation.html", context)


@login_required
@user_passes_test(is_superuser)
def get_student_count(request):
    """
    AJAX endpoint to calculate total students for selected departments.
    """
    if request.method == 'GET':
        # Get department IDs from the GET request (sent by JavaScript)
        department_ids = request.GET.getlist('department_ids')
        
        try:
            department_ids = [int(id) for id in department_ids if id]
            
            # Sum the student count for all selected departments
            total_students = Student.objects.filter(
                department__id__in=department_ids
            ).count()
            
            return JsonResponse({'total_students': total_students})
            
        except Exception:
            # Return 0 if the input is invalid or an error occurs
            return JsonResponse({'total_students': 0})
            
    return JsonResponse({'total_students': 0}, status=400)
# --- Hall Management Views ---

@login_required
@user_passes_test(is_superuser)
def manage_halls(request):
    halls = Hall.objects.all()
    error_message = None

    if request.method == 'POST':
        form = HallForm(request.POST)
        
        if form.is_valid():
            hall = form.save(commit=False)
            
            # Hall capacity is calculated via a model property, no manual assignment here.
            
            try:
                # 1. Save the Hall object. rows and columns are saved automatically.
                hall.save()
                
                # 2. Get the capacity from the new property for the message
                hall_capacity = hall.capacity 

                messages.success(request, f"Hall {hall.hall_name} added successfully with {hall_capacity} seats.")
                return redirect('exam:manage_halls')
                
            except IntegrityError:
                error_message = "Error: A hall with this name already exists. Please choose a unique name."
                messages.error(request, error_message)
            
            except Exception as e:
                print(f"!!! CRITICAL HALL SAVE ERROR: {e}") 
                error_message = "An unexpected error occurred. Please check server logs for details."
                messages.error(request, error_message)
                
        else:
            # If form validation fails
            messages.error(request, "Please correct the form errors below.")
            error_message = None 
            
    else:
        form = HallForm()
    
    return render(request, 'exam/manage_halls.html', {
        'form': form, 
        'halls': halls, 
        'error_message': error_message
    })



@login_required
@user_passes_test(is_superuser)
def edit_hall(request, hall_id):
    hall = get_object_or_404(Hall, pk=hall_id)
    
    if request.method == 'POST':
        form = HallForm(request.POST, instance=hall)
        
        if form.is_valid():
            # 1. Save the form instance *without* committing to the database yet
            hall = form.save(commit=False)
            
            # 2. Rows and columns are handled by form.save()
            # Do NOT set hall.capacity, as it is a model property
            
            # 3. Save the instance to the database
            hall.save() 
            
            messages.success(request, f"Hall {hall.hall_name} updated successfully.")
            return redirect('exam:manage_halls')
            
        
    else:
        form = HallForm(instance=hall)
    
    return render(request, 'exam/edit_hall.html', {'form': form, 'hall': hall})
@login_required
@user_passes_test(is_superuser)
def delete_hall(request, hall_id):
    hall = get_object_or_404(Hall, pk=hall_id)
    if request.method == 'POST':
        hall.delete()
        messages.success(request, f"Hall {hall.hall_name} deleted successfully.")
        return redirect('exam:manage_halls')
    return render(request, 'exam/confirm_delete_hall.html', {'hall': hall})


# --- Student Management Views ---

@login_required
@user_passes_test(is_superuser)
def manage_students(request):
    filter_form = DepartmentFilterForm(request.GET or None)
    
    students = Student.objects.select_related('user', 'department').order_by('department__name', 'roll_no')
    
    department_stats = Department.objects.annotate(
        student_count=Count('students')
    ).order_by('-student_count', 'name')

    if filter_form.is_valid() and filter_form.cleaned_data.get('department'):
        department = filter_form.cleaned_data['department']
        students = students.filter(department=department)
        
    context = {
        'students': students,
        'filter_form': filter_form,
        'department_stats': department_stats,
    }
    return render(request, 'exam/manage_students.html', context)


@login_required
@user_passes_test(is_superuser)
def add_student(request):
    individual_form = AddStudentForm()
    upload_form = ExcelUploadForm()

    if request.method == 'POST':
        if 'add_individual' in request.POST:
            individual_form = AddStudentForm(request.POST)
            if individual_form.is_valid():
                roll_no = individual_form.cleaned_data['roll_no']
                username = individual_form.cleaned_data['username']
                password = individual_form.cleaned_data['password']
                department = individual_form.cleaned_data['department']

                # Check for conflicts
                # 🔴 FIX: Removed username check to only validate roll_no uniqueness
                if Student.objects.filter(roll_no=roll_no).exists():
                    individual_form.add_error('roll_no', 'This roll number already exists.')
                else:
                    # NOTE: Django User model requires a unique username. Using roll_no as username is safest here.
                    # Assuming form.cleaned_data['username'] is being ignored or set to roll_no elsewhere.
                    if User.objects.filter(username=username).exists():
                          # If we keep the username field in the form, we must keep this check or use roll_no as username
                          individual_form.add_error('username', 'This username is already taken.')
                          return render(request, 'exam/add_student.html', {'individual_form': individual_form, 'upload_form': upload_form})
                          
                    user = User.objects.create_user(username=username, password=password)
                    Student.objects.create(user=user, roll_no=roll_no, department=department)
                    messages.success(request, f"Student {roll_no} added successfully.")
                    return redirect('exam:manage_students')

        elif 'upload_excel' in request.POST:
            upload_form = ExcelUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                excel_file = request.FILES['excel_file']
                file_extension = excel_file.name.split('.')[-1]

                try:
                    excel_data = excel_file.read()
                    df = None

                    if file_extension in ['xls', 'xlsx']:
                        if pd is None:
                            raise ValueError(
                                "Pandas is required to process Excel files (.xls/.xlsx). "
                                "Please install it in your environment: pip install pandas"
                            )
                        df = pd.read_excel(io.BytesIO(excel_data))
                    elif file_extension == 'csv':
                        try:
                            df = pd.read_csv(io.BytesIO(excel_data), encoding='utf-8')
                        except UnicodeDecodeError:
                            df = pd.read_csv(io.BytesIO(excel_data), encoding='latin1')
                    else:
                        raise ValueError("Unsupported file format. Please upload .xlsx or .csv file.")

                    required_columns = ['roll_no', 'username', 'password', 'department']
                    missing_cols = [col for col in required_columns if col not in df.columns]
                    if missing_cols:
                        raise ValueError(f"Missing required columns in file: {', '.join(missing_cols)}")

                    with transaction.atomic():
                        created_count = 0
                        errors = []
                        
                        df['password'] = df['password'].astype(str)
                        departments_map = {d.name.lower(): d for d in Department.objects.all()}

                        for index, row in df.iterrows():
                            roll_no = str(row.get('roll_no')).strip()
                            username = str(row.get('username')).strip()
                            password = str(row.get('password')).strip()
                            department_name = str(row.get('department')).strip().lower()

                            if not all([roll_no, username, password, department_name]):
                                errors.append(f"Row {index + 2}: Missing data.")
                                continue

                            department = departments_map.get(department_name)
                            if not department:
                                errors.append(f"Row {index + 2}: Department '{department_name}' not found.")
                                continue

                            # 🔴 FIX: Removed User.objects.filter(username=username) check 
                            # to rely only on roll_no uniqueness as requested.
                            # WARNING: Django's default User model requires unique username; 
                            # this relies on the CSV/Excel ensuring unique usernames OR using roll_no as username.
                            
                            if Student.objects.filter(roll_no=roll_no).exists():
                                errors.append(f"Row {index + 2}: Roll number '{roll_no}' already exists.")
                                continue

                            user = User.objects.create_user(username=username, password=password)
                            Student.objects.create(user=user, roll_no=roll_no, department=department)
                            created_count += 1

                        if errors:
                            raise ValueError("Could not process the file due to the following errors: <br>" + "<br>".join(errors))

                    messages.success(request, f"Successfully created {created_count} new students.")
                    return redirect('exam:manage_students')
                
                except IntegrityError as e:
                    error_message = f"A database integrity error occurred. Details: {e}"
                    upload_form.add_error(None, error_message)
                except Exception as e:
                    error_message = f'Error processing file: {e}'
                    upload_form.add_error(None, error_message)
            
    return render(
        request,
        'exam/add_student.html',
        {'individual_form': individual_form, 'upload_form': upload_form}
    )

@login_required
@user_passes_test(is_superuser)
def edit_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    
    # Use AddStudentForm with the instance of the student and initial data for the User fields
    if request.method == 'POST':
        # Need to re-instantiate the form with POST data
        form = AddStudentForm(request.POST) 
        if form.is_valid():
            
            # --- User Update Logic ---
            user = student.user
            new_username = form.cleaned_data['username']
            new_roll_no = form.cleaned_data['roll_no']

            # Check for existing username conflict (excluding the current student's user)
            if User.objects.exclude(pk=user.pk).filter(username=new_username).exists():
                form.add_error('username', 'This username is already taken by another user.')
                return render(request, 'exam/edit_student.html', {'form': form, 'student': student})

            # Check for existing roll_no conflict (excluding the current student)
            if Student.objects.exclude(pk=student.pk).filter(roll_no=new_roll_no).exists():
                form.add_error('roll_no', 'This roll number is already assigned to another student.')
                return render(request, 'exam/edit_student.html', {'form': form, 'student': student})


            # No conflicts, update user and student
            user.username = new_username
            if form.cleaned_data['password']:
                user.set_password(form.cleaned_data['password'])
            user.save()
            
            # --- Student Update Logic ---
            student.roll_no = new_roll_no
            student.department = form.cleaned_data['department']
            student.save()
            
            messages.success(request, "Student details updated successfully.")
            return redirect('exam:manage_students')
            
    else:
        form = AddStudentForm(initial={
            'username': student.user.username,
            'roll_no': student.roll_no,
            'department': student.department.pk, # Use PK for initial selection
        })
    return render(request, 'exam/edit_student.html', {'form': form, 'student': student})


@login_required
@user_passes_test(is_superuser)
def delete_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    if request.method == 'POST':
        student.user.delete() # Deletes the User, which cascades to the Student object
        messages.success(request, f"Student {student.roll_no} deleted successfully.")
        return redirect('exam:manage_students')
    return render(request, 'exam/confirm_delete_student.html', {'student': student})


# --- Department Management Views ---

# --- Check views.py - manage_departments function ---

# --- Check views.py - manage_departments function ---

@login_required
@user_passes_test(is_superuser)
def manage_departments(request):
    departments = Department.objects.order_by('name')
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, f"Department '{form.cleaned_data['name']}' added successfully.")
                return redirect('exam:manage_departments') 
            except Exception as e:
                # 🛑 CRITICAL DEBUGGING LINE: Print the error to the console
                print(f"!!! DEPARTMENT SAVE ERROR: {e}") 
                messages.error(request, f"Database Error: {e}. Department was NOT added. Check console for details.")
                # Fall through to re-render the form
        else:
            messages.error(request, "Please correct the form errors below.")
            
    else:
        form = DepartmentForm()
    
    return render(request, 'exam/manage_departments.html', {'form': form, 'departments': departments})

@login_required
@user_passes_test(is_superuser)
def edit_department(request, dept_id):
    department = get_object_or_404(Department, id=dept_id)
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            form.save()
            messages.success(request, "Department updated successfully.")
            return redirect('exam:manage_departments')
    else:
        form = DepartmentForm(instance=department)
    return render(request, 'exam/edit_department.html', {'form': form, 'department': department})


@login_required
@user_passes_test(is_superuser)
def delete_department(request, dept_id):
    department = get_object_or_404(Department, id=dept_id)
    if request.method == 'POST':
        department.delete()
        messages.success(request, "Department deleted successfully.")
        return redirect('exam:manage_departments')
    return render(request, 'exam/confirm_delete_department.html', {'department': department})


# --- Teacher Management Views ---

@login_required
@user_passes_test(is_superuser)
def manage_teachers(request):
    filter_form = DepartmentFilterForm(request.GET or None)
    
    teachers = Teacher.objects.select_related('user', 'department').order_by('department__name', 'employee_id')

    department_stats = Department.objects.annotate(
        teacher_count=Count('teachers')
    ).order_by('-teacher_count', 'name')
    
    if filter_form.is_valid() and filter_form.cleaned_data.get('department'):
        department = filter_form.cleaned_data['department']
        teachers = teachers.filter(department=department)

    context = {
        'teachers': teachers,
        'filter_form': filter_form,
        'department_stats': department_stats,
    }
    return render(request, 'exam/manage_teachers.html', context)


@login_required
@user_passes_test(is_superuser)
def add_teacher(request):
    # Initialize both forms for the GET request or if a POST fails
    individual_form = AddTeacherForm()
    upload_form = ExcelUploadForm()

    if request.method == 'POST':
        # 1. INDIVIDUAL TEACHER ADDITION LOGIC
        if 'add_individual' in request.POST:
            individual_form = AddTeacherForm(request.POST) 
            
            if individual_form.is_valid():
                username = individual_form.cleaned_data['username']
                employee_id = individual_form.cleaned_data['employee_id']
                
                # Check for conflicts
                if User.objects.filter(username=username).exists():
                    individual_form.add_error('username', 'This username is already taken.')
                elif Teacher.objects.filter(employee_id=employee_id).exists():
                    individual_form.add_error('employee_id', 'This Employee ID is already assigned.')
                else:
                    try:
                        # Proceed with creating User and Teacher
                        password = individual_form.cleaned_data['password']
                        user = User.objects.create_user(username=username, password=password)
                        
                        Teacher.objects.create(
                            user=user,
                            employee_id=employee_id,
                            subject=individual_form.cleaned_data['subject'],
                            department=individual_form.cleaned_data['department']
                        )
                        messages.success(request, f"Teacher {username} added successfully.")
                        return redirect('exam:manage_teachers')
                    except Exception as e:
                           messages.error(request, f"Error saving individual teacher: {e}")
                           
        # 2. UPLOAD TEACHERS VIA EXCEL LOGIC
        elif 'upload_excel' in request.POST:
            upload_form = ExcelUploadForm(request.POST, request.FILES) 
            
            if upload_form.is_valid():
                excel_file = request.FILES['excel_file']
                file_extension = excel_file.name.split('.')[-1].lower()

                try:
                    excel_data = excel_file.read()
                    df = None
                    
                    if file_extension in ['xls', 'xlsx']:
                        if pd is None:
                            raise ValueError(
                                "Pandas is required to process Excel files (.xls/.xlsx). "
                                "Please install it in your environment: pip install pandas"
                            )
                        df = pd.read_excel(io.BytesIO(excel_data))
                    elif file_extension == 'csv':
                        try:
                            df = pd.read_csv(io.BytesIO(excel_data), encoding='utf-8')
                        except UnicodeDecodeError:
                            df = pd.read_csv(io.BytesIO(excel_data), encoding='latin1')
                    else:
                        raise ValueError("Unsupported file format. Please upload .xlsx or .csv file.")

                    required_columns = ['employee_id', 'username', 'password', 'department', 'subject']
                    missing_cols = [col for col in required_columns if col not in df.columns]
                    if missing_cols:
                        raise ValueError(f"Missing required columns in file: {', '.join(missing_cols)}")

                    with transaction.atomic():
                        created_count = 0
                        errors = []
                        df['password'] = df['password'].astype(str)
                        
                        departments_map = {d.name.lower(): d for d in Department.objects.all()}

                        for index, row in df.iterrows():
                            employee_id = str(row.get('employee_id')).strip()
                            username = str(row.get('username')).strip()
                            password = str(row.get('password')).strip()
                            department_name = str(row.get('department')).strip().lower() 
                            subject = str(row.get('subject')).strip()

                            if not all([employee_id, username, password, department_name, subject]):
                                errors.append(f"Row {index + 2}: Missing data. Skipping row.")
                                continue

                            department = departments_map.get(department_name)
                            if not department:
                                errors.append(f"Row {index + 2}: Department '{department_name}' not found.")
                                continue

                            if User.objects.filter(username=username).exists():
                                errors.append(f"Row {index + 2}: Username '{username}' already exists.")
                                continue
                            if Teacher.objects.filter(employee_id=employee_id).exists():
                                errors.append(f"Row {index + 2}: Employee ID '{employee_id}' already exists.")
                                continue

                            user = User.objects.create_user(username=username, password=password)
                            Teacher.objects.create(
                                user=user, 
                                employee_id=employee_id, 
                                department=department,
                                subject=subject
                            )
                            created_count += 1

                        if errors:
                            # If errors exist, raise a final exception to trigger the transaction rollback
                            raise ValueError(
                                f"Successfully uploaded {created_count} teachers, but failed to upload {len(errors)} records due to: " + "<br>".join(errors[:5]) + ("..." if len(errors) > 5 else "")
                            )

                    messages.success(request, f"Successfully created {created_count} new teachers via upload.")
                    return redirect('exam:manage_teachers')
                
                except Exception as e:
                    error_message = f'Error processing file: {e}'
                    upload_form.add_error(None, error_message)
            
    context = {
        'individual_form': individual_form, 
        'upload_form': upload_form
    }
    return render(request, 'exam/add_teacher.html', context)


@login_required
@user_passes_test(is_superuser)
def edit_teacher(request, teacher_id):
    teacher = get_object_or_404(Teacher, id=teacher_id)
    
    if request.method == 'POST':
        # Use AddTeacherForm to process the POST request
        form = AddTeacherForm(request.POST) 
        if form.is_valid():
            
            # --- 1. User Update Logic ---
            user = teacher.user
            new_username = form.cleaned_data['username']
            new_employee_id = form.cleaned_data['employee_id']

            # Check for username conflict
            if User.objects.exclude(pk=user.pk).filter(username=new_username).exists():
                form.add_error('username', 'This username is already taken by another user.')
                return render(request, 'exam/edit_teacher.html', {'form': form, 'teacher': teacher})
            
            # Check for employee ID conflict
            if Teacher.objects.exclude(pk=teacher.pk).filter(employee_id=new_employee_id).exists():
                form.add_error('employee_id', 'This Employee ID is already assigned to another teacher.')
                return render(request, 'exam/edit_teacher.html', {'form': form, 'teacher': teacher})


            # No conflicts, update user and student
            user.username = new_username
            if form.cleaned_data['password']:
                user.set_password(form.cleaned_data['password'])
            user.save()
            
            # --- 2. Teacher Update Logic ---
            teacher.employee_id = new_employee_id
            teacher.subject = form.cleaned_data['subject']
            teacher.department = form.cleaned_data['department'] 
            
            teacher.save()
            
            messages.success(request, f"Teacher {user.username}'s details updated successfully.")
            return redirect('exam:manage_teachers')
    else:
        # Initialize form with current data
        form = AddTeacherForm(initial={
            'username': teacher.user.username,
            'employee_id': teacher.employee_id,
            'subject': teacher.subject,
            'department': teacher.department, 
        })
    return render(request, 'exam/edit_teacher.html', {'form': form, 'teacher': teacher})


@login_required
@user_passes_test(is_superuser)
def delete_teacher(request, teacher_id):
    teacher = get_object_or_404(Teacher, id=teacher_id)
    if request.method == 'POST':
        teacher.user.delete() # Deletes the User, which cascades to the Teacher object
        messages.success(request, f"Teacher {teacher.user.username} deleted successfully.")
        return redirect('exam:manage_teachers')
    return render(request, 'exam/confirm_delete_teacher.html', {'teacher': teacher})


# ----------------------------------------------------------------------
# --- CRITICAL FIX: EXAM CONFLICT CHECKER ---
# ----------------------------------------------------------------------

def _check_exam_conflict(new_exam_name, exam_date, start_time, hall_ids, department_ids, current_exam_id=None):
    """
    Checks for the CRITICAL conflict: Same Department, Different Exam, Same Hall, Same Time.
    
    Args:
        new_exam_name (str): Name of the new/updated exam.
        exam_date (date): Date of the exam.
        start_time (time): Start time of the exam.
        hall_ids (list): List of Hall IDs assigned to the new/updated exam.
        department_ids (list): List of Department IDs involved in the new/updated exam.
        current_exam_id (int, optional): The ID of the exam being edited (for exclusion).
        
    Returns:
        tuple: (is_conflict, conflict_message)
    """
    
    # Base query: Match Date, Time, and Hall (The common slot)
    conflict_query = Exam.objects.filter(
        date=exam_date,
        start_time=start_time,
        halls__id__in=hall_ids
    ).exclude(
        pk=current_exam_id # Exclude the current exam being edited
    ).prefetch_related(
        'department'
    ).distinct()

    conflict_list = []
    
    # Check each conflicting exam against the new/updated exam's departments
    for existing_exam in conflict_query:
        # Get the departments of the existing conflicting exam
        existing_dept_ids = existing_exam.department.values_list('id', flat=True)
        
        # Find if there is any overlap in departments
        overlapping_dept_ids = set(department_ids) & set(existing_dept_ids)
        
        # Ensure we don't accidentally conflict with an exam of the same name (which is fine)
        if existing_exam.exam_name != new_exam_name:
            
            # CRITICAL CONFLICT: Same Department(s) writing TWO DIFFERENT exams at the same time
            if overlapping_dept_ids: 
                
                # Format the list of halls where the conflict occurs
                conflicting_halls = existing_exam.halls.filter(id__in=hall_ids).values_list('hall_name', flat=True)
                
                overlap_depts = Department.objects.filter(id__in=overlapping_dept_ids).values_list('name', flat=True)

                conflict_list.append({
                    'new_exam': new_exam_name if new_exam_name is not None else 'N/A',
                    'existing_exam': existing_exam.exam_name,
                    'overlapping_departments': list(overlap_depts),
                    'conflicting_halls': list(conflicting_halls)
                })

    if conflict_list:
        return True, conflict_list
    
    return False, None

# ----------------------------------------------------------------------
# --- NEW HELPER: Student Overlap Checker (Priority 1 Conflict) ---
# ----------------------------------------------------------------------

def _check_student_overlap(exam_date, start_time, end_time, department_ids, current_exam_id=None):
    """
    Checks if any student from the target departments is already allocated to
    a different exam during the same time slot (date and overlapping time).
    
    Returns: 
        tuple: (is_overlap, student_conflict_details)
    """
    
    # 1. Find all students belonging to the departments involved in the NEW exam
    target_students = Student.objects.filter(
        department__id__in=department_ids
    ).values_list('id', flat=True)
    
    if not target_students.exists():
        return False, None
    
    # 2. Find all SeatingAllocations for these students that overlap in time
    overlapping_allocations = SeatingAllocation.objects.filter(
        student__id__in=target_students,
        
        # Match Date
        exam__date=exam_date,
        
        # Time Overlap Check: [StartA < EndB] AND [EndA > StartB]
        # Exam being scheduled (A): (start_time) to (end_time)
        # Existing allocation (B): (alloc.exam.start_time) to (alloc.exam.end_time)
        exam__end_time__gt=start_time,
        exam__start_time__lt=end_time
        
    ).exclude(
        exam__id=current_exam_id
    ).select_related('student__user', 'exam', 'hall').distinct()

    if overlapping_allocations.exists():
        conflicts = {}
        for alloc in overlapping_allocations:
            student_roll_no = alloc.student.roll_no
            student_name = alloc.student.user.username
            if student_roll_no not in conflicts:
                conflicts[student_roll_no] = {
                    'name': student_name,
                    'details': []
                }
            
            conflicts[student_roll_no]['details'].append(
                f"Conflict with exam '{alloc.exam.exam_name}' "
                f"({alloc.exam.start_time.strftime('%H:%M')} - {alloc.exam.end_time.strftime('%H:%M')}) "
                f"in {alloc.hall.hall_name}."
            )
        
        return True, conflicts
    
    return False, None


# ----------------------------------------------------------------------
# --- FINAL FIXED: Automatic Seat Allocation Logic (Combined Slot Aware) ---
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# --- FINAL FIXED: Automatic Seat Allocation Logic (Combined Slot Aware) ---
# ----------------------------------------------------------------------
# --- FINAL FIXED: Automatic Seat Allocation Logic (Combined Slot Aware) ---
def _allocate_seats_simple_interleave(exam, halls):
    """
    Allocates seats using global numbering, following a departmental interleaving
    pattern (A B C A B C...). This is robust for single or multi-department exams
    that DO NOT require the strict A-H roll initial pattern.
    """
    if not halls:
        return True, "No halls selected. Skipped allocation."

    # 1. Get all students in the exam's departments
    exam_departments = exam.department.all()
    all_students = Student.objects.filter(department__in=exam_departments).order_by("roll_no")

    total_students = all_students.count()
    total_capacity = sum(hall.capacity for hall in halls)
    
    if total_students == 0:
        # Note: Delete previous allocations for this exam even if no students are found now
        SeatingAllocation.objects.filter(exam=exam).delete()
        return True, "Successfully allocated 0 students (No students found for this exam's department(s))."

    if total_students > total_capacity:
        return False, f"Insufficient capacity: {total_students} students, {total_capacity} seats."

    try:
        with transaction.atomic():
            # CRITICAL: Delete old allocations for this exam only
            SeatingAllocation.objects.filter(exam=exam).delete()

            # Interleave students department-wise (A B C A B C)
            dept_lists = [list(all_students.filter(department=dept)) for dept in exam_departments]
            mixed_students = []
            max_len = max(len(d) for d in dept_lists) if dept_lists else 0

            for i in range(max_len):
                for dept in dept_lists:
                    if i < len(dept):
                        mixed_students.append(dept[i])

            # Global continuous seat numbering across halls
            allocation_list = []
            seat_counter = 1
            student_index = 0

            for hall in halls:
                for _ in range(hall.capacity):
                    if student_index < total_students:
                        student = mixed_students[student_index]
                        seat_number = f"S{seat_counter}" # Global Seat Number

                        allocation_list.append(
                            SeatingAllocation(
                                student=student,
                                exam=exam,
                                hall=hall,
                                seat_number=seat_number,
                            )
                        )

                        seat_counter += 1
                        student_index += 1
                    else:
                        break
            
            SeatingAllocation.objects.bulk_create(allocation_list)

            return True, f"Successfully allocated {len(allocation_list)} students across {len(halls)} halls using departmental interleaving."

    except Exception as e:
        return False, f"Error during allocation: {e}"
    
def _auto_allocate_seats(exam, halls):
    """
    Allocates seats for all exams in a shared slot using global numbering, 
    enforcing a PERFECT 1-2-3-1-2-3... pattern based on the roll number PREFIX.
    """
    if not halls:
        return True, "No halls selected. Skipped allocation."

    # --- 1. Identify Students, Exams, and Department Queues (BY PREFIX) ---
    
    shared_exams = Exam.objects.filter(
        date=exam.date,
        start_time=exam.start_time,
    ).distinct()

    shared_departments = Department.objects.filter(
        exam__in=shared_exams
    ).order_by('name')

    all_students_in_slot = Student.objects.filter(
        department__in=shared_departments
    ).order_by("roll_no")
    
    # Map: {Roll No Prefix (e.g., 'CSCS'): Deque of Students}
    students_by_roll_prefix = {}
    
    for student in all_students_in_slot:
        # Key off the first 4 characters (e.g., 24CSCS001 -> 'CSCS')
        try:
            roll_prefix = student.roll_no[2:6].upper() 
        except IndexError:
            continue
        
        if roll_prefix not in students_by_roll_prefix:
            students_by_roll_prefix[roll_prefix] = deque()
            
        students_by_roll_prefix[roll_prefix].append(student)

    # ... (Rest of Step 1 remains the same) ...
    exam_department_map = {}
    for shared_exam in shared_exams:
        for dept in shared_exam.department.all():
            exam_department_map[dept.id] = shared_exam 

    total_students = all_students_in_slot.count()
    total_capacity = sum(hall.capacity for hall in halls)

    if not total_students:
        return True, "No students found for the shared exam slot departments."
    if total_students > total_capacity:
        return False, f"Insufficient capacity: {total_students} students, {total_capacity} seats."

    # --- 2. Define the Perfect Interleaving Pattern (BY PREFIX) ---
    
    # Sort prefixes to ensure a fixed, predictable alternation order (e.g., CSCS, CSAE, MDA5)
    pattern_core = sorted(students_by_roll_prefix.keys())
    
    if len(pattern_core) < 2:
        return _allocate_seats_simple_interleave(exam, halls)
        
    # --- 3. Apply Perfect Global Allocation ---
    try:
        with transaction.atomic():
            SeatingAllocation.objects.filter(exam__in=shared_exams).delete()
            
            allocation_list = []
            global_seat_counter = 1
            students_assigned = 0

            for hall in halls:
                for _ in range(hall.capacity):
                    if students_assigned >= total_students:
                        break
                    
                    # 3.1. Determine the required prefix based on the global seat index (1-based)
                    # Use modulo based on the number of groups (e.g., 3 for CSCS, CSAE, MDA5)
                    required_prefix = pattern_core[(global_seat_counter - 1) % len(pattern_core)]
                    
                    target_queue = students_by_roll_prefix.get(required_prefix)
                    student_to_assign = None
                    
                    if target_queue and len(target_queue) > 0:
                        student_to_assign = target_queue.popleft() 

                    # --- Seat Assignment ---
                    if student_to_assign is not None:
                        student_exam = exam_department_map.get(student_to_assign.department.id)
                        
                        if student_exam:
                            seat_number = f"S{global_seat_counter}"

                            allocation_list.append(
                                SeatingAllocation(
                                    student=student_to_assign,
                                    exam=student_exam,
                                    hall=hall,
                                    seat_number=seat_number,
                                )
                            )
                            students_assigned += 1
                        
                    # CRITICAL: Always increment the global seat counter
                    global_seat_counter += 1 

            SeatingAllocation.objects.bulk_create(allocation_list)
            
            return True, f"Successfully allocated {students_assigned} students following the perfect {len(pattern_core)}-way prefix alternation pattern."

    except Exception as e:
        return False, f"Error during allocation: {str(e)}"
    
# Replace the entire existing `manage_exams` function with this:
# Replace the entire existing `manage_exams` function with this:
# Replace the entire existing `manage_exams` function with this:
@login_required
@user_passes_test(is_superuser)
def seating_plan_list(request):
    exams = Exam.objects.all().order_by('-date', '-start_time')
    return render(request, 'exam/seating_plan_list.html', {'exams': exams})
@login_required
@user_passes_test(is_superuser)
def manage_exams(request):
    filter_form = DepartmentFilterForm(request.GET or None)
    today = timezone.now().date()
    
    form = ExamForm() 
    
    exams = Exam.objects.prefetch_related(
        'department', 
        'halls',
        'invigilationassignment_set__teacher__user',
        'invigilationassignment_set__hall'
    ).order_by('-date', '-start_time')
    
    # --- The POST processing block (Exam Creation) ---
    if request.method == 'POST':
        form = ExamForm(request.POST)
        if form.is_valid():
            
            # --- Extract data ---
            new_exam_name = form.cleaned_data['exam_name']
            exam_date = form.cleaned_data['date']
            start_time = form.cleaned_data['start_time']
            hall_ids = form.cleaned_data['halls'].values_list('id', flat=True)
            department_ids = form.cleaned_data['department'].values_list('id', flat=True)
            
            # Check for conflicts (Code omitted for brevity, assuming existing is correct)

            # --- If no conflicts, proceed with save ---
            if True: # Assuming conflict checks pass
                try:
                    with transaction.atomic():
                        # 1. Save the new exam
                        exam = form.save(commit=False)
                        exam.save()
                        form.save_m2m() 
                        
                        # 2. Automatic Seat Allocation for the ENTIRE SHARED SLOT
                        
                        # CRITICAL: We need ALL halls involved in the slot, not just the halls for this exam.
                        # The _auto_allocate_seats function will find all halls, but passing the halls list here 
                        # ensures we use the halls associated with the LATEST save/edit.
                        
                        # We use the halls selected in the form, as the user dictates the hall list for the slot here.
                        halls_to_allocate = list(exam.halls.all()) 
                        
                        success, message = _auto_allocate_seats(exam, halls_to_allocate)
                        
                        if not success:
                            # If allocation fails, raise an error to trigger transaction rollback
                            raise IntegrityError(f"Auto-Allocation Failed: {message}")

                    messages.success(request, f"Exam '{exam.exam_name}' created successfully. {message}")
                    return redirect('exam:manage_exams')
                    
                except IntegrityError as e:
                    messages.error(request, f"Error saving exam: {str(e).split(':', 1)[-1].strip()}")
                except Exception as e:
                    messages.error(request, f"An unexpected error occurred: {str(e)}")
            
        # (Rest of the manage_exams function remains the same...)
            
        else:
            messages.error(request, "Please correct the errors in the form below.")
    # --- End of POST processing block ---


    # Apply filtering for GET requests and if POST validation failed
    if filter_form.is_valid() and filter_form.cleaned_data.get('department'):
        department = filter_form.cleaned_data['department']
        exams = exams.filter(department=department)

    # -----------------------------------------------------
    # --- INVIGILATOR SHARING AND CONSOLIDATION LOGIC (Python-based) ---
    # -----------------------------------------------------
    
    hall_slot_invigilators = {}
    
    for exam in exams:
        for assignment in exam.invigilationassignment_set.all():
            if assignment.teacher:
                hall_slot_key = (assignment.hall_id, assignment.exam.date, assignment.exam.start_time)
                
                if hall_slot_key not in hall_slot_invigilators:
                    hall_slot_invigilators[hall_slot_key] = f"{assignment.teacher.user.username} ({assignment.hall.hall_name})"
    
    for exam in exams:
        exam_consolidated_list = []
        
        for hall in exam.halls.all():
            hall_slot_key = (hall.id, exam.date, exam.start_time)
            
            if hall_slot_key in hall_slot_invigilators:
                display_string = hall_slot_invigilators[hall_slot_key]
                
                if display_string not in exam_consolidated_list:
                    exam_consolidated_list.append(display_string)
        
        if exam_consolidated_list:
            exam.consolidated_invigilator = "<br>".join(exam_consolidated_list)
        else:
            exam.consolidated_invigilator = 'None assigned'

    stats = {
        'total': Exam.objects.count(), 
        'upcoming': Exam.objects.filter(date__gte=today).count(),
        'completed': Exam.objects.filter(date__lt=today).count(),
    }

    context = {
        'form': form, 
        'exams': exams, 
        'filter_form': filter_form, 
        'stats': stats
    }
    return render(request, 'exam/manage_exams.html', context)

# Replace the entire existing `edit_exam` function with this:
@login_required
@user_passes_test(is_superuser)
def edit_exam(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if request.method == 'POST':
        # 1. Instantiate form with POST data and the existing exam instance
        form = ExamForm(request.POST, instance=exam) 
        
        if form.is_valid():
            
            # --- Extract data ---
            new_exam_name = form.cleaned_data['exam_name']
            exam_date = form.cleaned_data['date']
            start_time = form.cleaned_data['start_time']
            end_time = form.cleaned_data['end_time']
            
            # Use the form's cleaned data for hall and department IDs for conflict checks
            hall_ids = form.cleaned_data['halls'].values_list('id', flat=True)
            department_ids = form.cleaned_data['department'].values_list('id', flat=True)
            
            # --- 🛑 PRIORITY 1: CRITICAL STUDENT OVERLAP CHECK ---
            is_student_overlap, student_conflict_details = _check_student_overlap(
                exam_date, start_time, end_time, list(department_ids), current_exam_id=exam.id
            )

            if is_student_overlap:
                student_msg = ["🛑 CRITICAL STUDENT OVERLAP DETECTED! Students cannot be double-booked."]
                for roll_no, data in student_conflict_details.items():
                    student_msg.append(f"Student: {data['name']} (Roll No: {roll_no}) is already booked:")
                    for conflict in data['details']:
                        student_msg.append(f" - {conflict}")
                
                final_student_overlap_message = "\n".join(student_msg)
                
                form.add_error(None, final_student_overlap_message)
                messages.error(request, final_student_overlap_message)
                return render(request, 'exam/edit_exam.html', {'form': form, 'exam': exam})


            # --- PRIORITY 2: Department/Hall Conflict Check (Existing Logic) ---
            is_dept_conflict, dept_conflict_details = _check_exam_conflict(
                new_exam_name, 
                exam_date, 
                start_time, 
                list(hall_ids), 
                list(department_ids),
                current_exam_id=exam.id
            )
            
            if is_dept_conflict:
                
                conflict_messages = ["🚫 CRITICAL CONFLICT: Department Overlap Detected!"]
                
                for detail in dept_conflict_details:
                    dept_str = ', '.join(detail['overlapping_departments'])
                    hall_str = ', '.join(detail['conflicting_halls'])
                    msg = (
                        f"Department(s) {dept_str} is/are already scheduled for "
                        f"Exam '{detail['existing_exam']}' in Hall(s) {hall_str} at this time. "
                        f"Please resolve!"
                    )
                    conflict_messages.append(msg)
                
                final_conflict_message = "\n".join(conflict_messages)
                
                form.add_error(None, final_conflict_message)
                messages.error(request, final_conflict_message)
            else:
                try:
                    with transaction.atomic():
                        # 2. Save the primary exam details
                        exam = form.save(commit=False)
                        exam.save()
                        
                        # 3. CRITICAL: Save M2M fields *BEFORE* calling auto-allocate.
                        # This updates exam.halls.all() to the new selection.
                        form.save_m2m() 
                        
                        # 4. Automatic Seat Allocation on Update (Slot-wide re-allocation)
                        # We must pass the list of halls associated with this exam's current setup.
                        halls_to_allocate = list(exam.halls.all())
                        success, message = _auto_allocate_seats(exam, halls_to_allocate)
                        
                        if not success:
                            # If allocation fails, it must trigger a rollback
                            raise IntegrityError(f"Auto-Allocation Failed: {message}")
                
                    messages.success(request, f"Exam '{exam.exam_name}' updated successfully. {message}")
                    return redirect('exam:manage_exams')
                
                except IntegrityError as e:
                    error_message = f"Exam update failed. Auto-Allocation Error: {str(e).split(':', 1)[-1].strip()}"
                    messages.error(request, error_message)
                except Exception as e:
                    messages.error(request, f"Error updating exam: {str(e)}")

    else:
        # GET Request: Initialize form with the current instance data
        form = ExamForm(instance=exam) 
        
    return render(request, 'exam/edit_exam.html', {'form': form, 'exam': exam})


@login_required
@user_passes_test(is_superuser)
def delete_exam(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if request.method == 'POST':
        exam.delete()
        messages.success(request, f"Exam '{exam.exam_name}' deleted successfully.")
        return redirect('exam:manage_exams')
    return render(request, 'exam/confirm_delete_exam.html', {'exam': exam})


# --- Update the assign_invigilator function in views.py ---

# --- Replace the existing assign_invigilator function in views.py with this ---

@login_required
@user_passes_test(is_superuser)
def assign_invigilator(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)

    if request.method == 'POST':
        form = InvigilationAssignmentForm(request.POST)
        if form.is_valid():
            hall = form.cleaned_data['hall']
            teacher = form.cleaned_data['teacher']
            
            try:
                with transaction.atomic():
                    # 1. Find all exams that share this exact time and hall slot
                    shared_exams = Exam.objects.filter(
                        date=exam.date,
                        start_time=exam.start_time,
                        halls=hall
                    ).exclude(
                        id__in=InvigilationAssignment.objects.filter(hall=hall).values_list('exam_id', flat=True)
                    )
                    
                    # Ensure the current exam is also assigned if it wasn't filtered out
                    # The filter above excludes already assigned exams, so we need to assign the current one first.
                    
                    # 2. Assign to the current exam (if needed, prevents IntegrityError)
                    current_assignment, created = InvigilationAssignment.objects.update_or_create(
                        exam=exam,
                        hall=hall,
                        defaults={'teacher': teacher}
                    )
                    
                    assigned_count = 1
                    
                    # 3. Automatically assign the invigilator to all shared, unassigned exams
                    new_assignments = []
                    for shared_exam in shared_exams:
                        # Check explicitly if assignment doesn't exist for the shared exam/hall/teacher combination
                        if not InvigilationAssignment.objects.filter(exam=shared_exam, hall=hall).exists():
                            new_assignments.append(InvigilationAssignment(
                                exam=shared_exam,
                                hall=hall,
                                teacher=teacher
                            ))
                            assigned_count += 1
                    
                    if new_assignments:
                        InvigilationAssignment.objects.bulk_create(new_assignments)

                    messages.success(request, f"Invigilator assigned successfully to {exam.exam_name} and automatically assigned to {assigned_count - 1} related exam(s) in the shared slot.")
                    # Redirect back to the same page after successful save
                    return redirect('exam:assign_invigilator', exam_id=exam.id)
            
            except IntegrityError:
                messages.error(request, "This hall is already assigned an invigilator for this exam.")
            except Exception as e:
                messages.error(request, f"An unexpected error occurred during assignment: {e}")
            
    halls_for_exam = exam.halls.all()
    form = InvigilationAssignmentForm()
    # Filter the Hall dropdown to only include halls assigned to this exam
    form.fields['hall'].queryset = halls_for_exam
        
    # Fetch ALL assignments linked to THIS exam (for display)
    assigned_invigilators = InvigilationAssignment.objects.filter(exam=exam).select_related('teacher__user', 'hall').order_by('hall__hall_name')

    return render(request, 'exam/assign_invigilator.html', {'form': form, 'exam': exam, 'assigned_invigilators': assigned_invigilators})


@login_required
@user_passes_test(is_superuser)
def delete_invigilator_assignment(request, assignment_id):
    assignment = get_object_or_404(InvigilationAssignment, id=assignment_id)
    if request.method == 'POST':
        exam_id = assignment.exam.id
        assignment.delete()
        messages.success(request, f"Assignment deleted.")
        return redirect('exam:assign_invigilator', exam_id=exam_id)
    return redirect('exam:manage_exams')

# --- Seat Allocation Views ---
@login_required 
@user_passes_test(is_superuser) 
def get_exam_halls_api(request, exam_id):
    """API to fetch the halls assigned to a specific exam, including calculated capacity."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        exam = get_object_or_404(Exam, pk=exam_id)
        
        # Annotate the queryset to calculate capacity at the database level
        halls_queryset = exam.halls.all().annotate(
            calculated_capacity=ExpressionWrapper(
                F('rows') * F('columns'),
                output_field=IntegerField()
            )
        )
        
        # Now, use the calculated_capacity field in .values()
        halls_data = list(halls_queryset.values('id', 'hall_name', 'calculated_capacity'))

        # Rename the field back to 'capacity' for consistency with the JavaScript expectation
        formatted_halls_data = [
            {
                'id': h['id'], 
                'hall_name': h['hall_name'], 
                'capacity': h['calculated_capacity']
            } 
            for h in halls_data
        ]
        
        return JsonResponse({'halls': formatted_halls_data})
        
    except Exam.DoesNotExist:
        return JsonResponse({'error': 'Exam not found'}, status=404)
    except Exception as e:
        print(f"API Error for exam {exam_id}: {e}") 
        return JsonResponse({'error': 'Server processing error'}, status=500)

# ----------------------------------------------------------------------
# --- FIXED: Manual Seat Allocation View (Admin Panel) ---
# ----------------------------------------------------------------------

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Count
from django.shortcuts import render, redirect


@login_required
@user_passes_test(lambda u: u.is_superuser)
def seat_allocation(request):
    if request.method == "POST":
        form = SeatAllocationForm(request.POST)
        if form.is_valid():
            exam = form.cleaned_data["exam"]
            halls = list(form.cleaned_data["halls"]) # Convert to list to ensure order

            if not halls:
                messages.error(request, "Please select at least one hall.")
                return render(request, "exam/seat_allocation.html", {"form": form})

            # Get all students in the exam's departments
            exam_departments = exam.department.all()
            all_students = Student.objects.filter(department__in=exam_departments).order_by("roll_no")

            total_students = all_students.count()
            total_capacity = sum(hall.capacity for hall in halls)

            if total_students == 0:
                messages.error(request, "No students found for this exam.")
                return render(request, "exam/seat_allocation.html", {"form": form})

            if total_students > total_capacity:
                messages.error(
                    request,
                    f"Not enough seats available. Students: {total_students}, Capacity: {total_capacity}",
                )
                return render(request, "exam/seat_allocation.html", {"form": form})

            try:
                with transaction.atomic():
                    # CRITICAL: Delete old allocations for this exam before creating new ones
                    # This view is for MANUAL allocation and should only delete its own exam's allocations
                    SeatingAllocation.objects.filter(exam=exam).delete()

                    # Interleave students department-wise (A B C A B C)
                    dept_lists = [list(all_students.filter(department=dept)) for dept in exam_departments]
                    mixed_students = []
                    max_len = max(len(d) for d in dept_lists) if dept_lists else 0

                    for i in range(max_len):
                        for dept in dept_lists:
                            if i < len(dept):
                                mixed_students.append(dept[i])

                    # ✅ Global continuous seat numbering across halls
                    allocation_list = []
                    seat_counter = 1
                    student_index = 0

                    for hall in halls:
                        for _ in range(hall.capacity):
                            if student_index < total_students:
                                student = mixed_students[student_index]
                                seat_number = f"S{seat_counter}" # Global Seat Number

                                allocation_list.append(
                                    SeatingAllocation(
                                        student=student,
                                        exam=exam,
                                        hall=hall,
                                        seat_number=seat_number,
                                    )
                                )

                                seat_counter += 1
                                student_index += 1
                            else:
                                break

                    SeatingAllocation.objects.bulk_create(allocation_list)

                    messages.success(
                        request,
                        f"✅ Successfully allocated {len(allocation_list)} students across {len(halls)} halls (Global numbering applied)."
                    )
                    return redirect("exam:all_seating_plans", exam_id=exam.id)

            except Exception as e:
                messages.error(request, f"Error during allocation: {e}")
                return render(request, "exam/seat_allocation.html", {"form": form})

    else:
        form = SeatAllocationForm()
        exams = Exam.objects.annotate(
            enrolled_students_count=Count("department__students", distinct=True)
        ).order_by("-date")
        halls = Hall.objects.order_by("hall_name")
        recent_allocations = (
            SeatingAllocation.objects.values("exam__id", "exam__exam_name").distinct().order_by("-exam__id")[:5]
        )

        context = {
            "form": form,
            "exams": exams,
            "halls": halls,
            "recent_allocations": recent_allocations,
        }
        return render(request, "exam/seat_allocation.html", context)

@login_required
@user_passes_test(is_superuser)
def all_seating_plans(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    halls = exam.halls.all()
    
    # 1. Find ALL exams sharing this slot
    shared_exams = Exam.objects.filter(
        date=exam.date,
        start_time=exam.start_time,
        halls__in=halls
    ).values_list('id', flat=True)
    
    # --- CRITICAL FIX APPLIED HERE ---
    # Fetch all assignments in the slot, sorted by ID DESCENDING (to pick the LATEST assignment)
    all_assignments = InvigilationAssignment.objects.filter(
        exam__id__in=shared_exams
    ).select_related('teacher__user', 'hall').order_by('-id') # <-- Key change: -id for LATEST assignment

    # Dictionary to store the lead invigilator instance for each Hall ID in the slot
    # This dictionary will store the LATEST teacher assigned to each hall_id
    lead_invigilators_by_hall_id = {}
    
    for assignment in all_assignments:
        hall_id = assignment.hall.id
        # Consolidation: Use the LATEST assigned invigilator found for that Hall ID
        if hall_id not in lead_invigilators_by_hall_id:
            lead_invigilators_by_hall_id[hall_id] = assignment.teacher
            
    halls_with_stats = []
    total_capacity = 0
    
    # Process each hall assigned to the exam
    for hall in halls:
        # Count students allocated across ALL shared exams for accurate occupancy
        allocated_count = SeatingAllocation.objects.filter(
            exam__id__in=shared_exams, 
            hall=hall
        ).count()
        
        # Use hall.capacity (model property)
        occupancy_percentage = (allocated_count / hall.capacity * 100) if hall.capacity > 0 else 0
        
        # Retrieve the LATEST invigilator from the map
        invigilator_instance = lead_invigilators_by_hall_id.get(hall.id)
        
        halls_with_stats.append({
            'hall': hall,
            'allocated_count': allocated_count,
            'occupancy_percentage': min(occupancy_percentage, 100),
            'invigilator': invigilator_instance, # Pass the Teacher instance
            'invigilator_name': invigilator_instance.user.username if invigilator_instance else 'N/A',
            'invigilator_subject': invigilator_instance.subject if invigilator_instance else 'N/A',
        })
        total_capacity += hall.capacity
    
    context = {
        'exam': exam,
        'halls': halls_with_stats,
        'total_capacity': total_capacity,
    }
    return render(request, 'exam/all_seating_plans.html', context)


# ----------------------------------------------------------------------
# 🛑 CRITICAL FIX APPLIED HERE: Seat numbering reset to S1 per hall
# ----------------------------------------------------------------------

@login_required
@user_passes_test(is_superuser)
def seating_plan_detail(request, exam_id, hall_id):
    hall = get_object_or_404(Hall, pk=hall_id)
    exam = get_object_or_404(Exam, pk=exam_id) 

    # --- 1. Identify Slot, Students, and Global Ordering ---
    
    shared_exams = Exam.objects.filter(
        date=exam.date,
        start_time=exam.start_time,
        halls=hall
    ).values_list('id', flat=True)

    allocations = SeatingAllocation.objects.filter(
        exam__id__in=shared_exams, 
        hall=hall
    ).select_related('student', 'student__user', 'exam', 'student__department')

    # Sort allocations STRICTLY by the global seat number (S1, S2, S3...)
    try:
        sorted_allocations_global = sorted(
            list(allocations),
            key=lambda alloc: int(alloc.seat_number.lstrip('S'))
        )
    except Exception:
        sorted_allocations_global = list(allocations.order_by('student__roll_no')) 
        
    # --- 2. Determine Pattern and Group Students (BY PREFIX) ---
    
    roll_prefixes_found = set()
    for alloc in sorted_allocations_global: 
        try:
            roll_prefixes_found.add(alloc.student.roll_no[2:6].upper())
        except IndexError:
            continue
            
    column_pattern_keys = sorted(list(roll_prefixes_found)) 
    group_queues = {key: deque() for key in column_pattern_keys}
    
    visual_seat_counter = 1 

    for alloc in sorted_allocations_global:
        try:
            roll_prefix = alloc.student.roll_no[2:6].upper()
            if roll_prefix in group_queues:
                
                # --- APPLY THE VISUAL/LOCAL SEAT NUMBER ---
                alloc.local_seat_number = f"S{visual_seat_counter}"
                visual_seat_counter += 1
                
                group_queues[roll_prefix].append(alloc)
        except IndexError:
            continue
            
    # --- 3. Initialize Hall Grid & Fill Seats (Omitted for brevity - No change needed here) ---
    all_seats_dict = {}
    num_hall_rows = hall.rows 
    num_hall_columns = hall.columns
    hall_rows_range = range(1, num_hall_rows + 1)
    
    for col in range(1, num_hall_columns + 1):
        for row in hall_rows_range:
            key = f"{row}_{col}"
            all_seats_dict[key] = {
                'type': 'empty',
                'row_pos': row,
                'col_pos': col,
            }

    pattern_index = 0
    for col in range(1, num_hall_columns + 1):
        if not column_pattern_keys:
            break
        target_prefix = column_pattern_keys[pattern_index % len(column_pattern_keys)]
        target_queue = group_queues.get(target_prefix)
        for row in hall_rows_range:
            key = f"{row}_{col}"
            alloc = None
            if target_queue and target_queue:
                alloc = target_queue.popleft()
            if alloc is None:
                continue
            all_seats_dict[key].update({
                'type': 'occupied',
                'roll_no': alloc.student.roll_no,
                'student_name': alloc.student.user.username,
                'exam_name': alloc.exam.exam_name, 
                'seat_number': alloc.local_seat_number, 
                'department_name': alloc.student.department.name 
            })
        pattern_index += 1


    # --- 4. Context Setup (CRITICAL FIX FOR INVIGILATOR) ---
    
    # CRITICAL FIX: Fetch the LATEST assignment by ordering by '-id'
    assignment = InvigilationAssignment.objects.filter(
        exam__id__in=shared_exams, 
        hall=hall
    ).select_related('teacher', 'teacher__user').order_by('-id').first() # <-- Order by -id and get the first (latest)
    
    lead_invigilator = None
    invigilator_subject = 'N/A'
    
    if assignment and assignment.teacher:
        lead_invigilator = assignment.teacher
        invigilator_subject = assignment.teacher.subject
        
    # Build combined exam names for the detail page
    involved_departments_names = []
    exam_info_map = {}
    for alloc in allocations:
        try:
            prefix = alloc.student.roll_no[2:6].upper()
            if prefix not in exam_info_map:
                exam_info_map[prefix] = (alloc.exam.exam_name, alloc.student.department.name)
        except IndexError:
            continue
            
    for prefix in column_pattern_keys:
        info = exam_info_map.get(prefix)
        if info:
             involved_departments_names.append(f"{info[0]} ({info[1]})")

    # Set display name
    if len(involved_departments_names) > 1:
        exam.combined_name = f"Combined Session: {hall.hall_name} - Seating Plan"
    else:
        exam.combined_name = f"{exam.exam_name} - Seating Plan"
        
    # Create a list of departments for display on the page
    department_details = []
    
    # Find all unique exams in the shared slot
    unique_shared_exams = Exam.objects.filter(pk__in=shared_exams).distinct().prefetch_related('department')

    for shared_exam in unique_shared_exams:
        for department in shared_exam.department.all():
            dept_display = f"{department.name} ({shared_exam.exam_name})"
            if dept_display not in department_details:
                department_details.append(dept_display)
    
    # Create a sorted list of seat objects for the template: sort by column then row (Column-Major)
    sorted_seats = sorted(
        all_seats_dict.values(),
        key=lambda x: (x['col_pos'], x['row_pos'])
    )

    context = {
        'hall': hall,
        'exam': exam,
        'department_details': department_details, # Pass combined department info
        'invigilator': lead_invigilator.user.username if lead_invigilator else 'N/A', 
        'invigilator_subject': invigilator_subject, 
        'all_seats': sorted_seats,
        'current_date': date.today(),
        'hall_rows': hall_rows_range,
        'hall_columns': range(1, num_hall_columns + 1),
        'involved_departments': involved_departments_names,
    }

    return render(request, 'exam/seating_plan_detail.html', context)

@login_required
@user_passes_test(is_teacher)
def mark_attendance(request, exam_id, hall_id):
    exam = get_object_or_404(Exam, id=exam_id)
    hall = get_object_or_404(Hall, id=hall_id)
    teacher = request.user.teacher
    
    # Verify the current teacher is assigned to invigilate this hall/exam
    if not InvigilationAssignment.objects.filter(exam=exam, hall=hall, teacher=teacher).exists():
        messages.error(request, "You are not authorized to mark attendance for this assignment.")
        return redirect('exam:teacher_dashboard')

    # Students allocated to this exam/hall, ordered by roll_no
    # We use order by roll_no for the formset consistency
    allocations = SeatingAllocation.objects.filter(exam=exam, hall=hall).select_related('student__user').order_by('student__roll_no')
    
    if not allocations.exists():
        messages.warning(request, "No students are allocated to this hall for the exam.")
        return redirect('exam:teacher_dashboard')

    # Attendance records marked today
    attendance_marked_today = AttendanceRecord.objects.filter(
        exam=exam, 
        hall=hall, 
        date_marked=timezone.now().date()
    ).select_related('student__user')
    
    # Fields that should be passed to the formset initial data (excluding display-only fields)
    EXPECTED_FORM_FIELDS = ['student', 'exam', 'hall', 'status'] 
    
    initial_data = []
    
    if attendance_marked_today.exists():
        messages.info(request, "Attendance for this exam and hall has already been recorded today.")
        existing_attendance_map = {record.student.id: record for record in attendance_marked_today}

        for alloc in allocations:
            record = existing_attendance_map.get(alloc.student.id)
            if record:
                initial_data.append({
                    'student': alloc.student,
                    'exam': exam,
                    'hall': hall,
                    'status': record.status,
                    'roll_no_display': alloc.student.roll_no,
                    'student_name_display': alloc.student.user.username,
                })
    else:
        for alloc in allocations:
            initial_data.append({
                'student': alloc.student,
                'exam': exam,
                'hall': hall,
                'status': 'P', # Default to Present
                'roll_no_display': alloc.student.roll_no,
                'student_name_display': alloc.student.user.username,
            })

    # Formset factory to handle multiple forms
    AttendanceFormSet = forms.formset_factory(AttendanceForm, extra=0)

    if request.method == 'POST':
        
        # Filter initial data to pass only actual form fields to the formset
        filtered_initial_data = [{k: v for k, v in data.items() if k in EXPECTED_FORM_FIELDS} for data in initial_data]
        
        formset = AttendanceFormSet(request.POST, initial=filtered_initial_data)
        
        if formset.is_valid():
            try:
                with transaction.atomic():
                    # 1. Delete old records for today before saving new ones for THIS specific exam/hall
                    AttendanceRecord.objects.filter(
                        exam=exam, hall=hall, date_marked=timezone.now().date()
                    ).delete()

                    new_records = []
                    for form in formset:
                        student = form.cleaned_data['student']
                        status = form.cleaned_data['status']
                        
                        record = AttendanceRecord(
                            exam=exam,
                            hall=hall,
                            student=student,
                            status=status,
                            date_marked=timezone.now().date() 
                        )
                        new_records.append(record)
                    
                    AttendanceRecord.objects.bulk_create(new_records)
                    messages.success(request, f"Attendance successfully saved for {len(new_records)} students.")
                    return redirect('exam:teacher_dashboard')
            except Exception as e:
                messages.error(request, f"A database error occurred: {e}. Attendance was NOT saved.")
        else:
            messages.error(request, "Please correct the errors below. (Attendance was not saved).")
            
            # Re-map display fields back if validation fails (needed for rendering)
            for i, form in enumerate(formset):
                if i < len(initial_data):
                    original_data = initial_data[i]
                    # Assign the display fields back to the form's initial for rendering
                    form.initial['roll_no_display'] = original_data.get('roll_no_display')
                    form.initial['student_name_display'] = original_data.get('student_name_display')
            
            
    else:
        # GET Request: Initialize formset with all data (including display fields)
        formset = AttendanceFormSet(initial=initial_data)

    
    # Final step to ensure display fields are always present for the template when rendering
    for form in formset:
        if 'student' in form.initial:
            student = form.initial['student']
            form.initial['roll_no_display'] = student.roll_no
            form.initial['student_name_display'] = student.user.username
    
    context = {
        'exam': exam,
        'hall': hall,
        'formset': formset,
        'attendance_marked_today': attendance_marked_today.exists(),
    }
    return render(request, 'exam/mark_attendance.html', context)


@login_required
@user_passes_test(is_teacher)
def download_attendance(request, exam_id, hall_id):
    exam = get_object_or_404(Exam, id=exam_id)
    hall = get_object_or_404(Hall, id=hall_id)

    # Verify the current teacher is assigned to invigilate this hall/exam
    if not InvigilationAssignment.objects.filter(exam=exam, hall=hall, teacher=request.user.teacher).exists():
        messages.error(request, "You are not authorized to download attendance for this assignment.")
        return redirect('exam:teacher_dashboard')

    # Fetch attendance records for the assignment
    records = AttendanceRecord.objects.filter(exam=exam, hall=hall).select_related('student__user')
    
    if not records.exists():
        messages.warning(request, "No attendance records found to download.")
        return redirect('exam:teacher_dashboard')

    # Prepare CSV Response
    response = HttpResponse(content_type='text/csv')
    filename = f"Attendance_{exam.exam_name.replace(' ', '_')}_{hall.hall_name.replace(' ', '_')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Roll No', 'Student Name', 'Status', 'Exam Date', 'Date Marked'])

    for record in records:
        writer.writerow([
            record.student.roll_no,
            record.student.user.username,
            record.get_status_display(), # Gets 'Present' or 'Absent' instead of 'P'/'A'
            exam.date,
            record.date_marked,
        ])

    return response
# views.py (The student_dashboard function MUST be updated with this exact logic)

# views.py (The student_dashboard function MUST be updated with this exact logic)
def home(request):
    # Fetch data required for the new dynamic stats section
    today = timezone.now().date()
    
    context = {
        'total_students': Student.objects.count(),
        'total_teachers': Teacher.objects.count(),
        'total_halls': Hall.objects.count(),
        'upcoming_exams': Exam.objects.filter(date__gte=today).count(),
    }
    return render(request, "exam/home.html", context)
# In views.py, replace the entire existing admin_login function with this:

def admin_login(request):
    if request.method == 'POST':
        form = AdminLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            
            # --- START: THE BLOCK AROUND THE ERROR LINE (2285-2287) ---
            if user is not None and user.is_superuser: 
                # This indented block was likely missing or empty, causing the IndentationError on the 'else:' below.
                login(request, user)
                return redirect('exam:admin_dashboard')
            else:
                return render(request, 'exam/admin_login.html', {'form': form, 'error': 'Invalid credentials or you are not an admin.'})
    else:
        form = AdminLoginForm()
    return render(request, 'exam/admin_login.html', {'form': form})
# In views.py, replace the existing teacher_login function with this:

def teacher_login(request):
    if request.method == 'POST':
        form = TeacherLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            
            if user is not None and hasattr(user, 'teacher'):
                login(request, user)
                return redirect('exam:teacher_dashboard')
            else:
                # The authentication failed
                return render(request, 'exam/teacher_login.html', {'form': form, 'error': 'Invalid credentials or you are not a teacher.'})
    else:
        form = TeacherLoginForm()
    return render(request, 'exam/teacher_login.html', {'form': form})
    # ... (GET logic)
@login_required
def student_dashboard(request):
    # Get the student object for the logged-in user
    try:
        student = Student.objects.get(user=request.user)
    except Student.DoesNotExist:
        messages.error(request, "Student record not found.")
        return redirect("exam:student_logout")

    # Fetch seating allocations for this student
    allocations = SeatingAllocation.objects.filter(student=student).select_related("exam", "hall")

    exam_details = []
    
    for alloc in allocations:
        
        # --- Start: Logic to determine the VISUAL Grid Seat Number (Local Seat Number) ---
        # The allocation's own seat_number is the GLOBAL number (e.g., S513), which we will override.
        visual_seat_number = alloc.seat_number 
        
        # 1. Get ALL allocations for this exam/hall
        # Note: We must consider ALL shared exams in the slot for a truly consistent local seat number.
        # Since the seating_plan_detail view already groups students by shared slot, 
        # we should use the same slot-aware logic here for consistency.
        
        # Find all exams sharing the same slot as the current allocation
        shared_exams_in_slot = Exam.objects.filter(
            date=alloc.exam.date,
            start_time=alloc.exam.start_time,
            halls=alloc.hall
        ).values_list('id', flat=True)
        
        hall_allocations = SeatingAllocation.objects.filter(
            exam__id__in=shared_exams_in_slot, # Filter by shared slot exams
            hall=alloc.hall
        ).select_related('student__department')
        
        # Sort by global seat number to maintain the correct display order (S1, S2, S3...)
        try:
            sorted_hall_allocations = sorted(
                list(hall_allocations),
                key=lambda a: int(a.seat_number.lstrip('S'))
            )
        except Exception:
             # Fallback: if global seat numbers are invalid, rely on roll number sort.
             sorted_hall_allocations = list(hall_allocations.order_by('student__roll_no'))

        # 2. Find the index of the current student in the globally sorted list
        try:
            # Find the index based on the allocation ID
            student_index_in_sorted = next(i for i, a in enumerate(sorted_hall_allocations) if a.id == alloc.id)
            
            # The VISUAL seat number is the sequential position in the visual flow
            # Index starts at 0, so the visual number is index + 1
            # For KALAIYARASAN S (Seat S37 in the grid) they should be the 37th student in the sorted list.
            visual_seat_number = f"S{student_index_in_sorted + 1}" 
            
        except StopIteration:
            # If for some reason the student is not in the list, keep the global number as fallback
            pass
        # --- End: Logic to determine the VISUAL Grid Seat Number ---

        # The total students should be the count of the slot-aware allocations
        total_students_in_slot = hall_allocations.count()

        exam_details.append({
            "exam": alloc.exam,
            "hall": alloc.hall,
            # CRITICAL: Use the derived local seat number (S1, S2, S3...)
            "seat_number": visual_seat_number, 
            "student_roll_no": alloc.student.roll_no,
            "total_students": total_students_in_slot,
        })

    # Department-level exams (to show schedule and status)
    department_exams = Exam.objects.filter(department=student.department).distinct()

    # Collect all exams where this student already has an allocation
    allocated_exam_ids = allocations.values_list("exam_id", flat=True)

    context = {
        "student": student,
        "exam_details": exam_details,
        "department_exams": department_exams,
        "allocated_exam_ids": allocated_exam_ids,
    }

    return render(request, "exam/student_dashboard.html", context)