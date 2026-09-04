import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from billing.models import Camp, Participant, ParticipantFamilyMember, Shift, ShiftAssignment
from billing.views import KIOSK_FAMILY_MEMBER_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY


@pytest.fixture
def active_camp(db):
    return Camp.objects.create(
        name="Test Camp",
        year=datetime.date.today().year,
        starts_on=datetime.date.today() - datetime.timedelta(days=1),
        ends_on=datetime.date.today() + datetime.timedelta(days=10),
        is_active=True,
    )


@pytest.fixture
def logged_in_kiosk_client(kiosk_client, active_camp):
    p = Participant.objects.create(camp=active_camp, first_name="Kiosk", last_name="User")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = p.pk
    session.save()
    kiosk_client.kiosk_user = p
    return kiosk_client


@pytest.fixture
def pre_camp_kiosk_client(kiosk_client):
    camp = Camp.objects.create(
        name="Future Camp",
        year=datetime.date.today().year + 1,
        starts_on=datetime.date.today() + datetime.timedelta(days=7),
        ends_on=datetime.date.today() + datetime.timedelta(days=14),
        is_active=True,
    )
    participant = Participant.objects.create(camp=camp, first_name="Kiosk", last_name="User")
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    session.save()
    kiosk_client.kiosk_user = participant
    return kiosk_client


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "home_route_name"),
    [("kiosk-shifts", "kiosk-home"), ("central-kiosk-shifts", "central-kiosk-home")],
)
def test_pre_camp_kiosk_shift_pages_redirect_home(pre_camp_kiosk_client, route_name, home_route_name):
    response = pre_camp_kiosk_client.get(reverse(route_name))

    assert response.status_code == 302
    assert response.url == reverse(home_route_name)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "home_route_name"),
    [("kiosk-shifts", "kiosk-home"), ("central-kiosk-shifts", "central-kiosk-home")],
)
def test_pre_camp_kiosk_shift_posts_cannot_create_assignments(pre_camp_kiosk_client, route_name, home_route_name):
    participant = pre_camp_kiosk_client.kiosk_user
    shift = Shift.objects.create(
        camp=participant.camp,
        name="Future Shift",
        date=participant.camp.starts_on,
        required_slots=1,
    )

    response = pre_camp_kiosk_client.post(
        reverse(route_name),
        {"action": "signup", "shift_id": shift.pk},
    )

    assert response.status_code == 302
    assert response.url == reverse(home_route_name)
    assert not ShiftAssignment.objects.filter(shift=shift, participant=participant).exists()


@pytest.mark.django_db
def test_kiosk_can_signup_for_shift(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert ShiftAssignment.objects.filter(shift=shift, participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_every_shift_category_exposes_description_info_button(logged_in_kiosk_client, active_camp):
    """Each rendered shift card carries its own safe description and dialog title."""
    today = timezone.localdate()
    open_shift = Shift.objects.create(
        camp=active_camp,
        name="Offener Dienst",
        date=today + datetime.timedelta(days=2),
        required_slots=1,
        description="Offene Beschreibung",
    )
    own_shift = Shift.objects.create(
        camp=active_camp,
        name="Eigener Dienst",
        date=today + datetime.timedelta(days=3),
        required_slots=1,
        description="Eigene Beschreibung",
    )
    ShiftAssignment.objects.create(shift=own_shift, participant=logged_in_kiosk_client.kiosk_user)
    offered_shift = Shift.objects.create(
        camp=active_camp,
        name="Angebotener Dienst",
        date=today + datetime.timedelta(days=4),
        required_slots=1,
        description="Angebotene Beschreibung",
    )
    other = Participant.objects.create(camp=active_camp, first_name="Andere", last_name="Person")
    ShiftAssignment.objects.create(shift=offered_shift, participant=other, offered_for_exchange=True)

    content = logged_in_kiosk_client.get(reverse("kiosk-shifts")).content.decode()

    for shift in (open_shift, own_shift, offered_shift):
        assert f'aria-label="Informationen zu {shift.name}"' in content
        assert f'data-help-title="Informationen zu {shift.name}"' in content
        assert f'data-help-text="{shift.description}"' in content
    assert content.count('class="kiosk-help-button kiosk-help-button--shift"') == 3


@pytest.mark.django_db
def test_shift_info_button_uses_fallback_and_escapes_script_like_description(logged_in_kiosk_client, active_camp):
    Shift.objects.create(
        camp=active_camp,
        name="Unbeschriebener Dienst",
        date=timezone.localdate() + datetime.timedelta(days=2),
        required_slots=1,
    )
    malicious_description = '<script>alert("xss")</script>'
    Shift.objects.create(
        camp=active_camp,
        name="Sicherer Dienst",
        date=timezone.localdate() + datetime.timedelta(days=3),
        required_slots=1,
        description=malicious_description,
    )

    content = logged_in_kiosk_client.get(reverse("kiosk-shifts")).content.decode()

    assert 'data-help-text="Für diesen Dienst sind noch keine Informationen hinterlegt."' in content
    assert 'data-help-text="&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;"' in content
    assert malicious_description not in content


@pytest.mark.django_db
def test_companion_can_book_own_shift_without_replacing_guardian_assignment(kiosk_client, active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Companion",
        last_name="User",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shift = Shift.objects.create(
        camp=active_camp,
        name="Gemeinsamer Dienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=2,
    )
    guardian_assignment = ShiftAssignment.objects.create(shift=shift, participant=guardian)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = guardian.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})

    assert response.status_code == 302
    assert ShiftAssignment.objects.filter(shift=shift).count() == 2
    assert ShiftAssignment.objects.filter(shift=shift, participant=guardian, family_member=companion).exists()
    guardian_assignment.refresh_from_db()
    assert guardian_assignment.family_member_id is None
    assert guardian.completed_shifts == 1

    duplicate_response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})

    assert duplicate_response.status_code == 302
    assert ShiftAssignment.objects.filter(shift=shift, participant=guardian, family_member=companion).count() == 1


