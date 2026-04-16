import os
from .settings import *
from .settings import BASE_DIR

DEBUG = False

RENDER_HOST = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')

ALLOWED_HOSTS = [
    RENDER_HOST,
    'production-web-conn.onrender.com',   # Django backend — explicit fallback
]

SECRET_KEY = os.getenv("SECRET_KEY")

# ── CSRF ──────────────────────────────────────────────────────────────────────
# Must include BOTH the backend domain AND the frontend domain.
# Django checks Origin header against this list on every POST/PUT/DELETE.
CSRF_TRUSTED_ORIGINS = [
    f"https://{RENDER_HOST}",
    "https://production-web-conn.onrender.com",      # Django backend
    "https://frontend-production-web.onrender.com",  # React frontend (sends requests here)
]

CSRF_COOKIE_SAMESITE  = 'None'   # cross-site cookie requires None in production
CSRF_COOKIE_SECURE    = True     # must be True when SameSite=None
CSRF_COOKIE_HTTPONLY  = False    # React must read csrftoken cookie via JS

SESSION_COOKIE_SAMESITE = 'None'
SESSION_COOKIE_SECURE   = True

# ── CORS ──────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = [
    "https://frontend-production-web.onrender.com",   # React frontend
    "https://production-web-conn-1.onrender.com",     # FastAPI (if it calls Django)
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept', 'accept-encoding', 'authorization', 'content-type',
    'dnt', 'origin', 'user-agent', 'x-csrftoken', 'x-requested-with',
]

# ── Middleware (order matters — CorsMiddleware must be first) ─────────────────
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',          # ← MUST be first
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

# ── MongoDB (from Render env vars) ────────────────────────────────────────────
MONGODB_URL   = os.getenv('MONGODB_URL')
MONGODB_URL_2 = os.getenv('MONGODB_URL_2')


GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME')
GCS_CREDENTIALS_JSON = os.getenv('GCS_CREDENTIALS_JSON')
