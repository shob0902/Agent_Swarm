# Django settings for the orchestrator project, loaded from backend/.env via django-environ.
from datetime import timedelta
from pathlib import Path
import environ
BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DEBUG=(bool, True),
)
environ.Env.read_env(BASE_DIR / ".env")
_DEV_SECRET_KEY = "dev-only-insecure-secret-key"
SECRET_KEY = env("DJANGO_SECRET_KEY", default=_DEV_SECRET_KEY)
DEBUG = env.bool("DEBUG", default=True)
# The key signs login tokens; the dev default is public in this repo, so production must never run on it.
if not DEBUG and (SECRET_KEY == _DEV_SECRET_KEY or len(SECRET_KEY) < 32):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY to a long random value when DEBUG=False, e.g. "
        "python -c \"import secrets; print(secrets.token_urlsafe(50))\""
    )
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
# Render sets this to the service's own *.onrender.com hostname; allow it so a missing ALLOWED_HOSTS entry can't 400 the deploy.
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "rest_framework",
    "corsheaders",
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
    "agents",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
# SQLite locally; set DATABASE_URL (e.g. a free Neon/Supabase Postgres) in production so task
# state survives restarts of an ephemeral free-tier web service.
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
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
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if not DEBUG:
    # Free-tier hosts (Render, Koyeb...) terminate TLS at a proxy.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)
