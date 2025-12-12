from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import UniqueConstraint # Import to use modern constraint method

# Define a choices tuple for departments (Kept, though usually handled by the Department model)
DEPARTMENT_CHOICES = (
    ('MBA', 'Master of Business Administration'),
    ('MSc', 'Master of Science'),
    ('MA', 'Master of Arts'),
    ('MEng', 'Master of Engineering'),
    ('MPH', 'Master of Public Health'),
    ('MSW', 'Master of Social Work'),
    ('MFA', 'Master of Fine Arts'),
    ('LLM', 'Master of Laws'),
    ('MCA', 'Master of Computer Applications'),
    ('MEd', 'Master of Education'),
)

# --- 1. Department Model (Must be defined before models that reference it) ---

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

# --- 2. Hall Model (Capacity Calculation Fix) ---

class Hall(models.Model):
    hall_name = models.CharField(max_length=50, unique=True)
    # capacity field is removed as it is CALCULATED
    # You MUST REMOVE 'capacity' field from your actual model file before running migrations.
    
    rows = models.PositiveIntegerField(default=1, help_text="Number of rows in the hall for seating.")
    columns = models.PositiveIntegerField(default=1, help_text="Number of columns (seats per row) in the hall.")
    
    # New calculated field to be accessed in Python/templates
    @property
    def capacity(self):
        return self.rows * self.columns

    # Overriding save to ensure 'capacity' is implicitly calculated and the model is correct
    def save(self, *args, **kwargs):
        # Note: While capacity is calculated, it's NOT a stored field here.
        # If you needed it stored, you would add capacity = models.IntegerField(editable=False) 
        # and set its value here. Based on your forms, the properties are calculated in views.
        super().save(*args, **kwargs)

    def __str__(self):
        # Access the property for a dynamic string representation
        return f"Hall: {self.hall_name} ({self.rows}R x {self.columns}C - {self.capacity} seats)"


# --- 3. User Models ---

class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    roll_no = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')

    def __str__(self):
        return f"{self.roll_no} - {self.user.username}"


class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='teachers')
    subject = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.employee_id} - {self.user.username}"


# --- 4. Exam and Allocation Models ---

class Exam(models.Model):
    exam_name = models.CharField(max_length=100)
    # The M2M fields will link to the correct models now
    department = models.ManyToManyField(Department)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    halls = models.ManyToManyField(Hall)
    is_combined = models.BooleanField(default=False)
    # Added total_students field to be stored on exam creation/update
    total_students = models.PositiveIntegerField(default=0, help_text="The total number of students expected for this exam.")

    def __str__(self):
        return f"{self.exam_name} on {self.date}"


class InvigilationAssignment(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)

    class Meta:
        # Use modern constraints for clarity and consistency
        constraints = [
            # CRITICAL FIX: Ensures that only ONE teacher is assigned to a specific Exam-Hall combination.
            UniqueConstraint(fields=['exam', 'hall'], name='unique_invigilation_per_hall')
        ]

    def __str__(self):
        return f"{self.teacher} assigned to {self.hall} for {self.exam}"

class SeatingAllocation(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE)
    seat_number = models.CharField(max_length=20) # Stores 'S1', 'S2', or potentially the Roll No.

    class Meta:
        # Define both unique constraints clearly
        constraints = [
            UniqueConstraint(fields=['exam', 'student'], name='unique_student_seat_per_exam'),
            UniqueConstraint(fields=['exam', 'hall', 'seat_number'], name='unique_seat_in_hall_per_exam')
        ]

    def __str__(self):
        return f"{self.student} -> {self.hall} ({self.seat_number}) for {self.exam}"
class AttendanceRecord(models.Model):
    # Assuming these fields exist in your model
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    date_marked = models.DateField(default=timezone.now) # This field is critical
    STATUS_CHOICES = [
        ('P', 'Present'),
        ('A', 'Absent'),
    ]
    status = models.CharField(max_length=1, choices=STATUS_CHOICES)

    class Meta:
        # 🟢 CRITICAL FIX: Add 'date_marked' to unique_together.
        # This allows a student to have a record for the same exam on different days.
        unique_together = ('exam', 'student', 'date_marked') 
        verbose_name_plural = "Attendance Records"

    def __str__(self):
        return f"{self.student.user.username} - {self.exam.exam_name} ({self.date_marked})"