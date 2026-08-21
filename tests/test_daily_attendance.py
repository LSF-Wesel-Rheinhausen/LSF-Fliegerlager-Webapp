from datetime import date
from decimal import Decimal

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.test import RequestFactory

from billing.admin import ParticipantAdmin, ParticipantFamilyMemberAdmin
from billing.forms import ParticipantFamilyMemberForm, ParticipantForm
from billing.models import AttendanceDay, KioskActionAuditLog, Participant, ParticipantFamilyMember, PriceRule
from billing.services import (
    calculate_participant_settlement,
    family_member_camp_flat_duration,
    replace_attendance_days,
    save_attendance_day,
)
from tests.factories import (
    CampFactory,
    ParticipantFactory,
    ParticipantFamilyMemberFactory,
    PriceRuleFactory,
    SuperUserFactory,
)


@pytest.mark.django_db
def test_attendance_day_represents_the_overnight_from_date_until_next_date():
    attendance = AttendanceDay.objects.create(
        participant=ParticipantFactory(),
        date=date(2026, 7, 3),
        is_present=True,
    )

    assert attendance.date == date(2026, 7, 3)
    assert attendance.overnight == (date(2026, 7, 3), date(2026, 7, 4))


@pytest.mark.django_db
def test_attendance_day_supports_guardian_and_optional_family_member_target_with_bounded_comment():
    guardian = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=guardian)
    attendance = AttendanceDay.objects.create(
        participant=guardian,
        family_member=member,
        date=date(2026, 7, 3),
        is_present=False,
        comment="Späte Abreise",
    )

    assert attendance.participant == guardian
    assert attendance.family_member == member
    assert attendance.is_present is False
    assert attendance.comment == "Späte Abreise"
    assert AttendanceDay._meta.get_field("comment").max_length == 500


@pytest.mark.django_db
def test_attendance_day_rejects_date_outside_target_stay_and_wrong_guardian():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 14))
    guardian = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 3),
        departure_date=date(2026, 7, 8),
    )
    other_guardian = ParticipantFactory(camp=camp)
    member = ParticipantFamilyMemberFactory(guardian=guardian)
    unrelated_member = ParticipantFamilyMemberFactory(guardian=other_guardian)

    with pytest.raises(ValidationError, match="Aufenthaltsbereich"):
        save_attendance_day(guardian, date(2026, 7, 2), is_present=True)
    with pytest.raises(ValidationError, match="Aufenthaltsbereich"):
        save_attendance_day(guardian, date(2026, 7, 8), is_present=True)
    with pytest.raises(ValidationError, match="Zielkonto"):
        save_attendance_day(guardian, date(2026, 7, 3), is_present=True, family_member=unrelated_member)

    saved = save_attendance_day(guardian, date(2026, 7, 3), is_present=True, family_member=member)
    assert saved.family_member == member


@pytest.mark.django_db
def test_explicit_attendance_count_zero_overrides_legacy_nights_for_billing():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, booked_nights=5, actual_nights=4)
    PriceRuleFactory(camp=camp, kind="night", unit_price=Decimal("12.00"), is_default=True)
    replace_attendance_days(
        participant,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 6),
        days=[],
    )

    night_line = next(
        line for line in calculate_participant_settlement(participant).lines if line.source.startswith("price_rule:")
    )
    assert night_line.quantity == Decimal("0.00")


@pytest.mark.django_db
def test_without_explicit_attendance_mode_legacy_actual_nights_remains_billable():
    camp = CampFactory()
    participant = ParticipantFactory(camp=camp, booked_nights=5, actual_nights=4)
    PriceRuleFactory(camp=camp, kind="night", unit_price=Decimal("12.00"), is_default=True)

    night_line = next(
        line for line in calculate_participant_settlement(participant).lines if line.source.startswith("price_rule:")
    )
    assert night_line.quantity == Decimal("4.00")


