#!/bin/bash
# Инициализация Superset при первом запуске и старт веб-сервера
set -e
superset db upgrade
superset fab create-admin --username "${SUPERSET_ADMIN_USER:-admin}" --firstname SPPR --lastname Admin \
  --email admin@sppr.local --password "${SUPERSET_ADMIN_PASSWORD}" || true
superset init
exec gunicorn --bind 0.0.0.0:8088 --workers 2 --timeout 120 --limit-request-line 0 "superset.app:create_app()"
