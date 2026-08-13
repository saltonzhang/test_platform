"""Shared data-factory database access and local configuration."""

from contextlib import contextmanager
import os
import re
from pathlib import Path

import pymysql
import pymysql.cursors


_LOCAL_ENV_PATH = Path(__file__).resolve().parents[2] / '.env'
_DB_ENV_PREFIX = 'DATA_FACTORY_DB'
_DB_PROFILE_ENV = f'{_DB_ENV_PREFIX}_PROFILE'
_DB_FIELD_ENV_SUFFIXES = {
    'host': 'HOST',
    'port': 'PORT',
    'user': 'USER',
    'password': 'PASSWORD',
    'database': 'NAME',
    'charset': 'CHARSET',
    'connect_timeout': 'CONNECT_TIMEOUT',
    'read_timeout': 'READ_TIMEOUT',
    'write_timeout': 'WRITE_TIMEOUT',
}
_DB_REQUIRED_FIELDS = ('host', 'port', 'user', 'password', 'database')
_DB_OPTIONAL_FIELDS = ('charset', 'connect_timeout', 'read_timeout', 'write_timeout')
_DB_INTEGER_FIELDS = {'port', 'connect_timeout', 'read_timeout', 'write_timeout'}
_DB_DEFAULT_PROFILE_NAMES = {'', 'default', 'legacy'}


def _load_local_env(path=_LOCAL_ENV_PATH):
    """Load backend/.env without requiring python-dotenv as a dependency."""
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (FileNotFoundError, OSError):
        return

    for line in lines:
        value = line.strip()
        if not value or value.startswith('#'):
            continue
        if value.startswith('export '):
            value = value[7:].lstrip()
        if '=' not in value:
            continue
        key, env_value = value.split('=', 1)
        key = key.strip()
        if not key:
            continue
        env_value = env_value.strip()
        if len(env_value) >= 2 and env_value[0] == env_value[-1] and env_value[0] in {'"', "'"}:
            env_value = env_value[1:-1]
        os.environ.setdefault(key, env_value)


def _get_int_env(name):
    value = os.getenv(name)
    if value in (None, ''):
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f'{name} 必须为整数') from exc


def _normalize_db_profile(profile):
    if profile is None:
        return None
    value = str(profile).strip()
    if not value or value.lower() in _DB_DEFAULT_PROFILE_NAMES:
        return None
    return value


def _selected_db_profile():
    return _normalize_db_profile(os.getenv(_DB_PROFILE_ENV))


def _db_env_prefix(profile=None):
    profile_name = _normalize_db_profile(profile)
    if profile_name is None:
        return _DB_ENV_PREFIX
    raw_token = re.sub(r'[^0-9A-Za-z]+', '_', profile_name).strip('_').upper()
    if raw_token.startswith('DATA_') and raw_token.endswith('_DB'):
        return raw_token
    token = raw_token
    if not token:
        raise ValueError('DATA_FACTORY_DB_PROFILE 不能为空')
    canonical_prefix = f'{_DB_ENV_PREFIX}_{token}'
    legacy_prefix = f'DATA_{token}_DB'
    # Support existing DATA_<PROFILE>_DB_* groups while keeping the newer
    # DATA_FACTORY_DB_<PROFILE>_* naming convention. Prefer the group that
    # actually exists so a package marker can be either FACTEST or the full
    # DATA_FACTEST_DB prefix.
    if os.getenv(f'{canonical_prefix}_HOST') not in (None, ''):
        return canonical_prefix
    if os.getenv(f'{legacy_prefix}_HOST') not in (None, ''):
        return legacy_prefix
    return canonical_prefix


def _get_env_database_value(field, profile=None):
    env_name = f'{_db_env_prefix(profile)}_{_DB_FIELD_ENV_SUFFIXES[field]}'
    value = os.getenv(env_name)
    if value in (None, ''):
        return None
    if field in _DB_INTEGER_FIELDS:
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f'{env_name} 必须为整数') from exc
    return value


def _read_env_database_config(profile=None, *, allow_generic_fallback=False):
    config = {field: _get_env_database_value(field, profile) for field in _DB_FIELD_ENV_SUFFIXES}
    if allow_generic_fallback and _normalize_db_profile(profile) is not None:
        for field in _DB_OPTIONAL_FIELDS:
            if config.get(field) in (None, ''):
                config[field] = _get_env_database_value(field)
    return config


_load_local_env()

# Values are read from backend/.env or the process environment.
# Use DATA_FACTORY_DB_PROFILE to switch among multiple groups; omit it to keep
# using the legacy DATA_FACTORY_DB_* group. For example:
#   DATA_FACTORY_DB_PROFILE=report
#   DATA_FACTORY_DB_REPORT_HOST=...
#   DATA_FACTORY_DB_REPORT_PORT=...
DATA_FACTORY_DATABASE_CONFIG = {
    **_read_env_database_config(_selected_db_profile(), allow_generic_fallback=True),
    'cursorclass': pymysql.cursors.DictCursor,
}

# Keep the shorter name used by existing callers.
DB_CONFIG = DATA_FACTORY_DATABASE_CONFIG


