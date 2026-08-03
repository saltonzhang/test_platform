"""Shared data-factory database access and local configuration."""

from contextlib import contextmanager
import os
from pathlib import Path

import pymysql
import pymysql.cursors


_LOCAL_ENV_PATH = Path(__file__).resolve().parents[2] / '.env'


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


_load_local_env()

# Values are read from backend/.env or the process environment.
DATA_FACTORY_DATABASE_CONFIG = {
    'host': os.getenv('DATA_FACTORY_DB_HOST'),
    'port': _get_int_env('DATA_FACTORY_DB_PORT'),
    'user': os.getenv('DATA_FACTORY_DB_USER'),
    'password': os.getenv('DATA_FACTORY_DB_PASSWORD'),
    'database': os.getenv('DATA_FACTORY_DB_NAME'),
    'charset': os.getenv('DATA_FACTORY_DB_CHARSET'),
    'cursorclass': pymysql.cursors.DictCursor,
    'connect_timeout': _get_int_env('DATA_FACTORY_DB_CONNECT_TIMEOUT'),
    'read_timeout': _get_int_env('DATA_FACTORY_DB_READ_TIMEOUT'),
    'write_timeout': _get_int_env('DATA_FACTORY_DB_WRITE_TIMEOUT'),
}

# Keep the shorter name used by existing callers.
DB_CONFIG = DATA_FACTORY_DATABASE_CONFIG


def _build_db_config(config=None, **overrides):
    db_config = dict(config or DB_CONFIG)
    db_config.update({key: value for key, value in overrides.items() if value is not None})
    missing = [
        key
        for key in ('host', 'port', 'user', 'password', 'database')
        if db_config.get(key) is None or (key != 'password' and db_config.get(key) == '')
    ]
    if missing:
        env_names = ', '.join(f'DATA_FACTORY_DB_{"NAME" if key == "database" else key.upper()}' for key in missing)
        raise RuntimeError(f'缺少数据工厂数据库配置，请在 backend/.env 中设置：{env_names}')
    return {key: value for key, value in db_config.items() if value is not None}


def get_db_connection(config=None, **overrides):
    return pymysql.connect(**_build_db_config(config, **overrides))


@contextmanager
def db_connection(config=None, **overrides):
    conn = get_db_connection(config=config, **overrides)
    try:
        yield conn
    finally:
        conn.close()


class DatabaseClient:
    """Small PyMySQL wrapper for one data-factory database session."""

    def __init__(self, config=None, **overrides):
        self.config = _build_db_config(config, **overrides)
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
    **overrides,
):
    fetch_mode = _resolve_fetch_mode(fetch, fetch_one, fetch_all)
    with DatabaseClient(config=config, **overrides) as db:
        return db.execute(sql, params, fetch=fetch_mode, commit=commit, many=many)


def query_one(sql, params=None, *, config=None, **overrides):
    return execute_sql(sql, params, fetch='one', config=config, **overrides)


def query_all(sql, params=None, *, config=None, **overrides):
    return execute_sql(sql, params, fetch='all', config=config, **overrides)


def execute_write(sql, params=None, *, many=False, config=None, **overrides):
    return execute_sql(sql, params, commit=True, many=many, config=config, **overrides)
