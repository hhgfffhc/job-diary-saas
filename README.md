# 📋 Job Diary Pro v7 SaaS - Production Ready

A complete **multi-tenant SaaS platform** for small businesses to manage jobs, invoices, and clients. Features Celery background tasks, PostgreSQL, Redis, Stripe integration, and professional UI.

## 🚀 Features

✅ **Multi-Tenant Architecture** - Each business gets isolated data  
✅ **User Authentication** - Signup, login, password management  
✅ **Job Management** - Schedule jobs, track customers, send reminders  
✅ **Invoice System** - Create, track, and generate PDF invoices  
✅ **Client Management** - Maintain client database with contact info  
✅ **Celery Background Tasks** - Async email, reminders, PDF generation  
✅ **Stripe Integration** - Accept online payments  
✅ **PostgreSQL Database** - Reliable, scalable data storage  
✅ **Redis Caching** - Fast sessions, task queuing  
✅ **Professional UI** - Modern, responsive design  
✅ **Email Notifications** - 24h job reminders, invoice alerts  
✅ **PDF Generation** - Professional invoice PDFs  
✅ **Docker Support** - Easy deployment with Docker Compose  

---

## 📋 Prerequisites

- **Docker & Docker Compose** (Recommended)
- **Python 3.11+** (if running without Docker)
- **PostgreSQL 13+** (if running without Docker)
- **Redis 6+** (if running without Docker)
- **Stripe Account** (for payments)
- **Gmail/SMTP Account** (for emails)

---

## ⚡ Quick Start (Docker - Recommended)

### 1. Clone/Setup Project
```bash
# Create project directory
mkdir job-diary-saas
cd job-diary-saas

# Copy all files into this directory
# - app.py
# - config.py
# - tasks.py
# - docker-compose.yml
# - Dockerfile
# - requirements.txt
# - .env.example
```

### 2. Configure Environment
```bash
# Copy example env file
cp .env.example .env

# Edit .env with your settings
nano .env
```

Update these critical values:
- `SECRET_KEY` - Generate a secure key: `python -c "import secrets; print(secrets.token_hex(32))"`
- `DB_PASSWORD` - Strong database password
- `REDIS_PASSWORD` - Strong Redis password
- `MAIL_USERNAME` / `MAIL_PASSWORD` - Gmail SMTP credentials
- `STRIPE_PUBLIC_KEY` / `STRIPE_SECRET_KEY` - From Stripe dashboard

### 3. Start Services
```bash
# Build and start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f web
```

### 4. Initialize Database
```bash
# Create database tables
docker-compose exec web flask db upgrade

# Or manually:
docker-compose exec web python -c "from app import db; db.create_all()"
```

### 5. Access Application
- **Web App**: http://localhost:5000
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379
- **Default Login**: Create account via signup

---

## 🏃 Local Development Setup (Without Docker)

### 1. Install Dependencies
```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Setup PostgreSQL
```bash
# Create database
createdb jobdiary_saas
psql jobdiary_saas < schema.sql  # If schema provided

# Or create user manually
createuser jobdiary -P  # Set password when prompted
```

### 3. Setup Redis
```bash
# Start Redis (macOS)
brew services start redis

# Or Linux
sudo systemctl start redis-server

# Or Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### 4. Configure Environment
```bash
cp .env.example .env
nano .env  # Update with your values
```

### 5. Run Application
```bash
# Terminal 1: Flask Web Server
python app.py

# Terminal 2: Celery Worker
celery -A app.celery worker -l info

# Terminal 3: Celery Beat Scheduler
celery -A app.celery beat -l info
```

Access at: http://localhost:5000

---

## 🔑 Environment Variables Explained

```
FLASK_ENV              # development or production
SECRET_KEY             # Random secret for session encryption
DATABASE_URL           # PostgreSQL connection string
CELERY_BROKER_URL      # Redis connection for tasks
MAIL_USERNAME          # Gmail address for sending emails
MAIL_PASSWORD          # Gmail app-specific password
STRIPE_PUBLIC_KEY      # Stripe publishable key
STRIPE_SECRET_KEY      # Stripe secret key
```

---

## 📊 Database Schema

**Tables:**
- `users` - User accounts
- `tenant` - Business/company accounts
- `clients` - Customer contacts
- `jobs` - Scheduled work
- `invoices` - Invoice records
- `invoice_items` - Invoice line items
- `payments` - Payment records

**Relationships:**
- Each User belongs to one Tenant
- Each Tenant has many Users, Clients, Jobs, Invoices
- Each Invoice belongs to one Client
- Each Invoice has many Items and Payments

---

## 🔄 Celery Tasks

Background tasks that run asynchronously:

```python
send_email_task()              # Send emails without blocking requests
check_24h_reminders_task()     # Send job reminders 24h before
check_overdue_invoices_task()  # Mark overdue invoices
generate_pdf_task()            # Generate invoice PDFs
```

**Check Celery Status:**
```bash
# List active tasks
celery -A app.celery inspect active

# Check workers
celery -A app.celery inspect registered

# Monitor in real-time
celery -A app.celery events
```

---

## 💳 Stripe Integration

### Setup Payment Processing:

1. **Get Stripe Keys:**
   - Go to https://dashboard.stripe.com
   - Copy Public Key (pk_test_...)
   - Copy Secret Key (sk_test_...)

2. **Add to .env:**
   ```
   STRIPE_PUBLIC_KEY=pk_test_xxxxx
   STRIPE_SECRET_KEY=sk_test_xxxxx
   STRIPE_WEBHOOK_SECRET=whsec_xxxxx
   ```

