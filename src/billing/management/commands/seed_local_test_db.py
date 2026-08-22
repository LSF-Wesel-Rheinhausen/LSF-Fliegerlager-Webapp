from datetime import date, time, timedelta
from decimal import Decimal
from time import sleep
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, transaction
from django.utils import timezone

from billing.models import (
    AttendanceDay,
    BookingAuditLog,
    Camp,
    CampKioskAccess,
    Charge,
    Expense,
    ExpenseAllocation,
    FirstAdminBootstrapLock,
    MealBookingOverride,
    MealOrder,
    MealPlanEntry,
    MealSignup,
    Participant,
    ParticipantBookingLink,
    ParticipantFamilyMember,
    ParticipantFamilyMemberPin,
    ParticipantPin,
    Payment,
    PriceRule,
    Settlement,
    SettlementRun,
)
from billing.roles import ROLE_ADMIN, ROLE_EDITOR, ROLE_HUEBERS, set_user_role

User = get_user_model()

ACTIVE_CAMP_NAME = "Local Testlager Active"
PRE_CAMP_NAME = "Local Testlager Pre-Camp"
ARCHIVED_CAMP_NAME = "Local Testlager Archived"
ACTIVE_CAMP_YEAR = 2026

ADMIN_PASSWORD = "LocalAdmin-417-Only!"
EDITOR_PASSWORD = "LocalEditor-417-Only!"
HUEBERS_PASSWORD = "LocalHuebers-417-Only!"
INACTIVE_PASSWORD = "LocalInactive-417-Only!"
SHARED_KIOSK_PIN = "864208"
SEED_LOCK_RETRY_DELAYS = (0.05, 0.15, 0.35, 0.75, 1.5, 2.5, 4.0, 5.0)


