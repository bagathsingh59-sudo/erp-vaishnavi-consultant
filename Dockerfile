FROM python:3.11-slim

# Install postgresql-client (provides pg_dump and psql)
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
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
