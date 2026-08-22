from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from billing.models import Charge, Expense, ParticipantFamilyMember, Settlement, SettlementRun
from billing.views import KIOSK_MODE_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY
from tests.factories import CampFactory, ExpenseFactory, ParticipantFactory, PriceRuleFactory, SuperUserFactory


@pytest.mark.django_db
def test_camp_phase_model_methods():
    today = timezone.localdate()
    pre_camp = CampFactory(year=2024, starts_on=today + timedelta(days=10), ends_on=today + timedelta(days=20))
    active_camp = CampFactory(year=2025, starts_on=today - timedelta(days=2), ends_on=today + timedelta(days=5))
    post_camp = CampFactory(year=2026, starts_on=today - timedelta(days=20), ends_on=today - timedelta(days=5))

    assert pre_camp.is_pre_camp(today) is True
    assert pre_camp.is_post_camp(today) is False
    assert pre_camp.days_until_start(today) == 10

    assert active_camp.is_pre_camp(today) is False
    assert active_camp.is_post_camp(today) is False

    assert post_camp.is_pre_camp(today) is False
    assert post_camp.is_post_camp(today) is True


@pytest.mark.django_db
def test_kiosk_pre_camp_renders_countdown_and_rejects_date_updates(kiosk_client):
    today = timezone.localdate()
    camp = CampFactory(is_active=True, starts_on=today + timedelta(days=7), ends_on=today + timedelta(days=14))
    participant = ParticipantFactory(camp=camp, arrival_date=camp.starts_on, departure_date=camp.ends_on)

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    assert response.status_code == 200
    assert b"Lagerbeginn" in response.content
    assert b"Noch 7 Tage bis Lagerbeginn" in response.content
    assert b"Dein geplanter Anmeldezeitraum" not in response.content

    new_arrival = (today + timedelta(days=8)).isoformat()
    new_departure = (today + timedelta(days=13)).isoformat()
    res_post = kiosk_client.post(
        reverse("kiosk-home"),
        {
            "action": "update_attendance_dates",
            "arrival_date": new_arrival,
            "departure_date": new_departure,
        },
        follow=True,
    )
    assert res_post.status_code == 200
    assert "Diese Funktion ist erst ab Lagerbeginn verfügbar." in res_post.content.decode("utf-8")
    participant.refresh_from_db()
    assert participant.arrival_date == camp.starts_on
    assert participant.departure_date == camp.ends_on


