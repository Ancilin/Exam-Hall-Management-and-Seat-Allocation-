from django.core.management.base import BaseCommand, CommandError
from exam.models import Exam
from exam.views import _auto_allocate_seats


class Command(BaseCommand):
    help = 'Regenerate seating allocations for an exam (or all exams if --all).' 

    def add_arguments(self, parser):
        parser.add_argument('--exam_id', type=int, help='ID of the exam to regenerate allocations for')
        parser.add_argument('--all', action='store_true', help='Regenerate allocations for all exams')

    def handle(self, *args, **options):
        exam_id = options.get('exam_id')
        do_all = options.get('all')

        if not exam_id and not do_all:
            raise CommandError('Provide --exam_id or --all')

        if do_all:
            exams = Exam.objects.all()
        else:
            exams = Exam.objects.filter(id=exam_id)

        for exam in exams:
            halls = list(exam.halls.all())
            self.stdout.write(f"Regenerating allocations for exam {exam.id} - {exam.exam_name} with halls {[h.hall_name for h in halls]}")
            ok, msg = _auto_allocate_seats(exam, halls)
            if ok:
                self.stdout.write(self.style.SUCCESS(msg))
            else:
                self.stdout.write(self.style.ERROR(msg))
