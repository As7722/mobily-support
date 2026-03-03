

Tech Support Elite System — Complete Cursor-Ready Specification v4.1
Production-Ready Master Document | Mobily Internal Support Portal
text
Project    : Mobily Technical Support Request Management System
Version    : v4.1 Final (Cursor-Optimized, Bilingual)
Date       : February 27, 2026
Status     : Production-Ready Specification
Stack      : FastAPI + HTMX + PostgreSQL + Redis + Celery
Languages  : Arabic (RTL) + English (LTR) — Full Bilingual System
Developer  : Cursor AI (Full-Stack)
________________________________________
📑 Table of Contents
text
Section 1  — Project Overview & Goals
Section 2  — Tech Stack & Dependencies
Section 3  — Bilingual System (i18n/l10n) — CRITICAL
Section 4  — Roles & Permissions (RBAC 2.0 Dynamic)
Section 5  — Full Page Structure (22 Pages)
Section 6  — Ticket & Queue System (Multi-Queue 3-Level)
Section 7  — Database Schema (50 Tables — Complete)
Section 8  — Security & Protection (Enterprise-Grade)
Section 9  — No-Code Features 2.0
Section 10 — Dynamic Theme System
Section 11 — Integration Hub (Email / WhatsApp / SMS)
Section 12 — Gamification & Rewards
Section 13 — UX, PWA & Mobile Experience
Section 14 — Analytics & Reports (100+ KPI)
Section 15 — Project File Structure
Section 16 — Error Handling & Monitoring
Section 17 — Deployment (Docker + Nginx + CI/CD)
Section 18 — 5-Phase Implementation Plan (Cursor Instructions)
Section 19 — Costs & Maintenance
________________________________________
═══════════════════════════════════════════════════════════
Section 1 — Project Overview & Goals
═══════════════════════════════════════════════════════════
1.1 Problem Statement
Mobily branch employees currently submit technical support requests via scattered emails with no tracking, no SLA enforcement, and no performance measurement. This system solves all of that.
1.2 Core Objectives
Problem	Solution
Scattered email-based ticket tracking	Centralized portal + unified inbox
No SLA enforcement	Automated SLA Engine with real-time alerts
No objective performance metrics	100+ KPIs per agent, team, and branch
Disconnected communication channels	Portal + Email + WhatsApp + Call Log unified
Lost/forgotten tickets	Zero lost tickets — every request tracked to closure
No branch-side transparency	Public timeline + live Status Page
1.3 System Scope
Role	Pages	Core Permissions
Public (branch employee)	4 pages	Submit ticket + Track + CSAT + Status
Employee (support agent)	3 pages	Resolve tickets + Call Log + KB
Supervisor	3 pages	Team mgmt + Workload + Queue + Reports
Manager	4 pages	Analytics + Config + All Queues + Audit
Admin (sys admin)	1 page (9 Tabs)	Full system control
________________________________________
═══════════════════════════════════════════════════════════
Section 2 — Tech Stack & Full Dependencies
═══════════════════════════════════════════════════════════
2.1 Technology Stack
text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BACKEND
  Runtime     : Python 3.12
  Framework   : FastAPI 0.115+   (Async, high-performance)
  ORM         : SQLAlchemy 2.0   (Async sessions)
  Migrations  : Alembic          (Version-controlled schema)
  Validation  : Pydantic v2      (Request/response models)
  Task Queue  : Celery 5.4       (Background tasks)
  Scheduler   : Celery Beat      (Periodic tasks: IMAP, SLA, Reports)
  ASGI Server : Uvicorn          (Production + Gunicorn process mgr)

DATABASE
  Primary DB  : PostgreSQL 16.4
  Extensions  : pg_trgm          (Fuzzy search Arabic + English)
                unaccent         (Accent-insensitive Arabic search)
                uuid-ossp        (UUID primary keys)
  Features    : Table Partitioning (tickets by created_at year)
                Soft Delete (deleted_at timestamp pattern)
                Optimistic Locking (version column)
                Row-Level Security (RLS for multi-tenant isolation)

CACHE & SESSIONS
  Engine      : Redis 7.2
  Usage       :
    - User sessions         TTL: 24 hours
    - Permission cache      TTL: 15 minutes
    - Dashboard KPI cache   TTL: 5 minutes
    - Rate limiting         TTL: 1 minute sliding window
    - Celery task backend

FRONTEND
  Interactivity : HTMX 2.0       (Server-driven UI, no SPA)
  Reactivity    : Alpine.js 3.14 (Client-side micro-interactions)
  CSS Framework : Tailwind CSS 4 (Utility-first, RTL support built-in)
  Charts        : ApexCharts 3.5 (RTL-aware, Arabic number formatting)
  Templates     : Jinja2 3.1.4   (Server-side rendering)
  Real-time     : Server-Sent Events (SSE) — live dashboard updates
  Icons         : Heroicons 2.0 + Custom SVG
  Fonts         : Tajawal (Arabic) + Inter (English)

AUTHENTICATION
  Protocol    : OAuth2 + JWT RS256 (asymmetric key pair)
  Password    : Argon2id via passlib (memory-hard hashing)
  2FA         : TOTP via pyotp (v1: optional, v2: required for admin)
  Biometric   : Web Authentication API (PWA — fingerprint/FaceID)
  Sessions    : Secure HttpOnly cookies + Redis session store

EMAIL
  Outbound    : aiosmtplib      (async SMTP — replies + notifications)
  Inbound     : python-imap     (IMAP polling → auto ticket creation)
  Templates   : Jinja2          (bilingual HTML email templates)

MESSAGING
  SMS         : Twilio 9.3+     (SLA alerts, OTP)
  WhatsApp    : Twilio WhatsApp API + Webhook Bot

FILE STORAGE
  Primary     : S3-compatible (Backblaze B2 or self-hosted MinIO)
  Encryption  : AES-256 for all stored files
  Virus Scan  : ClamAV integration (scan before storage)
  CDN         : CloudFlare (optional, for asset performance)

DEPLOYMENT
  Container   : Docker 27 + docker-compose
  Proxy       : Nginx 1.26 (reverse proxy + static files + SSL)
  SSL         : Let's Encrypt via Certbot (auto-renewal)
  CI/CD       : GitHub Actions
  Backup      : Automated daily PostgreSQL dump → S3

TESTING
  Framework   : Pytest 8.3 + pytest-asyncio
  Coverage    : 95%+ target
  Load Test   : Locust 2.20
  API Test    : httpx (async test client)

MONITORING
  Errors      : Sentry (APM + error tracking + performance)
  Metrics     : Prometheus + Grafana (optional v2)
  Logs        : Structured JSON logging + Loki (optional v2)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2.2 requirements.txt (Complete)
text
# Core
fastapi==0.115.0
uvicorn[standard]==0.30.1
gunicorn==22.0.0
python-multipart==0.0.9

# Database
sqlalchemy[asyncio]==2.0.31
alembic==1.13.2
asyncpg==0.29.0
psycopg2-binary==2.9.9

# Validation
pydantic[email]==2.8.2
pydantic-settings==2.4.0

# Auth
python-jose[cryptography]==3.3.0
passlib[argon2]==1.7.4
pyotp==2.9.0

# Cache
redis[hiredis]==5.0.8
celery[redis]==5.4.0
celery-beat==0.0.1  # use django-celery-beat pattern

# Templates
jinja2==3.1.4
aiofiles==24.1.0

# Email
aiosmtplib==3.0.1
imapclient==3.0.1

# SMS / WhatsApp
twilio==9.3.0

# Storage
boto3==1.35.0  # S3-compatible

# Security
python-magic==0.4.27  # file type detection
clamd==1.0.2  # ClamAV

# Utils
httpx==0.27.0
python-slugify==8.0.4
babel==2.15.0  # i18n number/date formatting
pyarabic==0.6.15  # Arabic text utilities
arrow==1.3.0  # timezone-aware datetimes

# Monitoring
sentry-sdk[fastapi]==2.13.0

# Testing
pytest==8.3.2
pytest-asyncio==0.23.8
pytest-cov==5.0.0
locust==2.20.1
________________________________________
═══════════════════════════════════════════════════════════
Section 3 — Bilingual System (i18n/l10n) — CRITICAL
═══════════════════════════════════════════════════════════
Cursor Instruction: This section is the most architecturally impactful part of the project. Every component, template, database field, and API response must respect these rules. Read carefully before generating any code.
3.1 Language Architecture
The system supports two languages simultaneously:
•	Arabic (ar) — RTL layout, default language
•	English (en) — LTR layout
The user can switch language anywhere in the system via a toggle button in the navbar. The language preference is:
1.	Stored per-user in the users.preferred_language database column
2.	Also stored in a lang cookie for unauthenticated pages (public portal)
3.	Reflected immediately via HTMX page partial reload — no full page refresh needed
3.2 Translation File Structure
text
app/
└── i18n/
    ├── ar.json          ← Arabic translations (default)
    ├── en.json          ← English translations
    └── __init__.py      ← Translation loader

