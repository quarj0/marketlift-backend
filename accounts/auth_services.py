import hashlib, hmac, secrets
from html import escape
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


def _mask_identifier(identifier):
    identifier = (identifier or "").strip()
    if "@" in identifier:
        return _mask_email(identifier)
    digits = "".join(ch for ch in identifier if ch.isdigit())
    return ("***" + digits[-2:]) if digits else "***"


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
    masked_destination = _mask_identifier(identifier)
    if not user:
        return {"success": True, "maskedDestination": masked_destination}
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
        (
            "Use the link below to reset your Marketlift password.\n\n"
            f"{url}\n\n"
            "If you did not request this change, you can ignore this email."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
        html_message=(
            '<div style="font-family:Arial,sans-serif;line-height:1.6;color:#0f172a">'
            '<h1 style="font-size:24px">Reset your Marketlift password</h1>'
            "<p>Use the button below to choose a new password.</p>"
            f'<p><a href="{escape(url, quote=True)}" style="display:inline-block;'
            "padding:12px 18px;border-radius:10px;background:#0b63f6;color:#fff;"
            'font-weight:700;text-decoration:none">Reset password</a></p>'
            '<p style="font-size:13px;color:#475569">If you did not request this '
            "change, you can ignore this email.</p></div>"
        ),
    )
    return {"success": True, "maskedDestination": masked_destination}


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


def _secret_digest(namespace, value):
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"{namespace}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def create_admin_login_challenge(*, user, request=None, send=True):
    from .models import AdminLoginChallenge

    AdminLoginChallenge.objects.filter(user=user, consumed_at__isnull=True).update(
        consumed_at=timezone.now()
    )
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    row = AdminLoginChallenge.objects.create(
        user=user,
        code_digest=_secret_digest(f"admin-mfa:{user.pk}", code),
        expires_at=timezone.now()
        + timedelta(seconds=settings.MARKETLIFT_ADMIN_LOGIN_CODE_TTL_SECONDS),
        requested_ip=(request.META.get("REMOTE_ADDR") if request else None),
    )
    if send:
        try:
            send_mail(
                "Your Marketlift Admin sign-in code",
                (
                    f"Your Marketlift Admin sign-in code is {code}. "
                    "It expires in 10 minutes. If you did not request this code, "
                    "you can ignore this email."
                ),
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
                html_message=(
                    '<div style="font-family:Arial,sans-serif;line-height:1.6;color:#0f172a">'
                    '<p style="font-size:12px;font-weight:700;letter-spacing:.08em;color:#0b63f6">'
                    'MARKETLIFT ADMIN</p>'
                    '<h1 style="font-size:24px;margin:8px 0 12px">Your sign-in code</h1>'
                    '<p>Enter this code to finish signing in to the Marketlift Admin console.</p>'
                    f'<p style="font-size:32px;font-weight:800;letter-spacing:.18em;margin:22px 0">{code}</p>'
                    '<p style="font-size:13px;color:#475569">This code expires in 10 minutes and can only be used once.</p>'
                    '<p style="font-size:13px;color:#475569">If you did not request this code, you can ignore this email.</p>'
                    '</div>'
                ),
            )
        except Exception:
            row.consumed_at = timezone.now()
            row.save(update_fields=("consumed_at", "updated_at"))
            raise
    return row, code


