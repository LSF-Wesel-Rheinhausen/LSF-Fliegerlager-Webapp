from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from billing.models import AttendanceDay, Charge, MealSignup
from billing.permissions import EDITOR_GROUP
from billing.services import calculate_position_report
from tests.factories import (
    CampFactory,
    ChargeFactory,
    GroupFactory,
    ParticipantFactory,
    ParticipantFamilyMemberFactory,
    SuperUserFactory,
    UserFactory,
)

CAMP_START = date(2026, 7, 1)
CAMP_END = date(2026, 7, 4)


@pytest.fixture
def camp(db):
    return CampFactory(starts_on=CAMP_START, ends_on=CAMP_END)


@pytest.mark.django_db
def test_articles_group_by_kind_and_description_with_totals(camp):
    participant = ParticipantFactory(camp=camp)
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Cola",
        quantity=Decimal("2.00"),
        unit_price=Decimal("2.50"),
    )
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.DRINK,
        description="Cola",
        quantity=Decimal("3.00"),
        unit_price=Decimal("2.50"),
    )
    ChargeFactory(
        participant=participant,
        kind=Charge.Kind.FOOD,
        description="Abendessen",
        quantity=Decimal("1.00"),
        unit_price=Decimal("7.00"),
    )

    report = calculate_position_report(camp)

    cola = next(a for a in report.articles if a.description == "Cola")
    assert cola.booking_count == 2
    assert cola.quantity_total == Decimal("5.00")
    assert cola.gross_total == Decimal("12.50")
    assert cola.kind_label == "Getränke"
    assert report.booking_total == 3
    assert report.gross_total == Decimal("19.50")


@pytest.mark.django_db
def test_articles_group_direct_family_and_partner_bookings_by_base_description(camp):
    actor = ParticipantFactory(camp=camp, first_name="Anna", last_name="Adler")
    partner = ParticipantFactory(camp=camp, first_name="Peter", last_name="Partner")
    family_member = ParticipantFamilyMemberFactory(
        guardian=actor,
        first_name="Fiona",
        last_name="Familie",
    )
    base_description = "Apfelschorle (Kiosk)"
    direct_charge = ChargeFactory(
        participant=actor,
        kiosk_booked_by=actor,
        kind=Charge.Kind.DRINK,
        description=base_description,
        position_report_description=base_description,
        quantity=Decimal("1.00"),
        unit_price=Decimal("2.50"),
    )
    family_charge = ChargeFactory(
        participant=actor,
        family_member=family_member,
        kiosk_booked_by=actor,
        kind=Charge.Kind.DRINK,
        description=f"{base_description} für {family_member.full_name}",
        position_report_description=base_description,
        quantity=Decimal("2.00"),
        unit_price=Decimal("2.50"),
    )
    partner_charge = ChargeFactory(
        participant=partner,
        kiosk_booked_by=actor,
        kind=Charge.Kind.DRINK,
        description=f"{base_description} für {partner.full_name}",
        position_report_description=base_description,
        quantity=Decimal("3.00"),
        unit_price=Decimal("2.50"),
    )

    report = calculate_position_report(camp)

    assert len(report.articles) == 1
    article = report.articles[0]
    assert article.kind == Charge.Kind.DRINK
    assert article.kind_label == "Getränke"
    assert article.description == base_description
    assert article.booking_count == 3
    assert article.quantity_total == Decimal("6.00")
    assert article.gross_total == Decimal("15.00")
    assert Charge.objects.get(pk=direct_charge.pk).description == base_description
    assert Charge.objects.get(pk=family_charge.pk).description == f"{base_description} für {family_member.full_name}"
    assert Charge.objects.get(pk=partner_charge.pk).description == f"{base_description} für {partner.full_name}"


@pytest.mark.django_db
def test_article_description_with_natural_target_suffix_without_matching_relation_is_preserved(camp):
    participant = ParticipantFactory(camp=camp, first_name="Nora", last_name="Natürlich")
    description = f"Workshop für {participant.full_name}"
    ChargeFactory(participant=participant, description=description)

    report = calculate_position_report(camp)

    assert [article.description for article in report.articles] == [description]