# Structure of translation files:
# ar.json
{
  "nav": {
    "dashboard": "لوحة التحكم",
    "tickets": "التذاكر",
    "logout": "تسجيل الخروج"
  },
  "ticket": {
    "status": {
      "new": "جديدة",
      "open": "قيد المعالجة",
      "pending_customer": "انتظار رد العميل",
      "pending_3rd": "انتظار طرف ثالث",
      "on_hold": "موقوفة مؤقتاً",
      "resolved": "محلولة",
      "closed": "مغلقة",
      "archived": "مؤرشفة"
    },
    "priority": {
      "critical": "حرجة",
      "high": "عالية",
      "medium": "متوسطة",
      "low": "منخفضة"
    },
    "actions": {
      "claim": "المطالبة بالتذكرة",
      "resolve": "حل التذكرة",
      "close": "إغلاق نهائي",
      "escalate": "تصعيد",
      "transfer": "تحويل",
      "merge": "دمج",
      "split": "تقسيم"
    }
  },
  ...
}

# en.json (parallel structure)
{
  "nav": {
    "dashboard": "Dashboard",
    "tickets": "Tickets",
    "logout": "Sign Out"
  },
  "ticket": {
    "status": {
      "new": "New",
      "open": "In Progress",
      "pending_customer": "Waiting for Customer",
      ...
    }
  },
  ...
}
3.3 Translation Engine (Python)
python
# app/i18n/__init__.py

import json
from pathlib import Path
from functools import lru_cache
from typing import Optional

SUPPORTED_LANGUAGES = ["ar", "en"]
DEFAULT_LANGUAGE = "ar"

