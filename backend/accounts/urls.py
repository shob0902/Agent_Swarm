# URL routes for auth: login, logout, signup, the OAuth provider config and the two OAuth code exchanges.
from django.urls import include, path
from .views import GitHubLogin, GoogleLogin, OAuthProvidersView, RegisterView
urlpatterns = [
    path("", include("dj_rest_auth.urls")),
    path("registration/", RegisterView.as_view(), name="rest_register"),
    path("registration/", include("dj_rest_auth.registration.urls")),
    path("providers/", OAuthProvidersView.as_view(), name="oauth_providers"),
    path("google/", GoogleLogin.as_view(), name="google_login"),
    path("github/", GitHubLogin.as_view(), name="github_login"),
]