@pytest.mark.django_db
def test_selected_presence_count_is_scoped_to_its_target_and_drives_shift_target():
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 7),
        shift_ratio_per_night=Decimal("0.5000"),
    )
    guardian = ParticipantFactory(camp=camp, booked_nights=6, actual_nights=6)
    member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role="companion",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 7),
    )
    replace_attendance_days(
        guardian,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 7),
        days=[{"date": date(2026, 7, day), "is_present": day in {1, 2, 3}} for day in range(1, 7)],
        family_member=member,
    )

    assert guardian.effective_attendance_nights == 6
    assert member.effective_attendance_nights == 3
    assert member.target_shifts == 2
    assert member.effective_target_shifts == 2


@pytest.mark.django_db
def test_untracked_family_member_without_own_stay_uses_guardians_actual_nights_before_booked_nights():
    guardian = ParticipantFactory(actual_nights=8, booked_nights=6)
    member = ParticipantFamilyMemberFactory(guardian=guardian, role="companion")

    assert member.effective_attendance_nights == 8
    assert family_member_camp_flat_duration(member, guardian) == PriceRule.CampFlatDuration.TWO_WEEKS


@pytest.mark.django_db
def test_replacing_with_no_days_removes_omitted_target_days_and_keeps_explicit_zero_mode():
    participant = ParticipantFactory(actual_nights=4, booked_nights=4)
    AttendanceDay.objects.create(participant=participant, date=date(2026, 7, 1), is_present=True)
    AttendanceDay.objects.create(participant=participant, date=date(2026, 7, 2), is_present=True)

    replace_attendance_days(
        participant,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
        days=[],
    )

    participant.refresh_from_db()
    assert not AttendanceDay.objects.filter(participant=participant).exists()
    assert participant.attendance_tracking_enabled is True
    assert participant.effective_attendance_nights == 0


@pytest.mark.django_db
def test_family_member_persists_profile_contact_and_birth_date_fields():
    member = ParticipantFamilyMemberFactory(
        email="family@example.test",
        phone="+49 123 456",
        birth_date=date(2010, 5, 4),
    )

    member.refresh_from_db()
    assert (member.email, member.phone, member.birth_date) == (
        "family@example.test",
        "+49 123 456",
        date(2010, 5, 4),
    )


def test_kiosk_audit_exposes_profile_updated_action_without_replacing_checkin_action():
    assert KioskActionAuditLog.Action.PROFILE_UPDATED == "profile_updated"
    assert KioskActionAuditLog.Action.CHECKIN_UPDATED == "checkin_updated"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("birth_date", "camp_start", "expected_age"),
    [
        (date(2008, 7, 1), date(2026, 7, 1), 18),
        (date(2008, 7, 2), date(2026, 7, 1), 17),
        (date(2008, 2, 29), date(2026, 2, 28), 17),
    ],
)
def test_participant_and_family_member_store_birth_dates_and_calculate_age_on_camp_start(
    birth_date, camp_start, expected_age
):
    camp = CampFactory(starts_on=camp_start)
    participant = ParticipantFactory(camp=camp, birth_date=birth_date)
    member = ParticipantFamilyMemberFactory(guardian=participant, birth_date=birth_date)

    assert participant.birth_date == birth_date
    assert member.birth_date == birth_date
    assert participant.age_on(camp.starts_on) == expected_age
    assert member.age_on(camp.starts_on) == expected_age


@pytest.mark.django_db
def test_birth_date_cannot_be_in_the_future_at_age_calculation_date():
    participant = ParticipantFactory(birth_date=date(2026, 7, 2))

    with pytest.raises(ValidationError, match="Zukunft"):
        participant.age_on(date(2026, 7, 1))


@pytest.mark.django_db
def test_all_administrative_profile_forms_reject_future_birth_dates():
    participant = ParticipantFactory()
    member = ParticipantFamilyMemberFactory(guardian=participant)
    future_birth_date = "2999-01-01"
    participant_form = ParticipantForm(
        {
            "first_name": participant.first_name,
            "last_name": participant.last_name,
            "email": participant.email,
            "phone": participant.phone,
            "birth_date": future_birth_date,
            "status": participant.status,
            "hilfssatz": participant.hilfssatz,
            "berufssatz": participant.berufssatz,
            "booked_nights": participant.booked_nights,
            "actual_nights": participant.actual_nights,
            "notes": participant.notes,
        },
        instance=participant,
    )
    family_form = ParticipantFamilyMemberForm(
        {
            "first_name": member.first_name,
            "last_name": member.last_name,
            "email": member.email,
            "phone": member.phone,
            "birth_date": future_birth_date,
            "role": member.role,
            "is_active": "on",
        },
        instance=member,
    )

    assert participant_form.is_valid() is False
    assert family_form.is_valid() is False
    assert participant_form.errors["birth_date"] == ["Das Geburtsdatum darf nicht in der Zukunft liegen."]
    assert family_form.errors["birth_date"] == ["Das Geburtsdatum darf nicht in der Zukunft liegen."]


