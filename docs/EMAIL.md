# Transactional and notification email

Marketlift uses **Resend through django-anymail** for account email and notification
delivery. This includes password resets, email verification, administrator
invitations, sign-in challenges, marketplace message alerts, listing updates,
recommendations and other notification types enabled by the user's preferences.

## Production configuration

Set these values in the backend deployment environment. Never commit the real API key.

```dotenv
RESEND_API_KEY=re_...
DEFAULT_FROM_EMAIL=Marketlift <noreply@marketlift.com.br>
MARKETLIFT_FRONTEND_URL=https://marketlift.com.br
```

The sender address or domain must be verified in Resend. Configure SPF, DKIM and
DMARC for the sending domain before production use.

Notification emails are queued immediately after the related database transaction
commits. Celery Beat also runs a recovery sweep every minute for pending emails,
so a temporary broker/provider failure can be retried.

## Verify delivery

After changing environment variables, restart the Django web process, Celery
worker and Celery Beat process. Then run:

```bash
uv run python manage.py sendtestemail recipient@example.com
uv run python manage.py deployment_diagnostics
```

Then verify a real marketplace flow with two accounts:

1. Enable **Email me when I receive a message** for the receiving account.
2. Send a message from the other account.
3. Confirm the in-app notification appears and the email is delivered.
4. Inspect backend/Celery logs if delivery remains pending or records a provider error.

For browser/PWA push, also set `MARKETLIFT_VAPID_PRIVATE_KEY` and
`MARKETLIFT_VAPID_SUBJECT`, then enable browser notifications on the receiving
device from Account Settings.
