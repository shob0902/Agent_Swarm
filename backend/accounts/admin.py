# Django admin registration and layout for the custom User model.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import User
@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    # Redefines the fieldsets from scratch because our model has no username or name fields.
    ordering = ("-date_joined",)
    list_display = ("id", "email", "name", "signup_provider", "role", "is_staff", "date_joined")
    list_filter = ("signup_provider", "role", "is_staff", "is_active")
    search_fields = ("email", "name")
    readonly_fields = ("date_joined",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("name", "avatar_url", "signup_provider", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )
