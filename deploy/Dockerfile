# Dockerfile for the Retail Application
#
# This Dockerfile builds a minimal image containing the Python
# application code and its dependencies.  It uses a slim
# Python base image and relies solely on the Python standard library,
# so no external packages are installed.  The application runs the
# built‑in web server defined in app_web.py.  Logs and the SQLite
# database are persisted via volumes configured in docker-compose.yml.

FROM python:3.11-slim AS base

# Set work directory
WORKDIR /app

# Copy project files into the container
COPY . /app

# Environment settings to improve Python behavior in containers
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Expose the port used by app_web.py (default 8000)
EXPOSE 8000

# Default command starts the web application
CMD ["python", "-u", "src/app_web.py"]