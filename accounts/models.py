import uuid

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models

from marketlift.common.models import UUIDTimeStampedModel


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    first_name = None
    last_name = None

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=160)
    avatar_url = models.URLField(blank=True)
    bio = models.TextField(blank=True)

    state = models.CharField(max_length=100, blank=True)
    state_code = models.CharField(max_length=8, blank=True)
    city = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=120, blank=True)

    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
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
        PORTUGUESE_BRAZIL = "pt-BR", "Português (Brasil)"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    language = models.CharField(
        max_length=8,
        choices=Language.choices,
        default=Language.PORTUGUESE_BRAZIL,
    )
    currency = models.CharField(max_length=3, default="BRL", editable=False)

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
