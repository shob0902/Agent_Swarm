# allauth adapter hooks that map our email-only User model onto allauth's signup/login flow.
from __future__ import annotations
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
class AccountAdapter(DefaultAccountAdapter):
    # Handles the plain email/password signup path.
    def save_user(self, request, user, form, commit=True):
        # Stamps the provider as "email" and falls back to the email prefix for a missing name.
        user = super().save_user(request, user, form, commit=False)
        user.signup_provider = "email"
        if not user.name:
            user.name = user.email.split("@")[0]
        if commit:
            user.save()
        return user
class AutoConnectSocialAccountAdapter(DefaultSocialAccountAdapter):
    # Handles the Google/GitHub OAuth path and keeps one account per email.
    def pre_social_login(self, request, sociallogin):
        # Links this OAuth login to an existing account with the same email instead of duplicating it.
        if sociallogin.is_existing:
            return
        email = sociallogin.account.extra_data.get("email") or sociallogin.user.email
        if not email:
            return
        User = get_user_model()
        try:
            existing = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return
        sociallogin.connect(request, existing)
    def populate_user(self, request, sociallogin, data):
        # Copies name, avatar and provider off the OAuth profile onto a brand-new user.
        user = super().populate_user(request, sociallogin, data)
        extra = sociallogin.account.extra_data
        user.name = data.get("name") or user.name or (user.email.split("@")[0] if user.email else "")
        user.avatar_url = extra.get("picture") or extra.get("avatar_url") or ""
        user.signup_provider = sociallogin.account.provider
        return user
