# Marketlift backend completion & production-hardening audit

Date: 2026-08-19

## Audit basis

The uploaded backend was treated as the source of truth and compared with the current marketplace and administration frontends. The backend already contained the major domains: accounts, sellers, listings, categories, subscriptions, promotions, payments, verification, uploads, messaging, moderation, reports, notifications, audit, reviews, saved searches, support, platform settings, analytics, listing expiry/search, and provider-neutral storage/database configuration.

Baseline validation before this pass: **42 tests passed**.

Validation after this pass: **55 tests passed**, `manage.py check` passed, and `makemigrations --check --dry-run` reported no drift.

## Confirmed frontend/backend gaps completed

- Seller follow/unfollow persistence, follower counts and `myFollowedSellers`.
- Public seller discovery and verified-seller discovery.
- Richer seller profile data: avatar, active listing count, response rate, followers, member since, viewer follow state.
- Aggregated seller dashboard matching the marketplace selling dashboard (active/draft/review counts, views, conversations, plan use/limit, recent listings/inquiries).
- Seller-side listing deletion using a soft-delete timestamp so public/search/messaging visibility stops without erasing moderation/audit history.
- Recent, nearby and similar listing convenience queries.
- Listing filtering by seller ID for public seller profile pages.
- Admin listing queries that can read draft/review/rejected/removed/seller-deleted records instead of being limited to public listings.
- Admin user and seller detail queries.
- Account overview now includes actual recent and saved listing rows, not counts only; unread message count is aggregated rather than looping over conversations.
- Category create/update plus a dedicated admin category query. Public category queries never expose disabled categories.
- Support ticket detail plus explicit assignment, priority and lifecycle control.
- Administrator roles (super admin, admin, moderator, support, finance) with domain-level GraphQL role boundaries.
- Administrator invitation, revocation and acceptance flow.
- Production administrator email-OTP MFA after password verification.

## Production hardening completed

- Environment-aware production mode (`MARKETLIFT_ENV`).
- Custom deployment checks integrated with `manage.py check --deploy`.
- Release-blocking checks for insecure secret key, DEBUG, hosts, secure cookies, HTTPS redirect, mock payments, missing Mercado Pago secrets when selected, insecure frontend URLs/origins, console email and disabled admin MFA.
- Warnings for local upload storage, missing PostgreSQL SSL mode confirmation, localhost origins, HSTS and production GraphQL introspection.
- GraphQL depth/token/alias limits are environment-configurable.
- GraphQL introspection and GraphiQL can be disabled in production; GraphQL queries via GET are disabled in production.
- GraphQL request rate limit is environment-configurable.
- Proxy forwarding headers are ignored unless `MARKETLIFT_TRUST_PROXY_HEADERS=true` is explicitly enabled.
- Maintenance mode keeps health/readiness, admin login/MFA/invite acceptance, logout and payment webhooks reachable.
- Registration now runs Django password validators rather than relying only on an eight-character minimum.
- Password-reset responses mask the supplied identifier consistently and do not reveal account existence.
- Expired database sessions are cleaned daily through Celery Beat.
- Listing favorite/inquiry counts are annotated instead of counted once per result.
- Messaging conversation unread/block state is annotated to avoid per-conversation count/exists queries.
- Database persistent-connection health checks can be configured with `DB_CONN_HEALTH_CHECKS`.
- A provider-neutral production checklist is included in `docs/PRODUCTION.md`.

## Intentional deployment/integration decisions still external to the backend

These are deliberately not hardcoded because they depend on the client's eventual providers or operational choices:

- Production PostgreSQL provider/host (self-hosted, managed PostgreSQL, Supabase, Neon, etc.).
- Production Redis-compatible cache/broker host.
- Production object/media storage adapter and credentials.
- Real SMTP/transactional-email provider and credentials.
- Mercado Pago or another future service-payment provider credentials.
- DNS, TLS termination, reverse proxy/load balancer, runtime/container platform.
- Database and media backup schedules/retention at the selected infrastructure provider.
- External error-monitoring/observability vendor.
- External SMS provider if phone-number verification is later required.
- External automated identity-verification provider if Marketlift chooses one; manual/final verification workflow already exists.

## Intentional product boundary

Marketlift service billing covers seller subscriptions and listing promotions. Buyer-to-seller product payments/escrow remain outside the V1 backend by product decision.

## Optional later enhancement

Messaging is complete through GraphQL request/response APIs. WebSocket push can be added later if true realtime delivery is required; it is not required for correctness and is not coupled to the current data model.
