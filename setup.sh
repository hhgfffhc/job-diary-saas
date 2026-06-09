#!/bin/bash

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════╗"
echo "║   📋 Job Diary Pro v7 - Setup Script      ║"
echo "║   Multi-Tenant SaaS Platform              ║"
echo "╚═══════════════════════════════════════════╝"
echo -e "${NC}"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed${NC}"
    echo "Please install Docker from https://docker.com"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose is not installed${NC}"
    echo "Please install Docker Compose"
    exit 1
fi

echo -e "${GREEN}✓ Docker and Docker Compose detected${NC}"

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file not found${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓ Created .env from template${NC}"
    echo -e "${YELLOW}📝 Please edit .env with your configuration${NC}"
    echo "Required settings:"
    echo "  - SECRET_KEY"
    echo "  - Database credentials"
    echo "  - Email settings (MAIL_USERNAME, MAIL_PASSWORD)"
    echo "  - Stripe keys (STRIPE_PUBLIC_KEY, STRIPE_SECRET_KEY)"
    exit 0
fi

echo -e "${GREEN}✓ .env file found${NC}"

# Generate SECRET_KEY if not set
if ! grep -q "SECRET_KEY=[^#]" .env; then
    echo -e "${YELLOW}⚠️  Generating SECRET_KEY...${NC}"
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
    sed -i.bak "s/SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" .env
    echo -e "${GREEN}✓ SECRET_KEY generated${NC}"
fi

# Build Docker images
echo -e "${BLUE}🏗️  Building Docker images...${NC}"
docker-compose build

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Docker build failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker images built successfully${NC}"

# Start services
echo -e "${BLUE}🚀 Starting services...${NC}"
docker-compose up -d

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to start services${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Services started${NC}"

# Wait for database to be ready
echo -e "${BLUE}⏳ Waiting for database to be ready...${NC}"
sleep 10

# Initialize database
echo -e "${BLUE}📊 Initializing database...${NC}"
docker-compose exec -T web python -c "from app import db; db.create_all()"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database initialized${NC}"
else
    echo -e "${YELLOW}⚠️  Database might already exist or there was an error${NC}"
fi

# Check services status
echo -e "${BLUE}📊 Checking service status...${NC}"
docker-compose ps

# Display information
echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════╗"
echo "║   ✅ Setup Complete!                       ║"
echo "╚═══════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${BLUE}🌐 Access your application:${NC}"
echo "   Web App:     http://localhost:5000"
echo "   PostgreSQL:  localhost:5432"
echo "   Redis:       localhost:6379"

echo -e "${BLUE}📝 Next steps:${NC}"
echo "   1. Create an account at http://localhost:5000/signup"
echo "   2. Configure your business settings"
echo "   3. Start managing jobs and invoices!"

echo -e "${BLUE}📊 Monitor services:${NC}"
echo "   View logs:      docker-compose logs -f"
echo "   Check status:   docker-compose ps"
echo "   Stop services:  docker-compose down"

echo -e "${BLUE}🧪 Testing:${NC}"
echo "   Test database:  docker-compose exec db psql -U jobdiary -d jobdiary_saas -c 'SELECT version();'"
echo "   Test Redis:     docker-compose exec redis redis-cli ping"
echo "   Check Celery:   docker-compose logs celery_worker"

echo -e "${YELLOW}📚 Documentation:${NC}"
echo "   Full guide:  cat README.md"
echo "   Environment: cat .env.example"

echo ""
echo -e "${GREEN}🎉 Happy coding!${NC}"
