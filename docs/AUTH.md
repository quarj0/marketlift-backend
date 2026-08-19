# Authentication and Account Lifecycle

## Account model

Marketlift has one customer `User`. Selling is optional and is activated by creating a `SellerProfile`; buyer and seller are not separate login roles.

## Registration

```text
register -> inactive account -> email code -> verified/active session
```

Registration records terms acceptance, checks unique email/phone, sends a short-lived email challenge, and keeps the account inactive until the email is verified.

Admin configuration can independently disable:

- new customer registrations
- seller activation

## Session login

Marketplace and admin use separate REST entry points. Admin login additionally requires `is_staff=True`.

Sessions use Django's session framework and are CSRF protected. The admin danger-zone mutation `invalidateAllSessions(reason)` deletes active server-side sessions and writes an audit event.

## Passwords

- password validation uses Django password validators
- current-password changes preserve the authenticated session
- forgot-password responses do not reveal whether an account exists
- reset links use Django's one-time password reset token generator

## Account deactivation

Customer deactivation is a soft account shutdown: `is_active=False` plus deactivation timestamp/reason. Historical listings, payments, reports, audit events, and support records are preserved according to their own retention rules.

## Rate limits

Sensitive public auth endpoints are cache-rate-limited. Rate limiting fails open during a cache outage so it cannot become a total marketplace outage; authentication and authorization still apply.
