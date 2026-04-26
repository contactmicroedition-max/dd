from pathlib import Path
import os
from django.contrib.messages import constants as messages

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_local_env(env_path):
    """Load simple KEY=VALUE pairs from a local .env file without overriding existing env vars."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env(BASE_DIR / '.env')

SECRET_KEY = (os.getenv('DJANGO_SECRET_KEY') or os.getenv('SECRET_KEY') or '').strip()
if not SECRET_KEY:
    raise RuntimeError('Missing required environment variable: DJANGO_SECRET_KEY (or SECRET_KEY).')

DEBUG = os.getenv('DJANGO_DEBUG', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
    if host.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'dronesec.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'dronesec.wsgi.application'

AUTH_USER_MODEL = 'core.CustomUser'

DB_ENGINE = os.getenv('DB_ENGINE', 'django.db.backends.mysql').strip()

if DB_ENGINE == 'django.db.backends.sqlite3':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / os.getenv('SQLITE_NAME', 'db.sqlite3'),
        }
    }
else:
    db_default = {
        'ENGINE': DB_ENGINE,
        'NAME': os.getenv('DB_NAME', 'dronesec_db'),
        'USER': os.getenv('DB_USER', 'root'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '3306'),
    }

    # Ensure full Unicode support in MySQL-compatible backends.
    if DB_ENGINE.endswith('mysql'):
        db_default['OPTIONS'] = {
            'charset': 'utf8mb4',
        }

    DATABASES = {
        'default': db_default,
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Tunis'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', True)
EMAIL_USE_SSL = _env_bool('EMAIL_USE_SSL', False)

# Use SMTP when host and credentials are provided, otherwise keep console backend for local dev.
if EMAIL_HOST and EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@dronesec.io')
CONTACT_RECEIVER_EMAIL = os.getenv('CONTACT_RECEIVER_EMAIL', DEFAULT_FROM_EMAIL)

RECAPTCHA_PUBLIC_KEY = os.getenv('RECAPTCHA_PUBLIC_KEY', '')
RECAPTCHA_PRIVATE_KEY = os.getenv('RECAPTCHA_PRIVATE_KEY', '')

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8000/users/google/callback/')

SESSION_COOKIE_AGE = 1209600
SESSION_SAVE_EVERY_REQUEST = True

MESSAGE_TAGS = {
    messages.DEBUG: 'debug',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'error',
}

# AI assistant provider configuration (OpenAI-compatible chat/completions API).
AI_ASSISTANT_ENABLED = _env_bool('AI_ASSISTANT_ENABLED', True)
AI_ASSISTANT_BASE_URL = os.getenv('AI_ASSISTANT_BASE_URL', os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')).rstrip('/')
AI_ASSISTANT_API_KEY = os.getenv('AI_ASSISTANT_API_KEY', os.getenv('OPENAI_API_KEY', ''))
AI_ASSISTANT_MODEL = os.getenv('AI_ASSISTANT_MODEL', 'gpt-4o-mini')
AI_ASSISTANT_TEMPERATURE = _env_float('AI_ASSISTANT_TEMPERATURE', 0.65)
AI_ASSISTANT_TIMEOUT_SECONDS = _env_int('AI_ASSISTANT_TIMEOUT_SECONDS', 25)
AI_ASSISTANT_MAX_HISTORY = _env_int('AI_ASSISTANT_MAX_HISTORY', 10)
