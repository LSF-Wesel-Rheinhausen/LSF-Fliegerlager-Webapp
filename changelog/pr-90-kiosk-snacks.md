# Kiosk Snacks and Breakfast Separation

## Feature / Change
Removed "Frühstück" and "Mittagssnack" from the daily calendar-based meal booking flow and transitioned them into quick-booking "Snacks". These are now located in a separate "Verpflegung buchen (Heute)" section on the Kiosk home page.

## Rationale
Users frequently booked multiple breakfasts to compensate for missing lunch/snack options. Moving breakfasts and snacks to the quick-booking flow removes the variant selection (Vegan/Fleisch), removes order cut-offs, and allows participants to easily book multiple snacks/breakfasts on the same day as needed without affecting the pre-planned dinner statistics.

## Database / Models
Added a new `SNACK` type to `PriceRule.Kind` and `Charge.Kind`.
