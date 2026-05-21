from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Participant, ParticipantPin


@receiver(post_save, sender=Participant)
def create_participant_pin(sender, instance, created, **kwargs):
    if created:
        ParticipantPin.objects.get_or_create(participant=instance)