class Command(BaseCommand):
    """Create the deterministic, synthetic local development data set."""

    help = "Seedet eine idempotente, synthetische lokale Testdatenbank."

    def handle(self, *args: Any, **options: Any) -> None:
        for _attempt, delay in enumerate((*SEED_LOCK_RETRY_DELAYS, None)):
            try:
                self._seed_once()
                break
            except OperationalError as error:
                if not self._is_retryable_lock_error(error) or delay is None:
                    if self._is_retryable_lock_error(error):
                        raise CommandError("Die lokale Testdatenbank war zu lange gesperrt.") from error
                    raise
                sleep(delay)
        else:  # pragma: no cover - the loop always either breaks or raises
            raise CommandError("Lokale Testdaten konnten nicht erzeugt werden.")

        self.stdout.write(self.style.SUCCESS("Lokale Testdaten wurden idempotent aktualisiert."))

    def _seed_once(self) -> None:
        with transaction.atomic():
            self._acquire_seed_lock()
            users = self._seed_users()
            camps = self._seed_camps()
            self._seed_kiosk_access(camps[ACTIVE_CAMP_NAME], users["admin"])
            participants = self._seed_participants(camps[ACTIVE_CAMP_NAME], camps[ARCHIVED_CAMP_NAME], users["admin"])
            self._seed_family(participants)
            self._seed_attendance(camps[ACTIVE_CAMP_NAME], participants)
            self._seed_meals(camps[ACTIVE_CAMP_NAME], participants, users["admin"])
            self._seed_financials(camps[ACTIVE_CAMP_NAME], participants, users["admin"])

    @staticmethod
    def _acquire_seed_lock() -> None:
        lock, _created = FirstAdminBootstrapLock.objects.get_or_create(pk=1)
        FirstAdminBootstrapLock.objects.filter(pk=lock.pk).update(id=lock.pk)
        FirstAdminBootstrapLock.objects.select_for_update().get(pk=1)

    @staticmethod
    def _is_retryable_lock_error(error: OperationalError) -> bool:
        message = str(error).lower()
        return any(
            marker in message
            for marker in (
                "database is locked",
                "database table is locked",
                "could not obtain lock",
                "lock not available",
            )
        )

    def _seed_users(self) -> dict[str, Any]:
        users = {
            "admin": self._user(
                "local-admin", "local-admin@example.test", ADMIN_PASSWORD, "Local", "Admin", True, True
            ),
            "editor": self._user(
                "local-editor", "local-editor@example.test", EDITOR_PASSWORD, "Local", "Editor", False, True
            ),
            "huebers": self._user(
                "local-huebers", "local-huebers@example.test", HUEBERS_PASSWORD, "Local", "Huebers", False, True
            ),
            "inactive": self._user(
                "local-inactive", "local-inactive@example.test", INACTIVE_PASSWORD, "Local", "Inactive", False, False
            ),
        }
        set_user_role(users["admin"], ROLE_ADMIN)
        users["admin"].is_superuser = True
        users["admin"].is_active = True
        users["admin"].save(update_fields=["is_superuser", "is_active"])
        set_user_role(users["editor"], ROLE_EDITOR)
        set_user_role(users["huebers"], ROLE_HUEBERS)
        set_user_role(users["inactive"], ROLE_EDITOR)
        users["inactive"].is_active = False
        users["inactive"].save(update_fields=["is_active"])
        return users

    @staticmethod
    def _user(
        username: str,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        is_staff: bool,
        is_active: bool,
    ) -> Any:
        user = User.objects.filter(username=username).first()
        if user is not None:
            has_full_seed_identity = (
                user.email == email
                and user.first_name == first_name
                and user.last_name == last_name
                and check_password(password, user.password)
            )
            has_legacy_seed_identity = (
                user.email == email
                and not user.first_name
                and not user.last_name
                and check_password(password, user.password)
            )
            if not (has_full_seed_identity or has_legacy_seed_identity):
                raise CommandError(f"Deterministischer Seed-Benutzer '{username}' ist bereits fremd belegt.")
        else:
            user = User(username=username)
            user.set_password(password)

        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.is_staff = is_staff
        user.is_active = is_active
        user.save()
        return user

    def _seed_camps(self) -> dict[str, Camp]:
        names = {ACTIVE_CAMP_NAME, PRE_CAMP_NAME, ARCHIVED_CAMP_NAME}
        foreign_active = Camp.objects.filter(is_active=True).exclude(name__in=names).first()
        if foreign_active is not None:
            raise CommandError(
                "Das lokale Seed benötigt ein aktives Lager, würde aber das fremde aktive Lager "
                f"'{foreign_active.name}' deaktivieren. Seed abgebrochen."
            )

        camps: dict[str, Camp] = {}
        camps[ACTIVE_CAMP_NAME] = self._camp(
            ACTIVE_CAMP_NAME,
            ACTIVE_CAMP_YEAR,
            starts_on=date(2026, 8, 18),
            ends_on=date(2026, 8, 28),
            is_active=True,
            meal_booking_cutoff_time=time(12, 0),
            allow_breakfast_prebooking_before_camp=True,
            allow_dinner_prebooking_before_camp=True,
            shift_ratio_per_night=Decimal("0.2000"),
            show_kiosk_invoices=True,
        )
        camps[PRE_CAMP_NAME] = self._camp(
            PRE_CAMP_NAME,
            2027,
            starts_on=date(2027, 7, 1),
            ends_on=date(2027, 7, 10),
            is_active=False,
            allow_breakfast_prebooking_before_camp=True,
            allow_dinner_prebooking_before_camp=False,
        )
        camps[ARCHIVED_CAMP_NAME] = self._camp(
            ARCHIVED_CAMP_NAME,
            2025,
            starts_on=date(2025, 7, 1),
            ends_on=date(2025, 7, 10),
            is_active=False,
            show_kiosk_invoices=False,
        )
        return camps

    @staticmethod
    def _camp(name: str, year: int, **defaults: Any) -> Camp:
        camp, _created = Camp.objects.update_or_create(name=name, year=year, defaults=defaults)
        return camp

    @staticmethod
    def _seed_kiosk_access(camp: Camp, admin: Any) -> None:
        access, _created = CampKioskAccess.objects.get_or_create(camp=camp)
        if not access.check_pin(SHARED_KIOSK_PIN):
            access.set_pin(SHARED_KIOSK_PIN, changed_by=admin)
            access.save(update_fields=["pin_hash", "generation", "rotated_at", "changed_by", "updated_at"])

    def _seed_participants(self, camp: Camp, archived_camp: Camp, admin: Any) -> dict[str, Participant]:
        participants = {
            "adult": self._participant(
                camp,
                "AdultComplete",
                "Synthetic",
                email="adultcomplete@example.test",
                phone="+49 000 1001",
                birth_date=date(1990, 1, 2),
                arrival_date=date(2026, 8, 18),
                departure_date=date(2026, 8, 28),
                status=Participant.Status.ACTIVE,
                attendance_tracking_enabled=True,
            ),
            "child": self._participant(
                camp,
                "ChildPartial",
                "Synthetic",
                email="childpartial@example.test",
                birth_date=date(2015, 5, 6),
                arrival_date=date(2026, 8, 20),
                departure_date=date(2026, 8, 25),
                is_child=True,
                status=Participant.Status.REGISTERED,
                attendance_tracking_enabled=True,
            ),
            "infant": self._participant(
                camp,
                "InfantNoDob",
                "Synthetic",
                email="infantnodob@example.test",
                birth_date=date(2024, 6, 1),
                status=Participant.Status.REGISTERED,
                attendance_tracking_enabled=True,
            ),
            "missing_dob": self._participant(
                camp,
                "MissingDob",
                "Synthetic",
                status=Participant.Status.REGISTERED,
            ),
            "archived": self._participant(
                archived_camp,
                "ArchivedSettled",
                "Synthetic",
                email="archivedsettled@example.test",
                birth_date=date(1985, 3, 4),
                status=Participant.Status.SETTLED,
                archived_at=timezone.now(),
                archived_by=admin,
            ),
        }

        pin, _created = ParticipantPin.objects.get_or_create(participant=participants["adult"])
        if not pin.check_pin("2468"):
            pin.set_pin("2468", changed_by=admin)
            pin.save(
                update_fields=[
                    "pin_hash",
                    "must_set_pin",
                    "failed_attempts",
                    "locked_until",
                    "changed_by",
                    "updated_at",
                ]
            )

        locked_pin, _created = ParticipantPin.objects.get_or_create(participant=participants["child"])
        if not locked_pin.check_pin("8642"):
            locked_pin.set_pin("8642", changed_by=admin)
        locked_pin.locked_until = timezone.now() + timedelta(minutes=5)
        locked_pin.save(
            update_fields=["pin_hash", "must_set_pin", "failed_attempts", "locked_until", "changed_by", "updated_at"]
        )
        ParticipantPin.objects.get_or_create(participant=participants["infant"])
        ParticipantPin.objects.get_or_create(participant=participants["missing_dob"])
        ParticipantPin.objects.get_or_create(participant=participants["archived"])
        return participants

    @staticmethod
    def _participant(camp: Camp, first_name: str, last_name: str, **defaults: Any) -> Participant:
        participant, _created = Participant.objects.update_or_create(
            camp=camp,
            first_name=first_name,
            last_name=last_name,
            defaults=defaults,
        )
        return participant

    @staticmethod
    def _seed_family(participants: dict[str, Participant]) -> None:
        adult = participants["adult"]
        family, _created = ParticipantFamilyMember.objects.update_or_create(
            guardian=adult,
            first_name="FamilyChild",
            last_name="Synthetic",
            defaults={
                "role": ParticipantFamilyMember.Role.CHILD,
                "email": "familychild@example.test",
                "birth_date": date(2016, 2, 3),
                "arrival_date": date(2026, 8, 20),
                "departure_date": date(2026, 8, 25),
                "is_active": True,
                "attendance_tracking_enabled": True,
            },
        )
        companion, _created = ParticipantFamilyMember.objects.update_or_create(
            guardian=adult,
            first_name="FamilyCompanion",
            last_name="Synthetic",
            defaults={
                "role": ParticipantFamilyMember.Role.COMPANION,
                "email": "familycompanion@example.test",
                "phone": "+49 000 1002",
                "birth_date": date(1988, 4, 5),
                "is_active": True,
            },
        )
        ParticipantFamilyMember.objects.update_or_create(
            guardian=adult,
            first_name="InactiveFamily",
            last_name="Synthetic",
            defaults={"role": ParticipantFamilyMember.Role.CHILD, "is_active": False},
        )
        family_pin, _created = ParticipantFamilyMemberPin.objects.get_or_create(family_member=companion)
        if not family_pin.check_pin("9753"):
            family_pin.set_pin("9753")
            family_pin.save(update_fields=["pin_hash", "must_set_pin", "failed_attempts", "locked_until", "updated_at"])
        ParticipantFamilyMemberPin.objects.get_or_create(family_member=family)
        ParticipantBookingLink.objects.update_or_create(
            inviter=adult,
            invitee=participants["child"],
            defaults={"status": ParticipantBookingLink.Status.ACCEPTED},
        )

    @staticmethod
    def _seed_attendance(camp: Camp, participants: dict[str, Participant]) -> None:
        adult = participants["adult"]
        child = participants["child"]
        infant = participants["infant"]
        family = ParticipantFamilyMember.objects.get(guardian=adult, first_name="FamilyChild")
        for attendance_date, is_present, comment in (
            (date(2026, 8, 18), True, ""),
            (date(2026, 8, 19), False, "Seed attendance note"),
            (date(2026, 8, 20), True, ""),
            (date(2026, 8, 27), True, ""),
        ):
            AttendanceDay.objects.update_or_create(
                participant=adult,
                family_member=None,
                date=attendance_date,
                defaults={"is_present": is_present, "comment": comment},
            )
        assert camp.starts_on is not None
        assert camp.ends_on is not None
        AttendanceDay.objects.update_or_create(
            participant=infant,
            family_member=None,
            date=camp.starts_on - timedelta(days=4),
            defaults={"is_present": True},
        )
        AttendanceDay.objects.update_or_create(
            participant=infant,
            family_member=None,
            date=camp.ends_on + timedelta(days=3),
            defaults={"is_present": False},
        )
        AttendanceDay.objects.update_or_create(
            participant=child,
            family_member=None,
            date=date(2026, 8, 21),
            defaults={"is_present": True},
        )
        AttendanceDay.objects.update_or_create(
            participant=adult,
            family_member=family,
            date=date(2026, 8, 21),
            defaults={"is_present": True},
        )

    def _seed_meals(self, camp: Camp, participants: dict[str, Participant], admin: Any) -> None:
        dates = (date(2026, 8, 21), date(2026, 8, 22))
        for meal_date in dates:
            for meal in (MealSignup.Meal.BREAKFAST, MealSignup.Meal.DINNER):
                MealPlanEntry.objects.update_or_create(
                    camp=camp,
                    meal_date=meal_date,
                    meal=meal,
                    defaults={"description": "Synthetisches Testmenü"},
                )
        MealBookingOverride.objects.update_or_create(
            camp=camp,
            meal_date=dates[0],
            meal=MealSignup.Meal.DINNER,
            defaults={"state": MealBookingOverride.State.CLOSED, "changed_by": admin},
        )
        MealBookingOverride.objects.update_or_create(
            camp=camp,
            meal_date=dates[1],
            meal=MealSignup.Meal.DINNER,
            defaults={"state": MealBookingOverride.State.OPEN, "changed_by": admin},
        )
        MealOrder.objects.update_or_create(
            camp=camp,
            meal_date=dates[0],
            defaults={"ordered_by": admin, "is_sent": True},
        )
        meal_charge = self._charge(
            participants["adult"],
            Charge.Kind.FOOD,
            "Seed meal booking",
            Decimal("12.00"),
            family_member=None,
        )
        MealSignup.objects.update_or_create(
            participant=participants["adult"],
            family_member=None,
            meal_date=dates[0],
            meal=MealSignup.Meal.BREAKFAST,
            defaults={"variant": MealSignup.Variant.VEGAN, "charge": meal_charge, "status": MealSignup.Status.ACTIVE},
        )
        retracted_charge = self._charge(
            participants["adult"],
            Charge.Kind.FOOD,
            "Seed retracted meal",
            Decimal("8.00"),
            family_member=None,
        )
        MealSignup.objects.update_or_create(
            participant=participants["adult"],
            family_member=None,
            meal_date=dates[1],
            meal=MealSignup.Meal.DINNER,
            defaults={
                "variant": MealSignup.Variant.NORMAL,
                "charge": retracted_charge,
                "status": MealSignup.Status.RETRACTED,
                "retracted_at": timezone.now(),
            },
        )
        family = ParticipantFamilyMember.objects.get(guardian=participants["adult"], first_name="FamilyChild")
        family_charge = self._charge(
            participants["adult"],
            Charge.Kind.FOOD,
            "Seed child meal booking",
            Decimal("5.00"),
            family_member=family,
        )
        MealSignup.objects.update_or_create(
            participant=participants["adult"],
            family_member=family,
            meal_date=dates[0],
            meal=MealSignup.Meal.DINNER,
            defaults={
                "variant": MealSignup.Variant.VEGAN_CHILD,
                "charge": family_charge,
                "status": MealSignup.Status.ACTIVE,
            },
        )

    def _seed_financials(self, camp: Camp, participants: dict[str, Participant], admin: Any) -> None:
        adult = participants["adult"]
        self._price_rules(camp)
        self._charge(adult, Charge.Kind.CAMP_FLAT, "Seed camp flat", Decimal("100.00"))
        self._charge(adult, Charge.Kind.DRINK, "Seed drink", Decimal("3.00"))
        donation = self._charge(adult, Charge.Kind.DONATION, "Seed donation", Decimal("15.00"))
        deleted = self._charge(adult, Charge.Kind.OTHER, "Seed deleted charge", Decimal("7.00"))
        deleted.deleted_at = timezone.now()
        deleted.deleted_by = admin
        deleted.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
        BookingAuditLog.objects.get_or_create(
            charge=deleted,
            action=BookingAuditLog.Action.DELETED,
            defaults={
                "participant": adult,
                "changed_by": admin,
                "before": {"deleted": False},
                "after": {"deleted": True},
            },
        )
        BookingAuditLog.objects.get_or_create(
            charge=donation,
            action=BookingAuditLog.Action.RESTORED,
            defaults={
                "participant": adult,
                "changed_by": admin,
                "before": {"deleted": True},
                "after": {"deleted": False},
            },
        )
        for amount, note in (
            (Decimal("0.00"), "No payment"),
            (Decimal("25.00"), "Partial payment"),
            (Decimal("200.00"), "Overpayment"),
        ):
            Payment.objects.update_or_create(
                participant=adult,
                amount=amount,
                note=note,
                defaults={"paid_on": date(2026, 8, 22), "method": "Bar"},
            )
        for index, cost_center in enumerate(Expense.CostCenter.values, start=1):
            status = (
                Expense.Status.APPROVED if cost_center == Expense.CostCenter.FOOD_BREAKFAST else Expense.Status.PENDING
            )
            expense = Expense.objects.update_or_create(
                camp=camp,
                description=f"Seed expense {cost_center}",
                defaults={
                    "participant": adult,
                    "category": "Unterkunft/Verpflegung",
                    "amount": Decimal(index * 10),
                    "paid_on": date(2026, 8, 22),
                    "reimbursable": True,
                    "status": status,
                    "allocation_method": Expense.AllocationMethod.COST_CENTER,
                    "cost_center": cost_center,
                    "approved_at": timezone.now() if status == Expense.Status.APPROVED else None,
                    "approved_by": admin if status == Expense.Status.APPROVED else None,
                },
            )[0]
            if status == Expense.Status.APPROVED:
                ExpenseAllocation.objects.update_or_create(
                    expense=expense,
                    participant=adult,
                    defaults={"amount": Decimal(index * 10)},
                )
        for version, run_type in ((1, SettlementRun.RunType.MANUAL), (2, SettlementRun.RunType.DAILY_BACKUP)):
            run, _created = SettlementRun.objects.update_or_create(
                camp=camp,
                version=version,
                defaults={"run_type": run_type, "calculated_by": admin, "participant_count": 1},
            )
            Settlement.objects.update_or_create(
                run=run,
                participant=adult,
                defaults={
                    "calculated_by": admin,
                    "participant_name": adult.full_name,
                    "participant_status": adult.status,
                    "total_gross": Decimal("125.00"),
                    "total_subsidy": Decimal("0.00"),
                    "total_due": Decimal("125.00"),
                    "total_paid": Decimal("225.00"),
                    "total_advanced": Decimal("40.00"),
                    "balance": Decimal("-100.00"),
                    "data": {"source": "local-seed", "cost_centers": [Expense.CostCenter.FOOD_BREAKFAST]},
                },
            )

    @staticmethod
    def _price_rules(camp: Camp) -> None:
        rules: tuple[tuple[Any, str, Decimal, dict[str, Any]], ...] = (
            (
                PriceRule.Kind.CAMP_FLAT,
                "Seed 1 week",
                Decimal("100.00"),
                {"camp_flat_duration": PriceRule.CampFlatDuration.ONE_WEEK},
            ),
            (PriceRule.Kind.NIGHT, "Seed night", Decimal("10.00"), {}),
            (PriceRule.Kind.MEAL, "Seed vegan breakfast", Decimal("8.00"), {"meal_type": PriceRule.MealType.BREAKFAST}),
            (PriceRule.Kind.DRINK, "Seed drink price", Decimal("3.00"), {}),
            (PriceRule.Kind.OTHER, "Seed other", Decimal("5.00"), {}),
            (PriceRule.Kind.DONATION, "Seed donation", Decimal("0.00"), {}),
        )
        for kind, name, unit_price, extra in rules:
            PriceRule.objects.update_or_create(
                camp=camp,
                name=name,
                defaults={
                    "kind": kind,
                    "unit_price": unit_price,
                    "is_default": kind != PriceRule.Kind.DONATION,
                    **extra,
                },
            )
        PriceRule.objects.update_or_create(
            camp=camp,
            name="Seed archived price",
            defaults={"kind": PriceRule.Kind.OTHER, "unit_price": Decimal("9.00"), "is_archived": True},
        )

    @staticmethod
    def _charge(
        participant: Participant,
        kind: str,
        description: str,
        unit_price: Decimal,
        *,
        family_member: ParticipantFamilyMember | None = None,
    ) -> Charge:
        charge, _created = Charge.objects.update_or_create(
            participant=participant,
            family_member=family_member,
            kind=kind,
            description=description,
            defaults={"quantity": Decimal("1.00"), "unit_price": unit_price, "occurred_on": date(2026, 8, 22)},
        )
        return charge