@pytest.mark.django_db
def test_kiosk_post_camp_renders_screen_and_settlement_archive(kiosk_client):
    admin = SuperUserFactory()
    today = timezone.localdate()
    camp = CampFactory(is_active=True, starts_on=today - timedelta(days=20), ends_on=today - timedelta(days=5))
    participant = ParticipantFactory(camp=camp)

    run = SettlementRun.objects.create(camp=camp, version=1, calculated_by=admin)
    settlement = Settlement.objects.create(
        run=run,
        participant=participant,
        total_due=Decimal("100.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("100.00"),
    )

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    assert response.status_code == 200
    assert b"Lager beendet" in response.content
    assert b"Letzte Abrechnung herunterladen" in response.content
    assert reverse("kiosk-settlement-pdf", args=[settlement.pk]).encode() in response.content


@pytest.mark.django_db
def test_kiosk_post_camp_renders_one_read_only_invoice_area(kiosk_client):
    admin = SuperUserFactory()
    today = timezone.localdate()
    camp = CampFactory(
        is_active=True,
        starts_on=today - timedelta(days=20),
        ends_on=today - timedelta(days=5),
        show_kiosk_invoices=True,
    )
    participant = ParticipantFactory(camp=camp)
    ExpenseFactory(
        camp=camp,
        participant=participant,
        description="Grillgut",
        status=Expense.Status.PENDING,
    )
    run = SettlementRun.objects.create(camp=camp, version=1, calculated_by=admin)
    Settlement.objects.create(
        run=run,
        participant=participant,
        total_due=Decimal("100.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("100.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert content.count("Lager beendet") == 1
    assert "Meine Rechnungen &amp; Dokumente" not in content
    assert "Grillgut" in content
    assert "Antrag einreichen" not in content
    assert "Getränk buchen" not in content
    assert "Verpflegung buchen" not in content
    assert "Check-in" not in content
    assert "Dienste" not in content
    assert "Familie" not in content
    assert "Mitbuchungen" not in content


@pytest.mark.django_db
def test_kiosk_post_camp_hides_invoice_actions_when_admin_disabled_them(kiosk_client):
    today = timezone.localdate()
    camp = CampFactory(
        is_active=True,
        starts_on=today - timedelta(days=20),
        ends_on=today - timedelta(days=5),
        show_kiosk_invoices=False,
    )
    participant = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Lager beendet" in content
    assert "Abrechnung herunterladen" not in content
    assert "Aktuelle Abrechnung" not in content
    assert kiosk_client.get(reverse("kiosk-current-settlement-pdf")).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("kiosk_mode,route_name", [("private", "kiosk-home"), ("central", "central-kiosk-home")])
@pytest.mark.parametrize(
    "action",
    [
        "quick",
        "quick_cancel",
        "meal",
        "meal_retract",
        "family_member_create",
        "family_member_deactivate",
        "booking_link_invite",
        "booking_link_accept",
        "booking_link_decline",
        "booking_link_revoke",
        "update_attendance_dates",
    ],
)
def test_kiosk_post_camp_rejects_every_home_write_action(kiosk_client, kiosk_mode, route_name, action):
    today = timezone.localdate()
    camp = CampFactory(is_active=True, starts_on=today - timedelta(days=20), ends_on=today - timedelta(days=1))
    participant = ParticipantFactory(camp=camp)
    PriceRuleFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = kiosk_mode
    session.save()

    response = kiosk_client.post(reverse(route_name), {"action": action}, follow=True)

    assert response.status_code == 200
    assert "Das Lager ist beendet. Änderungen sind nicht mehr möglich." in response.content.decode("utf-8")
    assert Charge.objects.filter(participant=participant).count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("kiosk_mode,route_name", [("private", "kiosk-home"), ("central", "central-kiosk-home")])
def test_kiosk_post_camp_keeps_checkin_available_during_attendance_buffer(kiosk_client, kiosk_mode, route_name):
    """#417 permits attendance updates through the four-day post-camp buffer."""
    today = timezone.localdate()
    camp = CampFactory(is_active=True, starts_on=today - timedelta(days=20), ends_on=today - timedelta(days=1))
    participant = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = kiosk_mode
    session.save()

    response = kiosk_client.post(reverse(route_name), {"action": "checkin"}, follow=True)

    assert response.status_code == 200
    assert "Das Lager ist beendet. Änderungen sind nicht mehr möglich." not in response.content.decode("utf-8")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "route_name,method",
    [
        ("kiosk-shifts", "get"),
        ("central-kiosk-shifts", "get"),
        ("kiosk-shared-expense-request", "post"),
        ("central-kiosk-shared-expense-request", "post"),
    ],
)
def test_kiosk_post_camp_blocks_separate_write_workflows(kiosk_client, route_name, method):
    today = timezone.localdate()
    camp = CampFactory(is_active=True, starts_on=today - timedelta(days=20), ends_on=today - timedelta(days=1))
    participant = ParticipantFactory(camp=camp)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()

    response = getattr(kiosk_client, method)(reverse(route_name), follow=True)

    assert response.status_code == 200
    assert "Das Lager ist beendet. Änderungen sind nicht mehr möglich." in response.content.decode("utf-8")
    assert Expense.objects.filter(participant=participant).count() == 0


@pytest.mark.django_db
def test_kiosk_settlement_pdf_download_permissions(kiosk_client):
    admin = SuperUserFactory()
    camp = CampFactory(is_active=True)
    participant = ParticipantFactory(camp=camp)
    other_participant = ParticipantFactory(camp=camp)

    run = SettlementRun.objects.create(camp=camp, version=1, calculated_by=admin)
    own_settlement = Settlement.objects.create(
        run=run,
        participant=participant,
        total_due=Decimal("50.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("50.00"),
    )
    other_settlement = Settlement.objects.create(
        run=run,
        participant=other_participant,
        total_due=Decimal("75.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("75.00"),
    )

    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    # 1. Download own settlement -> 200 PDF
    res_own = kiosk_client.get(reverse("kiosk-settlement-pdf", args=[own_settlement.pk]))
    assert res_own.status_code == 200
    assert res_own["Content-Type"] == "application/pdf"

    # 2. Try downloading another participant's settlement -> 403 Forbidden
    res_other = kiosk_client.get(reverse("kiosk-settlement-pdf", args=[other_settlement.pk]))
    assert res_other.status_code == 403

    # 3. Live current settlement -> 200 PDF
    res_live = kiosk_client.get(reverse("kiosk-current-settlement-pdf"))
    assert res_live.status_code == 200
    assert res_live["Content-Type"] == "application/pdf"


@pytest.mark.django_db
@pytest.mark.parametrize("identity_collision", ["email", "name", "family_member"])
def test_kiosk_settlement_pdf_rejects_attribute_based_identity_matches(kiosk_client, identity_collision):
    admin = SuperUserFactory()
    active_camp = CampFactory(name="Aktuelles Lager", year=2026, is_active=True)
    historic_camp = CampFactory(name="Früheres Lager", year=2025, is_active=False)
    participant = ParticipantFactory(
        camp=active_camp,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.test",
    )
    settlement_owner = ParticipantFactory(
        camp=historic_camp,
        first_name="Grace",
        last_name="Hopper",
        email="grace@example.test",
    )
    if identity_collision == "email":
        settlement_owner.email = participant.email
        settlement_owner.save(update_fields=["email", "updated_at"])
    elif identity_collision == "name":
        settlement_owner.first_name = participant.first_name
        settlement_owner.last_name = participant.last_name
        settlement_owner.save(update_fields=["first_name", "last_name", "updated_at"])
    else:
        ParticipantFamilyMember.objects.create(
            guardian=participant,
            first_name=settlement_owner.first_name,
            last_name=settlement_owner.last_name,
            role=ParticipantFamilyMember.Role.COMPANION,
        )

    run = SettlementRun.objects.create(camp=historic_camp, version=1, calculated_by=admin)
    foreign_settlement = Settlement.objects.create(
        run=run,
        participant=settlement_owner,
        total_due=Decimal("75.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("75.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    response = kiosk_client.get(reverse("kiosk-settlement-pdf", args=[foreign_settlement.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("identity_collision", ["email", "name"])
def test_kiosk_home_lists_only_exact_participant_settlements(kiosk_client, identity_collision):
    admin = SuperUserFactory()
    active_camp = CampFactory(name="Aktuelles Lager", year=2026, is_active=True)
    historic_camp = CampFactory(name="Früheres Lager", year=2025, is_active=False)
    participant = ParticipantFactory(
        camp=active_camp,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.test",
    )
    settlement_owner = ParticipantFactory(
        camp=historic_camp,
        first_name="Grace",
        last_name="Hopper",
        email="grace@example.test",
    )
    if identity_collision == "email":
        settlement_owner.email = participant.email
        settlement_owner.save(update_fields=["email", "updated_at"])
    else:
        participant.email = ""
        participant.save(update_fields=["email", "updated_at"])
        settlement_owner.first_name = participant.first_name
        settlement_owner.last_name = participant.last_name
        settlement_owner.email = ""
        settlement_owner.save(update_fields=["first_name", "last_name", "email", "updated_at"])

    current_run = SettlementRun.objects.create(camp=active_camp, version=1, calculated_by=admin)
    own_settlement = Settlement.objects.create(
        run=current_run,
        participant=participant,
        total_due=Decimal("50.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("50.00"),
    )
    historic_run = SettlementRun.objects.create(camp=historic_camp, version=1, calculated_by=admin)
    Settlement.objects.create(
        run=historic_run,
        participant=settlement_owner,
        total_due=Decimal("75.00"),
        total_paid=Decimal("0.00"),
        total_advanced=Decimal("0.00"),
        balance=Decimal("75.00"),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    response = kiosk_client.get(reverse("kiosk-home"))

    assert response.status_code == 200
    assert [settlement.pk for settlement in response.context["historic_settlements"]] == [own_settlement.pk]
