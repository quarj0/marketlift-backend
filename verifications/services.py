from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from marketlift.markets.service import (
    identity_provider_for_country_code,
    profile_for_country_code,
)
from notifications.services import create_admin_notifications, create_notification
from .models import VerificationSubmission


def require_identity_verification_enabled():
    enabled = getattr(
        settings, "MARKETLIFT_IDENTITY_VERIFICATION_ENABLED", False
    ) or getattr(settings, "MARKETLIFT_CPF_VERIFICATION_ENABLED", False)
    if not enabled:
        raise ValidationError("Seller identity verification is not available yet.")


def require_cpf_verification_enabled():
    """Backward-compatible alias for the original Brazil API/tests."""
    return require_identity_verification_enabled()


def normalize_cpf(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 11 or digits == digits[0] * 11:
        raise ValidationError({"cpf": "Enter a valid CPF."})
    numbers = [int(c) for c in digits]
    for size in (9, 10):
        total = sum(numbers[i] * (size + 1 - i) for i in range(size))
        check = (total * 10) % 11
        if check == 10:
            check = 0
        if numbers[size] != check:
            raise ValidationError({"cpf": "Enter a valid CPF."})
    return digits


def normalize_identity_number(value: str, *, country_code: str) -> str:
    profile = profile_for_country_code(country_code)
    if profile.country_code == "BR":
        return normalize_cpf(value)
    raw = (value or "").strip().upper()
    # External providers remain authoritative for country-specific identity rules.
    # This local check only rejects malformed/unsafe values before hashing them.
    normalized = re.sub(r"[\s.-]+", "", raw)
    if not re.fullmatch(r"[A-Z0-9]{6,32}", normalized):
        raise ValidationError(
            {"identityNumber": f"Enter a valid {profile.identity_label} number."}
        )
    return normalized


def identity_digest(
    identity_number: str, *, country_code: str, identity_type: str
) -> str:
    canonical = (
        f"{country_code.upper()}:{identity_type.strip().lower()}:{identity_number}"
    )
    return hmac.new(
        settings.SECRET_KEY.encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()


def cpf_digest(cpf: str) -> str:
    # Preserve the legacy digest algorithm so existing Brazil duplicate rows still match.
    return hmac.new(
        settings.SECRET_KEY.encode(), cpf.encode(), hashlib.sha256
    ).hexdigest()


def mask_cpf(cpf: str) -> str:
    return f"***.***.***-{cpf[-2:]}"


def mask_identity(identity_number: str, *, country_code: str) -> str:
    if country_code.upper() == "BR":
        return mask_cpf(identity_number)
    tail = identity_number[-4:] if len(identity_number) >= 4 else identity_number
    return f"••••{tail}"


@transaction.atomic
def submit_verification(
    *,
    seller,
    legal_name: str,
    birth_date: date,
    identity_number: str | None = None,
    identity_type: str | None = None,
    country_code: str | None = None,
    cpf: str | None = None,
    document_type: str = "",
    document_front_url: str = "",
    document_back_url: str = "",
    selfie_url: str = "",
    request=None,
):
    require_identity_verification_enabled()
    if seller.verified:
        raise ValidationError("This seller is already verified.")
    if seller.is_suspended:
        raise ValidationError("Selling access is suspended.")
    if VerificationSubmission.objects.filter(
        seller=seller,
        status__in=[
            VerificationSubmission.Status.PENDING,
            VerificationSubmission.Status.REVIEW,
        ],
    ).exists():
        raise ValidationError("A verification submission is already being reviewed.")
    legal_name = (legal_name or "").strip()
    if not legal_name:
        raise ValidationError({"legalName": "Legal name is required."})
    if birth_date >= timezone.localdate():
        raise ValidationError({"birthDate": "Birth date must be in the past."})
    if (
        document_type
        and document_type not in VerificationSubmission.DocumentType.values
    ):
        raise ValidationError({"documentType": "Invalid identity document type."})

    profile = profile_for_country_code(
        country_code or getattr(seller, "country_code", None)
    )
    if getattr(seller, "country_code", profile.country_code) != profile.country_code:
        raise ValidationError(
            {"countryCode": "Verification country must match the seller market."}
        )
    raw_identity = identity_number or cpf or ""
    if not raw_identity:
        raise ValidationError(
            {"identityNumber": f"{profile.identity_label} number is required."}
        )
    canonical_type = (identity_type or profile.identity_key).strip().lower()
    normalized = normalize_identity_number(
        raw_identity, country_code=profile.country_code
    )
    digest = identity_digest(
        normalized,
        country_code=profile.country_code,
        identity_type=canonical_type,
    )
    masked = mask_identity(normalized, country_code=profile.country_code)

    flags = []
    risk = VerificationSubmission.RiskLevel.LOW
    duplicate = (
        VerificationSubmission.objects.filter(
            identity_digest=digest,
            status=VerificationSubmission.Status.VERIFIED,
        )
        .exclude(seller=seller)
        .exists()
    )
    # Existing Brazil rows may predate generic identity_digest.
    legacy_cpf_digest = cpf_digest(normalized) if profile.country_code == "BR" else ""
    if not duplicate and legacy_cpf_digest:
        duplicate = (
            VerificationSubmission.objects.filter(
                cpf_digest=legacy_cpf_digest,
                status=VerificationSubmission.Status.VERIFIED,
            )
            .exclude(seller=seller)
            .exists()
        )
    if duplicate:
        flags.append(
            f"{profile.identity_label} is already associated with another verified seller"
        )
        risk = VerificationSubmission.RiskLevel.HIGH

    verification = VerificationSubmission.objects.create(
        seller=seller,
        identity_country_code=profile.country_code,
        identity_type=canonical_type,
        identity_digest=digest,
        identity_masked=masked,
        cpf_digest=legacy_cpf_digest,
        cpf_masked=mask_cpf(normalized) if profile.country_code == "BR" else "",
        legal_name=legal_name,
        birth_date=birth_date,
        document_type=document_type,
        document_front_url=document_front_url,
        document_back_url=document_back_url,
        selfie_url=selfie_url,
        provider=identity_provider_for_country_code(profile.country_code),
        provider_result="Identity checks queued for review",
        risk_flags=flags,
        risk_level=risk,
        automated_checks={
            "identity_format": "passed",
            "document_quality": "queued",
            "face_match": "queued",
            "duplicate_check": "flagged" if flags else "passed",
        },
    )
    record_audit_event(
        actor=seller.user,
        action="verification.submitted",
        target=verification,
        target_type="verification",
        target_label=str(seller),
        metadata={
            "risk_level": risk,
            "country_code": profile.country_code,
            "identity_type": canonical_type,
        },
        request=request,
    )
    create_admin_notifications(
        notification_type="verification",
        title="New seller verification",
        body=f"{seller} submitted identity verification.",
        href="/verifications",
        data={
            "verificationId": str(verification.id),
            "riskLevel": risk,
            "countryCode": profile.country_code,
        },
        preference="admin_verification_queue_alerts",
    )
    return verification


@transaction.atomic
def move_to_review(*, verification, actor, note: str = "", request=None):
    require_identity_verification_enabled()
    if verification.is_final:
        raise ValidationError("A final verification decision cannot be reopened.")
    if verification.status == VerificationSubmission.Status.REVIEW:
        return verification
    verification.status = VerificationSubmission.Status.REVIEW
    verification.review_started_at = timezone.now()
    if note.strip():
        verification.decision_note = note.strip()
    verification.save(
        update_fields=("status", "review_started_at", "decision_note", "updated_at")
    )
    record_audit_event(
        actor=actor,
        action="verification.moved_to_review",
        target=verification,
        target_type="verification",
        target_label=str(verification.seller),
        metadata={"note": note.strip()},
        request=request,
    )
    return verification


@transaction.atomic
def approve_verification(*, verification, actor, note: str, request=None):
    require_identity_verification_enabled()
    note = (note or "").strip()
    if verification.is_final:
        if verification.status == VerificationSubmission.Status.VERIFIED:
            return verification
        raise ValidationError("A rejected verification cannot be approved.")
    now = timezone.now()
    verification.status = VerificationSubmission.Status.VERIFIED
    verification.decided_at = now
    verification.decided_by = actor
    verification.decision_note = note
    verification.provider_result = (
        verification.provider_result or "Identity matched successfully"
    )
    verification.save(
        update_fields=(
            "status",
            "decided_at",
            "decided_by",
            "decision_note",
            "provider_result",
            "updated_at",
        )
    )
    seller = verification.seller
    seller.verified_at = now
    seller.save(update_fields=("verified_at", "updated_at"))
    record_audit_event(
        actor=actor,
        action="verification.approved",
        target=verification,
        target_type="verification",
        target_label=str(seller),
        metadata={"note": note},
        request=request,
    )
    create_notification(
        user=seller.user,
        notification_type="verification",
        title="Seller verification approved",
        body="Your seller identity has been verified.",
        href="/selling/verification",
    )
    return verification


@transaction.atomic
def reject_verification(*, verification, actor, note: str, request=None):
    require_identity_verification_enabled()
    note = (note or "").strip()
    if not note:
        raise ValidationError({"note": "A rejection reason is required."})
    if verification.is_final:
        if verification.status == VerificationSubmission.Status.REJECTED:
            return verification
        raise ValidationError("An approved verification cannot be rejected.")
    verification.status = VerificationSubmission.Status.REJECTED
    verification.decided_at = timezone.now()
    verification.decided_by = actor
    verification.decision_note = note
    verification.provider_result = (
        verification.provider_result or "Identity information could not be confirmed"
    )
    verification.save(
        update_fields=(
            "status",
            "decided_at",
            "decided_by",
            "decision_note",
            "provider_result",
            "updated_at",
        )
    )
    record_audit_event(
        actor=actor,
        action="verification.rejected",
        target=verification,
        target_type="verification",
        target_label=str(verification.seller),
        metadata={"reason": note},
        request=request,
    )
    create_notification(
        user=verification.seller.user,
        notification_type="verification",
        title="Seller verification needs attention",
        body="We could not confirm your identity information. You can review your details and submit a new verification.",
        href="/selling/verification",
        data={"reason": note},
    )
    return verification
