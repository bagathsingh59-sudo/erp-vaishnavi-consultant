FROM python:3.11-slim

# Install postgresql-client-18 to match Railway's PostgreSQL 18 server.
# Default apt only has pg_dump 17 (version mismatch error).
# We add the official PostgreSQL PGDG apt repo to get version 18.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source files
COPY . .

# Expose port (Railway injects $PORT at runtime)
EXPOSE 8080

# Same command as Procfile
CMD gunicorn --chdir backend run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
