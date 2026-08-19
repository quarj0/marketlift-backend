from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIRequestFactory

from marketlift.api.auth.serializers import RegisterSerializer
from marketlift.security.checks import marketlift_deploy_checks
from marketlift.security.middleware import MaintenanceModeMiddleware
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

    @override_settings(
        IS_PRODUCTION=True,
        DEBUG=True,
        SECRET_KEY="django-insecure-short",
        ALLOWED_HOSTS=["localhost"],
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
        SECURE_SSL_REDIRECT=False,
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

    def test_admin_mfa_challenge_requires_second_factor(self):
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