3. **Create Subscription Plans:**
   - Free: $0/month (5 invoices)
   - Pro: $29/month (unlimited)
   - Enterprise: Custom pricing

---

## 📧 Email Configuration

### Gmail Setup:

1. **Enable 2-Factor Authentication** on Gmail
2. **Create App Password:**
   - Go to https://myaccount.google.com/apppasswords
   - Select "Mail" and "Windows Computer"
   - Copy the generated password

3. **Add to .env:**
   ```
   MAIL_SERVER=smtp.gmail.com
   MAIL_PORT=587
   MAIL_USERNAME=your-email@gmail.com
   MAIL_PASSWORD=xxxx xxxx xxxx xxxx
   ```

### Test Email:
```python
from tasks import send_email
send_email('test@example.com', 'Test', 'Hello world!')
```

---

## 🚀 Deployment to Production

### AWS EC2 Deployment:

```bash
# 1. Create EC2 instance (Ubuntu 22.04)
# 2. SSH into instance
ssh -i key.pem ubuntu@your-ip

# 3. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# 4. Clone repository
git clone your-repo-url
cd job-diary-saas

# 5. Setup environment
cp .env.example .env
nano .env  # Update with production values

# 6. Start services
docker-compose -f docker-compose.yml up -d

# 7. Setup SSL (Let's Encrypt)
sudo apt-get install certbot python3-certbot-nginx
sudo certbot certonly --standalone -d your-domain.com
```

### DigitalOcean App Platform:

1. Push code to GitHub
2. Connect DigitalOcean App Platform
3. Configure:
   - Web Service: `gunicorn -w 4 -b 0.0.0.0:5000 app:app`
   - Worker: `celery -A app.celery worker -l info`
   - Database: PostgreSQL
4. Set environment variables from .env
5. Deploy!

### Environment Checklist:
```
[ ] SECRET_KEY changed
[ ] DATABASE_URL set to production DB
[ ] CELERY_BROKER_URL set to production Redis
[ ] MAIL_USERNAME/PASSWORD configured
[ ] STRIPE keys set (production keys)
[ ] HTTPS enabled
[ ] DEBUG set to False
[ ] SESSION_COOKIE_SECURE set to True
```

---

## 🧪 Testing

```bash
# Run tests
pytest tests/

# Test email sending
python -c "from tasks import send_email; send_email('your@email.com', 'Test', 'Works!')"

# Test database connection
python -c "from app import db; print(db.engine.execute('SELECT 1'))"

# Test Redis
redis-cli ping
```

---

## 📈 Monitoring & Logs

```bash
# Docker logs
docker-compose logs -f web          # Flask app
docker-compose logs -f celery_worker # Celery
docker-compose logs -f db          # Database

# Check database
docker-compose exec db psql -U jobdiary -d jobdiary_saas

# Check Redis
docker-compose exec redis redis-cli
> PING
> KEYS *
```

---

## 🔐 Security Best Practices

✅ **Change default passwords** in .env  
✅ **Enable HTTPS** in production  
✅ **Use strong SECRET_KEY** (32+ characters)  
✅ **Set SESSION_COOKIE_SECURE=True** in production  
✅ **Use environment variables** for secrets (never commit .env)  
✅ **Enable database backups** (automated)  
✅ **Monitor Celery** for failed tasks  
✅ **Rate limit** API endpoints  
✅ **Keep dependencies updated**  

---

## 🛠️ Troubleshooting

### Database Connection Error
```bash
# Check PostgreSQL is running
docker-compose ps db

# Verify credentials in .env
# Restart database
docker-compose restart db
```

### Celery Tasks Not Running
```bash
# Check Redis is running
docker-compose ps redis

# Check Celery worker logs
docker-compose logs celery_worker

# Verify CELERY_BROKER_URL in .env
```

### Email Not Sending
```bash
# Check Gmail credentials
# Verify app-specific password (not regular password)
# Check logs: docker-compose logs web | grep -i email

# Test manually:
python -c "from tasks import send_email; print(send_email('test@test.com', 'Test', 'Body'))"
```

### Out of Memory
```bash
# Increase container limits in docker-compose.yml
deploy:
  resources:
    limits:
      memory: 2G
```

---

## 📚 Additional Resources

- **Flask Documentation**: https://flask.palletsprojects.com/
- **SQLAlchemy ORM**: https://docs.sqlalchemy.org/
- **Celery Tasks**: https://docs.celeryproject.io/
- **Stripe API**: https://stripe.com/docs/api
- **Docker Guide**: https://docs.docker.com/

---

## 📄 API Reference

### Authentication
```
POST /signup              - Create new account
POST /login              - Login user
GET  /logout             - Logout user
```

### Jobs
```
POST   /jobs             - Create job
GET    /api/jobs         - Get all jobs (JSON)
DELETE /jobs/<id>/delete - Delete job
```

### Invoices
```
GET    /invoices              - List all invoices
POST   /invoices/create       - Create invoice
GET    /invoices/<id>         - View invoice
GET    /invoices/<id>/pdf     - Download PDF
DELETE /invoices/<id>/delete  - Delete invoice
```

### Clients
```
GET  /clients            - List clients
POST /clients            - Add client
DELETE /clients/<id>/delete - Delete client
```

---

## 📝 License

Proprietary - Job Diary Pro SaaS

---

## 🤝 Support

For issues, questions, or feature requests:
- Create an issue on GitHub
- Email: support@jobdiarypro.com
- Documentation: https://docs.jobdiarypro.com

---

**🚀 Ready to scale your business? Deploy Job Diary Pro SaaS today!**