@pytest.mark.django_db
def test_position_report_uses_persisted_description_and_falls_back_to_ledger_description(camp):
    participant = ParticipantFactory(camp=camp)
    ChargeFactory(
        participant=participant,
        description="Wasser (Kiosk) für Historisches Ziel",
        position_report_description="Wasser (Kiosk)",
    )
    ChargeFactory(
        participant=participant,
        description="Manuelle Sonderbuchung",
        position_report_description=None,
    )

    report = calculate_position_report(camp)

    assert {article.description for article in report.articles} == {
        "Wasser (Kiosk)",
        "Manuelle Sonderbuchung",
    }


@pytest.mark.django_db
def test_manual_family_charge_preserves_natural_description_matching_member_name(client, camp):
    guardian = ParticipantFactory(camp=camp)
    family_member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        first_name="Fiona",
        last_name="Familie",
    )
    description = f"Spende für {family_member.full_name}"
    client.force_login(SuperUserFactory())

    response = client.post(
        reverse("charge-create", args=[guardian.pk]),
        {
            "kind": Charge.Kind.DONATION,
            "description": description,
            "family_member": family_member.pk,
            "quantity": "1",
            "unit_price": "25.00",
            "foerdersatz": "0",
            "occurred_on": "",
        },
    )

    assert response.status_code == 302
    charge = Charge.objects.get(participant=guardian, family_member=family_member)
    assert charge.kiosk_booked_by_id is None
    report = calculate_position_report(camp)
    assert [article.description for article in report.articles] == [description]


@pytest.mark.django_db
def test_family_kiosk_booking_uses_historical_target_suffix_after_member_rename(camp):
    guardian = ParticipantFactory(camp=camp)
    family_member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        first_name="Alt",
        last_name="Familie",
    )
    base_description = "Abendessen"
    historical_description = f"{base_description} für {family_member.full_name}"
    ChargeFactory(
        participant=guardian,
        kiosk_booked_by=guardian,
        kind=Charge.Kind.FOOD,
        description=base_description,
        position_report_description=base_description,
        unit_price=Decimal("8.00"),
    )
    target_charge = ChargeFactory(
        participant=guardian,
        family_member=family_member,
        kiosk_booked_by=guardian,
        kind=Charge.Kind.FOOD,
        description=historical_description,
        position_report_description=base_description,
        unit_price=Decimal("8.00"),
    )
    family_member.first_name = "Neu"
    family_member.save(update_fields=["first_name", "updated_at"])

    report = calculate_position_report(camp)

    assert len(report.articles) == 1
    assert report.articles[0].description == base_description
    assert report.articles[0].booking_count == 2
    assert Charge.objects.get(pk=target_charge.pk).description == historical_description


@pytest.mark.django_db
def test_partner_kiosk_booking_uses_historical_target_suffix_after_participant_rename(camp):
    actor = ParticipantFactory(camp=camp)
    target = ParticipantFactory(camp=camp, first_name="Alt", last_name="Partner")
    base_description = "Apfelschorle (Kiosk)"
    historical_description = f"{base_description} für {target.full_name}"
    ChargeFactory(
        participant=actor,
        kiosk_booked_by=actor,
        kind=Charge.Kind.DRINK,
        description=base_description,
        position_report_description=base_description,
        unit_price=Decimal("2.50"),
    )
    target_charge = ChargeFactory(
        participant=target,
        kiosk_booked_by=actor,
        kind=Charge.Kind.DRINK,
        description=historical_description,
        position_report_description=base_description,
        unit_price=Decimal("2.50"),
    )
    target.first_name = "Neu"
    target.save(update_fields=["first_name", "updated_at"])

    report = calculate_position_report(camp)

    assert len(report.articles) == 1
    assert report.articles[0].description == base_description
    assert report.articles[0].booking_count == 2
    assert Charge.objects.get(pk=target_charge.pk).description == historical_description


