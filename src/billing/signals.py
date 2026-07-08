from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Camp, Participant, ParticipantFamilyMember, ParticipantFamilyMemberPin, ParticipantPin


@receiver(post_delete, sender=Camp)
def activate_remaining_camp(sender, **kwargs):
    if not Camp.objects.filter(is_active=True).exists():
        remaining = Camp.objects.order_by("-updated_at", "-pk").first()
        if remaining is not None:
            Camp.objects.filter(pk=remaining.pk).update(is_active=True)


@receiver(post_save, sender=Participant)
def create_participant_pin(sender, instance, created, **kwargs):
    if created:
        ParticipantPin.objects.get_or_create(participant=instance)


@receiver(post_save, sender=ParticipantFamilyMember)
def create_family_member_pin(sender, instance, created, **kwargs):
    if instance.role == ParticipantFamilyMember.Role.COMPANION:
        ParticipantFamilyMemberPin.objects.get_or_create(family_member=instance)