@lru_cache(maxsize=2)
def load_translations(lang: str) -> dict:
    path = Path(__file__).parent / f"{lang}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """
    Translate a dot-notation key.
    Example: t("ticket.status.open", lang="ar") → "قيد المعالجة"
    Example: t("ticket.status.open", lang="en") → "In Progress"
    """
    translations = load_translations(lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE)
    keys = key.split(".")
    value = translations
    for k in keys:
        value = value.get(k, key)  # fallback to key itself if missing
        if not isinstance(value, dict):
            break
    if isinstance(value, str) and kwargs:
        return value.format(**kwargs)
    return value if isinstance(value, str) else key
3.4 Language Detection & Middleware
python
# app/middleware/language.py

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class LanguageMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Priority order:
        # 1. Authenticated user's preferred_language from DB (injected by auth)
        # 2. "lang" cookie
        # 3. Accept-Language header
        # 4. Default: "ar"
        
        lang = None
        
        # From auth context (set by JWT middleware)
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "preferred_language"):
            lang = user.preferred_language
        
        # From cookie
        if not lang:
            lang = request.cookies.get("lang")
        
        # From Accept-Language header
        if not lang:
            accept_lang = request.headers.get("Accept-Language", "")
            if "ar" in accept_lang:
                lang = "ar"
            elif "en" in accept_lang:
                lang = "en"
        
        # Fallback
        request.state.lang = lang if lang in ["ar", "en"] else "ar"
        request.state.dir = "rtl" if request.state.lang == "ar" else "ltr"
        
        response = await call_next(request)
        return response
3.5 Jinja2 Template Integration
python
# app/core/templates.py

from jinja2 import Environment, FileSystemLoader
from app.i18n import t as translate_func

def create_template_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader("app/templates"),
        autoescape=True,
        extensions=["jinja2.ext.i18n"]
    )
    
    # Make translation function available in all templates
    env.globals["t"] = translate_func
    env.globals["SUPPORTED_LANGUAGES"] = ["ar", "en"]
    
    return env

templates = create_template_env()
In every Jinja2 template:
xml
<!-- app/templates/base.html -->
<!DOCTYPE html>
<html lang="{{ lang }}" dir="{{ dir }}">
<head>
    <meta charset="UTF-8">
    <title>{{ t("app.title", lang=lang) }}</title>
    
    <!-- Tailwind with RTL plugin -->
    <link rel="stylesheet" href="/static/css/tailwind.css">
    
    <!-- Fonts: load both, switch via CSS variable -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;700&family=Inter:wght@300;400;500;700&display=swap" rel="stylesheet">
    
    <style>
        :root {
            --font-primary: {% if lang == "ar" %}'Tajawal', sans-serif{% else %}'Inter', sans-serif{% endif %};
        }
        body { font-family: var(--font-primary); }
    </style>
</head>
<body class="{% if dir == 'rtl' %}rtl{% else %}ltr{% endif %}">

    <!-- Language Toggle Button (visible everywhere) -->
    <button
        hx-post="/api/language/toggle"
        hx-target="body"
        hx-swap="outerHTML"
        class="fixed top-4 {% if dir == 'rtl' %}left-4{% else %}right-4{% endif %} z-50 ...">
        {% if lang == "ar" %}🇺🇸 English{% else %}🇸🇦 عربي{% endif %}
    </button>

    {% block content %}{% endblock %}
</body>
</html>
3.6 Language Toggle API Endpoint
python
# app/api/language.py

@router.post("/api/language/toggle")
async def toggle_language(request: Request, db: AsyncSession = Depends(get_db)):
    current_lang = request.state.lang
    new_lang = "en" if current_lang == "ar" else "ar"
    
    # Update DB if authenticated
    user = getattr(request.state, "user", None)
    if user:
        await db.execute(
            update(User).where(User.id == user.id)
            .values(preferred_language=new_lang)
        )
        await db.commit()
    
    # Re-render the full page with new language
    # HTMX will replace <body> with new content
    response = templates.TemplateResponse(
        request.url.path.lstrip("/") + ".html",  # current page template
        {"request": request, "lang": new_lang, "dir": "ltr" if new_lang == "en" else "rtl"}
    )
    response.set_cookie("lang", new_lang, max_age=365*24*3600, httponly=False)
    return response
3.7 Database Bilingual Fields
All user-facing text stored in DB must support both languages:
python
# Pattern for bilingual DB fields:
# Use two columns: field_ar + field_en
# API/template reads based on current lang

class Category(Base):
    __tablename__ = "categories"
    id = Column(UUID, primary_key=True, default=uuid4)
    name_ar = Column(String(100), nullable=False)   # "شبكة"
    name_en = Column(String(100), nullable=False)   # "Network"
    description_ar = Column(Text)
    description_en = Column(Text)

class KnowledgeArticle(Base):
    title_ar = Column(String(200), nullable=False)
    title_en = Column(String(200), nullable=False)
    content_ar = Column(Text, nullable=False)
    content_en = Column(Text, nullable=False)

class CannedResponse(Base):
    name_ar = Column(String(100))
    name_en = Column(String(100))
    content_ar = Column(Text, nullable=False)
    content_en = Column(Text, nullable=False)

class SystemAlert(Base):
    message_ar = Column(Text, nullable=False)
    message_en = Column(Text, nullable=False)

class Theme(Base):
    name_ar = Column(String(100))
    name_en = Column(String(100))
    welcome_message_ar = Column(String(200))
    welcome_message_en = Column(String(200))
Helper in Jinja2 to pick the right field:
python
# Add to template globals
def bilingual(obj, field: str, lang: str) -> str:
    """
    bilingual(category, "name", lang) 
    → reads category.name_ar or category.name_en
    """
    return getattr(obj, f"{field}_{lang}", None) or getattr(obj, f"{field}_ar", "")

templates.globals["bl"] = bilingual
Usage in templates:
xml
<!-- Shows category name in current language -->
<span>{{ bl(category, "name", lang) }}</span>
3.8 Email Templates — Bilingual
text
app/templates/email/
├── base_email_ar.html       ← Arabic email base (RTL)
├── base_email_en.html       ← English email base (LTR)
├── ticket_created_ar.html
├── ticket_created_en.html
├── ticket_reply_ar.html
├── ticket_reply_en.html
├── csat_request_ar.html
├── csat_request_en.html
└── sla_breach_ar.html / sla_breach_en.html

# Email sender picks template based on recipient's preferred_language
# For public portal (no account) → defaults to Arabic
3.9 Date, Number & Currency Formatting
python
# app/utils/formatters.py
from babel import Locale, dates, numbers

def format_date(dt, lang: str) -> str:
    locale = Locale.parse("ar_SA" if lang == "ar" else "en_US")
    return dates.format_datetime(dt, locale=locale, format="short")

def format_number(n: int | float, lang: str) -> str:
    locale = Locale.parse("ar_SA" if lang == "ar" else "en_US")
    return numbers.format_number(n, locale=locale)

# Arabic: ٢٦/٠٢/٢٠٢٦  or  26/02/2026 depending on setting
# Default: use Western numerals (0-9) even in Arabic mode
# (modern Arabic UI convention — easier to read for tech staff)
3.10 Tailwind CSS RTL Configuration
javascript
// tailwind.config.js
module.exports = {
  content: ["./app/templates/**/*.html"],
  plugins: [
    require("@tailwindcss/forms"),
    require("tailwindcss-rtl"),  // adds rtl: variant
  ],
  theme: {
    extend: {
      fontFamily: {
        arabic: ["Tajawal", "sans-serif"],
        latin:  ["Inter", "sans-serif"],
      }
    }
  }
}
RTL-aware class examples:
xml
<!-- Wrong: hardcoded direction -->
<div class="pl-4 text-left">

<!-- Correct: direction-agnostic -->
<div class="ps-4 text-start">
<!-- ps- = padding-start (right in RTL, left in LTR) -->
<!-- text-start = text-right in RTL, text-left in LTR -->

<!-- Icons that must flip in RTL -->
<svg class="rtl:rotate-180 ...">  ← arrow icons flip automatically
3.11 Complete i18n Checklist for Cursor
text
When generating ANY file, ensure:

✅ HTML templates use lang="{{ lang }}" dir="{{ dir }}"
✅ All text strings use t("key", lang=lang) — no hardcoded text
✅ All DB models with user-facing text have _ar and _en columns
✅ All email templates have _ar and _en variants
✅ Tailwind classes use ps/pe/ms/me instead of pl/pr/ml/mr
✅ Charts (ApexCharts) configured with RTL option when lang=ar
✅ Date/number formatting uses Babel locale
✅ Form placeholders/labels use t() function
✅ Error messages use t() function
✅ Dropdown options use bl() bilingual helper
✅ Notification content stored bilingual in DB
✅ PDF reports generated in user's preferred language
✅ Language toggle available on every page including /portal
✅ Cookie "lang" set on language change for unauthenticated pages
✅ HTMX requests pass current lang in HX-Lang custom header
✅ Alpine.js text uses x-text with JS translation object
________________________________________
═══════════════════════════════════════════════════════════
Section 4 — Roles & Permissions (RBAC 2.0 Dynamic)
═══════════════════════════════════════════════════════════
4.1 Five Roles
text
[1] public     — Branch employee (no account, portal submission only)
[2] employee   — Support agent (resolves tickets)
[3] supervisor — Team supervisor (manages agents + tickets + queue)
[4] manager    — Executive manager (analytics + full config + all queues)
[5] admin      — System administrator (absolute control)
4.2 Full Permissions Matrix v4.1
text
Permission Key                              emp   sup   mgr   admin
──────────────────────────────────────────────────────────────────
🎫 TICKET MANAGEMENT
  tickets.view_own                           ✅    ✅    ✅    ✅
  tickets.view_team                          ❌    ✅    ✅    ✅
  tickets.view_all                           ❌    ✅    ✅    ✅
  tickets.claim_main_queue                   ✅    ✅    ✅    ✅
  tickets.claim_supervisor_queue             ❌    ✅    ✅    ✅
  tickets.claim_manager_queue                ❌    ❌    ✅    ✅
  tickets.resolve                            ✅    ✅    ✅    ✅
  tickets.close                              ✅    ✅    ✅    ✅
  tickets.reopen                             ❌    ✅    ✅    ✅
  tickets.reassign                           ❌    ✅    ✅    ✅
  tickets.transfer_to_supervisor_queue       ✅    ✅    ✅    ✅
  tickets.transfer_to_manager_queue          ❌    ✅    ✅    ✅
  tickets.return_to_agent                    ❌    ✅    ✅    ✅
  tickets.return_to_main_queue               ❌    ✅    ✅    ✅
  tickets.escalate                           ✅    ✅    ✅    ✅
  tickets.merge                              ❌    ✅    ✅    ✅
  tickets.split                              ❌    ✅    ✅    ✅
  tickets.add_watcher                        ✅    ✅    ✅    ✅
  tickets.lock_unlock                        ❌    ✅    ✅    ✅

👥 USER MANAGEMENT
  users.create                               ❌    ✅    ✅    ✅
  users.edit                                 ❌    ✅    ✅    ✅
  users.disable                              ❌    ✅    ✅    ✅
  users.reset_password                       ❌    ✅    ✅    ✅
  users.import_export_excel                  ❌    ✅    ✅    ✅
  users.set_backup_agent                     ❌    ✅    ✅    ✅
  users.view_active_sessions                 ❌    ❌    ✅    ✅
  users.force_logout_single                  ❌    ❌    ✅    ✅
  users.force_logout_all                     ❌    ❌    ❌    ✅

🏢 BRANCH MANAGEMENT
  branches.create_edit                       ❌    ✅    ✅    ✅
  branches.disable                           ❌    ✅    ✅    ✅
  branches.import_export_excel               ❌    ✅    ✅    ✅
  branches.internal_notes                    ❌    ✅    ✅    ✅
  branches.broadcast_email                   ❌    ✅    ✅    ✅
  branches.manage_employees                  ❌    ✅    ✅    ✅

📊 REPORTS & ANALYTICS
  reports.personal_dashboard                 ✅    ✅    ✅    ✅
  reports.leaderboard_partial                ✅    ✅    ✅    ✅
  reports.leaderboard_full                   ❌    ✅    ✅    ✅
  reports.team_performance                   ❌    ✅    ✅    ✅
  reports.executive_kpi                      ❌    ❌    ✅    ✅
  reports.advanced_builder                   ❌    ❌    ✅    ✅
  reports.scheduled_reports                  ❌    ❌    ✅    ✅
  reports.export_team_csv                    ❌    ✅    ✅    ✅
  reports.export_full                        ❌    ❌    ✅    ✅
  reports.audit_log_read                     ❌    ❌    ✅    ✅

📅 SCHEDULE MANAGEMENT
  schedule.view_own                          ✅    ✅    ✅    ✅
  schedule.view_team                         ❌    ✅    ✅    ✅
  schedule.edit                              ❌    ✅    ✅    ✅
  schedule.request_swap                      ✅    ✅    ✅    ✅
  schedule.approve_swap                      ❌    ✅    ✅    ✅
  schedule.request_leave                     ✅    ✅    ✅    ✅
  schedule.approve_leave                     ❌    ✅    ✅    ✅

📚 KNOWLEDGE BASE
  kb.read                                    ✅    ✅    ✅    ✅
  kb.create_edit                             ❌    ✅    ✅    ✅
  kb.delete                                  ❌    ✅    ✅    ✅
  kb.view_stats                              ❌    ✅    ✅    ✅

⚙️ CONFIGURATION
  config.sla_rules                           ❌    ❌    ✅    ✅
  config.automation_rules                    ❌    ❌    ✅    ✅
  config.form_builder                        ❌    ❌    ✅    ✅
  config.categories_tags                     ❌    ❌    ✅    ✅
  config.canned_responses                    ❌    ✅    ✅    ✅
  config.system_alerts                       ❌    ❌    ✅    ✅
  config.gamification                        ❌    ❌    ✅    ✅
  config.notification_rules                  ❌    ❌    ✅    ✅
  config.permissions_matrix                  ❌    ❌    ❌    ✅

🎨 BRANDING & THEMES
  branding.logo_colors_fonts                 ❌    ❌    ❌    ✅
  branding.themes_crud                       ❌    ❌    ❌    ✅
  branding.theme_schedule                    ❌    ❌    ❌    ✅
  branding.custom_css                        ❌    ❌    ❌    ✅
  ui.dark_light_mode                         ✅    ✅    ✅    ✅
  ui.language_toggle                         ✅    ✅    ✅    ✅  ← PUBLIC TOO

🔗 INTEGRATIONS
  integrations.email_smtp_imap               ❌    ❌    ❌    ✅
  integrations.whatsapp_sms                  ❌    ❌    ❌    ✅
  integrations.s3_storage                    ❌    ❌    ❌    ✅
  integrations.api_keys                      ❌    ❌    ❌    ✅
  integrations.test_mode_toggle              ❌    ❌    ❌    ✅

🔒 SECURITY & SYSTEM
  security.ip_whitelist                      ❌    ❌    ❌    ✅
  security.feature_flags                     ❌    ❌    ❌    ✅
  system.backup_restore                      ❌    ❌    ❌    ✅
  system.health_dashboard                    ❌    ❌    ❌    ✅
  system.db_maintenance                      ❌    ❌    ❌    ✅
  audit_log.delete                           ❌    ❌    ❌    ❌  ← HARDCODED NEVER
  admin_root.disable                         ❌    ❌    ❌    ❌  ← HARDCODED NEVER

🎮 GAMIFICATION
  gamification.view_own_badges               ✅    ✅    ✅    ✅
  gamification.announce_employee_month       ❌    ✅    ✅    ✅
  gamification.grant_badge_manually          ❌    ✅    ✅    ✅
  gamification.edit_criteria                 ❌    ❌    ✅    ✅
4.3 Dynamic Permission Check Implementation
python
# app/core/permissions.py

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

HARDCODED_DENIED = {
    "audit_log.delete",
    "admin_root.disable"
}

async def check_permission(
    user_id: UUID,
    user_role: str,
    permission_key: str,
    redis: aioredis.Redis,
    db: AsyncSession
) -> bool:
    # Hardcoded absolute denials
    if permission_key in HARDCODED_DENIED:
        return False
    
    # Admin always has full access (except hardcoded denials)
    if user_role == "admin":
        return True
    
    # Check Redis cache (15-minute TTL)
    cache_key = f"perms:{user_role}"
    cached = await redis.smembers(cache_key)
    if cached:
        return permission_key.encode() in cached
    
    # Load from DB
    result = await db.execute(
        select(RolePermission.permission_key)
        .where(
            RolePermission.role == user_role,
            RolePermission.is_granted == True
        )
    )
    granted = {row[0] for row in result.fetchall()}
    
    # Cache in Redis
    if granted:
        await redis.sadd(cache_key, *granted)
        await redis.expire(cache_key, 900)  # 15 minutes
    
    return permission_key in granted

# FastAPI dependency
def require_permission(permission_key: str):
    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),
        redis = Depends(get_redis)
    ):
        user = request.state.user
        if not user:
            raise HTTPException(403, t("errors.unauthorized", lang=request.state.lang))
        allowed = await check_permission(user.id, user.role, permission_key, redis, db)
        if not allowed:
            raise HTTPException(403, t("errors.permission_denied", lang=request.state.lang))
        return user
    return _check

# Usage in routes:
@router.post("/tickets/{id}/merge")
async def merge_tickets(
    id: UUID,
    user = Depends(require_permission("tickets.merge"))
):
    ...
________________________________________
═══════════════════════════════════════════════════════════
Section 5 — Full Page Structure (22 Pages)
═══════════════════════════════════════════════════════════
5.1 PUBLIC PORTAL — 4 Pages
________________________________________
GET /portal — Public Portal (Submit & Track)
Tab 1: Submit New Ticket
text
┌──────────────────────────────────────────────────────────────┐
│ 🚨 System Alert Banner (SSE Live — shows if active)          │
│ AR: "⚠️ نظام البيع في فرع الرياض متوقف حالياً"              │
│ EN: "⚠️ POS system is currently down at Riyadh branch"       │
└──────────────────────────────────────────────────────────────┘

[Language Toggle: 🇸🇦 عربي / 🇺🇸 English] ← always visible

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Pre-Ticket Checklist (reduces noise tickets):
  ☐ t("checklist.read_guide")
  ☐ t("checklist.restart_device")
  ☐ t("checklist.select_system")  [Dropdown from DB — bilingual]
  
  → If selected system has active incident:
    t("checklist.known_issue_warning") + link to /status

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Smart Auto-fill (finds submitter by employee ID or phone):
  [Input: employee ID or phone number]  [🔍 Search]
  
  On match → locks fields:
    Name / Employee # / Branch / Phone / Email
  
  Manual override button if not found

Dynamic Form (controlled by Form Builder):
  ├── category_id * [Dropdown — name_ar or name_en]
  │     └── Conditional sub-fields
  ├── priority * [critical/high/medium/low — translated labels]
  ├── description * [Textarea, min 50 chars]
  └── attachments [Drag & Drop, max 10MB, ClamAV scanned]

[🚀 t("form.submit_ticket")]

Post-submission:
  ✅ t("form.success_message", ticket_number="TKT-20260227-001")
  📱 QR Code
  [📧 t("form.send_email_link")]
  [💬 t("form.send_whatsapp_link")]
Tab 2: Track Existing Ticket
text
t("portal.track.title"):
[Input: ticket number or phone]  [t("portal.track.search")]

→ Shows: status (translated) + last update + public timeline

If closed:
  t("portal.track.ticket_closed_reopen_prompt")
  [t("portal.track.yes")] → creates Linked Ticket automatically
________________________________________
GET /ticket/{token} — Direct Ticket Tracking (No Login)
text
t("ticket.number"): #TKT-20260227-001
t("ticket.status"): 🟡 t("ticket.status.open")
t("ticket.assigned_to"): Ahmed Al-Ahmadi

Timeline (public events only — no internal notes):
  📝 t("timeline.ticket_created")
  👤 t("timeline.assigned_to", agent="Ahmed")
  💬 Agent → Customer reply
  ⏱️ t("timeline.status_changed", new_status=...)

[t("ticket.add_reply")] ← visible only when status = pending_customer
________________________________________
GET /csat/{token} — Customer Satisfaction Survey
text
t("csat.title")

⭐⭐⭐⭐⭐  t("csat.overall")

t("csat.dimensions"):
  t("csat.resolution_speed")    ⭐⭐⭐⭐⭐
  t("csat.agent_professionalism") ⭐⭐⭐⭐⭐
  t("csat.clarity")               ⭐⭐⭐⭐⭐

t("csat.comments_optional") [Textarea]

[t("csat.submit")]

Note: token is single-use, expires after 7 days or first submission
________________________________________
GET /status — Live System Status Page
text
t("status.title") — Live (SSE updates every 30s)

🟢 t("system.pos")         ✅ t("status.operational")
🟡 t("system.crm")         ⚠️ t("status.degraded")
🔴 t("system.recharge")    ❌ t("status.down") — ETA: 30 min

t("status.scheduled_maintenance"):
  🛠️ 28/02/2026 02:00 — t("status.routine_maintenance") (30 min)

t("status.past_incidents"):
  25/02/2026: t("status.pos_outage") (t("status.resolved") ✅)
________________________________________
5.2 EMPLOYEE DASHBOARD — 3 Pages
________________________________________
GET /dashboard — Agent Dashboard
text
[Alert Banner — SSE Live]

t("dashboard.welcome", name="Ahmed") | t("dashboard.shift"): 8:00AM - 4:00PM
Keyboard shortcut: [Ctrl+K → Call Log Drawer]

┌─ t("dashboard.today_stats") ────────────────────────┐
│ t("stats.resolved_today"):      8                   │
│ t("stats.avg_resolution_time"): 1.2h                │
│ t("stats.csat"):                ⭐ 4.7/5            │
│ t("stats.sla_compliance"):      95%                 │
│ t("stats.rank"):                #3 🥉               │
│ t("stats.workload"):            🟢 t("workload.low")│
└──────────────────────────────────────────────────────┘

📥 t("queue.smart_title") (sorted by Priority Score):
  [t("queue.claim")] button per row

📚 t("kb.quick_access"):
  [Search KB...]
  Most-used articles (title_ar or title_en based on lang)

━━━ Call Log Drawer (Ctrl+K) ━━━
  t("call_log.agent"): [Search by name or phone]
  t("call_log.reason"): [Dropdown — bilingual categories]
  t("call_log.outcome"):
    ○ t("call_log.resolved")
    ○ t("call_log.needs_followup")
    ○ t("call_log.create_ticket")
  t("call_log.notes"): [Textarea]
  ⏱️ Auto-timer starts on drawer open
  [t("call_log.save")] [t("call_log.cancel")]
________________________________________
GET /tickets/{id} — Full Ticket Detail Page
text
#TKT-20260227-001 | t("ticket.status.open") | SLA: ⏱️ 45 min left

Details panel, Timeline, Communication Thread (External/Internal toggle),
Reply box with Canned Responses (/greeting, /checking, /resolved),
KB Sidebar (auto-filtered by ticket category),
Actions panel:
  [t("ticket.actions.reply")]
  [t("ticket.actions.internal_note")]
  [t("ticket.actions.transfer")] + mandatory reason field
  [t("ticket.actions.add_watcher")]
  [t("ticket.actions.schedule_followup")]
  [t("ticket.actions.pause_sla")]
  [t("ticket.actions.resolve")]
  [t("ticket.actions.close")]
  
Status Dropdown (transitions enforced by backend):
  ● t("ticket.status.open")
  ○ t("ticket.status.pending_customer")   → pauses SLA
  ○ t("ticket.status.pending_3rd")        → pauses SLA
  ○ t("ticket.status.on_hold")            → pauses SLA
  ○ t("ticket.status.resolved")

⏱️ Time Tracker: [▶️ Start] | t("ticket.time_logged"): 0:45:00
Auto-save draft every 30 seconds
________________________________________
GET /profile — Agent Profile
text
Name | Role | Department
Performance stats (this month)
Badges earned
Schedule + upcoming leaves + backup agent
Notification preferences (bilingual toggles)
[t("profile.edit")] [t("profile.change_password")] [t("profile.setup_2fa")]
________________________________________
5.3 SUPERVISOR PANEL — 3 Pages
________________________________________
GET /supervisor — Supervisor Dashboard
text
Team Workload (Live SSE):
  Agent table: online/offline, active tickets, SLA%, CSAT, workload indicator
  [t("workload.auto_rebalance")] ← AI distributes based on capacity

SLA Violations (urgent):
  Red alerts for tickets near/past breach

Unassigned Main Queue:
  Count + oldest ticket age
  [t("queue.quick_assign")] ← auto-distributes

Supervisor Queue (transferred to supervisor):
  Table with: priority, ticket#, branch, transfer reason, from-agent, age
  Per-row actions:
    [t("queue.take_ownership")]
    [t("queue.assign_to")]
    [t("queue.return_to_agent")]
    [t("queue.escalate_to_manager")]

Agent Collision Detection:
  ⚠️ t("collision.warning", agent1="Mohamed", agent2="Ahmed", ticket="TKT-045")
________________________________________
GET /supervisor/tickets — Ticket Management
text
Omni-Search (Arabic + English + ticket# + description + tags)
Multi-filter: status, priority, agent, date range, branch, category, queue
Bulk actions: assign, change status, export
Actions per ticket: Merge, Split
________________________________________
GET /supervisor/team — Team Management (4 Tabs)
Tab 1: Agents (CRUD + Excel Import/Export)
Tab 2: Branches (CRUD + Excel Import/Export + Internal Notes + Broadcast)
Tab 3: Schedule (No-Code drag-and-drop scheduler with conflict detection)
Tab 4: Team Reports + Broadcast email composer
Full bilingual labels on all Tabs. All dropdown options use bilingual DB fields.
________________________________________
5.4 MANAGER DASHBOARD — 4 Pages
________________________________________
GET /manager — Executive Dashboard
text
KPI cards (100+): resolved, open, CSAT, SLA%, FCR, Reopened Rate
Channel breakdown pie chart (Portal/WhatsApp/Email/Phone)
Branch Heatmap (interactive Saudi Arabia map)
Peak Hours Heatmap (day × hour grid)
System Health Widget (DB, Redis, Celery, Disk)
Manager Queue (escalated tickets):
  Per-row actions: take, return to supervisor/agent, resolve directly
________________________________________
GET /manager/analytics — Advanced Analytics
text
Drag & Drop Report Builder
Scheduled Reports management
Special reports: FCR, Reopened Rate, Ticket Deflection, KB Gaps
All rendered in current user language
PDF reports generated in user's preferred_language
________________________________________
GET /manager/tickets — All Tickets (Live + Archive)
text
Full search including archived tickets
Cold Storage retrieval for tickets > 365 days old
All status filters including "archived"
________________________________________
GET /manager/settings — System Config (6 Tabs)
text
Tab 1: Form Builder (No-Code — all field labels bilingual)
Tab 2: SLA Configuration (business hours, holiday calendar)
Tab 3: Automation Rules (IF/AND/THEN engine with bilingual action labels)
Tab 4: Gamification Config (badge criteria, leaderboard settings)
Tab 5: Audit Log (read-only, filterable, exportable)
Tab 6: Scheduled Reports
________________________________________
5.5 ADMIN PANEL — 1 Page + 9 Tabs
GET /admin
text
Tab 1: 🎨 Branding & Themes (logo, colors, fonts, seasonal themes)
Tab 2: 👥 Users & Permissions (dynamic RBAC matrix)
Tab 3: 🔗 Integrations Hub (Email/WhatsApp/SMS/S3)
Tab 4: 🌐 Domain & SSL (domain settings, cert status)
Tab 5: 🔒 Security (IP whitelist, 2FA policy, session mgmt)
Tab 6: 🚩 Feature Flags (enable/disable system features)
Tab 7: 💾 Backup & Restore
Tab 8: 🏥 System Health (DB, Redis, Celery, Disk, Sentry)
Tab 9: 🗄️ Database Maintenance (vacuum, analyze, partition mgmt)
________________________________________
═══════════════════════════════════════════════════════════
Section 6 — Ticket & Queue System
═══════════════════════════════════════════════════════════
6.1 Ticket Lifecycle
python
class TicketStatus(str, Enum):
    NEW             = "new"              # just submitted, unassigned
    OPEN            = "open"             # assigned and being worked on
    PENDING_CUSTOMER = "pending_customer" # waiting for branch reply → SLA PAUSED
    PENDING_3RD     = "pending_3rd"      # waiting for 3rd party (ISP etc) → SLA PAUSED
    ON_HOLD         = "on_hold"          # manually paused → SLA PAUSED
    RESOLVED        = "resolved"         # marked resolved, awaiting confirmation
    CLOSED          = "closed"           # final state
    ARCHIVED        = "archived"         # >365 days closed → Cold Storage

class TicketPriority(str, Enum):
    CRITICAL = "critical"   # SLA: 30 minutes
    HIGH     = "high"       # SLA: 2 hours
    MEDIUM   = "medium"     # SLA: 8 hours
    LOW      = "low"        # SLA: 24 hours

# Valid status transitions:
ALLOWED_TRANSITIONS = {
    "new":              ["open"],
    "open":             ["pending_customer", "pending_3rd", "on_hold", "resolved"],
    "pending_customer": ["open", "resolved"],
    "pending_3rd":      ["open", "resolved"],
    "on_hold":          ["open"],
    "resolved":         ["closed", "open"],  # open = reopen (sup+ only)
    "closed":           ["open"],             # reopen (sup+ only)
}
6.2 Multi-Queue 3-Level System
text
Queue Level 1 — Main Queue:
  - Entry point for all new tickets
  - Employees can claim tickets from here
  - Auto-assigned via Automation Rules

Queue Level 2 — Supervisor Queue:
  - Tickets escalated by employees
  - SLA breach automatic escalation
  - Supervisors claim, return, or push to Manager Queue
  - Transfer field: mandatory reason (stored in timeline)

Queue Level 3 — Manager Queue:
  - VIP tickets, repeat-reopen tickets
  - Critical SLA breach after supervisor inaction
  - Manager handles directly or returns down

Sub-Queues per Specialized Department:
  - Created automatically when a new department/team is added
  - Automation Rules route tickets to sub-queues by category
  - Team members see only their sub-queue by default
  - Supervisor sees all sub-queues for their team

Every Queue Movement:
  → Mandatory reason field (logged in timeline)
  → Audit Log entry (who moved, when, why)
  → Notification to recipient agent/queue
6.3 Priority Score Algorithm
python
def calculate_priority_score(ticket: Ticket, now: datetime) -> float:
    """
    Returns 0-100 score. Higher = more urgent. Used to sort queue.
    """
    sla_elapsed_ratio = ticket.sla_elapsed_seconds / ticket.sla_total_seconds
    
    base_score = sla_elapsed_ratio * 100
    
    # Priority multiplier
    multipliers = {
        "critical": 1.5,
        "high":     1.3,
        "medium":   1.1,
        "low":      1.0
    }
    score = base_score * multipliers[ticket.priority]
    
    # Boost for reopened tickets
    if ticket.reopen_count > 0:
        score += ticket.reopen_count * 5
    
    # Boost for VIP branch
    if ticket.branch.is_vip:
        score += 10
    
    return min(score, 100.0)
6.4 SLA Engine
python
# app/services/sla.py

SLA_MINUTES = {
    "critical": 30,
    "high":     120,
    "medium":   480,
    "low":      1440
}

SLA_PAUSE_STATUSES = {
    "pending_customer",
    "pending_3rd",
    "on_hold"
}

# Business hours: Sun-Thu 08:00-16:00 Arabia/Riyadh timezone
# Official holidays loaded from `holidays` table in DB
# SLA clock uses business_hours_elapsed() function
# SLA pauses when status enters SLA_PAUSE_STATUSES
# SLA resumes when status returns to "open"
# Each pause/resume creates a sla_pauses table record

# Celery Beat task — runs every minute:
@celery.task
async def check_sla_breaches():
    tickets = await get_open_tickets_near_breach()
    for ticket in tickets:
        ratio = get_sla_elapsed_ratio(ticket)
        if ratio >= 0.75 and not ticket.notified_75:
            await send_sla_warning(ticket, threshold=75)
            ticket.notified_75 = True
        if ratio >= 0.90 and not ticket.notified_90:
            await send_sla_warning(ticket, threshold=90)
            await auto_escalate_if_critical(ticket)
            ticket.notified_90 = True
        if ratio >= 1.0 and not ticket.notified_breach:
            await send_sla_breach_alert(ticket)
            await notify_manager(ticket)
            ticket.notified_breach = True
    await db.commit()
________________________________________
═══════════════════════════════════════════════════════════
Section 7 — Database Schema (50 Tables)
═══════════════════════════════════════════════════════════
Cursor Instruction: All UUIDs as primary keys. All tables have created_at, updated_at timestamps. Soft delete via deleted_at nullable timestamp. All user-facing text fields have _ar + _en variants. Run alembic upgrade head to apply all migrations.
7.1 Core Tables
sql
-- 1. users
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username            VARCHAR(50) UNIQUE NOT NULL,
    email               VARCHAR(255) UNIQUE,
    phone               VARCHAR(20),
    full_name_ar        VARCHAR(150) NOT NULL,
    full_name_en        VARCHAR(150),
    employee_id         VARCHAR(50) UNIQUE,
    role                VARCHAR(20) NOT NULL CHECK (role IN ('employee','supervisor','manager','admin')),
    department_id       UUID REFERENCES departments(id),
    preferred_language  VARCHAR(5) DEFAULT 'ar' CHECK (preferred_language IN ('ar','en')),
    password_hash       VARCHAR(255) NOT NULL,
    totp_secret         VARCHAR(100),
    totp_enabled        BOOLEAN DEFAULT FALSE,
    is_active           BOOLEAN DEFAULT TRUE,
    is_online           BOOLEAN DEFAULT FALSE,
    last_seen_at        TIMESTAMPTZ,
    backup_agent_id     UUID REFERENCES users(id),
    dark_mode           BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

-- 2. departments (specialized support teams)
CREATE TABLE departments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar     VARCHAR(100) NOT NULL,
    name_en     VARCHAR(100) NOT NULL,
    code        VARCHAR(20) UNIQUE NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 3. role_permissions (dynamic RBAC)
CREATE TABLE role_permissions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role            VARCHAR(20) NOT NULL,
    permission_key  VARCHAR(100) NOT NULL,
    is_granted      BOOLEAN DEFAULT TRUE,
    updated_by      UUID REFERENCES users(id),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (role, permission_key)
);

-- 4. branches
CREATE TABLE branches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar         VARCHAR(150) NOT NULL,
    name_en         VARCHAR(150) NOT NULL,
    code            VARCHAR(20) UNIQUE NOT NULL,
    city_ar         VARCHAR(100),
    city_en         VARCHAR(100),
    region_ar       VARCHAR(100),
    region_en       VARCHAR(100),
    email           VARCHAR(255),
    phone           VARCHAR(20),
    is_vip          BOOLEAN DEFAULT FALSE,
    is_active       BOOLEAN DEFAULT TRUE,
    internal_notes  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- 5. branch_employees (branch staff — no system account)
CREATE TABLE branch_employees (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id       UUID REFERENCES branches(id),
    full_name_ar    VARCHAR(150) NOT NULL,
    full_name_en    VARCHAR(150),
    employee_id     VARCHAR(50) UNIQUE NOT NULL,
    phone           VARCHAR(20),
    email           VARCHAR(255),
    position_ar     VARCHAR(100),
    position_en     VARCHAR(100),
    preferred_language VARCHAR(5) DEFAULT 'ar',
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- 6. categories
CREATE TABLE categories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar         VARCHAR(100) NOT NULL,
    name_en         VARCHAR(100) NOT NULL,
    description_ar  TEXT,
    description_en  TEXT,
    parent_id       UUID REFERENCES categories(id),
    department_id   UUID REFERENCES departments(id),
    icon            VARCHAR(50),
    sort_order      INTEGER DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 7. tags
CREATE TABLE tags (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar     VARCHAR(50) NOT NULL,
    name_en     VARCHAR(50) NOT NULL,
    color_hex   VARCHAR(7) DEFAULT '#6B7280',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 8. tickets (partitioned by year)
CREATE TABLE tickets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_number       VARCHAR(30) UNIQUE NOT NULL, -- TKT-20260227-001
    
    -- Submitter info
    branch_id           UUID REFERENCES branches(id),
    branch_employee_id  UUID REFERENCES branch_employees(id),
    submitter_name_ar   VARCHAR(150),
    submitter_name_en   VARCHAR(150),
    submitter_phone     VARCHAR(20),
    submitter_email     VARCHAR(255),
    
    -- Ticket content
    category_id         UUID REFERENCES categories(id),
    subject             VARCHAR(255),
    description         TEXT NOT NULL,
    priority            VARCHAR(20) DEFAULT 'medium',
    status              VARCHAR(30) DEFAULT 'new',
    
    -- Queue tracking
    current_queue       VARCHAR(30) DEFAULT 'main', -- main, supervisor, manager
    sub_queue_dept_id   UUID REFERENCES departments(id),
    
    -- Assignment
    assigned_to         UUID REFERENCES users(id),
    assigned_at         TIMESTAMPTZ,
    
    -- Relations
    parent_ticket_id    UUID REFERENCES tickets(id),  -- merge/split
    
    -- Channel
    channel             VARCHAR(20) DEFAULT 'portal', -- portal, email, whatsapp, phone
    source_email_uid    VARCHAR(255),  -- for email-to-ticket mapping
    
    -- SLA
    sla_policy_id       UUID REFERENCES sla_policies(id),
    sla_deadline        TIMESTAMPTZ,
    sla_paused_at       TIMESTAMPTZ,
    sla_total_paused    INTEGER DEFAULT 0,  -- seconds
    sla_breached        BOOLEAN DEFAULT FALSE,
    sla_notified_75     BOOLEAN DEFAULT FALSE,
    sla_notified_90     BOOLEAN DEFAULT FALSE,
    sla_notified_100    BOOLEAN DEFAULT FALSE,
    
    -- Metrics
    first_response_at   TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    closed_at           TIMESTAMPTZ,
    reopen_count        INTEGER DEFAULT 0,
    total_time_seconds  INTEGER DEFAULT 0,  -- from time tracker
    
    -- CSAT
    csat_token          VARCHAR(100) UNIQUE,
    csat_sent_at        TIMESTAMPTZ,
    
    -- Locking (Agent Collision)
    locked_by           UUID REFERENCES users(id),
    locked_at           TIMESTAMPTZ,
    
    -- Optimistic Locking
    version             INTEGER DEFAULT 1,
    
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
) PARTITION BY RANGE (created_at);

-- Yearly partitions:
CREATE TABLE tickets_2026 PARTITION OF tickets
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE tickets_2027 PARTITION OF tickets
    FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');

-- 9. ticket_timeline (immutable event log)
CREATE TABLE ticket_timeline (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID REFERENCES tickets(id) ON DELETE CASCADE,
    event_type      VARCHAR(50) NOT NULL,
    -- Types: created, assigned, status_changed, reply_external,
    --        reply_internal, transfer, escalated, merged, split,
    --        sla_paused, sla_resumed, sla_breach, resolved, closed, reopened
    actor_id        UUID REFERENCES users(id),  -- NULL for system events
    actor_type      VARCHAR(20),  -- user, system, customer
    content_ar      TEXT,
    content_en      TEXT,
    is_public       BOOLEAN DEFAULT TRUE,  -- FALSE = internal note only
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 10. ticket_attachments
CREATE TABLE ticket_attachments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID REFERENCES tickets(id),
    timeline_id     UUID REFERENCES ticket_timeline(id),
    file_name       VARCHAR(255) NOT NULL,
    file_size       INTEGER NOT NULL,
    mime_type       VARCHAR(100),
    s3_key          VARCHAR(500) NOT NULL,
    s3_bucket       VARCHAR(100) NOT NULL,
    virus_scanned   BOOLEAN DEFAULT FALSE,
    virus_clean     BOOLEAN,
    uploaded_by     UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 11. ticket_watchers
CREATE TABLE ticket_watchers (
    ticket_id   UUID REFERENCES tickets(id),
    user_id     UUID REFERENCES users(id),
    added_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ticket_id, user_id)
);

-- 12. ticket_tags
CREATE TABLE ticket_tags (
    ticket_id   UUID REFERENCES tickets(id),
    tag_id      UUID REFERENCES tags(id),
    PRIMARY KEY (ticket_id, tag_id)
);

-- 13. queue_transfers (full history)
CREATE TABLE queue_transfers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID REFERENCES tickets(id),
    from_queue      VARCHAR(30),
    to_queue        VARCHAR(30),
    from_agent_id   UUID REFERENCES users(id),
    to_agent_id     UUID REFERENCES users(id),
    reason          TEXT NOT NULL,  -- mandatory
    transferred_by  UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 14. sla_pauses
CREATE TABLE sla_pauses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id   UUID REFERENCES tickets(id),
    paused_at   TIMESTAMPTZ NOT NULL,
    resumed_at  TIMESTAMPTZ,
    reason      VARCHAR(50),  -- pending_customer / pending_3rd / on_hold
    duration_s  INTEGER  -- calculated on resume
);

-- 15. sla_policies
CREATE TABLE sla_policies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar             VARCHAR(100) NOT NULL,
    name_en             VARCHAR(100) NOT NULL,
    priority            VARCHAR(20) NOT NULL,
    clock_minutes       INTEGER NOT NULL,
    business_hours_only BOOLEAN DEFAULT TRUE,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 16. csat_surveys
CREATE TABLE csat_surveys (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id               UUID REFERENCES tickets(id),
    token                   VARCHAR(100) UNIQUE NOT NULL,
    agent_id                UUID REFERENCES users(id),
    rating_overall          SMALLINT CHECK (rating_overall BETWEEN 1 AND 5),
    rating_speed            SMALLINT CHECK (rating_speed BETWEEN 1 AND 5),
    rating_professionalism  SMALLINT CHECK (rating_professionalism BETWEEN 1 AND 5),
    rating_clarity          SMALLINT CHECK (rating_clarity BETWEEN 1 AND 5),
    comments                TEXT,
    submitted_at            TIMESTAMPTZ,
    token_expires_at        TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- 17. call_logs
CREATE TABLE call_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID REFERENCES users(id),
    branch_employee_id  UUID REFERENCES branch_employees(id),
    caller_phone        VARCHAR(20),
    category_id         UUID REFERENCES categories(id),
    outcome             VARCHAR(30),  -- resolved, needs_followup, ticket_created
    notes               TEXT,
    duration_seconds    INTEGER,
    ticket_id           UUID REFERENCES tickets(id),  -- if ticket was created
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 18. knowledge_articles
CREATE TABLE knowledge_articles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title_ar        VARCHAR(200) NOT NULL,
    title_en        VARCHAR(200) NOT NULL,
    content_ar      TEXT NOT NULL,
    content_en      TEXT NOT NULL,
    category_id     UUID REFERENCES categories(id),
    author_id       UUID REFERENCES users(id),
    view_count      INTEGER DEFAULT 0,
    helpful_count   INTEGER DEFAULT 0,
    not_helpful_count INTEGER DEFAULT 0,
    is_published    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- 19. canned_responses
CREATE TABLE canned_responses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shortcut    VARCHAR(50) NOT NULL,  -- /greeting, /checking
    name_ar     VARCHAR(100) NOT NULL,
    name_en     VARCHAR(100) NOT NULL,
    content_ar  TEXT NOT NULL,
    content_en  TEXT NOT NULL,
    created_by  UUID REFERENCES users(id),
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 20. system_alerts
CREATE TABLE system_alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title_ar        VARCHAR(200) NOT NULL,
    title_en        VARCHAR(200) NOT NULL,
    message_ar      TEXT NOT NULL,
    message_en      TEXT NOT NULL,
    severity        VARCHAR(20) DEFAULT 'warning', -- info, warning, critical
    is_active       BOOLEAN DEFAULT TRUE,
    starts_at       TIMESTAMPTZ DEFAULT NOW(),
    ends_at         TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 21. system_statuses (for /status page)
CREATE TABLE system_statuses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    system_name_ar  VARCHAR(100) NOT NULL,
    system_name_en  VARCHAR(100) NOT NULL,
    status          VARCHAR(20) DEFAULT 'operational',
    -- operational, degraded, partial_outage, major_outage
    description_ar  VARCHAR(255),
    description_en  VARCHAR(255),
    eta_minutes     INTEGER,
    sort_order      INTEGER DEFAULT 0,
    updated_by      UUID REFERENCES users(id),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 22. incidents (for /status history)
CREATE TABLE incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id       UUID REFERENCES system_statuses(id),
    title_ar        VARCHAR(200) NOT NULL,
    title_en        VARCHAR(200) NOT NULL,
    description_ar  TEXT,
    description_en  TEXT,
    status          VARCHAR(20) DEFAULT 'investigating',
    -- investigating, identified, monitoring, resolved
    started_at      TIMESTAMPTZ NOT NULL,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 23. scheduled_maintenance
CREATE TABLE scheduled_maintenance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title_ar        VARCHAR(200) NOT NULL,
    title_en        VARCHAR(200) NOT NULL,
    description_ar  TEXT,
    description_en  TEXT,
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 24. automation_rules
CREATE TABLE automation_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar         VARCHAR(200) NOT NULL,
    name_en         VARCHAR(200) NOT NULL,
    trigger_type    VARCHAR(50) NOT NULL,
    -- ticket_created, status_changed, sla_threshold, ticket_count_spike
    conditions      JSONB NOT NULL,  -- [{field, operator, value}]
    actions         JSONB NOT NULL,  -- [{type, params}]
    priority_order  INTEGER DEFAULT 0,  -- lower = higher priority
    is_active       BOOLEAN DEFAULT TRUE,
    execution_count INTEGER DEFAULT 0,
    last_executed   TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 25. automation_execution_log
CREATE TABLE automation_execution_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id     UUID REFERENCES automation_rules(id),
    ticket_id   UUID REFERENCES tickets(id),
    success     BOOLEAN NOT NULL,
    error_msg   TEXT,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

-- 26. form_versions
CREATE TABLE form_versions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version     INTEGER NOT NULL,
    schema      JSONB NOT NULL,  -- full form schema
    is_active   BOOLEAN DEFAULT FALSE,
    published_by UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 27. form_field_definitions (for Form Builder)
CREATE TABLE form_field_definitions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_version_id     UUID REFERENCES form_versions(id),
    field_type          VARCHAR(30) NOT NULL,
    -- text, textarea, dropdown, checkbox, radio, date, phone, file, number, email
    field_key           VARCHAR(50) NOT NULL,
    label_ar            VARCHAR(200) NOT NULL,
    label_en            VARCHAR(200) NOT NULL,
    placeholder_ar      VARCHAR(200),
    placeholder_en      VARCHAR(200),
    is_required         BOOLEAN DEFAULT FALSE,
    sort_order          INTEGER DEFAULT 0,
    validation_rules    JSONB,
    conditional_logic   JSONB,
    -- {"show_if": {"field": "category_id", "equals": "uuid..."}}
    options             JSONB
    -- [{"value": "uuid", "label_ar": "شبكة", "label_en": "Network"}]
);

-- 28. gamification_badges
CREATE TABLE gamification_badges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar         VARCHAR(100) NOT NULL,
    name_en         VARCHAR(100) NOT NULL,
    description_ar  TEXT,
    description_en  TEXT,
    icon_emoji      VARCHAR(10),
    criteria        JSONB NOT NULL,
    -- {"metric": "resolution_time_minutes", "operator": "<", "value": 30}
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 29. user_badges
CREATE TABLE user_badges (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id),
    badge_id    UUID REFERENCES gamification_badges(id),
    ticket_id   UUID REFERENCES tickets(id),
    awarded_at  TIMESTAMPTZ DEFAULT NOW(),
    awarded_by  UUID REFERENCES users(id)  -- NULL = auto
);

-- 30. leaderboard_snapshots
CREATE TABLE leaderboard_snapshots (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id),
    period_type         VARCHAR(20) NOT NULL,  -- daily, weekly, monthly, yearly
    period_start        DATE NOT NULL,
    tickets_resolved    INTEGER DEFAULT 0,
    avg_resolution_min  FLOAT DEFAULT 0,
    csat_avg            FLOAT DEFAULT 0,
    sla_compliance_pct  FLOAT DEFAULT 0,
    fcr_pct             FLOAT DEFAULT 0,
    rank                INTEGER,
    computed_at         TIMESTAMPTZ DEFAULT NOW()
);

-- 31. employee_of_month
CREATE TABLE employee_of_month (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id),
    month           DATE NOT NULL,  -- first day of month
    is_auto_selected BOOLEAN DEFAULT TRUE,
    announced_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 32. themes
CREATE TABLE themes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar             VARCHAR(100) NOT NULL,
    name_en             VARCHAR(100) NOT NULL,
    description_ar      TEXT,
    description_en      TEXT,
    icon_emoji          VARCHAR(10),
    primary_color       VARCHAR(7) NOT NULL,
    secondary_color     VARCHAR(7) NOT NULL,
    background_color    VARCHAR(7),
    logo_s3_key         VARCHAR(500),
    bg_pattern_s3_key   VARCHAR(500),
    bg_opacity          FLOAT DEFAULT 0.2,
    welcome_message_ar  VARCHAR(200),
    welcome_message_en  VARCHAR(200),
    custom_css          TEXT,
    starts_at           TIMESTAMPTZ NOT NULL,
    ends_at             TIMESTAMPTZ NOT NULL,
    is_active           BOOLEAN DEFAULT FALSE,
    auto_activate       BOOLEAN DEFAULT TRUE,
    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 33. branding_config
CREATE TABLE branding_config (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    logo_s3_key         VARCHAR(500),
    favicon_s3_key      VARCHAR(500),
    primary_color       VARCHAR(7) DEFAULT '#0066CC',
    secondary_color     VARCHAR(7) DEFAULT '#C8215D',
    background_color    VARCHAR(7) DEFAULT '#FFFFFF',
    text_color          VARCHAR(7) DEFAULT '#1A1A1A',
    font_arabic         VARCHAR(100) DEFAULT 'Tajawal',
    font_latin          VARCHAR(100) DEFAULT 'Inter',
    custom_css          TEXT,
    updated_by          UUID REFERENCES users(id),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 34. integration_configs
CREATE TABLE integration_configs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(50) UNIQUE NOT NULL,
    -- smtp_host, smtp_port, smtp_user, smtp_password_enc,
    -- imap_host, imap_port, imap_user, imap_password_enc,
    -- twilio_account_sid, twilio_auth_token_enc, twilio_whatsapp_from,
    -- s3_endpoint, s3_bucket, s3_access_key, s3_secret_key_enc
    value_enc   TEXT,  -- AES-256 encrypted
    is_test_mode BOOLEAN DEFAULT FALSE,
    updated_by  UUID REFERENCES users(id),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 35. api_keys
CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar         VARCHAR(100),
    name_en         VARCHAR(100),
    key_hash        VARCHAR(255) NOT NULL,
    last_4          VARCHAR(4),
    created_by      UUID REFERENCES users(id),
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 36. audit_log (IMMUTABLE — no update/delete allowed)
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id        UUID REFERENCES users(id),
    actor_ip        INET,
    actor_role      VARCHAR(20),
    action          VARCHAR(100) NOT NULL,
    -- ticket.close, config.sla.update, permission.update, data.export ...
    resource_type   VARCHAR(50),
    resource_id     UUID,
    old_value       JSONB,
    new_value       JSONB,
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- IMPORTANT: Revoke DELETE and UPDATE on audit_log from app user:
-- REVOKE DELETE ON audit_log FROM app_user;
-- REVOKE UPDATE ON audit_log FROM app_user;

-- 37. sessions
CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id),
    token_hash      VARCHAR(255) NOT NULL,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    last_active_at  TIMESTAMPTZ DEFAULT NOW(),
    is_valid        BOOLEAN DEFAULT TRUE
);

-- 38. feature_flags
CREATE TABLE feature_flags (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(100) UNIQUE NOT NULL,
    name_ar     VARCHAR(200),
    name_en     VARCHAR(200),
    is_enabled  BOOLEAN DEFAULT TRUE,
    updated_by  UUID REFERENCES users(id),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 39. notifications
CREATE TABLE notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id),
    title_ar        VARCHAR(200) NOT NULL,
    title_en        VARCHAR(200) NOT NULL,
    body_ar         TEXT,
    body_en         TEXT,
    type            VARCHAR(50),
    -- ticket_assigned, sla_warning, sla_breach, new_reply, badge_earned ...
    ticket_id       UUID REFERENCES tickets(id),
    is_read         BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 40. notification_rules
CREATE TABLE notification_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR(50) NOT NULL,
    target_roles    VARCHAR[]  NOT NULL,  -- ['employee', 'supervisor']
    channels        VARCHAR[]  NOT NULL,  -- ['email', 'sms', 'in_app']
    template_key    VARCHAR(100),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 41. agent_schedules
CREATE TABLE agent_schedules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id),
    week_start  DATE NOT NULL,
    schedule    JSONB NOT NULL,
    -- {"sunday": {"start": "08:00", "end": "16:00"}, "monday": "OFF", ...}
    created_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, week_start)
);

-- 42. shift_swaps
CREATE TABLE shift_swaps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_id    UUID REFERENCES users(id),
    requested_id    UUID REFERENCES users(id),
    swap_date       DATE NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    -- pending, approved, rejected
    approved_by     UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 43. leave_requests
CREATE TABLE leave_requests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id),
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    reason_ar   TEXT,
    reason_en   TEXT,
    status      VARCHAR(20) DEFAULT 'pending',
    approved_by UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 44. holidays
CREATE TABLE holidays (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar     VARCHAR(100) NOT NULL,
    name_en     VARCHAR(100) NOT NULL,
    date        DATE NOT NULL,
    is_recurring BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 45. scheduled_reports
CREATE TABLE scheduled_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_ar         VARCHAR(200) NOT NULL,
    name_en         VARCHAR(200) NOT NULL,
    report_config   JSONB NOT NULL,
    frequency       VARCHAR(20) NOT NULL,  -- daily, weekly, monthly
    cron_expr       VARCHAR(100) NOT NULL,
    recipients      VARCHAR[],
    format          VARCHAR(10) DEFAULT 'pdf',
    language        VARCHAR(5)  DEFAULT 'ar',
    is_active       BOOLEAN DEFAULT TRUE,
    last_sent_at    TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 46. time_tracking
CREATE TABLE time_tracking (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id   UUID REFERENCES tickets(id),
    user_id     UUID REFERENCES users(id),
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    duration_s  INTEGER,
    notes_ar    TEXT,
    notes_en    TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 47. follow_ups
CREATE TABLE follow_ups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID REFERENCES tickets(id),
    scheduled_for   TIMESTAMPTZ NOT NULL,
    notes_ar        TEXT,
    notes_en        TEXT,
    created_by      UUID REFERENCES users(id),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 48. ip_whitelist
CREATE TABLE ip_whitelist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cidr        INET NOT NULL,
    label_ar    VARCHAR(100),
    label_en    VARCHAR(100),
    added_by    UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 49. email_ingestion_log
CREATE TABLE email_ingestion_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_uid     VARCHAR(255) NOT NULL,
    from_address    VARCHAR(255),
    subject         VARCHAR(500),
    ticket_id       UUID REFERENCES tickets(id),
    action          VARCHAR(30),
    -- created_ticket, appended_reply, duplicate_skipped, error
    error_msg       TEXT,
    processed_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 50. system_health_snapshots
CREATE TABLE system_health_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    db_response_ms  INTEGER,
    redis_ms        INTEGER,
    celery_workers  INTEGER,
    disk_usage_pct  FLOAT,
    memory_usage_pct FLOAT,
    cpu_usage_pct   FLOAT,
    recorded_at     TIMESTAMPTZ DEFAULT NOW()
);
________________________________________
═══════════════════════════════════════════════════════════
Section 8 — Security & Protection (Enterprise-Grade)
═══════════════════════════════════════════════════════════
8.1 Authentication Security
python
# JWT RS256 — asymmetric key pair
# Generate keys:
# openssl genrsa -out private_key.pem 4096
# openssl rsa -in private_key.pem -pubout -out public_key.pem

# Token payload:
{
  "sub": "user-uuid",
  "role": "employee",
  "jti": "unique-token-id",   # for revocation
  "iat": 1709001600,
  "exp": 1709088000,          # 24 hours
  "lang": "ar"
}

# Password hashing: Argon2id
# memory: 65536 KB, iterations: 3, parallelism: 4

# Session invalidation:
# Store jti in Redis. On logout → delete from Redis.
# On every request → verify jti still in Redis.
8.2 Rate Limiting
python
# Sliding window rate limits (Redis-backed):
RATE_LIMITS = {
    "/portal":           "20/minute",
    "/api/auth/login":   "5/minute",
    "/api/auth/register":"3/hour",
    "/api/*":            "100/minute per user"
}
8.3 File Upload Security
python
# Every uploaded file:
# 1. Check MIME type (python-magic — prevents extension spoofing)
# 2. ClamAV virus scan
# 3. Rename to UUID (no original filename in S3)
# 4. Encrypt with AES-256 before upload
# 5. Signed URL for download (expires in 1 hour)

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif",
    "application/pdf", "application/zip",
    "text/plain", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
8.4 SQL Injection & XSS Protection
python
# SQLAlchemy parameterized queries — no raw SQL with user input
# Jinja2 autoescaping enabled — all output HTML-escaped
# Content Security Policy headers via Nginx
# CSRF protection: Double-submit cookie pattern for all POST/PUT/DELETE
8.5 Audit Trail
python
# Every mutation is logged to audit_log:
# - Who (actor_id + IP)
# - What (action key)
# - Before/after values (old_value, new_value JSON)
# DB-level: REVOKE DELETE, UPDATE on audit_log from app_user
# Application-level: no endpoint provides delete/update for audit_log
________________________________________
═══════════════════════════════════════════════════════════
Section 9 — No-Code Features 2.0
═══════════════════════════════════════════════════════════
9.1 Form Builder
text
- Drag & Drop field ordering
- Field types: text, textarea, dropdown, checkbox, radio, date, phone, file, number, email
- All
