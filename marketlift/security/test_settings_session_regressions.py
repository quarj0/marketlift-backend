import json

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings

from accounts.auth_services import create_admin_login_challenge
from marketlift.security.middleware import MaintenanceModeMiddleware
from platform_settings.services import invalidate_all_sessions

TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "marketlift-settings-session-tests",
    }
}


@override_settings(
    CACHES=TEST_CACHES,
    SESSION_ENGINE="django.contrib.sessions.backends.cached_db",
    SESSION_COOKIE_NAME="marketlift_sessionid",
    MARKETLIFT_ADMIN_SESSION_COOKIE_NAME="marketlift_admin_sessionid",
    MARKETLIFT_ADMIN_SESSION_ORIGINS=["https://dash.marketlift.com.br"],
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_SAMESITE="Lax",
)
class SessionInvalidationRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_global_invalidation_removes_database_and_cached_session(self):
        from importlib import import_module
        from django.conf import settings

        SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
        store = SessionStore()
        store["marker"] = "active"
        store.save()
        session_key = store.session_key

        self.assertTrue(Session.objects.filter(session_key=session_key).exists())
        self.assertEqual(SessionStore(session_key=session_key).get("marker"), "active")

        self.assertEqual(invalidate_all_sessions(), 1)

        self.assertFalse(Session.objects.filter(session_key=session_key).exists())
        self.assertEqual(SessionStore(session_key=session_key).load(), {})

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MARKETLIFT_ADMIN_LOGIN_CODE_TTL_SECONDS=600,
    )
    def test_valid_admin_code_survives_stale_cached_session_after_old_invalidation(
        self,
    ):
        from importlib import import_module
        from django.conf import settings

        User = get_user_model()
        admin = User.objects.create_user(
            email="session-regression-admin@example.com",
            full_name="Session Regression Admin",
            password="Secure-Example-482!",
            is_staff=True,
            is_active=True,
            admin_role=User.AdminRole.ADMIN,
        )
        challenge, code = create_admin_login_challenge(user=admin, send=False)

        SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
        stale = SessionStore()
        stale["stale"] = True
        stale.save()
        stale_key = stale.session_key

        Session.objects.filter(session_key=stale_key).delete()
        self.assertTrue(SessionStore(session_key=stale_key).get("stale"))

        self.client.cookies[settings.MARKETLIFT_ADMIN_SESSION_COOKIE_NAME] = stale_key
        response = self.client.post(
            "/api/v1/auth/admin-login/verify/",
            data=json.dumps({"challengeId": str(challenge.id), "code": code}),
            content_type="application/json",
            HTTP_ORIGIN="https://dash.marketlift.com.br",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.consumed_at)

        second = self.client.post(
            "/api/v1/auth/admin-login/verify/",
            data=json.dumps({"challengeId": str(challenge.id), "code": code}),
            content_type="application/json",
            HTTP_ORIGIN="https://dash.marketlift.com.br",
        )
        self.assertEqual(second.status_code, 400)
        self.assertIn("Invalid or expired", second.json()["detail"])


@override_settings(CACHES=TEST_CACHES)
class MaintenanceModeSurfaceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.factory = RequestFactory()
        self.middleware = MaintenanceModeMiddleware(
            lambda request: JsonResponse({"ok": True})
        )
        cache.set("ml:platform:maintenance", True, 30)

    def test_staff_marketplace_request_is_blocked_during_maintenance(self):
        User = get_user_model()
        staff = User.objects.create_user(
            email="maintenance-staff@example.com",
            full_name="Maintenance Staff",
            is_staff=True,
            is_active=True,
            admin_role=User.AdminRole.ADMIN,
        )
        request = self.factory.post("/graphql/")
        request.user = staff
        request.marketlift_session_surface = "marketplace"

        response = self.middleware(request)

        self.assertEqual(response.status_code, 503)

    def test_staff_admin_request_can_manage_platform_during_maintenance(self):
        User = get_user_model()
        staff = User.objects.create_user(
            email="maintenance-admin@example.com",
            full_name="Maintenance Admin",
            is_staff=True,
            is_active=True,
            admin_role=User.AdminRole.ADMIN,
        )
        request = self.factory.post("/graphql/")
        request.user = staff
        request.marketlift_session_surface = "admin"

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_admin_login_remains_available_during_maintenance(self):
        request = self.factory.post("/api/v1/auth/admin-login/")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_public_maintenance_status_remains_available_during_maintenance(self):
        response = self.client.get("/api/v1/health/maintenance/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"maintenance": True})
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
