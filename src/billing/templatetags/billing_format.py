from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django import template

from billing.permissions import is_admin

register = template.Library()

ZERO = Decimal("0.00")
TWOPLACES = Decimal("0.01")


@register.filter
def money_eur(value: Any) -> str:
    try:
        amount = Decimal(value or ZERO)
    except (InvalidOperation, TypeError, ValueError):
        amount = ZERO

    quantized = amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    formatted = format(quantized, ",.2f").replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} €"


@register.filter
def can_manage_users(user: Any) -> bool:
    """Return whether a template user may access user management."""
    return is_admin(user)
