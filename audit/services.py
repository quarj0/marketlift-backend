def _request_metadata(request):
    if request is None:
        return None, ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else request.META.get("REMOTE_ADDR")
    ) or None
    return ip, request.META.get("HTTP_USER_AGENT", "")[:500]


def record_audit_event(
    *,
    actor,
    action: str,
    target=None,
    target_type: str,
    target_label: str = "",
    metadata=None,
    request=None,
    target_id=None,
):
    from .models import AuditEvent

    ip, user_agent = _request_metadata(request)
    actual_id = target_id if target_id is not None else getattr(target, "pk", "")
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        actor_name=(
            getattr(actor, "full_name", "") or getattr(actor, "email", "")
            if actor
            else "System"
        ),
        actor_email=getattr(actor, "email", "") if actor else "",
        action=action,
        target_type=target_type,
        target_id=str(actual_id or ""),
        target_label=target_label,
        metadata=metadata or {},
        ip_address=ip,
        user_agent=user_agent,
    )
