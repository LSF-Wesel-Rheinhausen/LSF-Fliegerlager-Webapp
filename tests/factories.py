from datetime import date
from decimal import Decimal

import factory
from django.contrib.auth.models import Group, User
from django.utils import timezone

from billing.models import Camp, Charge, DrinkEntry, Expense, Participant, Payment, PriceRule


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda user: f"{user.username}@example.test")

    @factory.post_generation
    def password(self, create, extracted, **_kwargs):
        self.set_password(extracted or "test")
        if create:
            self.save(update_fields=["password"])


class SuperUserFactory(UserFactory):
    is_staff = True
    is_superuser = True


class GroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Group
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"group-{n}")


class CampFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Camp

    name = "Fliegerlager"
    year = 2025


class ParticipantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Participant

    camp = factory.SubFactory(CampFactory)
    first_name = factory.Sequence(lambda n: f"Teilnehmer{n}")
    last_name = "Muster"


class PriceRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PriceRule

    camp = factory.SubFactory(CampFactory)
    kind = PriceRule.Kind.OTHER
    name = "Preisregel"
    unit_price = Decimal("10.00")


class ChargeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Charge

    participant = factory.SubFactory(ParticipantFactory)
    kind = Charge.Kind.OTHER
    description = "Kostenposition"
    quantity = Decimal("1.00")
    unit_price = Decimal("10.00")


class DrinkEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DrinkEntry

    participant = factory.SubFactory(ParticipantFactory)
    drink = DrinkEntry.Drink.WATER
    quantity = 1
    unit_price = Decimal("1.50")
    booked_at = factory.LazyFunction(
        lambda: timezone.datetime(2025, 7, 1, 12, 0, tzinfo=timezone.get_current_timezone())
    )


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    participant = factory.SubFactory(ParticipantFactory)
    amount = Decimal("10.00")
    paid_on = date(2025, 7, 1)


class ExpenseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Expense

    participant = factory.SubFactory(ParticipantFactory)
    camp = factory.SelfAttribute("participant.camp")
    category = "Einkauf"
    description = "Auslage"
    amount = Decimal("10.00")
    reimbursable = True