@transaction.atomic
def verify_admin_login_challenge(*, challenge_id, code):
    from .models import AdminLoginChallenge

    try:
        row = (
            AdminLoginChallenge.objects.select_for_update()
            .select_related("user")
            .get(pk=challenge_id)
        )
    except (AdminLoginChallenge.DoesNotExist, ValueError) as exc:
        raise ValidationError(
            "Invalid or expired administrator sign-in challenge."
        ) from exc
    if row.consumed_at is not None or row.expires_at <= timezone.now():
        raise ValidationError("Invalid or expired administrator sign-in challenge.")
    row.attempts += 1
    if row.attempts > 6:
        row.consumed_at = timezone.now()
        row.save(update_fields=("attempts", "consumed_at", "updated_at"))
        raise ValidationError("Too many administrator verification attempts.")
    expected = _secret_digest(f"admin-mfa:{row.user_id}", str(code).strip())
    if not hmac.compare_digest(row.code_digest, expected):
        row.save(update_fields=("attempts", "updated_at"))
        raise ValidationError("Invalid administrator verification code.")
    row.consumed_at = timezone.now()
    row.save(update_fields=("attempts", "consumed_at", "updated_at"))
    if not row.user.is_active or not row.user.is_staff:
        raise ValidationError("Administrator access is no longer available.")
    return row.user


def create_admin_invitation(*, email, role, invited_by, request=None, send=True):
    from .models import AdminInvitation
    from audit.services import record_audit_event

    email = User.objects.normalize_email((email or "").strip())
    if role not in User.AdminRole.values:
        raise ValidationError({"role": "Invalid administrator role."})
    if role == User.AdminRole.SUPER_ADMIN:
        raise ValidationError(
            {
                "role": "Super admin access must be granted through an existing superuser."
            }
        )
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError(
            {
                "email": "This email already has a Marketlift account. Assign its administrator role directly."
            }
        )
    AdminInvitation.objects.filter(
        email__iexact=email, accepted_at__isnull=True, revoked_at__isnull=True
    ).update(revoked_at=timezone.now())
    raw_token = secrets.token_urlsafe(32)
    invitation = AdminInvitation.objects.create(
        email=email,
        role=role,
        token_digest=_secret_digest("admin-invite", raw_token),
        invited_by=invited_by,
        expires_at=timezone.now() + timedelta(hours=48),
    )
    if send:
        base = settings.MARKETLIFT_ADMIN_FRONTEND_URL.rstrip("/")
        send_mail(
            "You're invited to Marketlift administration",
            f"Accept your Marketlift administrator invitation: {base}/accept-invite?token={raw_token}\n\nThis invitation expires in 48 hours.",
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
    record_audit_event(
        actor=invited_by,
        action="admin.invitation_created",
        target=invitation,
        target_type="admin_invitation",
        target_label=email,
        metadata={"role": role},
        request=request,
    )
    return invitation, raw_token


@transaction.atomic
def accept_admin_invitation(*, token, full_name, password):
    from django.contrib.auth.password_validation import validate_password
    from .models import AdminInvitation

    digest = _secret_digest("admin-invite", (token or "").strip())
    try:
        invitation = AdminInvitation.objects.select_for_update().get(
            token_digest=digest
        )
    except AdminInvitation.DoesNotExist as exc:
        raise ValidationError("Invalid or expired administrator invitation.") from exc
    if not invitation.active:
        raise ValidationError("Invalid or expired administrator invitation.")
    if User.objects.filter(email__iexact=invitation.email).exists():
        raise ValidationError("This invitation can no longer be accepted.")
    candidate = User(email=invitation.email, full_name=(full_name or "").strip())
    if not candidate.full_name:
        raise ValidationError({"fullName": "Full name is required."})
    validate_password(password, candidate)
    user = User.objects.create_user(
        email=invitation.email,
        full_name=candidate.full_name,
        password=password,
        is_active=True,
        is_staff=True,
        admin_role=invitation.role,
        email_verified_at=timezone.now(),
    )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=("accepted_at", "updated_at"))
    return user


@transaction.atomic
def revoke_admin_invitation(*, invitation, actor, request=None):
    from audit.services import record_audit_event

    if invitation.accepted_at is not None:
        raise ValidationError("An accepted invitation cannot be revoked.")
    if invitation.revoked_at is None:
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=("revoked_at", "updated_at"))
    record_audit_event(
        actor=actor,
        action="admin.invitation_revoked",
        target=invitation,
        target_type="admin_invitation",
        target_label=invitation.email,
        metadata={"role": invitation.role},
        request=request,
    )
    return invitation
