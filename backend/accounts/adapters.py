# allauth adapter hooks that map our email-only User model onto allauth's signup/login flow.
from __future__ import annotations
import logging
from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from django.http import HttpResponseBadRequest
logger = logging.getLogger(__name__)
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
def verified_provider_emails(sociallogin) -> list[str]:
    # Emails the provider itself vouches for (Google's email_verified, GitHub's verified flag), primary first.
    addresses = sorted(sociallogin.email_addresses or [], key=lambda a: not a.primary)
    return [a.email for a in addresses if a.verified and a.email]
class AutoConnectSocialAccountAdapter(DefaultSocialAccountAdapter):
    # Handles the Google/GitHub OAuth path and keeps one account per email -- but only on proof of ownership.
    def pre_social_login(self, request, sociallogin):
        # Links this OAuth login to an existing account with the same *provider-verified* email instead of duplicating it.
        if sociallogin.is_existing:
            return
        verified = verified_provider_emails(sociallogin)
        if not verified:
            # Signing up on an unverified address would let anyone claim someone else's email.
            provider = sociallogin.account.provider.title().replace("Github", "GitHub")
            raise ImmediateHttpResponse(HttpResponseBadRequest(
                f"Your {provider} account has no verified email address. Verify one with {provider} and try again."
            ))
        if (sociallogin.user.email or "").lower() not in {e.lower() for e in verified}:
            sociallogin.user.email = verified[0]
        User = get_user_model()
        for email in verified:
            existing = User.objects.filter(email__iexact=email).first()
            if existing is None:
                continue
            self._secure_unverified_password(existing, email)
            sociallogin.connect(request, existing)
            return
    def _secure_unverified_password(self, user, email: str) -> None:
        # Email signups aren't verified, so whoever set that password may not own the address. The provider
        # just proved ownership: drop the unproven password (pre-account-takeover defence) and record the
        # email as verified. The owner can keep signing in with Google/GitHub.
        already_verified = EmailAddress.objects.filter(user=user, email__iexact=email, verified=True).exists()
        if not already_verified and user.has_usable_password():
            logger.info("Linking OAuth login to user %s: retiring unverified password", user.pk)
            user.set_unusable_password()
            user.save(update_fields=["password"])
        EmailAddress.objects.update_or_create(
            user=user, email__iexact=email,
            defaults={"email": email, "verified": True, "primary": True},
        )
    def populate_user(self, request, sociallogin, data):
        # Copies name, avatar and provider off the OAuth profile onto a brand-new user.
        user = super().populate_user(request, sociallogin, data)
        extra = sociallogin.account.extra_data
        user.name = data.get("name") or extra.get("login") or user.name or (user.email.split("@")[0] if user.email else "")
        user.avatar_url = extra.get("picture") or extra.get("avatar_url") or ""
        user.signup_provider = sociallogin.account.provider
        return user
