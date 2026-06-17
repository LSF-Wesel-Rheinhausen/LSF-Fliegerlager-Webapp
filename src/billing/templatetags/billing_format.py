from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django import template

from billing.permissions import is_admin, is_huebers, is_meal_manager

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
def abs_value(value: Any) -> Decimal:
    try:
        amount = Decimal(value or ZERO)
    except (InvalidOperation, TypeError, ValueError):
        amount = ZERO
    return abs(amount)


@register.filter
def percent(value: Any) -> str:
    try:
        percentage = Decimal(value or 0) * Decimal("100")
    except (InvalidOperation, TypeError, ValueError):
        percentage = ZERO
    formatted = format(percentage.quantize(TWOPLACES, rounding=ROUND_HALF_UP), "f").rstrip("0").rstrip(".")
    return f"{formatted} %"


@register.filter
def can_manage_users(user: Any) -> bool:
    """Return whether a template user may access user management."""
    return is_admin(user)


@register.filter
def can_manage_meals(user: Any) -> bool:
    """Return whether a template user may access meal overview and cutoff pages."""
    return is_meal_manager(user)


@register.filter
def is_huebers_user(user: Any) -> bool:
    """Return whether a template user has the Huebers-only role."""
    return is_huebers(user)
