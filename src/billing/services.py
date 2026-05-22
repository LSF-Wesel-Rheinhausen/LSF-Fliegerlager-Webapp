from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import DrinkEntry, Expense, Participant, PriceRule, Settlement, SettlementRun

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class SettlementLine:
    label: str
    quantity: Decimal
    unit_price: Decimal
    gross_total: Decimal
    subsidy_rate: Decimal
    subsidy_amount: Decimal
    total: Decimal
    source: str


@dataclass(frozen=True)
class SettlementResult:
    participant: Participant
    lines: list[SettlementLine]
    total_gross: Decimal
    total_subsidy: Decimal
    total_due: Decimal
    total_paid: Decimal
    total_advanced: Decimal
    balance: Decimal

    @property
    def is_overpaid(self):
        return self.balance < ZERO


def money(value):
    return (value or ZERO).quantize(Decimal("0.01"))


def rate(value):
    return (value or ZERO).quantize(Decimal("0.0001"))


def _rule_applies(rule, participant):
    if participant.is_child and not rule.applies_to_children:
        return False
    if not participant.is_child and not rule.applies_to_adults:
        return False
    return True


def participant_nights(participant):
    return participant.effective_nights


def participant_camp_flat_duration(participant):
    nights = participant_nights(participant)
    if nights > 7:
        return PriceRule.CampFlatDuration.TWO_WEEKS
    return PriceRule.CampFlatDuration.ONE_WEEK


def participant_camp_flat_role(participant):
    if participant.is_companion:
        return PriceRule.CampFlatRole.COMPANION
    return PriceRule.CampFlatRole.PARTICIPANT


def participant_subsidy_rate(participant):
    if not participant.is_youth_group:
        return ZERO
    raw_rate = participant.camp.foerdersatz * participant.hilfssatz * participant.berufssatz
    return min(rate(raw_rate), Decimal("1.0000"))


def build_settlement_line(label, quantity, unit_price, source, eligible, participant):
    gross_total = money(quantity * unit_price)
    subsidy_rate = participant_subsidy_rate(participant) if eligible else ZERO
    subsidy_amount = money(gross_total * subsidy_rate)
    total = money(gross_total - subsidy_amount)
    return SettlementLine(
        label=label,
        quantity=quantity,
        unit_price=money(unit_price),
        gross_total=gross_total,
        subsidy_rate=subsidy_rate,
        subsidy_amount=subsidy_amount,
        total=total,
        source=source,
    )


def default_charge_lines(participant):
    default_rules = PriceRule.objects.filter(camp=participant.camp, is_default=True)
    rules = list(default_rules.filter(kind=PriceRule.Kind.NIGHT))
    camp_flat_rules = default_rules.filter(kind=PriceRule.Kind.CAMP_FLAT)
    matching_camp_flat_rules = PriceRule.objects.none()
    if participant.overnight_category_id:
        matching_camp_flat_rules = camp_flat_rules.filter(overnight_category=participant.overnight_category)
    if not matching_camp_flat_rules.exists():
        matching_camp_flat_rules = camp_flat_rules.filter(
            camp_flat_duration=participant_camp_flat_duration(participant),
            camp_flat_role=participant_camp_flat_role(participant),
        )
    if matching_camp_flat_rules.exists():
        rules.extend(matching_camp_flat_rules)
    else:
        rules.extend(camp_flat_rules.filter(overnight_category__isnull=True, camp_flat_duration="", camp_flat_role=""))
    lines = []
    for rule in rules:
        if not _rule_applies(rule, participant):
            continue
        quantity = Decimal("1.00")
        if rule.kind == PriceRule.Kind.NIGHT:
            quantity = Decimal(participant_nights(participant))
        lines.append(
            build_settlement_line(
                label=rule.name,
                quantity=quantity,
                unit_price=rule.unit_price,
                source=f"price_rule:{rule.pk}",
                eligible=rule.foerderfaehig,
                participant=participant,
            )
        )
    return lines


def manual_charge_lines(participant):
    return [
        build_settlement_line(
            label=charge.description,
            quantity=money(charge.quantity),
            unit_price=charge.unit_price,
            source=f"charge:{charge.pk}",
            eligible=charge.foerderfaehig,
            participant=participant,
        )
        for charge in participant.charges.all()
    ]


def drink_charge_lines(participant):
    lines = []
    entries = (
        DrinkEntry.objects.filter(participant=participant)
        .values("drink", "unit_price", "foerderfaehig")
        .annotate(quantity_sum=Sum("quantity"))
        .order_by("drink", "foerderfaehig")
    )
    for entry in entries:
        quantity = Decimal(entry["quantity_sum"] or 0)
        unit_price = money(entry["unit_price"])
        lines.append(
            build_settlement_line(
                label=f"Getränke: {dict(DrinkEntry.Drink.choices).get(entry['drink'], entry['drink'])}",
                quantity=quantity,
                unit_price=unit_price,
                source=f"drink:{entry['drink']}",
                eligible=entry["foerderfaehig"],
                participant=participant,
            )
        )
    return lines


