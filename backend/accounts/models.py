"""Custom user model: email is the login identity.

`AbstractUser` keeps `username` as the login field, which doesn't cleanly
support "one account per email regardless of signup provider" (Google,
GitHub, and email/password all need to resolve to the same row when the
email matches -- see adapters.py). Building on `AbstractBaseUser` +
`PermissionsMixin` instead, with `email` as `USERNAME_FIELD`, is the
standard Django pattern for email-only auth.
"""
from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
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
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """One account per email, regardless of how they first signed up.

    `signup_provider` records how the account was *originally* created for
    display purposes only -- it doesn't limit which providers can
    subsequently log in as this user (see adapters.AutoConnectSocialAccountAdapter).
    """

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
        return self.email

    @property
    def created_at(self):
        """Alias so API responses can use the same field name the rest of
        the project's models use for creation timestamps (see agents.Task)."""
        return self.date_joined
