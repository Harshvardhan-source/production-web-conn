import os

from django.apps import AppConfig


class SocialintelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'socialintel'
    verbose_name = 'Social Media Intelligence'

    def ready(self):
        # Django's dev-server autoreloader imports every app twice (once in the
        # watcher process, once in the reloaded child) — only start the
        # background scheduler in the real child process to avoid running the
        # ingestion cycle twice under `manage.py runserver`.
        if os.environ.get('RUN_MAIN') == 'false':
            return
        from . import jobs
        jobs.start_scheduler_once()
