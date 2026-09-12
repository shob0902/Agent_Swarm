# URL routes for auth: login, logout, signup and the two OAuth callbacks.
from django.urls import include, path
from .views import GitHubLogin, GoogleLogin, RegisterView
urlpatterns = [
    path("", include("dj_rest_auth.urls")),
    path("registration/", RegisterView.as_view(), name="rest_register"),
    path("registration/", include("dj_rest_auth.registration.urls")),
    path("google/", GoogleLogin.as_view(), name="google_login"),
    path("github/", GitHubLogin.as_view(), name="github_login"),
]
