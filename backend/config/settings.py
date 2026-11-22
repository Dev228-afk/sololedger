from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "sololedger-local-dev-secret-change-in-production-2026",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if h.strip()
]

SOLOLEDGER_SESSION_SECRET = os.environ.get(
    "SOLOLEDGER_SESSION_SECRET",
    "sololedger-local-cookie-hmac-secret-2026",
)
SOLOLEDGER_STORAGE_DIR = Path(
    os.environ.get("SOLOLEDGER_STORAGE_DIR", str(PROJECT_ROOT / "var" / "uploads"))
).resolve()
SOLOLEDGER_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
SOLOLEDGER_LLM_PROVIDER = os.environ.get("SOLOLEDGER_LLM_PROVIDER", "mock").lower()
SOLOLEDGER_VERSION = "0.1.0"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "apps.accounts",
    "apps.categorization",
    "apps.audit",
    "apps.imports",
    "apps.transactions",
    "apps.reports",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.accounts.middleware.RequestIdAndSessionMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
APPEND_SLASH = False

_db_url = urlparse(
    os.environ.get(
        "DATABASE_URL",
        "postgresql://sololedger:sololedger_local_2026@127.0.0.1:5436/sololedger",
    )
)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db_url.path.lstrip("/") or "sololedger",
        "USER": _db_url.username or "sololedger",
        "PASSWORD": _db_url.password or "sololedger_local_2026",
        "HOST": _db_url.hostname or "127.0.0.1",
        "PORT": str(_db_url.port or 5436),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 5},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
STATIC_URL = "/static/"

CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5201",
    "http://localhost:5201",
]
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.accounts.exceptions.sololedger_exception_handler",
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SoloLedger API",
    "DESCRIPTION": "Freelance statement import, categorization & exact ledger API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6382/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6382/1")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = False
CELERY_TASK_DEFAULT_QUEUE = "sololedger"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_BEAT_SCHEDULE = {
    "recover-stranded-imports": {
        "task": "tasks.import_tasks.recover_stranded_imports",
        "schedule": 30.0,
    },
}