@pytest.mark.django_db
def test_kiosk_target_booking_removes_only_last_appended_target_segment(camp):
    guardian = ParticipantFactory(camp=camp)
    family_member = ParticipantFamilyMemberFactory(guardian=guardian)
    base_description = "Workshop für Fortgeschrittene"
    ChargeFactory(
        participant=guardian,
        kiosk_booked_by=guardian,
        description=base_description,
        position_report_description=base_description,
    )
    ChargeFactory(
        participant=guardian,
        family_member=family_member,
        kiosk_booked_by=guardian,
        description=f"{base_description} für {family_member.full_name}",
        position_report_description=base_description,
    )

    report = calculate_position_report(camp)

    assert len(report.articles) == 1
    assert report.articles[0].description == base_description
    assert report.articles[0].booking_count == 2


@pytest.mark.django_db
def test_kiosk_target_booking_preserves_empty_or_malformed_trailing_separator(camp):
    guardian = ParticipantFactory(camp=camp)
    family_member = ParticipantFamilyMemberFactory(guardian=guardian)
    descriptions = ["Artikel für ", "Artikel für", " für Historisches Ziel"]
    for description in descriptions:
        ChargeFactory(
            participant=guardian,
            family_member=family_member,
            kiosk_booked_by=guardian,
            description=description,
        )

    report = calculate_position_report(camp)

    assert {article.description for article in report.articles} == set(descriptions)


@pytest.mark.django_db
def test_articles_are_sorted_by_booking_count_descending(camp):
    participant = ParticipantFactory(camp=camp)
    ChargeFactory(participant=participant, description="Selten", quantity=Decimal("1.00"))
    for _ in range(3):
        ChargeFactory(participant=participant, description="Haeufig", quantity=Decimal("1.00"))

    report = calculate_position_report(camp)

    assert [a.description for a in report.articles] == ["Haeufig", "Selten"]


@pytest.mark.django_db
def test_soft_deleted_charges_are_excluded_from_articles(camp):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(camp=camp)
    ChargeFactory(participant=participant, description="Aktiv", unit_price=Decimal("5.00"))
    deleted = ChargeFactory(participant=participant, description="Geloescht", unit_price=Decimal("99.00"))
    deleted.deleted_at = timezone.now()
    deleted.deleted_by = admin
    deleted.save(update_fields=["deleted_at", "deleted_by"])

    report = calculate_position_report(camp)

    assert [a.description for a in report.articles] == ["Aktiv"]
    assert report.gross_total == Decimal("5.00")


@pytest.mark.django_db
def test_charges_from_other_camps_are_excluded(camp):
    other_camp = CampFactory(name="Anderes Lager", starts_on=CAMP_START, ends_on=CAMP_END)
    ChargeFactory(participant=ParticipantFactory(camp=camp), description="Eigen")
    ChargeFactory(participant=ParticipantFactory(camp=other_camp), description="Fremd")

    report = calculate_position_report(camp)

    assert [a.description for a in report.articles] == ["Eigen"]


@pytest.mark.django_db
def test_meal_totals_count_active_signups_by_variant(camp):
    participant = ParticipantFactory(camp=camp)
    for meal_date, variant in [
        (CAMP_START, MealSignup.Variant.NORMAL),
        (CAMP_START, MealSignup.Variant.VEGAN),
    ]:
        MealSignup.objects.create(
            participant=participant,
            meal_date=meal_date if variant == MealSignup.Variant.NORMAL else CAMP_END,
            meal=MealSignup.Meal.DINNER,
            variant=variant,
        )
    MealSignup.objects.create(
        participant=participant,
        meal_date=CAMP_START,
        meal=MealSignup.Meal.BREAKFAST,
        variant=MealSignup.Variant.NORMAL,
    )

    report = calculate_position_report(camp)

    dinner = next(m for m in report.meals if m.meal == MealSignup.Meal.DINNER)
    breakfast = next(m for m in report.meals if m.meal == MealSignup.Meal.BREAKFAST)
    assert dinner.total == 2
    assert dinner.variant_counts["Mit Fleisch"] == 1
    assert dinner.variant_counts["Vegan"] == 1
    assert breakfast.total == 1
    assert dinner.meal_label == "Abendessen"


@pytest.mark.django_db
def test_retracted_meal_signups_are_excluded(camp):
    participant = ParticipantFactory(camp=camp)
    MealSignup.objects.create(
        participant=participant,
        meal_date=CAMP_START,
        meal=MealSignup.Meal.DINNER,
        variant=MealSignup.Variant.NORMAL,
        status=MealSignup.Status.RETRACTED,
    )

    report = calculate_position_report(camp)

    dinner = next(m for m in report.meals if m.meal == MealSignup.Meal.DINNER)
    assert dinner.total == 0


