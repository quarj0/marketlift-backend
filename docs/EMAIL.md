# Transactional email

Marketlift uses Django's SMTP backend for password resets, email verification,
administrator invitations, and sign-in challenges.

## Configure SMTP

Set these values in the deployment environment or the local `.env` file. Do
not commit real credentials.

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.provider.example
EMAIL_PORT=587
EMAIL_HOST_USER=provider-account
EMAIL_HOST_PASSWORD=provider-secret
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
EMAIL_TIMEOUT=15
DEFAULT_FROM_EMAIL=Marketlift <noreply@your-verified-domain.example>
MARKETLIFT_FRONTEND_URL=https://your-marketplace.example
```

For implicit TLS on port 465, set `EMAIL_USE_TLS=false` and
`EMAIL_USE_SSL=true`. Never enable both.

The sender address or domain must be verified with the selected email provider.
SPF, DKIM, and DMARC records should be configured in DNS before production
launch.

## Verify delivery

Restart the Django web process after changing environment variables, then run:

```bash
.venv/bin/python manage.py sendtestemail recipient@example.com
```

After that succeeds, request a password reset through `/forgot-password` and
confirm the delivered button opens `/reset-password?token=...` on the public
frontend URL.
