from django.urls import path
from .views import AdminLoginView, CsrfView, LoginView, LogoutView, SessionView

urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="auth-csrf"),
    path("session/", SessionView.as_view(), name="auth-session"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("admin-login/", AdminLoginView.as_view(), name="auth-admin-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
]
