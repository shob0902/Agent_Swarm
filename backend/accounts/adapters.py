"""allauth adapter hooks -- the layer where our custom User model's shape
(email-only, no username, plus name/avatar_url/signup_provider) meets
allauth's generic signup/login machinery.
"""
from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model


class AccountAdapter(DefaultAccountAdapter):
    """Email/password signup path (dj_rest_auth's RegisterSerializer)."""

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        user.signup_provider = "email"
        if not user.name:
            user.name = user.email.split("@")[0]
        if commit:
            user.save()
        return user


class AutoConnectSocialAccountAdapter(DefaultSocialAccountAdapter):
    """OAuth (Google/GitHub) signup/login path.

    - `pre_social_login`: if the provider's verified email already belongs
      to an existing account -- created via email/password or a *different*
      OAuth provider -- connect this login to that account instead of
      erroring or creating a duplicate. This is the concrete mechanism for
      "prevent duplicate accounts when the same email is used across
      providers."
    - `populate_user`: fills in name/avatar_url/signup_provider from the
      provider's profile data for brand-new accounts (the base
      implementation only knows about first_name/last_name, which our
      model doesn't have).
    """

    def pre_social_login(self, request, sociallogin):
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
        user = super().populate_user(request, sociallogin, data)
        extra = sociallogin.account.extra_data
        user.name = data.get("name") or user.name or (user.email.split("@")[0] if user.email else "")
        # google's provider profile picture key is 'picture', github's is 'avatar_url'
        user.avatar_url = extra.get("picture") or extra.get("avatar_url") or ""
        user.signup_provider = sociallogin.account.provider
        return user
