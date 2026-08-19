from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit_event
from .serializers import LoginSerializer, serialize_session_user


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"csrf": "ready"})


class SessionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"authenticated": False, "user": None})
        return Response(
            {"authenticated": True, "user": serialize_session_user(request.user)}
        )


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    require_staff = False
    audit_action = "auth.login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            email=serializer.validated_data["email"],
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
