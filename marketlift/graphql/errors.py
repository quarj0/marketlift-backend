from django.core.exceptions import ValidationError
from graphql import GraphQLError


def validation_error(exc: ValidationError) -> GraphQLError:
    if hasattr(exc, "message_dict"):
        parts = []
        for field, messages in exc.message_dict.items():
            if not isinstance(messages, (list, tuple)):
                messages = [messages]
            parts.extend(f"{field}: {message}" for message in messages)
        return GraphQLError("; ".join(parts))
    messages = getattr(exc, "messages", None)
    if messages:
        return GraphQLError("; ".join(messages))
    return GraphQLError(str(exc))
