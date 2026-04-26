# 🛡️ DroneSec — Drone-Based Security Monitoring System

A premium full-stack Django SaaS application for real-time drone surveillance with face recognition, object detection, live monitoring and smart alerts.

---

## ⚡ Quick Start

```bash
# 1. Clone / extract the project
cd dronesec

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Apply migrations
python manage.py migrate

# 5. Seed demo data (admin + drones + alerts)
python manage.py seed

# 6. Run the server
python manage.py runserver
```

Open **http://localhost:8000** in your browser.

### One-Command Local Start (MySQL + Django)

From project root (PowerShell):

```powershell
.\start-dev.ps1
```

What it does:
- Starts MySQL automatically if port `3306` is not listening
- Runs `python manage.py migrate`
- Starts Django on `127.0.0.1:8000`

Optional flags:

```powershell
.\start-dev.ps1 -NoRunserver      # only start/check MySQL + run migrations
.\start-dev.ps1 -SkipMigrate      # start MySQL + runserver without migrate
.\start-dev.ps1 -Port 8001        # use a different Django port
```

---

## 🔐 Demo Credentials

| Role  | Username | Password     | Status   |
|-------|----------|--------------|----------|
| Admin | `admin`  | from `SEED_ADMIN_PASSWORD` | Approved |
| Agent | `agent1` | from `SEED_AGENT_PASSWORD` | Approved |
| Agent | `agent2` | from `SEED_AGENT_PASSWORD` | Approved |
| Agent | `agent3` | from `SEED_AGENT_PASSWORD` | Pending  |

---

## 📁 Project Structure

```
dronesec/
├── dronesec/          # Core settings & URLs
├── users/             # Custom user model, auth, roles
├── dashboard/         # KPI cards, fleet overview, map
├── drones/            # Drone management & telemetry API
├── monitoring/        # Live stream (simulated), bounding boxes
├── alerts/            # Real-time alerts, severity system
├── reports/           # Chart.js analytics
├── settings_app/      # Profile & password management
├── templates/         # All HTML templates
├── static/
│   ├── css/main.css   # Full dark SaaS stylesheet
│   └── js/main.js     # Live polling, toasts, popups
├── manage.py
└── requirements.txt
```

---

## ✨ Features

- **Dark Mode UI** — glassmorphism, neon blue, animated components
- **Role System** — Admin / Agent with approval workflow
- **reCAPTCHA v2** — on login & register (configured via environment variables)
- **Google OAuth2** — "Continue with Google" button
- **Live Alerts** — real-time polling with popup notifications
- **Drone Telemetry** — simulated live battery, GPS, speed
- **Simulated Stream** — bounding box overlay, detection feed
- **Chart.js Reports** — alerts per day, severity donut, per-drone bar
- **Admin Approval** — agents must be approved before accessing the platform

---

## 🔧 Configuration

Recommended: create a local .env file in the project root and put your secrets there.

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

Set environment variables before running the server:

```powershell
# Django core
$env:DJANGO_SECRET_KEY = 'replace-with-a-strong-random-secret'
$env:DJANGO_DEBUG = 'true'
$env:DJANGO_ALLOWED_HOSTS = '127.0.0.1,localhost'

# reCAPTCHA
$env:RECAPTCHA_PUBLIC_KEY = 'your-site-key'
$env:RECAPTCHA_PRIVATE_KEY = 'your-secret-key'

# Google OAuth
$env:GOOGLE_CLIENT_ID = 'your-client-id.apps.googleusercontent.com'
$env:GOOGLE_CLIENT_SECRET = 'your-client-secret'

# SMTP (required for real forgot-password emails)
$env:EMAIL_HOST = 'smtp.gmail.com'
$env:EMAIL_PORT = '587'
$env:EMAIL_HOST_USER = 'your-email@gmail.com'
$env:EMAIL_HOST_PASSWORD = 'your-app-password'
$env:EMAIL_USE_TLS = 'true'
$env:DEFAULT_FROM_EMAIL = 'DroneSec <your-email@gmail.com>'
$env:CONTACT_RECEIVER_EMAIL = 'security@your-domain.com'

# Seed credentials (required for python manage.py seed)
$env:SEED_ADMIN_PASSWORD = 'your-admin-password'
$env:SEED_AGENT_PASSWORD = 'your-agent-password'

# Request Access verification
$env:PHONE_VALIDATION_API_KEY = 'your-abstractapi-phone-key'
$env:PHONE_VALIDATION_TIMEOUT_SECONDS = '8'

# AI Assistant (LLM mode)
$env:AI_ASSISTANT_ENABLED = 'true'
$env:AI_ASSISTANT_API_KEY = 'your-provider-api-key'
$env:AI_ASSISTANT_BASE_URL = 'https://api.openai.com/v1'
$env:AI_ASSISTANT_MODEL = 'gpt-4o-mini'
```

Notes:
- If SMTP variables are not set, DroneSec uses console email backend (reset emails print in terminal).
- Request Access now uses email verification codes and country-based phone verification.
- Real phone existence verification requires `PHONE_VALIDATION_API_KEY`.
- For Gmail, use an App Password (not your regular account password).
- LLM mode uses OpenAI-compatible API format and also accepts OPENAI_API_KEY / OPENAI_BASE_URL names.

### MySQL Setup

DroneSec now supports MySQL using environment variables.

Add these values to your local `.env`:

```env
DB_ENGINE=django.db.backends.mysql
DB_NAME=dronesec_db
DB_USER=dronesec_user
DB_PASSWORD=change_me
DB_HOST=127.0.0.1
DB_PORT=3306
```

Create the database and user (run in MySQL shell):

```sql
CREATE DATABASE dronesec_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'dronesec_user'@'localhost' IDENTIFIED BY 'change_me';
GRANT ALL PRIVILEGES ON dronesec_db.* TO 'dronesec_user'@'localhost';
FLUSH PRIVILEGES;
```

Install dependencies and run migrations:

```bash
pip install -r requirements.txt
python manage.py migrate
```

If you already have data in SQLite, export/import data first (e.g. `dumpdata`/`loaddata`) before switching production traffic.

### Free Local AI Mode (No Paid API)

You can run the assistant with a free local model using Ollama:

```powershell
# 1) Install Ollama from https://ollama.com

# 2) Pull a lightweight model
ollama pull llama3.2:3b

# 3) In .env set:
AI_ASSISTANT_ENABLED=true
AI_ASSISTANT_API_KEY=
AI_ASSISTANT_BASE_URL=http://127.0.0.1:11434/v1
AI_ASSISTANT_MODEL=llama3.2:3b

# 4) Keep Ollama running, then start Django
python manage.py runserver
```

This mode is slower than cloud APIs but avoids paid usage.

### Groq Cloud Mode (OpenAI-compatible)

If you prefer Groq APIs:

```powershell
# In .env set:
AI_ASSISTANT_ENABLED=true
AI_ASSISTANT_API_KEY=your_groq_api_key
AI_ASSISTANT_BASE_URL=https://api.groq.com/openai/v1
AI_ASSISTANT_MODEL=llama-3.1-8b-instant

# Then restart Django
python manage.py runserver
```

Groq keys usually start with `gsk_`.

---

## 🎓 PFE — Institut Supérieur d'Informatique de Mahdia (ISIMA)

Built as a demonstration of a real-world IoT Security SaaS platform.
