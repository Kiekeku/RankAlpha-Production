#!/bin/bash

# Test script for Docker deployment
set -e

echo "🚀 Testing RankAlpha Docker Deployment"
echo "======================================="

# Navigate to compose directory
cd "$(dirname "$0")/../compose"

echo "📦 Building and starting services..."
docker compose down -v 2>/dev/null || true
docker compose up --build -d

echo "⏳ Waiting for services to be healthy..."
sleep 30

# Check database
echo "🗄️  Checking database..."
docker compose exec database pg_isready -U rankalpha -d rankalpha || {
    echo "❌ Database check failed"
    docker compose logs database
    exit 1
}

# Check API
echo "🔌 Checking API..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -f http://localhost:6080/ > /dev/null 2>&1; then
        echo "✅ API is responding"
        break
    fi
    echo "⏳ API not ready yet (attempt $((attempt + 1))/$max_attempts)..."
    sleep 10
    attempt=$((attempt + 1))
done

if [ $attempt -eq $max_attempts ]; then
    echo "❌ API failed to start"
    docker compose logs api
    exit 1
fi

# Test API endpoints
echo "🧪 Testing API endpoints..."
curl -f http://localhost:6080/openapi.json > /dev/null || {
    echo "❌ OpenAPI endpoint failed"
    exit 1
}

echo "✅ OpenAPI endpoint working"

# Check if we can get grades (might fail if no data, but endpoint should respond)
curl -f "http://localhost:6080/api/v1/grading/grades?limit=1" > /dev/null 2>&1 && {
    echo "✅ Grading endpoint working"
} || {
    echo "⚠️  Grading endpoint not ready (expected if no data)"
}

# Check frontend
echo "🌐 Checking frontend..."
max_attempts=20
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -f http://localhost:3000/ > /dev/null 2>&1; then
        echo "✅ Frontend is responding"
        break
    fi
    echo "⏳ Frontend not ready yet (attempt $((attempt + 1))/$max_attempts)..."
    sleep 10
    attempt=$((attempt + 1))
done

if [ $attempt -eq $max_attempts ]; then
    echo "❌ Frontend failed to start"
    docker compose logs frontend
    exit 1
fi

echo "🎉 All services are running successfully!"
echo ""
echo "📱 Access the application:"
echo "   Frontend: http://localhost:3000"
echo "   API:      http://localhost:6080"
echo "   API Docs: http://localhost:6080/"
echo ""
echo "🔧 To stop services:"
echo "   docker compose down"
echo ""
echo "📊 To view logs:"
echo "   docker compose logs [service-name]"