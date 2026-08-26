#!/bin/sh
set -eu

# Apply the checked-in schema before accepting traffic. Neither the command nor
# Alembic's logging renders environment values.
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000