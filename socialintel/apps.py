import os
import sys

from django.apps import AppConfig

# manage.py subcommands that import the app registry without actually serving
# traffic — migrate/collectstatic run on every deploy's build step, and
# check/shell/test are routine local commands. AppConfig.ready() fires for
# ALL of these, not just the running server, so without this guard every one
# of them silently kicks off a real (API-calling) ingestion cycle.
_NON_SERVING_COMMANDS = {
    'migrate', 'makemigrations', 'collectstatic', 'check', 'shell', 'shell_plus',
    'test', 'dbshell', 'createsuperuser', 'loaddata', 'dumpdata',
    'showmigrations', 'sqlmigrate', 'flush', 'startapp', 'startproject',
}


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
        if len(sys.argv) > 1 and sys.argv[1] in _NON_SERVING_COMMANDS:
            return
        from . import jobs
        jobs.start_scheduler_once()
