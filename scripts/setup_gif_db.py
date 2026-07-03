import os
from datetime import date, time, timedelta

import django
from django.contrib.auth.hashers import make_password

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from billing.models import Camp, Participant, ParticipantPin, ShiftAssignment  # noqa: E402

c = Camp.objects.first()

c.meal_booking_cutoff_time = time(23, 59)
c.save()

p = Participant.objects.filter(first_name="Max", last_name="Mustermann").first()
if not p:
    p = Participant.objects.create(
        camp=c,
        first_name="Max",
        last_name="Mustermann",
        arrival_date=date.today(),
        departure_date=date.today() + timedelta(days=10),
    )
p_pin, _ = ParticipantPin.objects.get_or_create(participant=p)
p_pin.pin_hash = make_password("1234")
p_pin.must_set_pin = False
p_pin.save()

p_new = Participant.objects.filter(first_name="Lara", last_name="Neu").first()
if not p_new:
    p_new = Participant.objects.create(
        camp=c,
        first_name="Lara",
        last_name="Neu",
        arrival_date=date.today(),
        departure_date=date.today() + timedelta(days=10),
    )
p_new_pin, _ = ParticipantPin.objects.get_or_create(participant=p_new)
p_new_pin.pin_hash = ""
p_new_pin.must_set_pin = True
p_new_pin.save()
p_new.family_members.all().delete()

ShiftAssignment.objects.filter(participant=p_new).delete()

print("DB configured for GIFs")
