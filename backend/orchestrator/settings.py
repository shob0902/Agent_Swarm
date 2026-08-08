"""
Django settings for the orchestrator project.

Uses django-environ to load configuration from backend/.env (see .env.example).
Models stick to the standard ORM (no SQLite-only features) so swapping
DATABASES to Postgres later is a config-only change.
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
)
# Read backend/.env if present; falls back to real environment variables
# (and the defaults below) when it isn't, so `docker-compose`/CI can set
# vars directly instead of shipping a .env file.
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-secret-key")
DEBUG = env.bool("DEBUG", default=True)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",  # required by allauth
    "rest_framework",
    "corsheaders",
    # --- auth (Section: see README "Auth" for the OAuth setup story) -----
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.github",
    "dj_rest_auth",
    "dj_rest_auth.registration",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "accounts",
    # -----------------------------------------------------------------------
    "agents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "orchestrator.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "orchestrator.wsgi.application"

# --- Database -----------------------------------------------------------
# SQLite for local dev. Models avoid SQLite-only features so this can be
# swapped for Postgres (DATABASES = env.db("DATABASE_URL")) with no model
# changes.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Custom email-only User model (see accounts/models.py) -- must be set
# before the first migration touching auth ever runs.
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- CORS (frontend dev server) -----------------------------------------
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)
# The httpOnly JWT cookies (see REST_AUTH below) have to ride along on
# cross-port XHR from the Vite dev server, which requires both this and
# axios's `withCredentials: true` on the frontend (frontend/src/api/client.js).
CORS_ALLOW_CREDENTIALS = True

# --- DRF -------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    # JWTCookieAuthentication reads the access token from an httpOnly
    # cookie rather than an Authorization header (see REST_AUTH) -- keeps
    # both tokens out of reach of any XSS in the SPA.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "dj_rest_auth.jwt_auth.JWTCookieAuthentication",
    ],
    # "Protect all API routes" (Section: Data Isolation & Security) done
    # once, globally, instead of per-view; dj_rest_auth's own auth/registration
    # endpoints override this back to AllowAny where login itself needs it.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# --- Celery / Redis -------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TRACK_STARTED = True
# Fail fast in dev rather than hanging forever on a stuck sandbox/LLM call.
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 10
CELERY_TASK_TIME_LIMIT = 60 * 12

# --- LLM provider (Groq) ----------------------------------------------------
# Every LLM-backed agent runs on Groq. Gemini was dropped because its free
# tier is capped per Google Cloud *project* rather than per API key (20
# requests/day), which a single multi-retry pipeline run exhausts on its
# own -- Groq's per-key limits are both higher and genuinely independent
# per key, so spreading across keys actually buys headroom there.
#
# Four keys, one per agent role rather than one shared key, so a role that
# burns through its quota can't starve the others. The Coder is the
# highest-volume agent by far (one call per plan, plus one per retry
# attempt), so it alone gets two keys and rotates between them -- see
# agents/services/key_pool.py for the selection algorithm.
GROQ_API_KEY_PLANNER = env("GROQ_API_KEY_PLANNER", default="")
GROQ_API_KEY_CODER_A = env("GROQ_API_KEY_CODER_A", default="")
GROQ_API_KEY_CODER_B = env("GROQ_API_KEY_CODER_B", default="")
GROQ_API_KEY_REVIEWER = env("GROQ_API_KEY_REVIEWER", default="")

# Model name is centralized here (not scattered in llm_client.py) so
# swapping models is a one-line config change.
GROQ_MODEL = env("GROQ_MODEL", default="llama-3.1-8b-instant")

# Pipeline tuning
MAX_TEST_RETRIES = env.int("MAX_TEST_RETRIES", default=3)
SANDBOX_TIMEOUT_SECONDS = env.int("SANDBOX_TIMEOUT_SECONDS", default=60)
# python:3.11-slim has no test runner preinstalled and the sandbox has no
# network access to `pip install` one at run time, so the Tester agent
# needs a purpose-built image with pytest (and the toy demo's deps) baked
# in -- see docker/sandbox.Dockerfile. Build it once with:
#   docker build -t agent-swarm-sandbox:latest -f docker/sandbox.Dockerfile .
SANDBOX_IMAGE = env("SANDBOX_IMAGE", default="agent-swarm-sandbox:latest")

# --- Auth: allauth + dj-rest-auth + SimpleJWT ------------------------------
# Frontend origin used to build absolute links (password reset emails,
# OAuth callback_url below). Same list of dev ports as CORS_ALLOWED_ORIGINS
# -- take the first one as *the* canonical frontend origin.
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:5173")
# The frontend page each provider redirects back to with `?code=...` after
# the user approves access (AuthCallbackPage.jsx) -- must exactly match
# what's registered as an authorized redirect URI in each provider's console.
FRONTEND_OAUTH_CALLBACK_URLS = {
    "google": f"{FRONTEND_BASE_URL}/auth/callback/google",
    "github": f"{FRONTEND_BASE_URL}/auth/callback/github",
}

SITE_ID = 1
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_ADAPTER = "accounts.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "accounts.adapters.AutoConnectSocialAccountAdapter"
# Email is the only login identity -- our User model has no username field
# at all (see accounts/models.py) -- so allauth must never require or try
# to generate one.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
# allauth itself hard-errors if "username" appears in ACCOUNT_SIGNUP_FIELDS
# at all while ACCOUNT_USER_MODEL_USERNAME_FIELD is None -- so the field
# can't be listed here as "present but optional". The RegisterSerializer's
# own hardcoded username requirement is dropped instead via a custom
# REGISTER_SERIALIZER (accounts.serializers.RegisterSerializer) below.
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
# No SMTP configured for this project yet (Non-goal-adjacent: local dev
# only per the plan) -- signup logs the user in immediately instead of
# blocking on a verification email. Revisit before any real deployment.
ACCOUNT_EMAIL_VERIFICATION = "none"

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": env("GOOGLE_CLIENT_ID", default=""),
            "secret": env("GOOGLE_CLIENT_SECRET", default=""),
            "key": "",
        },
        "SCOPE": ["profile", "email"],
    },
    "github": {
        "APP": {
            "client_id": env("GITHUB_CLIENT_ID", default=""),
            "secret": env("GITHUB_CLIENT_SECRET", default=""),
            "key": "",
        },
        "SCOPE": ["user:email"],
    },
}

REST_AUTH = {
    # JWT-only -- no DRF authtoken app installed, so there's no legacy
    # Token model to back this with.
    "TOKEN_MODEL": None,
    "USE_JWT": True,
    "JWT_AUTH_HTTPONLY": True,  # neither token is readable from JS -- immune to XSS token theft
    "JWT_AUTH_COOKIE": "access_token",
    "JWT_AUTH_REFRESH_COOKIE": "refresh_token",
    "JWT_AUTH_SAMESITE": "Lax",
    "JWT_AUTH_SECURE": not DEBUG,  # dev over http:// needs this off; flip on for any real deploy
    "SESSION_LOGIN": False,
    "USER_DETAILS_SERIALIZER": "accounts.serializers.UserSerializer",
    "REGISTER_SERIALIZER": "accounts.serializers.RegisterSerializer",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,  # logout / refresh-rotation actually invalidates the old token
    "AUTH_HEADER_TYPES": ("Bearer",),
}
