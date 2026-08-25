import uuid

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models

from marketlift.common.models import UUIDTimeStampedModel
from marketlift.markets.defaults import (
    default_market_country_code,
    default_market_currency,
    default_market_locale,
)


class UserManager(DjangoUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("admin_role", "super_admin")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Marketlift customer identity.

    Buying and selling use the same account. A user becomes a seller by gaining
    a sellers.SellerProfile; seller is intentionally not an account role.
    """

    class AdminRole(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super admin"
        ADMIN = "admin", "Administrator"
        MODERATOR = "moderator", "Moderator"
        SUPPORT = "support", "Support"
        FINANCE = "finance", "Finance"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    first_name = None
    last_name = None

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=160)
    avatar_url = models.URLField(blank=True)
    bio = models.TextField(blank=True)

    country_code = models.CharField(
        max_length=2, default=default_market_country_code, db_index=True
    )
    state = models.CharField(max_length=100, blank=True)
    state_code = models.CharField(max_length=8, blank=True)
    city = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=120, blank=True)

    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)

    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivation_reason = models.TextField(blank=True)
    admin_role = models.CharField(
        max_length=20, choices=AdminRole.choices, blank=True, default=""
    )

    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ("-date_joined",)

    def __str__(self) -> str:
        return self.full_name or self.email

    @property
    def name(self) -> str:
        return self.full_name

    def get_full_name(self) -> str:
        return self.full_name

    def get_short_name(self) -> str:
        return self.full_name.split()[0] if self.full_name else self.email


class AccountSettings(UUIDTimeStampedModel):
    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        ENGLISH_GHANA = "en-GH", "English (Ghana)"
        ENGLISH_NIGERIA = "en-NG", "English (Nigeria)"
        ENGLISH_KENYA = "en-KE", "English (Kenya)"
        ENGLISH_SOUTH_AFRICA = "en-ZA", "English (South Africa)"
        PORTUGUESE_BRAZIL = "pt-BR", "Português (Brasil)"
        FRENCH_COTE_DIVOIRE = "fr-CI", "Français (Côte d’Ivoire)"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    language = models.CharField(
        max_length=8,
        choices=Language.choices,
        default=default_market_locale,
    )
    currency = models.CharField(
        max_length=3, default=default_market_currency, editable=False
    )

    email_messages = models.BooleanField(default=True)
    email_listing_updates = models.BooleanField(default=True)
    email_recommendations = models.BooleanField(default=True)
    push_messages = models.BooleanField(default=True)
    push_listing_updates = models.BooleanField(default=True)
    marketing_emails = models.BooleanField(default=False)
    show_phone_to_sellers = models.BooleanField(default=False)
    show_online_status = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "account settings"

    def __str__(self) -> str:
        return f"Settings for {self.user_id}"


class EmailVerificationChallenge(UUIDTimeStampedModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="email_verification_challenges"
    )
    code_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "consumed_at", "-created_at"),
                name="accounts_verify_user_idx",
            )
        ]


class PasswordResetRequest(UUIDTimeStampedModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="password_reset_requests"
    )
    requested_ip = models.GenericIPAddressField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)


class AdminLoginChallenge(UUIDTimeStampedModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="admin_login_challenges"
    )
    code_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "consumed_at", "-created_at"),
                name="accounts_admin_mfa_idx",
            )
        ]


class AdminInvitation(UUIDTimeStampedModel):
    email = models.EmailField(db_index=True)
    role = models.CharField(max_length=20, choices=User.AdminRole.choices)
    token_digest = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_invitations_sent",
    )
    expires_at = models.DateTimeField(db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("email", "accepted_at", "revoked_at"),
                name="accounts_admin_invite_idx",
            )
        ]

    @property
    def active(self):
        from django.utils import timezone

        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )
