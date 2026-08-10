import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_local_env():
    env_path = BASE_DIR / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


load_local_env()

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'aibetauto-local-only-secret-key-change-before-production-2026')
DEBUG = os.getenv('DJANGO_DEBUG', 'true').lower() in {'1', 'true', 'yes'}
ALLOWED_HOSTS = [item.strip() for item in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if item.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'platform_api.apps.PlatformApiConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('MYSQL_DATABASE', 'test_aibetauto'),
        'USER': os.getenv('MYSQL_USER', 'root'),
        'PASSWORD': os.getenv('MYSQL_PASSWORD', '123456'),
        'HOST': os.getenv('MYSQL_HOST', '127.0.0.1'),
        'PORT': os.getenv('MYSQL_PORT', '3306'),
        'CONN_MAX_AGE': int(os.getenv('MYSQL_CONN_MAX_AGE', '60')),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}
AUTH_USER_MODEL = 'platform_api.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOWED_ORIGINS = [item.strip() for item in os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:4173,http://127.0.0.1:4173').split(',') if item.strip()]
FEISHU_BOT_WEBHOOK_URL = os.getenv('FEISHU_BOT_WEBHOOK_URL', '')
FEISHU_BOT_SSL_VERIFY = os.getenv('FEISHU_BOT_SSL_VERIFY', 'true').lower() in {'1', 'true', 'yes'}
LARK_APP_ID = os.getenv('LARK_APP_ID', os.getenv('AppID', ''))
LARK_APP_SECRET = os.getenv('LARK_APP_SECRET', os.getenv('AppSecret', ''))
LARK_REDIRECT_URI = os.getenv('LARK_REDIRECT_URI', '')
LARK_FRONTEND_URL = os.getenv('LARK_FRONTEND_URL', 'http://localhost:4173').rstrip('/')
LARK_OPEN_BASE_URL = os.getenv('LARK_OPEN_BASE_URL', 'https://open.feishu.cn').rstrip('/')
LARK_DEFAULT_ROLE_CODE = os.getenv('LARK_DEFAULT_ROLE_CODE', 'viewer')
SESSION_COOKIE_DOMAIN = os.getenv('SESSION_COOKIE_DOMAIN', '').strip() or None
DATA_FACTORY_FRONTEND_ACCOUNT = os.getenv('DATA_FACTORY_FRONTEND_ACCOUNT', '').strip()
DATA_FACTORY_FRONTEND_PASSWORD = os.getenv('DATA_FACTORY_FRONTEND_PASSWORD', '')
DATA_FACTORY_BACKEND_ACCOUNT = os.getenv('DATA_FACTORY_BACKEND_ACCOUNT', '').strip()
DATA_FACTORY_BACKEND_PASSWORD = os.getenv('DATA_FACTORY_BACKEND_PASSWORD', '')
MONITOR_TASK_PASSWORD_KEY = os.getenv('MONITOR_TASK_PASSWORD_KEY', '').strip()
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework_simplejwt.authentication.JWTAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS': 'platform_api.pagination.StandardPagination',
    'PAGE_SIZE': 10,
    'EXCEPTION_HANDLER': 'platform_api.responses.exception_handler',
}
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'AUTH_HEADER_TYPES': ('Bearer',),
}