@pytest.mark.django_db
def test_companion_bulk_signup_keeps_companion_identity(kiosk_client, active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Companion",
        last_name="User",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shifts = [
        Shift.objects.create(
            camp=active_camp,
            name=f"Bulk Shift {index}",
            date=datetime.date.today() + datetime.timedelta(days=index + 1),
        )
        for index in range(2)
    ]
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = guardian.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    response = kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(shift.pk) for shift in shifts]},
    )

    assert response.status_code == 302
    assert list(
        ShiftAssignment.objects.filter(participant=guardian, family_member=companion)
        .order_by("shift_id")
        .values_list("shift_id", flat=True)
    ) == [shift.pk for shift in shifts]


@pytest.mark.django_db
@pytest.mark.parametrize(("age_seconds", "should_retract"), [(14 * 60, True), (15 * 60 - 1, True), (16 * 60, False)])
def test_companion_retract_boundary_uses_companion_assignment(
    kiosk_client, active_camp, age_seconds, should_retract, monkeypatch
):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Companion",
        last_name="User",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shift = Shift.objects.create(
        camp=active_camp,
        name="Companion Retract",
        date=datetime.date.today() + datetime.timedelta(days=1),
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=guardian, family_member=companion)
    fixed_now = timezone.now()
    ShiftAssignment.objects.filter(pk=assignment.pk).update(
        created_at=fixed_now - datetime.timedelta(seconds=age_seconds)
    )
    monkeypatch.setattr("billing.views.timezone.now", lambda: fixed_now)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = guardian.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "retract", "shift_id": shift.pk})

    assert response.status_code == 302
    assert ShiftAssignment.objects.filter(pk=assignment.pk).exists() is not should_retract