@pytest.mark.django_db
def test_attendance_counts_people_inside_their_stay_window(camp):
    ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=date(2026, 7, 2))
    ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=CAMP_END)

    report = calculate_position_report(camp)

    counts = {day.day: day.total for day in report.attendance_days}
    assert counts == {
        date(2026, 7, 1): 1,
        date(2026, 7, 2): 1,
        date(2026, 7, 3): 1,
        date(2026, 7, 4): 1,
    }


@pytest.mark.django_db
def test_attendance_counts_family_members_individually(camp):
    guardian = ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=CAMP_END)
    ParticipantFamilyMemberFactory(guardian=guardian, arrival_date=CAMP_START, departure_date=CAMP_END)
    ParticipantFamilyMemberFactory(guardian=guardian, arrival_date=CAMP_START, departure_date=CAMP_END)

    report = calculate_position_report(camp)

    first_day = report.attendance_days[0]
    assert first_day.participant_count == 1
    assert first_day.family_member_count == 2
    assert first_day.total == 3


@pytest.mark.django_db
def test_family_member_without_dates_falls_back_to_guardian_window(camp):
    guardian = ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=date(2026, 7, 2))
    ParticipantFamilyMemberFactory(guardian=guardian, arrival_date=None, departure_date=None)

    report = calculate_position_report(camp)

    counts = {day.day: day.family_member_count for day in report.attendance_days}
    assert counts[date(2026, 7, 1)] == 1
    assert counts[date(2026, 7, 2)] == 1
    assert counts[date(2026, 7, 3)] == 0


@pytest.mark.django_db
def test_people_without_any_dates_are_not_counted_as_present(camp):
    ParticipantFactory(camp=camp, arrival_date=None, departure_date=None)

    report = calculate_position_report(camp)

    assert all(day.total == 0 for day in report.attendance_days)
    assert report.peak_day is None


@pytest.mark.django_db
def test_archived_participants_and_inactive_members_are_excluded(camp):
    archived = ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=CAMP_END)
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    guardian = ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=CAMP_END)
    ParticipantFamilyMemberFactory(
        guardian=guardian,
        arrival_date=CAMP_START,
        departure_date=CAMP_END,
        is_active=False,
    )

    report = calculate_position_report(camp)

    first_day = report.attendance_days[0]
    assert first_day.participant_count == 1
    assert first_day.family_member_count == 0


@pytest.mark.django_db
def test_active_family_member_of_archived_guardian_is_excluded(camp):
    guardian = ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=CAMP_END)
    guardian.archived_at = timezone.now()
    guardian.save(update_fields=["archived_at"])
    ParticipantFamilyMemberFactory(
        guardian=guardian,
        arrival_date=CAMP_START,
        departure_date=CAMP_END,
        is_active=True,
    )

    report = calculate_position_report(camp)

    assert report.family_member_nights == 0
    assert all(day.family_member_count == 0 for day in report.attendance_days)


@pytest.mark.django_db
def test_person_nights_prefer_actual_and_fall_back_to_booked(camp):
    ParticipantFactory(camp=camp, booked_nights=5, actual_nights=3)
    ParticipantFactory(camp=camp, booked_nights=4, actual_nights=0)

    report = calculate_position_report(camp)

    assert report.participant_nights == 7


@pytest.mark.django_db
def test_family_member_nights_use_their_own_window_then_guardian(camp):
    guardian = ParticipantFactory(camp=camp, booked_nights=6, actual_nights=0)
    ParticipantFamilyMemberFactory(
        guardian=guardian,
        arrival_date=CAMP_START,
        departure_date=date(2026, 7, 3),
    )
    ParticipantFamilyMemberFactory(guardian=guardian, arrival_date=None, departure_date=None)

    report = calculate_position_report(camp)

    assert report.family_member_nights == 8
    assert report.person_nights == report.participant_nights + report.family_member_nights