CORS_ALLOW_CREDENTIALS = True
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "dj_rest_auth.jwt_auth.JWTCookieAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}
# --- Pipeline execution -------------------------------------------------------
# "github_actions" (production): Django only creates the task and fires a
# workflow_dispatch; the agents run on a GitHub-hosted runner.
# "local" (development): the same pipeline runs as a detached
# `manage.py run_agent_task` subprocess on this machine.
PIPELINE_EXECUTOR = env("PIPELINE_EXECUTOR", default="local")
# Repo that hosts .github/workflows/agent-swarm.yml (this project's own repo), e.g. "owner/Agent_Swarm".
GITHUB_ACTIONS_REPO = env("GITHUB_ACTIONS_REPO", default="")
GITHUB_ACTIONS_WORKFLOW = env("GITHUB_ACTIONS_WORKFLOW", default="agent-swarm.yml")
GITHUB_ACTIONS_REF = env("GITHUB_ACTIONS_REF", default="main")
# Fine-grained PAT with "Actions: read & write" on GITHUB_ACTIONS_REPO only. Web-process only.
GITHUB_DISPATCH_TOKEN = env("GITHUB_DISPATCH_TOKEN", default="")
# Shared HMAC secret the runner signs its callbacks with. Must match the Actions secret of the same name.
RUNNER_SHARED_SECRET = env("RUNNER_SHARED_SECRET", default="")
RUNNER_SIGNATURE_MAX_AGE_SECONDS = env.int("RUNNER_SIGNATURE_MAX_AGE_SECONDS", default=300)
# Public base URL of this API as seen by the runner, e.g. https://agent-swarm-api.onrender.com/api
AGENT_SWARM_API_URL = env("AGENT_SWARM_API_URL", default="http://localhost:8000/api")
# --- GitHub pull requests (used by the runner, never sent to the frontend) ------
# Token the runner uses to push a branch and open the PR: fine-grained PAT with
# "Contents: read & write" + "Pull requests: read & write" on the target repos.
AGENT_GITHUB_TOKEN = env("AGENT_GITHUB_TOKEN", default="")
CREATE_PULL_REQUESTS = env.bool("CREATE_PULL_REQUESTS", default=True)
# When the token can't write to the target repo, fork it into the token's account, push the branch
# there and open a cross-repo PR to upstream. Restrict targets with ALLOWED_REPO_OWNERS on a public
# deployment, otherwise any signed-in user can have the bot open PRs on any public repository.
PR_ALLOW_FORKS = env.bool("PR_ALLOW_FORKS", default=True)
# Optional comma-separated allow-list of repo owners tasks may target (empty = any public repo).
ALLOWED_REPO_OWNERS = [o.lower() for o in env.list("ALLOWED_REPO_OWNERS", default=[])]
PR_BRANCH_PREFIX = env("PR_BRANCH_PREFIX", default="agent-swarm")
PR_LABELS = env.list("PR_LABELS", default=["agent-swarm", "automated-pr"])
GITHUB_API_URL = env("GITHUB_API_URL", default="https://api.github.com")
# Look the repo up on GitHub when a task is created (rejects typos, private and archived repos early).
GITHUB_VALIDATE_REPOS = env.bool("GITHUB_VALIDATE_REPOS", default=True)
# --- LLM -------------------------------------------------------------------------
GROQ_API_KEY_PLANNER = env("GROQ_API_KEY_PLANNER", default="")
GROQ_API_KEY_CODER_A = env("GROQ_API_KEY_CODER_A", default="")
GROQ_API_KEY_CODER_B = env("GROQ_API_KEY_CODER_B", default="")
GROQ_API_KEY_REVIEWER = env("GROQ_API_KEY_REVIEWER", default="")
# llama-3.1-8b-instant was retired from Groq; gpt-oss-120b is on the free tier (8K tokens/min per key).
GROQ_MODEL = env("GROQ_MODEL", default="openai/gpt-oss-120b")
# gpt-oss models reason before answering, and those tokens count against max_tokens. "low" keeps
# the reasoning short so the JSON answer fits each agent's budget. Ignored by non-reasoning models.
GROQ_REASONING_EFFORT = env("GROQ_REASONING_EFFORT", default="low")
# --- Retry limits ------------------------------------------------------------------
# Coder -> Tester attempts per review cycle.
MAX_TEST_RETRIES = env.int("MAX_TEST_RETRIES", default=3)
# Extra Coder -> Tester -> Reviewer cycles after a Reviewer rejection.
MAX_REVIEW_RETRIES = env.int("MAX_REVIEW_RETRIES", default=1)
# --- Sandbox -----------------------------------------------------------------------
SANDBOX_TIMEOUT_SECONDS = env.int("SANDBOX_TIMEOUT_SECONDS", default=120)
SANDBOX_INSTALL_TIMEOUT_SECONDS = env.int("SANDBOX_INSTALL_TIMEOUT_SECONDS", default=300)
# Dependency installation is the only sandbox step that gets network access; tests/lint/build never do.
SANDBOX_INSTALL_DEPENDENCIES = env.bool("SANDBOX_INSTALL_DEPENDENCIES", default=True)
SANDBOX_IMAGE = env("SANDBOX_IMAGE", default="agent-swarm-sandbox:latest")
# Node builds (webpack/vite/tsc) regularly need more than the 512m that was enough for pytest.
SANDBOX_MEMORY_LIMIT = env("SANDBOX_MEMORY_LIMIT", default="1g")
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:5173")
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
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = "none"
# OAuth: fetch GitHub's /user/emails (with their verified flags), and never persist provider access tokens --
# they're only needed once, to read the profile.
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
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
        "SCOPE": ["read:user", "user:email"],
    },
}
REST_AUTH = {
    "TOKEN_MODEL": None,
    "USE_JWT": True,
    "JWT_AUTH_HTTPONLY": True,
    "JWT_AUTH_COOKIE": "access_token",
    "JWT_AUTH_REFRESH_COOKIE": "refresh_token",
    "JWT_AUTH_SAMESITE": "Lax" if DEBUG else "None",
    "JWT_AUTH_SECURE": not DEBUG,
    "SESSION_LOGIN": False,
    "USER_DETAILS_SERIALIZER": "accounts.serializers.UserSerializer",
    "REGISTER_SERIALIZER": "accounts.serializers.RegisterSerializer",
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}
# Console logging so pipeline progress shows up in `run_agent_task` output and the GitHub Actions log.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {
        "agents": {"handlers": ["console"], "level": env("AGENTS_LOG_LEVEL", default="INFO"), "propagate": False},
        "accounts": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Django only prints 500 tracebacks to the console when DEBUG=True; this makes them show up in the
        # host's log stream (Render "Logs") in production too.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
