import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _cipher():
    configured_key = str(getattr(settings, 'MONITOR_TASK_PASSWORD_KEY', '') or '').strip()
    key = configured_key.encode('ascii') if configured_key else base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    )
    return Fernet(key)


def encrypt_secret(value):
    text = str(value or '')
    return _cipher().encrypt(text.encode('utf-8')).decode('ascii') if text else ''


def decrypt_secret(value):
    if not value:
        return ''
    try:
        return _cipher().decrypt(str(value).encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError, ValueError):
        return ''
