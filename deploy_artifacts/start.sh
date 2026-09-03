#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
exec ./.venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 2 --timeout 60 --access-logfile - --error-logfile - webapp.app:app
