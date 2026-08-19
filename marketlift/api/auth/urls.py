from django.urls import path
from .views import (
    AdminInvitationAcceptView,
    AdminLoginView,
    AdminMfaVerifyView,
    CsrfView,
    LoginView,
    LogoutView,
    PasswordResetRequestView,
    PasswordResetView,
    RegisterView,
    ResendVerificationView,
    SessionView,
    VerifyEmailView,
)

urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="auth-csrf"),
    path("session/", SessionView.as_view(), name="auth-session"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("admin-login/", AdminLoginView.as_view(), name="auth-admin-login"),
    path(
        "admin-login/verify/",
        AdminMfaVerifyView.as_view(),
        name="auth-admin-login-verify",
    ),
    path(
        "admin-invite/accept/",
        AdminInvitationAcceptView.as_view(),
        name="auth-admin-invite-accept",
    ),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path(
        "resend-verification/",
        ResendVerificationView.as_view(),
        name="auth-resend-verification",
    ),
    path(
        "password-reset/request/",
        PasswordResetRequestView.as_view(),
        name="auth-password-reset-request",
    ),
    path(
        "password-reset/confirm/",
        PasswordResetView.as_view(),
        name="auth-password-reset-confirm",
    ),
]
