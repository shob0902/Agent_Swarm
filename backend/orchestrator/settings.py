"""
Django settings for the orchestrator project.

Uses django-environ to load configuration from backend/.env (see .env.example).
Models stick to the standard ORM (no SQLite-only features) so swapping
DATABASES to Postgres later is a config-only change.
"""
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
    "rest_framework",
    "corsheaders",
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

# --- DRF -------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
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

# --- LLM providers ----------------------------------------------------------
GOOGLE_API_KEY = env("GOOGLE_API_KEY", default="")
GROQ_API_KEY = env("GROQ_API_KEY", default="")

# Model names are centralized here (not scattered in llm_client.py) so
# swapping a provider's model is a one-line config change.
# "gemini-flash-latest" is Google's own alias for their current recommended
# flash model -- used instead of pinning a dated model name (e.g.
# "gemini-2.5-flash") because Google periodically sunsets older model
# versions for new API keys, which would otherwise silently 404 this
# pipeline. Pin to a specific version instead if reproducibility across
# model upgrades matters more than staying unblocked.
GEMINI_MODEL = env("GEMINI_MODEL", default="gemini-flash-latest")
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
