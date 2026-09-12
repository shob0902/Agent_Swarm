# Custom user model that uses email as the login identity instead of a username.
from __future__ import annotations
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
class UserManager(BaseUserManager):
    use_in_migrations = True
    def _create_user(self, email: str, password: str | None, **extra_fields):
        # Shared builder that normalises the email, hashes the password and saves the row.
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_user(self, email: str, password: str | None = None, **extra_fields):
        # Creates a regular non-staff, non-superuser account.
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)
    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        # Creates an admin account and refuses if the staff/superuser flags were forced off.
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)
class User(AbstractBaseUser, PermissionsMixin):
    # One account per email; signup_provider only records how it was first created.
    PROVIDER_CHOICES = [
        ("email", "email"),
        ("google", "google"),
        ("github", "github"),
    ]
    ROLE_CHOICES = [
        ("user", "user"),
        ("admin", "admin"),
    ]
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150, blank=True)
    avatar_url = models.URLField(blank=True, default="")
    signup_provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="email")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="user")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []
    class Meta:
        ordering = ["-date_joined"]
    def __str__(self):
        # Shows the email in the admin and in debug output.
        return self.email
    @property
    def created_at(self):
        # Alias for date_joined so API payloads match the naming used by other models.
        return self.date_joined
