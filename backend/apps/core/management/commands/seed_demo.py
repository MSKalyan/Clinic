"""Seed a demo clinic so the API and the dashboard have something to show.

Usage::

    python manage.py seed_demo
    python manage.py seed_demo --reset --with-second-clinic

The seed writes through the same tenant-scoped code paths the application
uses, so the Row Level Security session variable is set for every clinic it
touches.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import ClinicMembership, ClinicServiceToken, User
from apps.appointments.models import Patient
from apps.appointments.services.booking import BookingService, get_or_create_patient
from apps.core.authentication import generate_token, hash_token
from apps.core.constants import BookingSource, ClinicStatus, DoctorStatus
from apps.core.rls import rls_scope
from apps.doctors.models import Doctor, DoctorSchedule
from apps.tenancy.models import (
    Clinic,
    ClinicAgentConfig,
    ClinicChannelNumber,
    ClinicSettings,
    ProviderConnection,
)

DEMO_PASSWORD = "demo-password-123"

DOCTORS = [
    {
        "name": "Dr Anita Rao",
        "slug": "anita-rao",
        "specialization": "General Medicine",
        "phone": "+919000000001",
        "languages": ["hi-IN", "en-IN"],
        "sort_order": 1,
        "status": DoctorStatus.PRESENT,
    },
    {
        "name": "Dr Vikram Shetty",
        "slug": "vikram-shetty",
        "specialization": "Cardiology",
        "phone": "+919000000002",
        "languages": ["en-IN", "kn-IN"],
        "sort_order": 2,
        "status": DoctorStatus.RUNNING_LATE,
    },
    {
        "name": "Dr Meera Iyer",
        "slug": "meera-iyer",
        "specialization": "Paediatrics",
        "phone": "+919000000003",
        "languages": ["hi-IN", "ta-IN"],
        "sort_order": 3,
        "status": DoctorStatus.SCHEDULED,
    },
]


class Command(BaseCommand):
    help = "Create a demo clinic, staff, doctors, a patient and an appointment."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the demo clinic (and its data) before seeding.",
        )
        parser.add_argument(
            "--with-second-clinic",
            action="store_true",
            help="Also create a second clinic, to demonstrate tenant isolation.",
        )
        parser.add_argument(
            "--service-token",
            action="store_true",
            help="Print a freshly generated service token for the voice agent.",
        )

    def handle(self, *args, **options) -> None:
        if options["reset"]:
            self._reset()

        clinic, token = self._seed_clinic(
            slug="sunrise-clinic",
            name="Sunrise Family Clinic",
            timezone_name="Asia/Kolkata",
            email="admin@sunriseclinic.test",
            phone="+919000010000",
        )

        if options["with_second_clinic"]:
            self._seed_clinic(
                slug="harbour-clinic",
                name="Harbour Health Centre",
                timezone_name="Asia/Kolkata",
                email="admin@harbourclinic.test",
                phone="+919000020000",
            )

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  clinic id      : {clinic.id}")
        self.stdout.write(f"  staff email    : admin@sunriseclinic.test")
        self.stdout.write(f"  password       : {DEMO_PASSWORD}")
        self.stdout.write(f"  header         : X-Clinic-Id: {clinic.id}")
        if options["service_token"] and token:
            self.stdout.write(f"  service token  : {token}")

    # ------------------------------------------------------------------
    def _reset(self) -> None:
        """Remove the demo clinics and everything that belongs to them.

        Row Level Security means the delete has to be scoped to the clinic
        first: an unscoped delete would not see the tenant rows and the
        foreign keys would refuse the delete.
        """
        from apps.core.rls import rls_scope

        clinics = list(Clinic.objects.filter(slug__in=["sunrise-clinic", "harbour-clinic"]))
        for clinic in clinics:
            with rls_scope(str(clinic.id)):
                # Channel numbers protect their provider connection, so they
                # have to go first.
                ClinicChannelNumber.objects.filter(clinic=clinic).delete()
                ProviderConnection.objects.filter(clinic=clinic).delete()
                clinic.delete()
        self.stdout.write(f"Removed {len(clinics)} demo clinics.")

    def _seed_clinic(
        self,
        *,
        slug: str,
        name: str,
        timezone_name: str,
        email: str,
        phone: str,
    ) -> tuple[Clinic, str]:
        existing = Clinic.objects.filter(slug=slug).first()
        if existing is not None:
            self.stdout.write(f"Clinic '{slug}' already exists -- leaving it alone.")
            return existing, ""

        user, created = User.objects.get_or_create(
            email=email,
            defaults={"username": email, "first_name": "Clinic", "last_name": "Admin"},
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])

        clinic = Clinic.objects.create(
            name=name,
            slug=slug,
            timezone=timezone_name,
            status=ClinicStatus.ACTIVE,
            onboarded_at=timezone.now(),
        )
        ClinicSettings.objects.create(clinic=clinic)
        ClinicMembership.objects.create(
            clinic=clinic, user=user, role="clinic_admin", status="active"
        )

        raw_token = generate_token()
        ClinicServiceToken.objects.create(
            clinic=clinic,
            name="voice-agent",
            token_hash=hash_token(raw_token),
            scopes=["tools:invoke"],
            provider_type="sarvam",
        )

        # Everything below is tenant data: scope the session to this clinic.
        with rls_scope(str(clinic.id)):
            connection = ProviderConnection.objects.create(
                clinic=clinic,
                provider_type="voice",
                account_mode="shared",
                external_account_id=f"sarvam-{slug}",
                secret_reference=f"secrets/sarvam/{slug}",
                status="active",
                display_name="Sarvam voice agent",
            )
            ClinicChannelNumber.objects.create(
                clinic=clinic,
                channel="voice",
                provider_connection=connection,
                external_number_id=f"voice-{slug}",
                display_number=phone,
            )
            ClinicAgentConfig.objects.create(
                clinic=clinic,
                name="Default",
                greeting=(
                    "You are the virtual receptionist for {}. "
                    "Introduce yourself as an automated assistant."
                ).format(name),
                enabled_channels=["voice", "whatsapp"],
                voice_language="hi-IN",
            )

            doctors = []
            for spec in DOCTORS:
                doctor = Doctor.objects.create(
                    clinic=clinic,
                    name=spec["name"],
                    slug=spec["slug"],
                    specialization=spec["specialization"],
                    phone=spec["phone"],
                    languages=spec["languages"],
                    sort_order=spec["sort_order"],
                )
                # Monday to Saturday, 09:00 - 13:00 and 16:00 - 19:00.
                for weekday in range(6):
                    DoctorSchedule.objects.create(
                        clinic=clinic,
                        doctor=doctor,
                        weekday=weekday,
                        start_time=time(9, 0),
                        end_time=time(13, 0),
                    )
                    DoctorSchedule.objects.create(
                        clinic=clinic,
                        doctor=doctor,
                        weekday=weekday,
                        start_time=time(16, 0),
                        end_time=time(19, 0),
                    )
                doctors.append(doctor)

            from apps.doctors.services.status import DoctorStatusService

            DoctorStatusService.record(
                doctor=doctors[0],
                status=DoctorStatus.PRESENT,
                source="dashboard",
                notes="Seeded demo status.",
            )
            DoctorStatusService.record(
                doctor=doctors[1],
                status=DoctorStatus.RUNNING_LATE,
                source="dashboard",
                notes="Seeded demo status.",
            )

            patient, _ = get_or_create_patient(
                clinic=clinic,
                phone="+919000100001",
                name="Ravi Kumar",
                preferred_language="hi-IN",
            )
            Patient.objects.filter(pk=patient.pk).update(
                communication_preferences={"opt_out_sms": False, "opt_out_whatsapp": False}
            )

            start_at = self._next_slot(clinic, doctors[0])
            with transaction.atomic():
                BookingService.book(
                    clinic=clinic,
                    doctor=doctors[0],
                    patient=patient,
                    start_at=start_at,
                    source=BookingSource.DASHBOARD,
                    notes="Seeded demo appointment.",
                )

        self.stdout.write(f"Seeded clinic '{slug}' ({clinic.id}).")
        return clinic, raw_token

    @staticmethod
    def _next_slot(clinic, doctor) -> datetime:
        """The next weekday slot the doctor is actually working."""
        from apps.appointments.services.availability import AvailabilityService

        availability = AvailabilityService(clinic)
        today = timezone.localdate()
        for offset in range(1, 15):
            day = today + timedelta(days=offset)
            slots = availability.slots(doctors=[doctor], on_date=day)
            if slots:
                return slots[0].start_at
        raise RuntimeError("No bookable slot found in the next two weeks.")