@pytest.mark.django_db
def test_companion_can_offer_revoke_and_take_without_guardian_self_exchange(kiosk_client, active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Companion",
        last_name="User",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    own_shift = Shift.objects.create(camp=active_camp, name="Own Exchange", date=datetime.date.today())
    own_assignment = ShiftAssignment.objects.create(shift=own_shift, participant=guardian, family_member=companion)
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    offered_shift = Shift.objects.create(camp=active_camp, name="Take Exchange", date=datetime.date.today())
    ShiftAssignment.objects.create(shift=offered_shift, participant=other, offered_for_exchange=True)
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = guardian.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    assert kiosk_client.post(reverse("kiosk-shifts"), {"action": "offer", "shift_id": own_shift.pk}).status_code == 302
    own_assignment.refresh_from_db()
    assert own_assignment.offered_for_exchange is True
    assert (
        kiosk_client.post(reverse("kiosk-shifts"), {"action": "revoke_offer", "shift_id": own_shift.pk}).status_code
        == 302
    )
    own_assignment.refresh_from_db()
    assert own_assignment.offered_for_exchange is False

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": offered_shift.pk})

    assert response.status_code == 302
    takeover = ShiftAssignment.objects.get(shift=offered_shift)
    assert takeover.participant_id == guardian.pk
    assert takeover.family_member_id == companion.pk


@pytest.mark.django_db
def test_companion_can_take_sibling_companion_offer_but_not_own_identity(kiosk_client, active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    offered_companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Offered",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    taking_companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Taking",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shift = Shift.objects.create(
        camp=active_camp,
        name="Sibling Exchange",
        date=datetime.date.today(),
        required_slots=1,
    )
    offered_assignment = ShiftAssignment.objects.create(
        shift=shift,
        participant=guardian,
        family_member=offered_companion,
        offered_for_exchange=True,
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = guardian.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = taking_companion.pk
    session.save()

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})

    assert response.status_code == 302
    takeover = ShiftAssignment.objects.get(pk=offered_assignment.pk)
    assert takeover.family_member_id == taking_companion.pk
    assert "Offered Companion" in " ".join(message.message for message in response.wsgi_request._messages)


@pytest.mark.django_db
def test_shift_assignment_integrity_is_enforced_for_bulk_create_and_queryset_update(active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    foreign_guardian = Participant.objects.create(camp=active_camp, first_name="Foreign", last_name="User")
    foreign_companion = ParticipantFamilyMember.objects.create(
        guardian=foreign_guardian,
        first_name="Foreign",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shift = Shift.objects.create(camp=active_camp, name="Integrity", date=datetime.date.today())

    with pytest.raises(ValidationError, match="Begleitung gehört nicht zum Teilnehmerkonto"):
        ShiftAssignment.objects.bulk_create(
            [ShiftAssignment(shift=shift, participant=guardian, family_member=foreign_companion)]
        )

    assignment = ShiftAssignment.objects.create(shift=shift, participant=guardian)
    with pytest.raises(ValidationError, match="Identitätsänderungen"):
        ShiftAssignment.objects.filter(pk=assignment.pk).update(family_member=foreign_companion)


@pytest.mark.django_db
def test_shift_assignment_uniqueness_keeps_legacy_null_and_family_branches(active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Companion",
        last_name="User",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    second_companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Second",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shift = Shift.objects.create(camp=active_camp, name="Unique", date=datetime.date.today())

    legacy_assignment = ShiftAssignment.objects.create(shift=shift, participant=guardian)
    ShiftAssignment.objects.create(shift=shift, participant=guardian, family_member=companion)
    ShiftAssignment.objects.create(shift=shift, participant=guardian, family_member=second_companion)

    assert legacy_assignment.family_member_id is None
    with pytest.raises(ValidationError):
        ShiftAssignment.objects.create(shift=shift, participant=guardian)
    with pytest.raises(ValidationError):
        ShiftAssignment.objects.create(shift=shift, participant=guardian, family_member=companion)


@pytest.mark.django_db
def test_shift_assignment_rejects_companion_from_another_guardian(active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    foreign_guardian = Participant.objects.create(camp=active_camp, first_name="Other", last_name="Guardian")
    foreign_companion = ParticipantFamilyMember.objects.create(
        guardian=foreign_guardian,
        first_name="Other",
        last_name="Companion",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shift = Shift.objects.create(
        camp=active_camp,
        name="Autorisierter Dienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
    )

    with pytest.raises(ValidationError, match="Begleitung gehört nicht zum Teilnehmerkonto"):
        ShiftAssignment.objects.create(shift=shift, participant=guardian, family_member=foreign_companion)


@pytest.mark.django_db
def test_companion_shift_progress_uses_companion_stay_target(kiosk_client, active_camp):
    active_camp.shift_ratio_per_night = Decimal("0.2")
    active_camp.save(update_fields=["shift_ratio_per_night", "updated_at"])
    guardian = Participant.objects.create(
        camp=active_camp,
        first_name="Guardian",
        last_name="User",
        booked_nights=10,
    )
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Companion",
        last_name="User",
        role=ParticipantFamilyMember.Role.COMPANION,
        arrival_date=datetime.date.today(),
        departure_date=datetime.date.today() + datetime.timedelta(days=5),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = guardian.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()

    response = kiosk_client.get(reverse("kiosk-shifts"))

    assert response.status_code == 200
    assert response.context["shift_progress_target"] == 1


@pytest.mark.django_db
def test_shift_mutation_rejects_deactivated_companion_session(kiosk_client, active_camp):
    guardian = Participant.objects.create(camp=active_camp, first_name="Guardian", last_name="User")
    companion = ParticipantFamilyMember.objects.create(
        guardian=guardian,
        first_name="Companion",
        last_name="User",
        role=ParticipantFamilyMember.Role.COMPANION,
    )
    shift = Shift.objects.create(
        camp=active_camp,
        name="Stale Session Dienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
    )
    session = kiosk_client.session
    session[KIOSK_PARTICIPANT_SESSION_KEY] = guardian.pk
    session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = companion.pk
    session.save()
    ParticipantFamilyMember.objects.filter(pk=companion.pk).update(is_active=False)

    response = kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})

    assert response.status_code == 302
    assert response.url == reverse("kiosk-login")
    assert not ShiftAssignment.objects.filter(shift=shift).exists()


@pytest.mark.django_db
def test_kiosk_can_filter_open_shifts_by_date_and_name(logged_in_kiosk_client, active_camp):
    matching_shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    Shift.objects.create(
        camp=active_camp,
        name="Aufsicht",
        date=datetime.date.today() + datetime.timedelta(days=3),
        required_slots=1,
    )

    response = logged_in_kiosk_client.get(
        reverse("kiosk-shifts"),
        {"date": matching_shift.date.isoformat(), "name": "küche"},
    )

    assert response.status_code == 200
    assert [shift.pk for shift in response.context["open_shifts"]] == [matching_shift.pk]
    assert response.context["shift_date_filter"] == matching_shift.date.isoformat()
    assert response.context["shift_name_filter"] == "küche"


@pytest.mark.django_db
def test_kiosk_bulk_selection_excludes_full_shifts_without_exchange_offer(logged_in_kiosk_client, active_camp):
    available = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    full = Shift.objects.create(
        camp=active_camp,
        name="Aufsicht",
        date=datetime.date.today() + datetime.timedelta(days=3),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=full, participant=other)

    response = logged_in_kiosk_client.get(reverse("kiosk-shifts"))

    content = response.content.decode()
    assert f'name="shift_ids" value="{available.pk}"' in content
    assert f'name="shift_ids" value="{full.pk}"' not in content
    assert full.name in content


@pytest.mark.django_db
def test_kiosk_full_shift_with_exchange_offer_stays_available_for_takeover(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Aufsicht",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=shift, participant=other, offered_for_exchange=True)

    response = logged_in_kiosk_client.get(reverse("kiosk-shifts"))

    content = response.content.decode()
    assert f'name="shift_ids" value="{shift.pk}"' not in content
    assert "Dienst übernehmen" in content


@pytest.mark.django_db
def test_kiosk_shift_filter_keeps_last_booked_service_selected(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    filter_data = {"date": shift.date.isoformat(), "name": shift.name}

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "signup", "shift_id": shift.pk, **filter_data},
        follow=True,
    )

    assert response.status_code == 200
    assert response.context["shift_name_choices"] == [shift.name]
    assert f'<option value="{shift.name}" selected>' in response.content.decode()


@pytest.mark.django_db
def test_kiosk_shift_filters_use_german_weekday_and_existing_service_choices(logged_in_kiosk_client, active_camp):
    monday = datetime.date.today() + datetime.timedelta(days=(7 - datetime.date.today().weekday()) % 7)
    kitchen_shift = Shift.objects.create(camp=active_camp, name="Küchendienst", date=monday, required_slots=1)
    Shift.objects.create(camp=active_camp, name="Aufsicht", date=monday, required_slots=1)

    response = logged_in_kiosk_client.get(reverse("kiosk-shifts"), {"date": monday.isoformat(), "name": "Küchendienst"})

    assert response.status_code == 200
    assert f"Montag, {monday:%d.%m.%Y}" in response.content.decode()
    assert response.context["shift_name_choices"] == ["Aufsicht", "Küchendienst"]
    assert [shift.pk for shift in response.context["open_shifts"]] == [kitchen_shift.pk]


@pytest.mark.django_db
def test_kiosk_single_signup_preserves_combined_filters(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    filter_data = {"date": shift.date.isoformat(), "name": shift.name}

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "signup", "shift_id": shift.pk, **filter_data},
    )

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('kiosk-shifts')}?date={shift.date.isoformat()}&name=K%C3%BCchendienst"


@pytest.mark.django_db
def test_kiosk_bulk_signup_books_all_selected_shifts_atomically(logged_in_kiosk_client, active_camp):
    shifts = [
        Shift.objects.create(
            camp=active_camp,
            name=name,
            date=datetime.date.today() + datetime.timedelta(days=offset),
            required_slots=1,
        )
        for name, offset in (("Küchendienst", 2), ("Aufsicht", 3))
    ]

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(shift.pk) for shift in shifts]},
    )

    assert response.status_code == 302
    assert set(
        ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).values_list("shift_id", flat=True)
    ) == {shift.pk for shift in shifts}