def _build_db_config(config=None, *, profile=None, **overrides):
    source_is_env = config is None
    if config is None:
        db_config = _read_env_database_config(
            _selected_db_profile() if profile is None else profile,
            allow_generic_fallback=True,
        )
    else:
        db_config = dict(config)
    db_config.update({key: value for key, value in overrides.items() if value is not None})
    for field in _DB_INTEGER_FIELDS:
        value = db_config.get(field)
        if value in (None, '') or isinstance(value, int):
            continue
        try:
            db_config[field] = int(value)
        except (TypeError, ValueError) as exc:
            if source_is_env:
                env_name = f'{_db_env_prefix(profile if profile is not None else _selected_db_profile())}_{_DB_FIELD_ENV_SUFFIXES[field]}'
                raise ValueError(f'{env_name} 必须为整数') from exc
            raise ValueError(f'{field} 必须为整数') from exc
    db_config.setdefault('cursorclass', pymysql.cursors.DictCursor)
    missing = [
        key
        for key in _DB_REQUIRED_FIELDS
        if db_config.get(key) is None or (key != 'password' and db_config.get(key) == '')
    ]
    if missing:
        if source_is_env:
            env_prefix = _db_env_prefix(profile if profile is not None else _selected_db_profile())
            env_names = ', '.join(f'{env_prefix}_{_DB_FIELD_ENV_SUFFIXES[key]}' for key in missing)
            profile_hint = profile if profile is not None else _selected_db_profile()
            profile_text = f'（profile={profile_hint}）' if profile_hint else ''
            raise RuntimeError(f'缺少数据工厂数据库配置{profile_text}，请在 backend/.env 中设置：{env_names}')
        raise RuntimeError(f'缺少数据库配置：{", ".join(missing)}')
    return {key: value for key, value in db_config.items() if value is not None}


def get_database_config(config=None, *, profile=None, **overrides):
    """Resolve the final MySQL connection config without opening a socket."""
    return _build_db_config(config, profile=profile, **overrides)


def get_db_connection(config=None, *, profile=None, **overrides):
    return pymysql.connect(**_build_db_config(config, profile=profile, **overrides))


@contextmanager
def db_connection(config=None, *, profile=None, **overrides):
    conn = get_db_connection(config=config, profile=profile, **overrides)
    try:
        yield conn
    finally:
        conn.close()


class DatabaseClient:
    """Small PyMySQL wrapper for one data-factory database session."""

    def __init__(self, config=None, *, profile=None, **overrides):
        self.config = _build_db_config(config, profile=profile, **overrides)
        self.connection = None

    def __enter__(self):
        self.connection = pymysql.connect(**self.config)
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.connection:
            self.connection.close()
            self.connection = None
        return False

    def execute(self, sql, params=None, *, fetch='none', commit=False, many=False):
        if not self.connection:
            raise RuntimeError('数据库连接未初始化')
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError('SQL 不能为空')
        fetch_mode = _normalize_fetch_mode(fetch)
        try:
            with self.connection.cursor() as cursor:
                if many:
                    affected_rows = cursor.executemany(sql, params or [])
                else:
                    affected_rows = cursor.execute(sql, params or ())

                if fetch_mode == 'one':
                    result = cursor.fetchone()
                elif fetch_mode == 'all':
                    result = cursor.fetchall()
                else:
                    result = affected_rows

            if commit:
                self.connection.commit()
            return result
        except Exception:
            if commit:
                self.connection.rollback()
            raise

    def query_one(self, sql, params=None):
        return self.execute(sql, params, fetch='one')

    def query_all(self, sql, params=None):
        return self.execute(sql, params, fetch='all')

    def execute_write(self, sql, params=None, *, many=False):
        return self.execute(sql, params, commit=True, many=many)


def _normalize_fetch_mode(fetch):
    fetch_mode = 'none' if fetch is None else str(fetch).strip().lower()
    if fetch_mode not in {'none', 'one', 'all'}:
        raise ValueError('fetch 只能是 none、one 或 all')
    return fetch_mode


def _resolve_fetch_mode(fetch, fetch_one, fetch_all):
    if fetch_one and fetch_all:
        raise ValueError('fetch_one 和 fetch_all 不能同时为 True')
    if fetch_one:
        return 'one'
    if fetch_all:
        return 'all'
    return _normalize_fetch_mode(fetch)


def execute_sql(
    sql,
    params=None,
    *,
    fetch='none',
    fetch_one=False,
    fetch_all=False,
    commit=False,
    many=False,
    config=None,
    profile=None,
    **overrides,
):
    fetch_mode = _resolve_fetch_mode(fetch, fetch_one, fetch_all)
    with DatabaseClient(config=config, profile=profile, **overrides) as db:
        return db.execute(sql, params, fetch=fetch_mode, commit=commit, many=many)


def query_one(sql, params=None, *, config=None, profile=None, **overrides):
    return execute_sql(sql, params, fetch='one', config=config, profile=profile, **overrides)


def query_all(sql, params=None, *, config=None, profile=None, **overrides):
    return execute_sql(sql, params, fetch='all', config=config, profile=profile, **overrides)


def execute_write(sql, params=None, *, many=False, config=None, profile=None, **overrides):
    return execute_sql(sql, params, commit=True, many=many, config=config, profile=profile, **overrides)