@pytest.mark.django_db
def test_effective_attendance_excludes_records_outside_the_current_stay():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 4))
    guardian = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 4),
        attendance_tracking_enabled=True,
    )
    member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role="companion",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 4),
        attendance_tracking_enabled=True,
    )
    for attendance_date in (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)):
        AttendanceDay.objects.create(participant=guardian, date=attendance_date, is_present=True)
        AttendanceDay.objects.create(
            participant=guardian,
            family_member=member,
            date=attendance_date,
            is_present=True,
        )

    guardian.departure_date = date(2026, 7, 3)
    guardian.save(update_fields=["departure_date", "updated_at"])
    member.departure_date = date(2026, 7, 2)
    member.save(update_fields=["departure_date", "updated_at"])

    assert guardian.effective_attendance_nights == 2
    assert member.effective_attendance_nights == 1


@pytest.mark.django_db
@pytest.mark.parametrize("cleared_bounds", [{"starts_on": None}, {"ends_on": None}])
def test_tracked_attendance_is_clamped_to_the_current_camp_window_after_camp_bounds_change(cleared_bounds):
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 20), shift_ratio_per_night=Decimal("0.5"))
    guardian = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 20),
        attendance_tracking_enabled=True,
    )
    member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        role="companion",
        arrival_date=date(2026, 7, 1),
        departure_date=date(2026, 7, 20),
        attendance_tracking_enabled=True,
    )
    for attendance_date in (date(2026, 7, 1), date(2026, 7, 18)):
        AttendanceDay.objects.create(participant=guardian, date=attendance_date, is_present=True)
        AttendanceDay.objects.create(
            participant=guardian,
            family_member=member,
            date=attendance_date,
            is_present=True,
        )

    camp.starts_on = cleared_bounds.get("starts_on", date(2026, 7, 10))
    camp.ends_on = cleared_bounds.get("ends_on", date(2026, 7, 12))
    camp.save(update_fields=[*cleared_bounds, "updated_at"])

    assert guardian.effective_attendance_nights == 0
    assert member.effective_attendance_nights == 0
    assert guardian.target_shifts == 0
    assert member.target_shifts == 0


@pytest.mark.django_db
def test_tracked_attendance_uses_a_shortened_valid_camp_window_for_database_and_prefetched_records():
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 20))
    guardian = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 6, 25),
        departure_date=date(2026, 7, 20),
        attendance_tracking_enabled=True,
    )
    member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        arrival_date=date(2026, 6, 25),
        departure_date=date(2026, 7, 20),
        attendance_tracking_enabled=True,
    )
    for attendance_date in (date(2026, 7, 5), date(2026, 7, 6), date(2026, 7, 15), date(2026, 7, 16)):
        AttendanceDay.objects.create(participant=guardian, date=attendance_date, is_present=True)
        AttendanceDay.objects.create(
            participant=guardian,
            family_member=member,
            date=attendance_date,
            is_present=True,
        )

    camp.starts_on = date(2026, 7, 10)
    camp.ends_on = date(2026, 7, 12)
    camp.save(update_fields=["starts_on", "ends_on", "updated_at"])

    guardian_from_database = Participant.objects.select_related("camp").get(pk=guardian.pk)
    guardian_prefetched = (
        Participant.objects.select_related("camp")
        .prefetch_related(
            Prefetch(
                "attendance_days",
                queryset=AttendanceDay.objects.order_by("date", "pk"),
                to_attr="prefetched_attendance_days",
            )
        )
        .get(pk=guardian.pk)
    )
    member_from_database = ParticipantFamilyMember.objects.select_related("guardian__camp").get(pk=member.pk)
    member_prefetched = (
        ParticipantFamilyMember.objects.select_related("guardian__camp")
        .prefetch_related(
            Prefetch(
                "attendance_days",
                queryset=AttendanceDay.objects.order_by("date", "pk"),
                to_attr="prefetched_attendance_days",
            )
        )
        .get(pk=member.pk)
    )

    assert guardian_from_database.effective_attendance_nights == 2
    assert guardian_prefetched.effective_attendance_nights == 2
    assert member_from_database.effective_attendance_nights == 2
    assert member_prefetched.effective_attendance_nights == 2


