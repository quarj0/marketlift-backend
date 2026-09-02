import json

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIRequestFactory

from marketlift.api.auth.serializers import RegisterSerializer
from marketlift.security.checks import marketlift_deploy_checks
from marketlift.security.middleware import (
    ClientScopedSessionMiddleware,
    MaintenanceModeMiddleware,
    SecurityRateLimitMiddleware,
)
from marketlift.security.rate_limit import client_ip
from accounts.auth_services import request_password_reset


class SecurityHardeningTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(MARKETLIFT_TRUST_PROXY_HEADERS=False)
    def test_forwarded_ip_is_not_trusted_by_default(self):
        request = self.factory.get(
            "/", HTTP_X_FORWARDED_FOR="203.0.113.7", REMOTE_ADDR="10.0.0.9"
        )
        self.assertEqual(client_ip(request), "10.0.0.9")

    @override_settings(MARKETLIFT_TRUST_PROXY_HEADERS=True)
    def test_forwarded_ip_can_be_enabled_behind_trusted_proxy(self):
        request = self.factory.get(
            "/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.9", REMOTE_ADDR="10.0.0.9"
        )
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_registration_uses_django_password_validators(self):
        serializer = RegisterSerializer(
            data={
                "fullName": "Test User",
                "email": "test@example.com",
                "phone": "+5511999999999",
                "password": "12345678",
                "terms": True,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)

    def test_password_reset_response_does_not_reveal_account_existence(self):
        User = get_user_model()
        User.objects.create_user(
            email="alice@example.com", password="Secure-Example-482!", full_name="Alice"
        )
        known = request_password_reset(identifier="alice@example.com")
        unknown = request_password_reset(identifier="adam@example.com")
        self.assertEqual(known["maskedDestination"], "a***@example.com")
        self.assertEqual(unknown["maskedDestination"], "a***@example.com")
        message = mail.outbox[-1]
        self.assertIn("/reset-password?token=", message.body)
        self.assertNotIn("/reset--password", message.body)
        self.assertEqual(message.alternatives[0].mimetype, "text/html")
        self.assertIn("Reset password", message.alternatives[0].content)

    @override_settings(
        IS_PRODUCTION=True,
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="",
        EMAIL_HOST_USER="",
        EMAIL_HOST_PASSWORD="",
        EMAIL_USE_TLS=True,
        EMAIL_USE_SSL=False,
    )
    def test_production_check_rejects_incomplete_smtp_configuration(self):
        ids = {issue.id for issue in marketlift_deploy_checks(None)}
        self.assertIn("marketlift.E017", ids)

    @override_settings(
        IS_PRODUCTION=True,
        DEBUG=True,
        SECRET_KEY="django-insecure-short",
        ALLOWED_HOSTS=["localhost"],
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
        SECURE_SSL_REDIRECT=False,
        MARKETLIFT_PAYMENTS_ENABLED=True,
        MARKETLIFT_PAYMENT_PROVIDER="mock",
        PAYMENT_MOCK_AUTO_APPROVE=True,
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        MARKETLIFT_STORAGE_BACKENDS={
            "default": "uploads.storage.local.LocalStorageBackend"
        },
        DB_SSLMODE="",
        CORS_ALLOWED_ORIGINS=["http://localhost:3000"],
        CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
        SECURE_HSTS_SECONDS=0,
        MARKETLIFT_DISABLE_GRAPHQL_INTROSPECTION=False,
    )
    def test_production_check_reports_release_blockers(self):
        ids = {issue.id for issue in marketlift_deploy_checks(None)}
        self.assertTrue(
            {
                "marketlift.E001",
                "marketlift.E002",
                "marketlift.E003",
                "marketlift.E004",
                "marketlift.E005",
                "marketlift.E006",
            }.issubset(ids)
        )

    def test_admin_roles_enforce_least_privilege(self):
        from types import SimpleNamespace
        from graphql import GraphQLError
        from marketlift.graphql.auth import require_staff

        User = get_user_model()
        staff = User.objects.create_user(
            email="support-role@example.com",
            password="Secure-Example-482!",
            full_name="Support",
            is_staff=True,
            admin_role=User.AdminRole.SUPPORT,
        )
        info = SimpleNamespace(context=SimpleNamespace(user=staff))
        self.assertIs(require_staff(info, roles={"support"}), staff)
        with self.assertRaises(GraphQLError):
            require_staff(info, roles={"admin"})

    def test_admin_login_challenge_requires_email_code(self):
        from accounts.auth_services import (
            create_admin_login_challenge,
            verify_admin_login_challenge,
        )

        User = get_user_model()
        admin = User.objects.create_user(
            email="admin-mfa@example.com",
            password="Secure-Example-482!",
            full_name="Admin MFA",
            is_staff=True,
            admin_role=User.AdminRole.ADMIN,
        )
        challenge, code = create_admin_login_challenge(user=admin, send=False)
        with self.assertRaises(Exception):
            verify_admin_login_challenge(challenge_id=challenge.id, code="000000")
        self.assertEqual(
            verify_admin_login_challenge(challenge_id=challenge.id, code=code), admin
        )

    def test_admin_invitation_creates_role_scoped_staff_account(self):
        from accounts.auth_services import (
            create_admin_invitation,
            accept_admin_invitation,
        )

        User = get_user_model()
        owner = User.objects.create_superuser(
            email="owner@example.com", password="Secure-Example-482!", full_name="Owner"
        )
        invitation, token = create_admin_invitation(
            email="new-support@example.com",
            role=User.AdminRole.SUPPORT,
            invited_by=owner,
            send=False,
        )
        user = accept_admin_invitation(
            token=token, full_name="New Support", password="Invite-Secure-482!"
        )
        self.assertTrue(user.is_staff)
        self.assertEqual(user.admin_role, User.AdminRole.SUPPORT)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)

    def test_maintenance_mode_keeps_admin_login_and_webhooks_reachable(self):
        cache.set("ml:platform:maintenance", True, 30)
        self.addCleanup(cache.delete, "ml:platform:maintenance")
        middleware = MaintenanceModeMiddleware(
            lambda request: __import__(
                "django.http", fromlist=["JsonResponse"]
            ).JsonResponse({"ok": True})
        )
        for path in ("/api/v1/auth/admin-login/", "/api/v1/webhooks/mercado-pago/"):
            response = middleware(self.factory.post(path))
            self.assertEqual(response.status_code, 200)

    @override_settings(
        SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
        SESSION_COOKIE_NAME="marketlift_sessionid",
        MARKETLIFT_ADMIN_SESSION_COOKIE_NAME="marketlift_admin_sessionid",
        MARKETLIFT_ADMIN_SESSION_ORIGINS=["http://localhost:3001"],
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    def test_marketplace_and_admin_sessions_are_isolated_by_origin(self):
        def endpoint(request):
            if request.path == "/set/":
                request.session["surface"] = request.marketlift_session_surface
            elif request.path == "/logout/":
                request.session.flush()
            return JsonResponse({"surface": request.session.get("surface")})

        middleware = ClientScopedSessionMiddleware(endpoint)

        market_response = middleware(
            self.factory.get("/set/", HTTP_ORIGIN="http://localhost:3000")
        )
        market_cookie = market_response.cookies["marketlift_sessionid"].value
        self.assertNotIn("marketlift_admin_sessionid", market_response.cookies)

        admin_request = self.factory.get("/set/", HTTP_ORIGIN="http://localhost:3001")
        admin_request.COOKIES["marketlift_sessionid"] = market_cookie
        admin_response = middleware(admin_request)
        admin_cookie = admin_response.cookies["marketlift_admin_sessionid"].value
        self.assertNotEqual(admin_cookie, market_cookie)

        market_request = self.factory.get("/", HTTP_ORIGIN="http://localhost:3000")
        market_request.COOKIES.update(
            marketlift_sessionid=market_cookie,
            marketlift_admin_sessionid=admin_cookie,
        )
        self.assertEqual(
            json.loads(middleware(market_request).content)["surface"], "marketplace"
        )

        admin_request = self.factory.get("/", HTTP_ORIGIN="http://localhost:3001")
        admin_request.COOKIES.update(
            marketlift_sessionid=market_cookie,
            marketlift_admin_sessionid=admin_cookie,
        )
        self.assertEqual(
            json.loads(middleware(admin_request).content)["surface"], "admin"
        )

        logout_request = self.factory.post(
            "/logout/", HTTP_ORIGIN="http://localhost:3000"
        )
        logout_request.COOKIES.update(
            marketlift_sessionid=market_cookie,
            marketlift_admin_sessionid=admin_cookie,
        )
        logout_response = middleware(logout_request)
        self.assertEqual(
            str(logout_response.cookies["marketlift_sessionid"]["max-age"]), "0"
        )
        self.assertNotIn("marketlift_admin_sessionid", logout_response.cookies)

        admin_after_logout = self.factory.get("/", HTTP_ORIGIN="http://localhost:3001")
        admin_after_logout.COOKIES["marketlift_admin_sessionid"] = admin_cookie
        self.assertEqual(
            json.loads(middleware(admin_after_logout).content)["surface"], "admin"
        )

    @override_settings(
        SESSION_COOKIE_NAME="marketlift_sessionid",
        MARKETLIFT_ADMIN_SESSION_COOKIE_NAME="marketlift_admin_sessionid",
        MARKETLIFT_ADMIN_SESSION_ORIGINS=["http://localhost:3001"],
    )
    def test_browser_origin_cannot_be_overridden_by_surface_header(self):
        request = self.factory.get(
            "/",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_X_MARKETLIFT_SURFACE="admin",
        )
        self.assertEqual(
            ClientScopedSessionMiddleware.cookie_name_for(request),
            "marketlift_sessionid",
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MARKETLIFT_ADMIN_LOGIN_CODE_TTL_SECONDS=600,
    )
    def test_admin_login_is_passwordless_email_verification(self):
        User = get_user_model()
        admin = User.objects.create_user(
            email="passwordless-admin@example.com",
            password="Secure-Example-482!",
            full_name="Passwordless Admin",
            is_staff=True,
            is_active=True,
            admin_role=User.AdminRole.ADMIN,
        )

        response = self.client.post(
            "/api/v1/auth/admin-login/",
            data=json.dumps({"email": admin.email}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertTrue(payload["verificationRequired"])
        self.assertIn("challengeId", payload)
        self.assertEqual(len(mail.outbox), 1)

        import re

        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        verified = self.client.post(
            "/api/v1/auth/admin-login/verify/",
            data=json.dumps(
                {"challengeId": payload["challengeId"], "code": code}
            ),
            content_type="application/json",
        )
        self.assertEqual(verified.status_code, 200)
        self.assertTrue(verified.json()["authenticated"])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MARKETLIFT_ADMIN_LOGIN_CODE_TTL_SECONDS=600,
    )
    def test_admin_login_does_not_reveal_unknown_email(self):
        response = self.client.post(
            "/api/v1/auth/admin-login/",
            data=json.dumps({"email": "unknown-admin@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertTrue(payload["verificationRequired"])
        self.assertIn("challengeId", payload)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(MARKETLIFT_GRAPHQL_MUTATION_RATE_LIMIT_PER_MINUTE=1)
    def test_graphql_queries_are_not_request_count_rate_limited(self):
        cache.clear()
        middleware = SecurityRateLimitMiddleware(
            lambda request: JsonResponse({"ok": True})
        )
        body = json.dumps({"query": "query Dashboard { adminDashboard { counts { totalUsers } } }"})
        for _ in range(3):
            response = middleware(
                self.factory.post(
                    "/graphql/",
                    data=body,
                    content_type="application/json",
                    REMOTE_ADDR="198.51.100.20",
                )
            )
            self.assertEqual(response.status_code, 200)

    @override_settings(MARKETLIFT_GRAPHQL_MUTATION_RATE_LIMIT_PER_MINUTE=1)
    def test_graphql_mutations_are_rate_limited_per_action(self):
        cache.clear()
        middleware = SecurityRateLimitMiddleware(
            lambda request: JsonResponse({"ok": True})
        )
        body = json.dumps(
            {"query": "mutation MarkRead { markAllNotificationsRead }"}
        )
        first = middleware(
            self.factory.post(
                "/graphql/",
                data=body,
                content_type="application/json",
                REMOTE_ADDR="198.51.100.21",
            )
        )
        second = middleware(
            self.factory.post(
                "/graphql/",
                data=body,
                content_type="application/json",
                REMOTE_ADDR="198.51.100.21",
            )
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(
            json.loads(second.content)["errors"][0]["extensions"]["code"],
            "GRAPHQL_MUTATION_RATE_LIMITED",
        )

