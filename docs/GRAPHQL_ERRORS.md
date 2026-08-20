# GraphQL error contract

Marketlift GraphQL operations return business/application failures through the
standard GraphQL `errors` array. HTTP responses normally remain `200` when the
GraphQL document itself was processed successfully.

Expected application errors include stable metadata in `extensions`:

```json
{
  "data": null,
  "errors": [
    {
      "message": "This moderation case is already final as 'approved'.",
      "path": ["rejectListing"],
      "extensions": {
        "code": "MODERATION_CASE_FINAL",
        "status": 409
      }
    }
  ]
}
```

Clients should branch on `extensions.code`, not by parsing English messages.
`extensions.status` is HTTP-like domain metadata and does not imply that the
GraphQL HTTP response itself uses that status code.

## Validation errors

Field validation errors use a domain validation code and `422` metadata. When
Django provides field-level errors, Marketlift preserves them in
`extensions.details.fields`:

```json
{
  "message": "brand: Brand is required.; model: Model is required.",
  "extensions": {
    "code": "LISTING_VALIDATION_ERROR",
    "status": 422,
    "details": {
      "fields": {
        "brand": ["Brand is required."],
        "model": ["Model is required."]
      }
    }
  }
}
```

## Common codes

- `AUTHENTICATION_REQUIRED` — no authenticated session (`401` metadata)
- `ADMIN_PERMISSION_REQUIRED` — staff access required (`403`)
- `ADMIN_ROLE_FORBIDDEN` — staff role is insufficient (`403`)
- `SELLER_REQUIRED` — selling has not been activated (`403`)
- `*_NOT_FOUND` — requested resource does not exist or is inaccessible (`404`)
- `*_VALIDATION_ERROR` — invalid input/business rule (`422`)
- `MODERATION_CASE_FINAL` — irreversible moderation decision conflict (`409`)
- `REPORT_FINAL` — irreversible report decision conflict (`409`)
- `VERIFICATION_FINAL` — irreversible verification decision conflict (`409`)
- `GRAPHQL_REQUEST_ERROR` — GraphQL syntax/schema/validation error (`400`)
- `INTERNAL_SERVER_ERROR` — unexpected resolver failure (`500`)

Unexpected resolver exceptions are still logged server-side. In production,
Marketlift replaces their client-visible message with `An unexpected error
occurred.` while preserving `INTERNAL_SERVER_ERROR` metadata.

Expected `DomainGraphQLError` failures are not printed as full resolver
tracebacks by Marketlift's schema logger. This keeps normal business-rule
conflicts from looking like server crashes in development logs.
