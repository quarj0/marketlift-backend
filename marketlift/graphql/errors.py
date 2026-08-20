from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from graphql import GraphQLError


class DomainGraphQLError(GraphQLError):
    """Expected application error that is safe to return to GraphQL clients."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        extensions: dict[str, Any] = {
            "code": code,
            "status": int(status),
        }
        if details:
            extensions["details"] = dict(details)
        super().__init__(message, extensions=extensions)
        self.code = code
        self.status = int(status)


def domain_error(
    message: str,
    *,
    code: str = "BAD_REQUEST",
    status: int = 400,
    details: Mapping[str, Any] | None = None,
) -> DomainGraphQLError:
    return DomainGraphQLError(
        str(message).strip() or "Request could not be completed.",
        code=code,
        status=status,
        details=details,
    )


def _validation_payload(exc: ValidationError) -> tuple[str, dict[str, list[str]]]:
    fields: dict[str, list[str]] = {}

    if hasattr(exc, "message_dict"):
        parts: list[str] = []
        for field, raw_messages in exc.message_dict.items():
            messages = (
                list(raw_messages)
                if isinstance(raw_messages, (list, tuple))
                else [raw_messages]
            )
            clean_messages = [str(message) for message in messages]
            fields[str(field)] = clean_messages
            parts.extend(f"{field}: {message}" for message in clean_messages)
        return "; ".join(parts), fields

    messages = [str(message) for message in (getattr(exc, "messages", None) or [])]
    if messages:
        return "; ".join(messages), fields

    return str(exc), fields


def validation_error(
    exc: ValidationError,
    *,
    code: str = "VALIDATION_ERROR",
    status: int = 422,
) -> DomainGraphQLError:
    message, fields = _validation_payload(exc)
    details = {"fields": fields} if fields else None
    return domain_error(message, code=code, status=status, details=details)


def not_found_error(
    resource: str,
    *,
    code: str | None = None,
    message: str | None = None,
) -> DomainGraphQLError:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", resource).strip("_").upper()
    return domain_error(
        message or f"{resource} not found.",
        code=code or f"{normalized}_NOT_FOUND",
        status=404,
    )


def authentication_error(
    message: str = "Authentication required.",
    *,
    code: str = "AUTHENTICATION_REQUIRED",
) -> DomainGraphQLError:
    return domain_error(message, code=code, status=401)


def forbidden_error(
    message: str = "You do not have permission to perform this action.",
    *,
    code: str = "PERMISSION_DENIED",
) -> DomainGraphQLError:
    return domain_error(message, code=code, status=403)


def permission_error(
    exc: PermissionDenied | Exception,
    *,
    code: str = "PERMISSION_DENIED",
) -> DomainGraphQLError:
    return forbidden_error(str(exc), code=code)


def conflict_error(
    message: str,
    *,
    code: str = "CONFLICT",
    details: Mapping[str, Any] | None = None,
) -> DomainGraphQLError:
    return domain_error(message, code=code, status=409, details=details)


def finality_validation_error(
    exc: ValidationError,
    *,
    final_code: str,
    default_code: str,
) -> DomainGraphQLError:
    """Map irreversible state-transition failures to HTTP-like 409 metadata."""

    message, _ = _validation_payload(exc)
    lowered = message.lower()
    markers = (
        "already final",
        "final decision",
        "final report",
        "final moderation",
        "cannot be changed",
        "cannot be reopened",
        "cannot return to review",
        "cannot be approved",
        "cannot be rejected",
        "already has a final",
    )
    if any(marker in lowered for marker in markers):
        return validation_error(exc, code=final_code, status=409)
    return validation_error(exc, code=default_code, status=422)
