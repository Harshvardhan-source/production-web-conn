import os
from .settings import *
from .settings import BASE_DIR

DEBUG = False

RENDER_HOST = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')

ALLOWED_HOSTS = [
    RENDER_HOST,
    'production-web-conn-e2h8.onrender.com',
    'production-web-conn.onrender.com',
    'production-web-conn-1-82wl.onrender.com'
]

SECRET_KEY = os.getenv("SECRET_KEY")

# ── CSRF ──────────────────────────────────────────────────────────────────────
CSRF_TRUSTED_ORIGINS = [
    f"https://{RENDER_HOST}",
    "https://production-web-conn-e2h8.onrender.com",
    "https://production-web-conn.onrender.com",
    "https://frontend-production-web-ulhf.onrender.com",
]

CSRF_COOKIE_SAMESITE  = 'None'
CSRF_COOKIE_SECURE    = True
CSRF_COOKIE_HTTPONLY  = False

SESSION_COOKIE_SAMESITE = 'None'
SESSION_COOKIE_SECURE   = True

# ── CORS ──────────────────────────────────────────────────────────────────────
# corsheaders middleware handles all standard endpoints.
# The _ai_cors() helper in views.py additionally handles OPTIONS preflight
# for the AI chat endpoints specifically.
CORS_ALLOWED_ORIGINS = [
    "https://frontend-production-web-ulhf.onrender.com",
    "https://production-web-conn-1-82wl.onrender.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False   # keep explicit — never True in production

# Allow ALL headers so Authorization + X-CSRFToken both pass through
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# Allow all standard methods including OPTIONS (preflight)
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# ── Middleware (order matters — CorsMiddleware MUST be first) ─────────────────
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',           # 1st — always
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ── Static files ──────────────────────────────────────────────────────────────
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}

# ── Database ──────────────────────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGODB_URL   = os.getenv('MONGODB_URL')
MONGODB_URL_2 = os.getenv('MONGODB_URL_2')

# ── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# ── GCS ───────────────────────────────────────────────────────────────────────
GCS_BUCKET_NAME      = os.getenv('GCS_BUCKET_NAME')
GCS_CREDENTIALS_JSON = os.getenv('GCS_CREDENTIALS_JSON')