@pytest.mark.django_db
def test_tracked_family_member_nights_use_effective_attendance(camp):
    guardian = ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=CAMP_END)
    member = ParticipantFamilyMemberFactory(
        guardian=guardian,
        arrival_date=CAMP_START,
        departure_date=CAMP_END,
        attendance_tracking_enabled=True,
    )
    AttendanceDay.objects.create(
        participant=guardian,
        family_member=member,
        date=CAMP_START,
        is_present=True,
    )

    report = calculate_position_report(camp)

    assert member.booked_nights == 3
    assert member.effective_attendance_nights == 1
    assert report.family_member_nights == 1


@pytest.mark.django_db
def test_peak_day_reports_the_busiest_day(camp):
    ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=CAMP_END)
    ParticipantFactory(camp=camp, arrival_date=date(2026, 7, 3), departure_date=CAMP_END)

    report = calculate_position_report(camp)

    assert report.peak_day is not None
    assert report.peak_day.day == date(2026, 7, 3)
    assert report.peak_day.total == 2


@pytest.mark.django_db
def test_report_view_renders_all_sections_for_admins(client, camp):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    participant = ParticipantFactory(camp=camp, arrival_date=CAMP_START, departure_date=CAMP_END)
    ChargeFactory(participant=participant, description="Cola", unit_price=Decimal("2.50"))
    client.force_login(admin)

    response = client.get(reverse("camp-position-report", args=[camp.pk]))
    page = response.content.decode()

    assert response.status_code == 200
    assert "Positionsauswertung" in page
    assert "Buchungen je Artikel" in page
    assert "Mahlzeiten gesamt" in page
    assert "Anwesenheit pro Tag" in page
    assert "Anwesenheitstage gesamt" in page
    assert "Cola" in page


@pytest.mark.django_db
def test_report_view_is_denied_to_editors(client, camp):
    editor = UserFactory(username="editor")
    editor.groups.add(GroupFactory(name=EDITOR_GROUP))
    client.force_login(editor)

    response = client.get(reverse("camp-position-report", args=[camp.pk]))

    assert response.status_code == 302
    assert reverse("login") in response["Location"]


@pytest.mark.django_db
def test_camp_detail_links_to_report_for_admins(client, camp):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    client.force_login(admin)

    page = client.get(reverse("camp-detail", args=[camp.pk])).content.decode()

    assert reverse("camp-position-report", args=[camp.pk]) in page
    assert page.count("Positionsauswertung") == 1


@pytest.mark.django_db
def test_empty_camp_renders_without_errors(client, camp):
    admin = SuperUserFactory(username="admin", email="admin@example.test")
    client.force_login(admin)

    report = calculate_position_report(camp)
    response = client.get(reverse("camp-position-report", args=[camp.pk]))

    assert response.status_code == 200
    assert report.articles == []
    assert report.booking_total == 0
    assert report.person_nights == 0
    assert len(report.attendance_days) == 4
    assert b"Keine Buchungen in diesem Lager erfasst." in response.content


@pytest.mark.django_db
def test_position_report_query_budget_is_bounded_as_camp_size_grows(camp):
    def populate(camp, count):
        for index in range(count):
            participant = ParticipantFactory(
                camp=camp,
                first_name=f"Teilnehmer{index}",
                arrival_date=CAMP_START,
                departure_date=CAMP_END,
            )
            member = ParticipantFamilyMemberFactory(
                guardian=participant,
                first_name=f"Familie{index}",
                arrival_date=CAMP_START,
                departure_date=CAMP_END,
                attendance_tracking_enabled=True,
            )
            ChargeFactory(
                participant=participant,
                family_member=member,
                description=f"Artikel{index} für {member.full_name}",
            )
            MealSignup.objects.create(
                participant=participant,
                meal_date=CAMP_START,
                meal=MealSignup.Meal.DINNER,
                variant=MealSignup.Variant.NORMAL,
            )

    populate(camp, 1)
    with CaptureQueriesContext(connection) as small_queries:
        calculate_position_report(camp)

    larger_camp = CampFactory(starts_on=CAMP_START, ends_on=CAMP_END, name="Großes Lager")
    populate(larger_camp, 4)
    with CaptureQueriesContext(connection) as large_queries:
        calculate_position_report(larger_camp)

    assert len(large_queries) == len(small_queries)
