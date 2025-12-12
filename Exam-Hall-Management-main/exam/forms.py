from django import forms
from django.contrib.auth.models import User
# 🟢 FIX: Ensure AttendanceRecord is imported from .models
from .models import (
    Student, 
    Teacher, 
    Hall, 
    Exam, 
    InvigilationAssignment, 
    Department, 
    AttendanceRecord # <-- ADD THIS
)

# -------------------------
# Login Forms
# -------------------------

class AdminLoginForm(forms.Form):
    username = forms.CharField(
        label='Username',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )


class TeacherLoginForm(forms.Form):
    username = forms.CharField(
        label='Teacher Username',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )


class StudentLoginForm(forms.Form):
    roll_no = forms.CharField(
        label='Roll Number',
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control','placeholder': 'Roll Number'})
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control','placeholder': 'Password'})
    )


# -------------------------
# Admin Forms for Adding Users
# -------------------------

class AddStudentForm(forms.Form):
    roll_no = forms.CharField(
        label='Roll Number',
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    username = forms.CharField(
        label='Username',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        label='Department',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.all()


class DepartmentFilterForm(forms.Form):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label='Filter by Department',
        empty_label='All Departments',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.all()


class AddTeacherForm(forms.Form):
    employee_id = forms.CharField(
        label='Employee ID',
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    username = forms.CharField(
        label='Username',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        label='Select Department',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    subject = forms.CharField(
        label='Subject',
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.all()


# -------------------------
# Management Forms
# -------------------------

class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Computer Science'}),
        }


class HallForm(forms.ModelForm):
    class Meta:
        model = Hall
        # FIX: Ensure 'rows' and 'columns' are included in fields
        fields = ['hall_name', 'rows', 'columns'] 
        widgets = {
            'hall_name': forms.TextInput(attrs={'class': 'form-control'}),
            'rows': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}), 
            'columns': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }


class ExamForm(forms.ModelForm):
    # FIX 1: Change widget for the M2M field to CheckboxSelectMultiple for better UX
    department = forms.ModelMultipleChoiceField( 
        queryset=Department.objects.all(),
        label='Select Department(s)',
        widget=forms.SelectMultiple(attrs={'class': 'form-control'}), 
    )
    
    # FIX 2: Change widget for the M2M Halls field to CheckboxSelectMultiple for easy multi-select
    halls = forms.ModelMultipleChoiceField(
        queryset=Hall.objects.all(),
        label="Select Halls",
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )
    
    # Adding total_students field explicitly to ensure it shows up
    total_students = forms.IntegerField(
        label='Total Students',
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Exam
        # List the fields, including the M2M fields defined above
        fields = ['exam_name', 'department', 'date', 'start_time', 'end_time', 'halls', 'total_students','is_combined']
        widgets = {
            'exam_name': forms.TextInput(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        }
        
class InvigilationAssignmentForm(forms.ModelForm):
    class Meta:
        model = InvigilationAssignment
        # Exclude 'exam' field as it will be set in the view
        fields = ['hall', 'teacher'] 
        widgets = {
            'hall': forms.Select(attrs={'class': 'form-control'}),
            'teacher': forms.Select(attrs={'class': 'form-control'}),
        }


class ExcelUploadForm(forms.Form):
    excel_file = forms.FileField(label='Select an Excel file (.xlsx)', widget=forms.FileInput(attrs={'class': 'form-control'}))


from django import forms
from .models import Exam, Hall


class SeatAllocationForm(forms.Form):
    exam = forms.ModelChoiceField(
        queryset=Exam.objects.all().order_by('date'),
        label="Select Exam",
        empty_label="-----------",
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'id_exam'
        })
    )

    halls = forms.ModelMultipleChoiceField(
        queryset=Hall.objects.all().order_by('hall_name'),
        label="Select Halls",
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input'
        })
    )

    def __init__(self, *args, **kwargs):
        # ✅ Pop custom argument safely before calling super()
        initial_exam = kwargs.pop('initial_exam', None)
        super().__init__(*args, **kwargs)

        # ✅ If specific exam provided, pre-select it and its related halls
        if initial_exam and isinstance(initial_exam, Exam):
            # Pre-select exam in dropdown
            self.fields['exam'].initial = initial_exam.pk

            # Pre-select halls linked to the exam (if any relation exists)
            try:
                pre_selected_halls = initial_exam.halls.all()
                self.fields['halls'].initial = pre_selected_halls
            except AttributeError:
                # Fallback in case Exam doesn’t have direct relation with Hall
                pass

class AttendanceForm(forms.Form):
    # These three MUST be defined as hidden fields for the POST request to pass the IDs
    student = forms.ModelChoiceField(queryset=Student.objects.all(), widget=forms.HiddenInput())
    exam = forms.ModelChoiceField(queryset=Exam.objects.all(), widget=forms.HiddenInput())
    hall = forms.ModelChoiceField(queryset=Hall.objects.all(), widget=forms.HiddenInput())
    
    # This is the dropdown
    status = forms.ChoiceField(
        choices=AttendanceRecord.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    # Display-only field for Roll Number
    roll_no_display = forms.CharField(label='Roll No.', required=False, 
                                      widget=forms.TextInput(attrs={'class': 'form-control-plaintext', 'readonly': True}))

    # Display-only field for Student Name
    student_name_display = forms.CharField(label='Student Name', required=False, 
                                           widget=forms.TextInput(attrs={'class': 'form-control-plaintext', 'readonly': True}))

    class Meta:
        model = AttendanceRecord
        fields = ['student', 'exam', 'hall', 'status']
        widgets = {
            'status': forms.Select(choices=AttendanceRecord.STATUS_CHOICES, attrs={'class': 'form-select'}),
        }