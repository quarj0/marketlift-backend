import hashlib, hmac, secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from .models import EmailVerificationChallenge, PasswordResetRequest, User


def _digest(user_id, code):
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"verify:{user_id}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _mask_email(email):
    local, _, domain = email.partition("@")
    return (local[:1] + "***@" + domain) if domain else "***"


def create_email_verification(*, user, send=True):
    EmailVerificationChallenge.objects.filter(
        user=user, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())
    code = f"{secrets.randbelow(900000)+100000:06d}"
    row = EmailVerificationChallenge.objects.create(
        user=user,
        code_digest=_digest(user.pk, code),
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    if send:
        send_mail(
            "Your Marketlift verification code",
            f"Your Marketlift verification code is {code}. It expires in 15 minutes.",
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    return row, code


@transaction.atomic
def verify_email_code(*, user, code):
    row = (
        EmailVerificationChallenge.objects.select_for_update()
        .filter(user=user, consumed_at__isnull=True)
        .first()
    )
    if not row or row.expires_at <= timezone.now():
        raise ValidationError("Verification code has expired. Request a new code.")
    row.attempts += 1
    if row.attempts > 8:
        row.consumed_at = timezone.now()
        row.save(update_fields=("attempts", "consumed_at", "updated_at"))
        raise ValidationError("Too many verification attempts. Request a new code.")
    if not hmac.compare_digest(row.code_digest, _digest(user.pk, str(code).strip())):
        row.save(update_fields=("attempts", "updated_at"))
        raise ValidationError("Invalid verification code.")
    row.consumed_at = timezone.now()
    row.save(update_fields=("attempts", "consumed_at", "updated_at"))
    user.email_verified_at = timezone.now()
    user.is_active = True
    user.save(update_fields=("email_verified_at", "is_active", "updated_at"))
    return user


def request_password_reset(*, identifier, request=None):
    identifier = (identifier or "").strip()
    qs = (
        User.objects.filter(email__iexact=identifier)
        if "@" in identifier
        else User.objects.filter(phone=identifier)
    )
    user = qs.first()
    if not user:
        return {"success": True, "maskedDestination": "***"}
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    combined = f"{uid}.{token}"
    base = settings.MARKETLIFT_FRONTEND_URL.rstrip("/")
    url = f"{base}/reset-password?token={combined}"
    PasswordResetRequest.objects.create(
        user=user, requested_ip=(request.META.get("REMOTE_ADDR") if request else None)
    )
    send_mail(
        "Reset your Marketlift password",
        f"Use this link to reset your Marketlift password: {url}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    return {"success": True, "maskedDestination": _mask_email(user.email)}


@transaction.atomic
def reset_password(*, combined_token, new_password):
    from django.contrib.auth.password_validation import validate_password

    try:
        uid, token = combined_token.split(".", 1)
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
    except Exception as exc:
        raise ValidationError("Invalid or expired password reset token.") from exc
    if not default_token_generator.check_token(user, token):
        raise ValidationError("Invalid or expired password reset token.")
    validate_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=("password", "updated_at"))
    PasswordResetRequest.objects.filter(user=user, used_at__isnull=True).update(
        used_at=timezone.now()
    )
    return True
