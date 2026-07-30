from django.apps import AppConfig


class PlatformApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_api'
    verbose_name = 'AIBET 平台'

    def ready(self):
        from .local_monitor_scheduler import start_local_monitor_scheduler

        start_local_monitor_scheduler()
