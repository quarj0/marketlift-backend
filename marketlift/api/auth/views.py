from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.middleware.csrf import get_token
from accounts.auth_services import (
    accept_admin_invitation,
    create_admin_login_challenge,
    create_email_verification,
    request_password_reset,
    reset_password,
    verify_admin_login_challenge,
    verify_email_code,
)
from accounts.models import User
from audit.services import record_audit_event
from marketlift.security.rate_limit import enforce_rate_limit
from platform_settings.models import PlatformConfiguration

from .serializers import (
    AdminInvitationAcceptSerializer,
    AdminMfaVerifySerializer,
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetSerializer,
    RegisterSerializer,
    VerifySerializer,
    serialize_session_user,
)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        csrf_token = get_token(request)

        return Response(
            {
                "csrfToken": csrf_token,
            }
        )


class SessionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "authenticated": bool(request.user.is_authenticated),
                "user": (
                    serialize_session_user(request.user)
                    if request.user.is_authenticated
                    else None
                ),
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    require_staff = False
    audit_action = "auth.login"

    def post(self, request):
        enforce_rate_limit(request, "auth-login", limit=10, window=300)
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = (
            serializer.validated_data.get("emailOrPhone")
            or serializer.validated_data.get("email")
            or ""
        ).strip()
        email = identifier
        if "@" not in identifier:
            found = User.objects.filter(phone=identifier).only("email").first()
            email = found.email if found else ""

        user = authenticate(
            request,
            email=email,
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=400)
        if self.require_staff and not user.is_staff:
            return Response({"detail": "Administrator access required."}, status=403)

        login(request, user)
        record_audit_event(
            actor=user,
            action=self.audit_action,
            target=user,
            target_type="user",
            target_label=user.full_name or user.email,
            request=request,
        )
        return Response({"authenticated": True, "user": serialize_session_user(user)})


class AdminLoginView(LoginView):
    require_staff = True
    audit_action = "auth.admin_login"

    def post(self, request):
        if not settings.MARKETLIFT_ADMIN_MFA_REQUIRED:
            return super().post(request)

        enforce_rate_limit(request, "auth-admin-login", limit=8, window=300)
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = (
            serializer.validated_data.get("emailOrPhone")
            or serializer.validated_data.get("email")
            or ""
        ).strip()
        email = identifier
        if "@" not in identifier:
            found = User.objects.filter(phone=identifier).only("email").first()
            email = found.email if found else ""
        user = authenticate(
            request, email=email, password=serializer.validated_data["password"]
        )
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=400)
        if not user.is_staff:
            return Response({"detail": "Administrator access required."}, status=403)
        challenge, _ = create_admin_login_challenge(user=user, request=request)
        record_audit_event(
            actor=user,
            action="auth.admin_mfa_challenge",
            target=user,
            target_type="user",
            target_label=user.full_name or user.email,
            request=request,
        )
        return Response(
            {
                "authenticated": False,
                "mfaRequired": True,
                "challengeId": str(challenge.id),
                "expiresIn": settings.MARKETLIFT_ADMIN_MFA_TTL_SECONDS,
            },
            status=202,
        )


@method_decorator(csrf_protect, name="dispatch")
class AdminMfaVerifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        enforce_rate_limit(request, "auth-admin-mfa", limit=12, window=900)
        serializer = AdminMfaVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = verify_admin_login_challenge(
                challenge_id=serializer.validated_data["challengeId"],
                code=serializer.validated_data["code"],
            )
        except Exception as exc:
            return Response(
                {"detail": getattr(exc, "messages", [str(exc)])[0]}, status=400
            )
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        record_audit_event(
            actor=user,
            action="auth.admin_login",
            target=user,
            target_type="user",
            target_label=user.full_name or user.email,
            request=request,
        )
        return Response({"authenticated": True, "user": serialize_session_user(user)})


@method_decorator(csrf_protect, name="dispatch")
class AdminInvitationAcceptView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        enforce_rate_limit(request, "auth-admin-invite-accept", limit=8, window=3600)
        serializer = AdminInvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = accept_admin_invitation(
                token=serializer.validated_data["token"],
                full_name=serializer.validated_data["fullName"],
                password=serializer.validated_data["password"],
            )
        except Exception as exc:
            return Response(
                {"detail": getattr(exc, "messages", [str(exc)])[0]}, status=400
            )
        return Response(
            {"success": True, "user": serialize_session_user(user)}, status=201
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        record_audit_event(
            actor=user,
            action="auth.logout",
            target=user,
            target_type="user",
            target_label=user.full_name or user.email,
            request=request,
        )
        logout(request)
        return Response(status=204)


@method_decorator(csrf_protect, name="dispatch")
class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @transaction.atomic
    def post(self, request):
        enforce_rate_limit(request, "auth-register", limit=5, window=3600)
        if not PlatformConfiguration.load().allow_new_registrations:
            return Response(
                {"detail": "New registrations are temporarily disabled."}, status=403
            )

        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if User.objects.filter(email__iexact=data["email"]).exists():
            return Response(
                {"email": ["An account with this email already exists."]}, status=400
            )
        if User.objects.filter(phone=data["phone"]).exists():
            return Response(
                {"phone": ["An account with this phone already exists."]}, status=400
            )

        user = User.objects.create_user(
            email=data["email"],
            phone=data["phone"],
            full_name=data["fullName"],
            password=data["password"],
            is_active=False,
            terms_accepted_at=timezone.now(),
        )
        create_email_verification(user=user)
        return Response(
            {
                "id": str(user.id),
                "name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "requiresVerification": True,
            },
            status=201,
        )


@method_decorator(csrf_protect, name="dispatch")
class VerifyEmailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        enforce_rate_limit(request, "auth-verify", limit=15, window=900)
        serializer = VerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.objects.get(pk=serializer.validated_data["userId"])
            verify_email_code(user=user, code=serializer.validated_data["code"])
        except User.DoesNotExist:
            return Response({"detail": "Invalid verification request."}, status=400)
        except Exception as exc:
            return Response(
                {"detail": getattr(exc, "messages", [str(exc)])[0]}, status=400
            )

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response({"success": True, "user": serialize_session_user(user)})


@method_decorator(csrf_protect, name="dispatch")
class ResendVerificationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        enforce_rate_limit(request, "auth-resend", limit=5, window=3600)
        user_id = request.data.get("userId")
        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            # Avoid making this endpoint a user-enumeration primitive.
            return Response({"success": True})
        if not user.email_verified_at:
            create_email_verification(user=user)
        return Response({"success": True})


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        enforce_rate_limit(request, "auth-password-request", limit=5, window=3600)
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            request_password_reset(
                identifier=serializer.validated_data["identifier"],
                request=request,
            )
        )


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        enforce_rate_limit(request, "auth-password-reset", limit=10, window=3600)
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reset_password(
                combined_token=serializer.validated_data["token"],
                new_password=serializer.validated_data["password"],
            )
        except Exception as exc:
            return Response(
                {"detail": getattr(exc, "messages", [str(exc)])[0]}, status=400
            )
        return Response({"success": True})
