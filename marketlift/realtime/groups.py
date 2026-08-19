from __future__ import annotations


def user_group(user_id) -> str:
    """Return a Channels-safe private group name for a Marketlift account."""
    return f"marketlift.user.{user_id}"
