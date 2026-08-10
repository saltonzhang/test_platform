import os
import sys
import threading
import time

from django.db import close_old_connections
from django.utils import timezone

from .models import MonitorTask
from .services import execute_monitor_task, sync_monitor_next_run_time

_START_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_STARTED = False
_STOP_EVENT = threading.Event()
_RUNNING_TASK_IDS = set()


def should_start_local_monitor_scheduler():
    if os.environ.get('DISABLE_LOCAL_MONITOR_SCHEDULER') == '1':
        return False

    command = sys.argv[1] if len(sys.argv) > 1 else ''
    if command in {'makemigrations', 'migrate', 'collectstatic', 'shell', 'dbshell', 'test', 'check'}:
        return False

    if command == 'runserver':
        return os.environ.get('RUN_MAIN') == 'true'

    return True


def _acquire_running_lock(task_id):
    with _STATE_LOCK:
        if task_id in _RUNNING_TASK_IDS:
            return False
        _RUNNING_TASK_IDS.add(task_id)
        return True


def _release_running_lock(task_id):
    with _STATE_LOCK:
        _RUNNING_TASK_IDS.discard(task_id)


def _run_task(task_id):
    if not _acquire_running_lock(task_id):
        return
    try:
        task = MonitorTask.objects.select_related('environment').prefetch_related('api_configs').get(pk=task_id, enabled=True)
        execute_monitor_task(task, task.created_by, '')
    except Exception:
        pass
    finally:
        _release_running_lock(task_id)


def _ensure_next_run_times():
    for task in MonitorTask.objects.filter(enabled=True, next_run_time=None):
        try:
            sync_monitor_next_run_time(task)
        except Exception:
            continue


def _scheduler_loop():
    while not _STOP_EVENT.wait(5):
        close_old_connections()
        try:
            _ensure_next_run_times()
            due_tasks = MonitorTask.objects.filter(enabled=True, next_run_time__lte=timezone.now()).only('id')[:20]
            for task in due_tasks:
                threading.Thread(target=_run_task, args=[task.id], daemon=True).start()
        except Exception:
            continue


def start_local_monitor_scheduler():
    global _STARTED

    if not should_start_local_monitor_scheduler():
        return False

    with _START_LOCK:
        if _STARTED:
            return False
        _STOP_EVENT.clear()
        threading.Thread(target=_scheduler_loop, daemon=True).start()
        _STARTED = True
        return True


def shutdown_local_monitor_scheduler():
    global _STARTED

    with _START_LOCK:
        if not _STARTED:
            return False
        _STOP_EVENT.set()
        _STARTED = False
        return True