@pytest.mark.django_db
@pytest.mark.parametrize("shift_ids", [[], ["not-an-id"], ["999999"]])
def test_kiosk_bulk_signup_rejects_empty_foreign_or_malformed_ids(logged_in_kiosk_client, active_camp, shift_ids):
    Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    payload = {"action": "bulk_signup", "shift_ids": shift_ids}
    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), payload)

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_bulk_signup_rejects_duplicates_and_does_not_partially_book(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(shift.pk), str(shift.pk)]},
    )

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_bulk_signup_rejects_full_shift_without_partial_booking(logged_in_kiosk_client, active_camp):
    available = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    full = Shift.objects.create(
        camp=active_camp,
        name="Aufsicht",
        date=datetime.date.today() + datetime.timedelta(days=3),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=full, participant=other)

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(available.pk), str(full.pk)]},
    )

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_bulk_signup_rejects_shift_from_another_camp(logged_in_kiosk_client, active_camp):
    foreign_camp = Camp.objects.create(
        name="Foreign Camp",
        year=active_camp.year,
        starts_on=active_camp.starts_on,
        ends_on=active_camp.ends_on,
        is_active=True,
    )
    local_shift = Shift.objects.create(
        camp=active_camp,
        name="Küchendienst",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    foreign_shift = Shift.objects.create(
        camp=foreign_camp,
        name="Fremder Dienst",
        date=local_shift.date,
        required_slots=1,
    )

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "bulk_signup", "shift_ids": [str(local_shift.pk), str(foreign_shift.pk)]},
    )

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_can_retract_own_shift_assignment_within_15_minutes(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=logged_in_kiosk_client.kiosk_user)
    ShiftAssignment.objects.filter(pk=assignment.pk).update(created_at=timezone.now() - datetime.timedelta(minutes=14))

    response = logged_in_kiosk_client.post(
        reverse("kiosk-shifts"),
        {"action": "retract", "shift_id": shift.pk},
    )

    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_private_kiosk_shifts_context_disables_autologout(logged_in_kiosk_client, active_camp):
    response = logged_in_kiosk_client.get(reverse("kiosk-shifts"))
    assert response.status_code == 200
    assert response.context["kiosk_autologout"] is False