def calculate_participant_settlement(participant):
    participant = (
        Participant.objects.select_related("camp", "overnight_category", "primary_participant")
        .prefetch_related("charges", "payments", "expenses", "drink_entries")
        .get(pk=participant.pk)
    )
    lines = default_charge_lines(participant) + manual_charge_lines(participant) + drink_charge_lines(participant)
    total_gross = money(sum((line.gross_total for line in lines), ZERO))
    total_subsidy = money(sum((line.subsidy_amount for line in lines), ZERO))
    total_due = money(sum((line.total for line in lines), ZERO))
    total_paid = money(participant.payments.aggregate(total=Sum("amount"))["total"])
    total_advanced = money(
        Expense.objects.filter(participant=participant, reimbursable=True).aggregate(total=Sum("amount"))["total"]
    )
    balance = money(total_due - total_paid - total_advanced)
    return SettlementResult(
        participant=participant,
        lines=lines,
        total_gross=total_gross,
        total_subsidy=total_subsidy,
        total_due=total_due,
        total_paid=total_paid,
        total_advanced=total_advanced,
        balance=balance,
    )


def calculate_camp_settlements(camp):
    participants = Participant.objects.filter(camp=camp).order_by("last_name", "first_name")
    return [calculate_participant_settlement(participant) for participant in participants]


def settlement_result_data(result: SettlementResult) -> dict[str, object]:
    return {
        "participant": {
            "id": result.participant.pk,
            "first_name": result.participant.first_name,
            "last_name": result.participant.last_name,
            "status": result.participant.status,
        },
        "totals": {
            "gross": str(result.total_gross),
            "subsidy": str(result.total_subsidy),
            "due": str(result.total_due),
            "paid": str(result.total_paid),
            "advanced": str(result.total_advanced),
            "balance": str(result.balance),
        },
        "lines": [
            {
                "label": line.label,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "gross_total": str(line.gross_total),
                "subsidy_rate": str(line.subsidy_rate),
                "subsidy_amount": str(line.subsidy_amount),
                "total": str(line.total),
                "source": line.source,
            }
            for line in result.lines
        ],
    }


def create_settlement_run(camp, calculated_by=None) -> SettlementRun:
    with transaction.atomic():
        results = calculate_camp_settlements(camp)
        run = SettlementRun.objects.create(
            camp=camp,
            created_by=calculated_by if getattr(calculated_by, "is_authenticated", False) else None,
            participant_count=len(results),
            total_gross=money(sum((result.total_gross for result in results), ZERO)),
            total_subsidy=money(sum((result.total_subsidy for result in results), ZERO)),
            total_due=money(sum((result.total_due for result in results), ZERO)),
            total_paid=money(sum((result.total_paid for result in results), ZERO)),
            total_advanced=money(sum((result.total_advanced for result in results), ZERO)),
            balance=money(sum((result.balance for result in results), ZERO)),
            data={"source": "live_calculation"},
        )
        Settlement.objects.bulk_create(
            [
                Settlement(
                    run=run,
                    participant=result.participant,
                    calculated_by=run.created_by,
                    total_gross=result.total_gross,
                    total_subsidy=result.total_subsidy,
                    total_due=result.total_due,
                    total_paid=result.total_paid,
                    total_advanced=result.total_advanced,
                    balance=result.balance,
                    data=settlement_result_data(result),
                )
                for result in results
            ]
        )
    return run


def participant_kiosk_summary(participant):
    result = calculate_participant_settlement(participant)
    return {
        "participant": participant.full_name,
        "total_gross": result.total_gross,
        "total_subsidy": result.total_subsidy,
        "total_due": result.total_due,
        "total_paid": result.total_paid,
        "total_advanced": result.total_advanced,
        "balance": result.balance,
        "lines": [
            {
                "label": line.label,
                "quantity": line.quantity,
                "gross_total": line.gross_total,
                "subsidy_amount": line.subsidy_amount,
                "total": line.total,
            }
            for line in result.lines
        ],
    }


def default_drink_price(camp):
    rule = PriceRule.objects.filter(camp=camp, kind=PriceRule.Kind.DRINK, is_default=True).order_by("name").first()
    if rule is None:
        rule = PriceRule.objects.filter(camp=camp, kind=PriceRule.Kind.DRINK).order_by("name").first()
    return money(rule.unit_price if rule else ZERO)
