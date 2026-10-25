"""Local teaching settings. Compose binds the HTTP service to localhost."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "course-only-do-not-use-in-production")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "web", "testserver"]
INSTALLED_APPS = ["django.contrib.contenttypes", "orders"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

if os.getenv("POSTGRES_HOST"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "course"),
        "USER": os.getenv("POSTGRES_USER", "course"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "course-local-only"),
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
    }}

BROKER_URL = os.getenv("BROKER_URL", "amqp://student:student-local-only@localhost:5672/learning")
CELERY_BROKER_URL = BROKER_URL
CELERY_RESULT_BACKEND = "rpc://"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_DEFAULT_QUEUE = "celery"
CELERY_TASK_DEFAULT_DELIVERY_MODE = "persistent"
CELERY_BROKER_TRANSPORT_OPTIONS = {"confirm_publish": True}
CELERY_BROKER_CONNECTION_TIMEOUT = 5
CELERY_TASK_PUBLISH_RETRY_POLICY = {"max_retries": 2, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5}
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
