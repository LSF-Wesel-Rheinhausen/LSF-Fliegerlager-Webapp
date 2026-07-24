from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from billing.models import Settlement, SettlementRun
from billing.views import KIOSK_MODE_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY
from tests.factories import CampFactory, ParticipantFactory, SuperUserFactory


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
def test_kiosk_pre_camp_renders_countdown_and_updates_dates(client):
    today = timezone.localdate()
    camp = CampFactory(is_active=True, starts_on=today + timedelta(days=7), ends_on=today + timedelta(days=14))
    participant = ParticipantFactory(camp=camp, arrival_date=camp.starts_on, departure_date=camp.ends_on)

    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    # 1. Render Pre-Camp home
    response = client.get(reverse("kiosk-home"))
    assert response.status_code == 200
    assert b"Vor dem Fliegerlager" in response.content
    assert b"Noch 7 Tage bis Lagerbeginn!" in response.content

    # 2. Update attendance dates
    new_arrival = (today + timedelta(days=8)).isoformat()
    new_departure = (today + timedelta(days=13)).isoformat()
    res_post = client.post(
        reverse("kiosk-home"),
        {
            "action": "update_attendance_dates",
            "arrival_date": new_arrival,
            "departure_date": new_departure,
        },
    )
    assert res_post.status_code == 302
    participant.refresh_from_db()
    assert participant.arrival_date == date.fromisoformat(new_arrival)
    assert participant.departure_date == date.fromisoformat(new_departure)


@pytest.mark.django_db
def test_kiosk_post_camp_renders_screen_and_settlement_archive(client):
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

    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    response = client.get(reverse("kiosk-home"))
    assert response.status_code == 200
    assert b"Lager beendet" in response.content
    assert b"Letzte Abrechnung herunterladen" in response.content
    assert reverse("kiosk-settlement-pdf", args=[settlement.pk]).encode() in response.content


@pytest.mark.django_db
def test_kiosk_settlement_pdf_download_permissions(client):
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

    session = client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session[KIOSK_MODE_SESSION_KEY] = "private"
    session.save()

    # 1. Download own settlement -> 200 PDF
    res_own = client.get(reverse("kiosk-settlement-pdf", args=[own_settlement.pk]))
    assert res_own.status_code == 200
    assert res_own["Content-Type"] == "application/pdf"

    # 2. Try downloading another participant's settlement -> 403 Forbidden
    res_other = client.get(reverse("kiosk-settlement-pdf", args=[other_settlement.pk]))
    assert res_other.status_code == 403

    # 3. Live current settlement -> 200 PDF
    res_live = client.get(reverse("kiosk-current-settlement-pdf"))
    assert res_live.status_code == 200
    assert res_live["Content-Type"] == "application/pdf"
