from django.apps import apps
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Camp, Participant, ParticipantFamilyMember, ParticipantFamilyMemberPin, ParticipantPin


@receiver(post_delete, sender=Camp)
def activate_remaining_camp(sender, **kwargs):
    if not Camp.objects.filter(is_active=True).exists():
        remaining = Camp.objects.order_by("-updated_at", "-pk").first()
        if remaining is not None:
            remaining.is_active = True
            remaining.save(update_fields=["is_active"])


@receiver(post_save, sender=Participant)
def create_participant_pin(sender, instance, created, **kwargs):
    if created:
        ParticipantPin.objects.get_or_create(participant=instance)


@receiver(post_save, sender=ParticipantFamilyMember)
def create_family_member_pin(sender, instance, created, **kwargs):
    if instance.role == ParticipantFamilyMember.Role.COMPANION:
        ParticipantFamilyMemberPin.objects.get_or_create(family_member=instance)


def remove_local_seed_ownership(sender, instance, using, **kwargs):
    """Never transfer seed ownership to a later row reusing a deleted primary key."""
    from .models import LocalSeedOwnership

    if sender._meta.apps is apps:
        LocalSeedOwnership.objects.using(using).filter(
            model_label=sender._meta.label_lower, object_id=str(instance.pk)
        ).delete()


SEED_OWNERSHIP_MODELS = {
    "auth.user",
    "billing.camp",
    "billing.campkioskaccess",
    "billing.participant",
    "billing.participantpin",
    "billing.participantfamilymember",
    "billing.participantfamilymemberpin",
    "billing.participantbookinglink",
    "billing.attendanceday",
    "billing.mealplanentry",
    "billing.mealbookingoverride",
    "billing.mealorder",
    "billing.mealsignup",
    "billing.charge",
    "billing.bookingauditlog",
    "billing.payment",
    "billing.expense",
    "billing.expenseallocation",
    "billing.settlementrun",
    "billing.settlement",
    "billing.pricerule",
}

for model_label in SEED_OWNERSHIP_MODELS:
    post_delete.connect(
        remove_local_seed_ownership,
        sender=apps.get_model(model_label),
        dispatch_uid=f"billing.seed_ownership_cleanup.{model_label}",
    )