@pytest.mark.django_db
def test_kiosk_cannot_signup_for_full_shift(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User")
    ShiftAssignment.objects.create(shift=shift, participant=other)

    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(shift=shift, participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_cannot_retract(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today() + datetime.timedelta(days=2),
        required_slots=1,
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=logged_in_kiosk_client.kiosk_user)
    ShiftAssignment.objects.filter(pk=assignment.pk).update(created_at=timezone.now() - datetime.timedelta(minutes=16))
    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "retract", "shift_id": shift.pk})
    assert response.status_code == 302
    assert ShiftAssignment.objects.filter(shift=shift, participant=logged_in_kiosk_client.kiosk_user).exists()


@pytest.mark.django_db
def test_kiosk_can_offer_and_revoke_shift(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today(),
        required_slots=1,
    )
    assignment = ShiftAssignment.objects.create(shift=shift, participant=logged_in_kiosk_client.kiosk_user)

    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "offer", "shift_id": shift.pk})
    assert response.status_code == 302
    assignment.refresh_from_db()
    assert assignment.offered_for_exchange is True

    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "revoke_offer", "shift_id": shift.pk})
    assert response.status_code == 302
    assignment.refresh_from_db()
    assert assignment.offered_for_exchange is False


@pytest.mark.django_db
def test_kiosk_can_takeover_offered_shift(logged_in_kiosk_client, active_camp):
    shift = Shift.objects.create(
        camp=active_camp,
        name="Test Shift",
        date=datetime.date.today(),
        required_slots=1,
    )
    other = Participant.objects.create(camp=active_camp, first_name="Other", last_name="User", status="active")
    ShiftAssignment.objects.create(shift=shift, participant=other, offered_for_exchange=True)

    response = logged_in_kiosk_client.post(reverse("kiosk-shifts"), {"action": "signup", "shift_id": shift.pk})
    assert response.status_code == 302
    assert not ShiftAssignment.objects.filter(shift=shift, participant=other).exists()
    assert ShiftAssignment.objects.filter(shift=shift, participant=logged_in_kiosk_client.kiosk_user).exists()
