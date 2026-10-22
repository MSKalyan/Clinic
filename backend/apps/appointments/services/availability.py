"""Availability engine.

Turns the recurring rota, schedule exceptions, doctor status and existing
appointments into a concrete list of bookable slots.

Everything is computed in the clinic's timezone and returned as UTC
datetimes. The engine never guesses: a slot only exists if the rota says the
doctor is working, no exception closes the window, the doctor is not on
leave, the clinic is open and nothing else is already booked.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Sequence

from django.utils import timezone

from apps.core.constants import OCCUPYING_STATUSES, AppointmentStatus, DoctorStatus
from apps.core.timeutils import combine_local, clinic_zone, minutes_since_midnight, to_clinic_local
from apps.doctors.models import Doctor, DoctorScheduleException
from apps.doctors.services.status import DoctorStatusService

logger = logging.getLogger("apps.appointments.availability")

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Slot:
    """A bookable (or explicitly unavailable) window."""

    doctor_id: str
    doctor_name: str
    specialization: str
    start_at: datetime
    end_at: datetime
    local_date: str
    display_start: str
    display_end: str
    doctor_status: str
    status_is_stale: bool
    available: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "doctor_id": self.doctor_id,
            "doctor_name": self.doctor_name,
            "specialization": self.specialization,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "local_date": self.local_date,
            "display_start": self.display_start,
            "display_end": self.display_end,
            "doctor_status": self.doctor_status,
            "status_is_stale": self.status_is_stale,
            "available": self.available,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TimeWindow:
    start: time
    end: time


def _subtract(window: TimeWindow, cut: TimeWindow) -> list[TimeWindow]:
    """Remove ``cut`` from ``window``."""
    if cut.end <= window.start or cut.start >= window.end:
        return [window]
    pieces: list[TimeWindow] = []
    if cut.start > window.start:
        pieces.append(TimeWindow(window.start, cut.start))
    if cut.end < window.end:
        pieces.append(TimeWindow(cut.end, window.end))
    return pieces


def _intersect(window: TimeWindow, other: TimeWindow) -> list[TimeWindow]:
    """The overlap between ``window`` and ``other`` (possibly empty).

    A doctor can only see patients while the clinic is open, so the rota
    window has to be clipped by the clinic's operating hours.
    """
    start = max(window.start, other.start)
    end = min(window.end, other.end)
    if start < end:
        return [TimeWindow(start, end)]
    return []


class AvailabilityService:
    """Computes bookable slots for a clinic."""

    def __init__(self, clinic) -> None:  # noqa: ANN001
        self.clinic = clinic
        self.zone = clinic_zone(clinic)
        self.rules = clinic.appointment_rules()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def slots(
        self,
        *,
        doctors: Iterable[Doctor] | None = None,
        on_date: date | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        duration_minutes: int | None = None,
        include_unavailable: bool = False,
    ) -> list[Slot]:
        """Return the slots a patient could book.

        ``on_date`` restricts to a single clinic-local date. ``from_dt`` /
        ``to_dt`` accept UTC datetimes and restrict the range.
        """
        rules = self.rules
        duration = int(duration_minutes or rules["appointment_duration_minutes"])
        buffer_minutes = int(rules["buffer_minutes"])
        interval = int(rules["slot_interval_minutes"])
        horizon_days = int(rules["booking_horizon_days"])

        now = timezone.now()
        window_start = from_dt or now
        window_end = to_dt or (now + timedelta(days=horizon_days))
        if window_end <= window_start:
            return []

        doctors = list(doctors if doctors is not None else self._active_doctors())
        if not doctors:
            return []

        occupied = self._occupied_intervals(doctors, window_start, window_end, buffer_minutes)

        slots: list[Slot] = []
        for doctor in doctors:
            status = DoctorStatusService.get_current(doctor)
            for day in self._days_in_range(window_start, window_end):
                if on_date is not None and day != on_date:
                    continue
                for window in self._working_windows(doctor, day):
                    for start_local in self._candidate_starts(window, interval, duration):
                        start_utc = combine_local(day, start_local, self.zone)
                        end_utc = start_utc + timedelta(minutes=duration)
                        if start_utc < window_start or start_utc >= window_end:
                            continue
                        if start_utc <= now:
                            continue
                        available = True
                        reason = ""
                        if status.blocks_booking:
                            available = False
                            reason = f"Doctor is {status.status.replace('_', ' ')}."
                        elif self._conflicts(
                            start_utc, end_utc, occupied.get(doctor.id, [])
                        ):
                            available = False
                            reason = "Slot already booked."
                        if not available and not include_unavailable:
                            continue
                        slots.append(
                            Slot(
                                doctor_id=str(doctor.id),
                                doctor_name=doctor.name,
                                specialization=doctor.specialization,
                                start_at=start_utc,
                                end_at=end_utc,
                                local_date=day.isoformat(),
                                display_start=to_clinic_local(start_utc, self.clinic).strftime("%H:%M"),
                                display_end=to_clinic_local(end_utc, self.clinic).strftime("%H:%M"),
                                doctor_status=status.status,
                                status_is_stale=status.is_stale,
                                available=available,
                                reason=reason,
                            )
                        )
        slots.sort(key=lambda s: (s.start_at, s.doctor_name))
        return slots

    def is_slot_available(
        self,
        doctor: Doctor,
        start_at: datetime,
        duration_minutes: int | None = None,
        *,
        ignore_appointment_id=None,
    ) -> bool:
        """Cheap, authoritative check used inside the booking transaction."""
        rules = self.rules
        duration = int(duration_minutes or rules["appointment_duration_minutes"])
        buffer_minutes = int(rules["buffer_minutes"])
        end_at = start_at + timedelta(minutes=duration)

        status = DoctorStatusService.get_current(doctor, at=start_at)
        if status.blocks_booking:
            return False

        local = to_clinic_local(start_at, self.clinic)
        if not self._within_working_window(doctor, local.date(), local.time(), duration):
            return False

        occupied = self._occupied_intervals(
            [doctor], start_at, end_at, buffer_minutes, ignore_appointment_id=ignore_appointment_id
        )
        return not self._conflicts(start_at, end_at, occupied.get(doctor.id, []))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _active_doctors(self) -> list[Doctor]:
        return list(
            Doctor.objects.filter(clinic=self.clinic, is_active=True)
            .select_related("clinic")
            .order_by("sort_order", "name")
        )

    def _days_in_range(self, start: datetime, end: datetime) -> list[date]:
        first = to_clinic_local(start, self.clinic).date()
        last = to_clinic_local(end, self.clinic).date()
        days: list[date] = []
        cursor = first
        while cursor <= last:
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def _working_windows(self, doctor: Doctor, day: date) -> list[TimeWindow]:
        """The windows in which ``doctor`` could see a patient on ``day``."""
        clinic_hours = self.clinic.operating_hours().get(_WEEKDAY_KEYS[day.weekday()], {})
        if not clinic_hours or clinic_hours.get("closed"):
            return []
        clinic_open = datetime.strptime(clinic_hours["open"], "%H:%M").time()
        clinic_close = datetime.strptime(clinic_hours["close"], "%H:%M").time()
        clinic_window = TimeWindow(clinic_open, clinic_close)

        windows: list[TimeWindow] = []
        for schedule in doctor.schedules.filter(is_active=True, weekday=day.weekday()):
            if not schedule.applies_on(day):
                continue
            window = TimeWindow(schedule.start_time, schedule.end_time)
            # The doctor can only work while the clinic is open.
            windows.extend(_intersect(window, clinic_window))

        exceptions = list(
            DoctorScheduleException.objects.filter(doctor=doctor, date=day).order_by("start_time")
        )
        for exception in exceptions:
            if exception.kind == "unavailable":
                if exception.start_time and exception.end_time:
                    cut = TimeWindow(exception.start_time, exception.end_time)
                    new_windows: list[TimeWindow] = []
                    for window in windows:
                        new_windows.extend(_subtract(window, cut))
                    windows = new_windows
                else:
                    # Whole-day closure.
                    windows = []
            elif exception.kind == "available" and exception.start_time and exception.end_time:
                # An extra window, still clipped by the clinic's opening hours.
                windows.extend(
                    _intersect(
                        TimeWindow(exception.start_time, exception.end_time), clinic_window
                    )
                )

        # Merge overlapping windows so we do not emit duplicate slots.
        windows = self._merge(windows)
        return [w for w in windows if w.start < w.end]

    def _within_working_window(
        self, doctor: Doctor, day: date, start_time: time, duration_minutes: int
    ) -> bool:
        # Compare on a minute axis so a slot that runs past midnight is
        # handled correctly (``time`` objects cannot be added to directly).
        start_minutes = minutes_since_midnight(start_time)
        end_minutes = start_minutes + duration_minutes
        for window in self._working_windows(doctor, day):
            if (
                minutes_since_midnight(window.start) <= start_minutes
                and end_minutes <= minutes_since_midnight(window.end)
            ):
                return True
        return False

    @staticmethod
    def _merge(windows: Sequence[TimeWindow]) -> list[TimeWindow]:
        if not windows:
            return []
        ordered = sorted(windows, key=lambda w: w.start)
        merged = [ordered[0]]
        for window in ordered[1:]:
            last = merged[-1]
            if window.start <= last.end:
                merged[-1] = TimeWindow(last.start, max(last.end, window.end))
            else:
                merged.append(window)
        return merged

    @staticmethod
    def _candidate_starts(
        window: TimeWindow, interval_minutes: int, duration_minutes: int
    ) -> list[time]:
        starts: list[time] = []
        current = window.start
        step = timedelta(minutes=interval_minutes)
        span = timedelta(minutes=duration_minutes)
        base = datetime.combine(date(2000, 1, 1), window.start)
        while base + span <= datetime.combine(date(2000, 1, 1), window.end):
            starts.append(current)
            base += step
            current = (datetime.combine(date(2000, 1, 1), current) + step).time()
        return starts

    def _occupied_intervals(
        self,
        doctors: Sequence[Doctor],
        window_start: datetime,
        window_end: datetime,
        buffer_minutes: int,
        *,
        ignore_appointment_id=None,
    ) -> dict:
        """Existing appointments, widened by the buffer, per doctor."""
        from apps.appointments.models import Appointment

        doctor_ids = [doctor.id for doctor in doctors]
        if not doctor_ids:
            return {}
        appointments = (
            Appointment.objects.filter(
                clinic=self.clinic,
                doctor_id__in=doctor_ids,
                status__in=list(OCCUPYING_STATUSES),
                start_at__lt=window_end + timedelta(minutes=buffer_minutes),
                end_at__gt=window_start - timedelta(minutes=buffer_minutes),
            )
            .select_related("doctor")
            .only("doctor_id", "start_at", "end_at", "status")
        )
        occupied: dict = {}
        for appointment in appointments:
            if ignore_appointment_id and appointment.id == ignore_appointment_id:
                continue
            occupied.setdefault(appointment.doctor_id, []).append(
                (
                    appointment.start_at - timedelta(minutes=buffer_minutes),
                    appointment.end_at + timedelta(minutes=buffer_minutes),
                )
            )
        return occupied

    @staticmethod
    def _conflicts(start: datetime, end: datetime, intervals: Sequence[tuple]) -> bool:
        for interval_start, interval_end in intervals:
            if start < interval_end and interval_start < end:
                return True
        return False
