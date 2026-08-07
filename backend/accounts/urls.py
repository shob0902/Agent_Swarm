from django.urls import include, path

from .views import GitHubLogin, GoogleLogin, RegisterView

urlpatterns = [
    # login/, logout/, user/, password/reset/, password/change/,
    # token/refresh/, token/verify/ (dj_rest_auth, JWT-cookie based -- see
    # orchestrator/settings.py REST_AUTH)
    path("", include("dj_rest_auth.urls")),
    # registration/ -- email + password signup. Our RegisterView (not the
    # stock one) exactly matches this path first and wins; the include()
    # below only ends up handling registration/verify-email/ and friends.
    path("registration/", RegisterView.as_view(), name="rest_register"),
    path("registration/", include("dj_rest_auth.registration.urls")),
    path("google/", GoogleLogin.as_view(), name="google_login"),
    path("github/", GitHubLogin.as_view(), name="github_login"),
]
