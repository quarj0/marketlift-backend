from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from uploads.models import UploadAsset
from uploads.services import claim_upload
from marketlift.location.validators import validate_location_strings
from marketlift.markets.service import normalize_enabled_country_code

from .models import AccountSettings, User


@transaction.atomic
def suspend_account(*, user, actor, reason: str, request=None):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A suspension reason is required."})
    if user.is_superuser:
        raise ValidationError(
            "A superuser account cannot be suspended through this action."
        )
    if not user.is_active and user.suspended_at:
        return user

    user.is_active = False
    user.suspended_at = timezone.now()
    user.suspension_reason = reason
    user.save(
        update_fields=("is_active", "suspended_at", "suspension_reason", "updated_at")
    )
    record_audit_event(
        actor=actor,
        action="account.suspended",
        target=user,
        target_type="user",
        target_label=user.full_name or user.email,
        metadata={"reason": reason},
        request=request,
    )
    return user


@transaction.atomic
def reactivate_account(*, user, actor, reason: str, request=None):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reactivation reason is required."})
    if user.is_active and user.suspended_at is None:
        return user

    previous_reason = user.suspension_reason
    user.is_active = True
    user.suspended_at = None
    user.suspension_reason = ""
    user.deactivated_at = None
    user.deactivation_reason = ""
    user.save(
        update_fields=(
            "is_active",
            "suspended_at",
            "suspension_reason",
            "deactivated_at",
            "deactivation_reason",
            "updated_at",
        )
    )
    record_audit_event(
        actor=actor,
        action="account.reactivated",
        target=user,
        target_type="user",
        target_label=user.full_name or user.email,
        metadata={"reason": reason, "previous_suspension_reason": previous_reason},
        request=request,
    )
    return user


def get_account_settings(user):
    return AccountSettings.objects.get_or_create(user=user)[0]


@transaction.atomic
def update_profile(*, user, data, avatar_upload=None, request=None):
    allowed = (
        "full_name",
        "email",
        "phone",
        "bio",
        "country_code",
        "state",
        "state_code",
        "city",
        "district",
    )
    email_changed = False

    if "email" in data and data["email"] is not None:
        email = User.objects.normalize_email(str(data["email"]).strip())
        if not email:
            raise ValidationError({"email": "Email is required."})
        if email.lower() != user.email.lower():
            if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                raise ValidationError({"email": "Email is already in use."})
            data["email"] = email
            user.email_verified_at = None
            email_changed = True

    if "phone" in data and data["phone"] is not None:
        phone = str(data["phone"]).strip() or None
        if phone != user.phone:
            if phone and User.objects.filter(phone=phone).exclude(pk=user.pk).exists():
                raise ValidationError({"phone": "Phone number is already in use."})
            data["phone"] = phone
            user.phone_verified_at = None

    if "country_code" in data and data["country_code"] is not None:
        data["country_code"] = normalize_enabled_country_code(data["country_code"])

    location_keys = {"country_code", "state", "state_code", "city", "district"}
    if location_keys.intersection(data):
        country_code = data.get("country_code", user.country_code)
        state = data.get("state", user.state)
        state_code = data.get("state_code", user.state_code)
        city = data.get("city", user.city)
        district = data.get("district", user.district)
        # Empty location remains valid on a buyer account. Once city/state values are
        # supplied, reuse the same country-aware validation used by listings.
        if any(str(value or "").strip() for value in (state, state_code, city, district)):
            location = validate_location_strings(
                country_code=country_code,
                state=state,
                state_code=state_code,
                city=city,
                district=district,
            )
            data.update(location)
        else:
            data["country_code"] = country_code
            data["state"] = ""
            data["state_code"] = ""
            data["city"] = ""
            data["district"] = ""

    if "full_name" in data:
        data["full_name"] = str(data["full_name"] or "").strip()
        if not data["full_name"]:
            raise ValidationError({"fullName": "Full name is required."})

    for key in allowed:
        if key in data and data[key] is not None:
            setattr(user, key, data[key])

    if avatar_upload is not None:
        asset = claim_upload(
            asset=avatar_upload, user=user, purpose=UploadAsset.Purpose.AVATAR
        )
        user.avatar_url = asset.preferred_image_url("thumbnail")

    user.full_clean(exclude=("password",))
    user.save()

    if email_changed:
        from .auth_services import create_email_verification

        transaction.on_commit(lambda: create_email_verification(user=user))

    record_audit_event(
        actor=user,
        action="account.profile_updated",
        target=user,
        target_type="user",
        target_label=user.full_name or user.email,
        metadata={"emailChanged": email_changed},
        request=request,
    )
    return user


def change_password(*, request, user, current_password, new_password):
    from django.contrib.auth.password_validation import validate_password

    if not user.check_password(current_password):
        raise ValidationError({"currentPassword": "Current password is incorrect."})
    validate_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=("password", "updated_at"))
    if request is not None:
        update_session_auth_hash(request, user)
    record_audit_event(
        actor=user,
        action="account.password_changed",
        target=user,
        target_type="user",
        target_label=user.full_name or user.email,
        request=request,
    )
    return True


@transaction.atomic
def deactivate_account(*, user, reason="", request=None):
    if user.is_superuser:
        raise ValidationError(
            "A superuser account cannot self-deactivate through this action."
        )
    user.is_active = False
    user.deactivated_at = timezone.now()
    user.deactivation_reason = (reason or "").strip()
    user.save(
        update_fields=(
            "is_active",
            "deactivated_at",
            "deactivation_reason",
            "updated_at",
        )
    )
    record_audit_event(
        actor=user,
        action="account.deactivated",
        target=user,
        target_type="user",
        target_label=user.full_name or user.email,
        metadata={"reason": user.deactivation_reason},
        request=request,
    )
    return True