@pytest.mark.django_db
def test_attendance_tracking_is_an_internal_model_state_not_an_editable_form_field():
    request = RequestFactory().get("/admin/")
    request.user = SuperUserFactory()
    participant_admin_form = ParticipantAdmin(Participant, admin.site).get_form(request)
    family_member_admin_form = ParticipantFamilyMemberAdmin(ParticipantFamilyMember, admin.site).get_form(request)

    assert Participant._meta.get_field("attendance_tracking_enabled").editable is False
    assert ParticipantFamilyMember._meta.get_field("attendance_tracking_enabled").editable is False
    assert "attendance_tracking_enabled" not in ParticipantForm.base_fields
    assert "attendance_tracking_enabled" not in ParticipantFamilyMemberForm.base_fields
    assert "attendance_tracking_enabled" not in participant_admin_form.base_fields
    assert "attendance_tracking_enabled" not in family_member_admin_form.base_fields


@pytest.mark.django_db
def test_replacing_attendance_days_is_atomic_preserves_overlap_comments_and_removes_shrunk_dates():
    participant = ParticipantFactory()
    replace_attendance_days(
        participant,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
        days=[
            {"date": date(2026, 7, 1), "is_present": True, "comment": "Bleibt"},
            {"date": date(2026, 7, 2), "is_present": True, "comment": "Entfernen"},
        ],
    )
    replace_attendance_days(
        participant,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        days=[{"date": date(2026, 7, 1), "is_present": False}],
    )

    assert list(AttendanceDay.objects.values_list("date", "is_present", "comment")) == [
        (date(2026, 7, 1), False, "Bleibt"),
    ]


@pytest.mark.django_db
def test_attendance_day_requires_a_participant_account_holder():
    with pytest.raises((ValidationError, TypeError)):
        AttendanceDay.objects.create(date=date(2026, 7, 1), is_present=True)


@pytest.mark.django_db
def test_tracked_participant_shift_target_uses_selected_present_nights():
    camp = CampFactory(
        starts_on=date(2026, 7, 1),
        ends_on=date(2026, 7, 7),
        shift_ratio_per_night=Decimal("0.5000"),
    )
    participant = ParticipantFactory(camp=camp, booked_nights=6, actual_nights=6)

    replace_attendance_days(
        participant,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 7),
        days=[{"date": date(2026, 7, day), "is_present": day in {1, 2}} for day in range(1, 7)],
    )

    assert participant.effective_attendance_nights == 2
    assert participant.target_shifts == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("camp_kwargs", "attendance_date"),
    [
        ({"starts_on": date(2026, 7, 1), "ends_on": date(2026, 7, 5)}, date(2026, 6, 26)),
        ({"starts_on": date(2026, 7, 1), "ends_on": None}, date(2026, 6, 26)),
        ({"starts_on": None, "ends_on": date(2026, 7, 5)}, date(2026, 7, 9)),
    ],
)
def test_attendance_day_enforces_configured_camp_window_bounds(camp_kwargs, attendance_date):
    camp = CampFactory(**camp_kwargs)
    participant = ParticipantFactory(
        camp=camp,
        arrival_date=date(2026, 6, 1),
        departure_date=date(2026, 7, 20),
    )

    with pytest.raises(ValidationError, match="Lagerfensters"):
        save_attendance_day(participant, attendance_date, is_present=True)


@pytest.mark.django_db
def test_save_attendance_day_enables_tracking_for_the_exact_target():
    participant = ParticipantFactory(attendance_tracking_enabled=False)

    saved = save_attendance_day(participant, date(2026, 7, 1), is_present=False)

    participant.refresh_from_db()
    assert saved.is_present is False
    assert participant.attendance_tracking_enabled is True
