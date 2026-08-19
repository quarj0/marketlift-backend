# Security Notes

Before production, run:

```bash
uv run python manage.py check --deploy
uv run python manage.py test
```

## Implemented controls

- session authentication with CSRF protection
- staff authorization for admin GraphQL operations
- password validators and one-time password reset tokens
- rate limits on authentication and GraphQL requests
- GraphQL depth/token/alias limits
- upload ownership/purpose/size/MIME validation
- actual image-content validation
- private attachment authorization
- webhook signature verification and payment idempotency
- immutable audit events for sensitive operations
- irreversible moderation/report/verification decisions enforced server-side
- secure-cookie/HSTS/proxy settings controlled by environment variables
- account/seller suspension enforced by backend services/public query managers

## Production environment

At minimum configure unique secret key, HTTPS cookie flags, trusted origins, allowed hosts and secure proxy settings appropriate to the chosen host.

Never put provider/API secrets in `PlatformConfiguration`; secrets remain deployment-managed environment/secrets values.

## Authorization review checklist

Test negative cases for:

- Buyer A reading Buyer B conversations
- Seller A editing Seller B listings
- a user claiming another user's upload
- non-staff calling admin fields
- a reporter reading another user's private data
- suspended sellers publishing or messaging
- final decisions being reversed
