#!/bin/bash
set -e  # exit immediately if a command exits with a non-zero status

# run migrations to ensure the DB schema is up to date
# alembic is used for migrations
echo "Running database migrations..."
flask db upgrade

# start the application - referenced in Dockerfile
echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:8080 main:app