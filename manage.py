#!/usr/bin/env python
import os
import sys

def main():
    settings_module = 'telusko.deployment_settings' if 'RENDER_EXTERNAL_HOSTNAME' in os.environ else 'telusko.settings'
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Couldn't import Django.") from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
