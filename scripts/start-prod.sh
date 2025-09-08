#!/bin/bash

set -e  # Exit on any error

echo "🚀 Starting Betting MVP in Production Mode"

# Wait for database to be ready
echo "⏳ Waiting for database connection..."
timeout=60
elapsed=0

while ! pg_isready -h postgres -p 5432 -U betting -d betting_prod; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [ $elapsed -ge $timeout ]; then
        echo "❌ Database connection timeout after ${timeout} seconds"
        exit 1
    fi
done

echo "✅ Database is ready"

# Run database migrations
echo "📦 Running database migrations..."
python -m alembic upgrade head

if [ $? -ne 0 ]; then
    echo "❌ Database migrations failed"
    exit 1
fi

echo "✅ Database migrations completed"

# Start the application with production settings
echo "🌐 Starting FastAPI application..."

exec uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --access-log \
    --log-config logging.conf \
    --no-server-header