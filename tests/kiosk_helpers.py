from billing.kiosk_access import KIOSK_FAMILY_MEMBER_SESSION_KEY, KIOSK_PARTICIPANT_SESSION_KEY
from billing.kiosk_security import KIOSK_PIN_FINGERPRINT_SESSION_KEY, kiosk_pin_fingerprint


def authenticate_kiosk_session(session, participant, *, family_member=None):
    """Populate a test kiosk session with the identity proof created by kiosk login."""
    session[KIOSK_PARTICIPANT_SESSION_KEY] = participant.pk
    if family_member is not None:
        session[KIOSK_FAMILY_MEMBER_SESSION_KEY] = family_member.pk
        identity = family_member
    else:
        identity = participant
    session[KIOSK_PIN_FINGERPRINT_SESSION_KEY] = kiosk_pin_fingerprint(identity.pin.pin_hash)
