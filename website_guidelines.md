# Website Development Guidelines
*Patterns for this containerized Flask template. Adapt sections marked “optional / larger apps” when you grow beyond the starter.*

## **How this template handles the database (canonical)**

Schema creation and **incremental, idempotent changes** live in **`setup_database.py`**, not in a checked-in `database_schema.sql` and not in a separate `migrate_database.py` in this repo.

1. **`init_db()`** in `setup_database.py` defines the baseline:
   - `CREATE TABLE IF NOT EXISTS …` for core tables (`tenants`, `users`, `blocked_registration_prefixes`, `security_events`, …).
   - **`_column_exists` / `_ensure_column`** for additive upgrades (same pattern as a larger app: check `information_schema`, then `ALTER TABLE … ADD COLUMN …` when missing).
2. **When it runs:** `app/app.py` calls `init_db()` **during application startup**, under an **`fcntl` file lock** in `logs/` so **only one Gunicorn worker** performs initialization; others skip after a short wait. Re-running is safe (idempotent DDL).
3. **Seeding:** default tenant and admin user (from `.env`: `ADMIN_*`) are ensured inside `init_db()` when configured.
4. **Optional / larger apps:** you may add SQL migration files or a dedicated migration tool later; until then, **extend `setup_database.py`** using the same idempotent style as your production projects.

## 🎯 **Core Principles**

### **1. Multi-Tenant Architecture**
- **Isolate tenant data** in every query that reads or writes tenant-owned rows.
- Use **`tenant_id`** on user-scoped and business tables; **`tenant_id` must reference `tenants(id)`** (not `users`). Users belong to a tenant via `users.tenant_id → tenants.id`.
- Add `tenant_id` to new data tables and enforce it in routes/services (template starts with `tenants` + `users` only).

### **2. Security First**
- **Rate limiting** on all API endpoints and forms
- **CSRF protection** for all state-changing operations
- **Input validation** and sanitization using `bleach`
- **SQL injection prevention** using parameterized queries
- **Security event logging** for monitoring and debugging

### **3. Database Design Standards**

#### **Naming Conventions**
- **Tables**: `snake_case`, descriptive names (`tenants`, `users`, …). Optional prefixes like `pc_`, `fc_`, `custom_` are for larger multi-module apps only—not required in this starter.
- **Columns**: `snake_case` with clear purpose
- **Foreign Keys**: `{table}_id` format
- **Timestamps**: `created_at`, `updated_at`, `{action}_at`

#### **Required columns (target pattern for new tables)**
For tables that belong to a tenant, include at minimum:

```sql
id SERIAL PRIMARY KEY,
tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

#### **Schema change rules (this template)**
- **Prefer** idempotent DDL inside **`setup_database.py`** (`CREATE IF NOT EXISTS`, `_ensure_column`, guarded `ALTER TABLE`) so fresh installs and upgrades share one code path.
- **Avoid** editing historical migration files after production has run them; add new guarded steps at the bottom of `init_db()` (or a clearly named helper called from `init_db()`).
- **Optional / larger apps:** keep a separate migration process if you need downgrades or team review; this starter does not ship `database_schema.sql` or `migrate_database.py`.

### **4. Flask Application Structure**

#### **File organization (this repository)**
```
project_template_containerized/
├── app/
│   ├── app.py              # Application factory, startup DB init lock, blueprints
│   ├── static/             # CSS, JS, favicon
│   └── templates/          # Jinja2 templates
├── routes.py               # Blueprints (thin starter)
├── auth.py                 # User / UserManager
├── database.py             # Connection pool + execute_query
├── security.py             # Rate limits, CSRF helpers, bleach, security_events logging
├── email_service.py        # Mailgun → SendGrid → SMTP (not Flask-Mail)
├── setup_database.py       # init_db(): schema + idempotent upgrades + seed
├── requirements.txt
├── .env.example
├── Containerfile
├── deployment_items/
│   ├── website_setup.sh    # Rename via init_new_project.sh → <slug>_setup.sh
│   ├── init_new_project.sh
│   └── DEPLOYMENT.md
└── website_guidelines.md   # This file
```

#### **Imports (illustrative — match your module)**
```python
# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_compress import Compress
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import os
import logging
```

### **5. Database Connection Management**

#### **Connection Pooling**
```python
class DatabaseManager:
    def __init__(self):
        self.db_config = {
            'host': os.environ.get('DB_HOST', 'localhost'),
            'port': int(os.environ.get('DB_PORT', 5432)),
            'dbname': os.environ.get('DB_NAME', 'app_db'),
            'user': os.environ.get('DB_USER', 'app_user'),
            'password': os.environ.get('DB_PASSWORD', 'app_password')
        }
        
        self.pool_config = {
            'min_size': int(os.environ.get('DB_POOL_MIN_SIZE', '2')),
            'max_size': int(os.environ.get('DB_POOL_MAX_SIZE', '10')),
            'max_idle': int(os.environ.get('DB_POOL_MAX_IDLE', '300')),
            'max_lifetime': int(os.environ.get('DB_POOL_MAX_LIFETIME', '3600')),
            'reconnect_timeout': int(os.environ.get('DB_POOL_RECONNECT_TIMEOUT', '10')),
            'check': psycopg_pool.ConnectionPool.check_connection
        }
```

#### **Query Patterns**
- **Always use context managers** for database connections
- **Return dictionaries** using `psycopg.rows.dict_row`
- **Handle exceptions** gracefully with proper error messages
- **Use parameterized queries** to prevent SQL injection

### **6. Security Implementation**

#### **Rate Limiting Decorator**
```python
@rate_limit("10 per minute")
@login_required
def sensitive_operation():
    # Protected endpoint
    pass
```

#### **CSRF Protection**
```python
@require_csrf
@login_required
def form_submission():
    # CSRF-protected form handler
    pass
```

#### **Input Validation**
- Use `bleach` for HTML sanitization
- Validate all form inputs server-side
- Implement proper error handling and user feedback

### **7. Frontend Standards**

#### **Template Structure**
```html
<!-- === LICENSE HEADER START ===
Copyright (c) 2025 Robert Brake
This file is part of a proprietary software project.
Unauthorized use, modification, or distribution is strictly prohibited.
=== LICENSE HEADER END === -->

{% extends "base.html" %}

{% block title %}Page Title - App Name{% endblock %}

{% block content %}
<!-- Page content -->
{% endblock %}
```

#### **Bootstrap 5 Integration**
- **Use Bootstrap 5** for responsive design
- **Custom CSS variables** for theming
- **Dark mode support** with `data-theme` attributes
- **Responsive breakpoints**: Mobile (<1024px), Desktop (≥1024px)

#### **JavaScript Patterns**
- **Event delegation** for dynamic content
- **Debounced API calls** to prevent duplicates
- **Error handling** with user-friendly messages
- **Loading states** for better UX
- **Remove debug code** before production

### **8. API Design Standards**

#### **Response Format**
```python
# Success response
return jsonify({
    "success": True,
    "data": result_data,
    "message": "Operation completed successfully"
})

# Error response  
return jsonify({
    "success": False,
    "error": "Error message",
    "details": "Additional error details"
}), 400
```

#### **Endpoint Naming**
- **RESTful conventions**: `/api/resource`, `/api/resource/<id>`
- **Prefer resource-oriented names** over RPC-style URLs unless you have a good reason
- **Consistent naming**: snake_case path segments where practical

### **9. Environment Configuration**

#### **Environment variables (align with `.env.example`)**
```bash
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=work_logs_db
DB_USER=work_logs_user
DB_PASSWORD=secure_password

# Flask
FLASK_SECRET_KEY=your-secret-key
FLASK_ENV=production
FLASK_DEBUG=False
HOST=0.0.0.0
PORT=5050

# Email — primary Mailgun; SendGrid and SMTP are fallbacks (see email_service.py)
MAILGUN_API_KEY=
MAILGUN_DOMAIN=
# … plus SMTP / SendGrid vars as needed

# Redis (Flask-Limiter)
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379

# Application / legal contact addresses (see .env.example)
SUPPORT_EMAIL=support@logs.brakesystems.ca
PRIVACY_EMAIL=privacy@logs.brakesystems.ca
```

Flask-WTF CSRF uses the app secret; there is **no separate `CSRF_SECRET_KEY`** in this template unless you add one.

### **10. Deployment Standards**

#### **Deployment directory (this template)**
```
deployment_items/
├── website_setup.sh      # Generic setup; init_new_project.sh renames to <slug>_setup.sh
├── init_new_project.sh   # Placeholder substitution + script rename
└── DEPLOYMENT.md         # Container / Quadlet overview
```

Production **runs under Podman + Quadlet** (see `website_setup.sh` and `DEPLOYMENT.md`): image build from `Containerfile`, `.container` unit, Nginx reverse proxy, optional Cloudflare tunnel. Paths and unit names differ from a bare `venv` + `python app.py` host.

#### **Legacy venv + systemd example (optional / other hosts)**
```ini
[Unit]
Description=Your App Name
After=network.target

[Service]
Type=simple
User=deploy
WorkingDirectory=/path/to/your/app
Environment=PATH=/path/to/your/app/venv/bin
ExecStart=/path/to/your/app/venv/bin/gunicorn -b 127.0.0.1:8000 app.app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

### **11. Performance Optimization**

#### **Caching Strategy**
- **In-memory caching** for static data (exercise lists, settings)
- **Cache TTL** based on data update frequency
- **Cache invalidation** on data changes
- **Flask-Compress** for API response compression

#### **Database Optimization**
- **Connection pooling** for concurrent requests
- **Indexed columns** for frequently queried fields
- **Query optimization** with proper JOINs
- **Batch operations** for bulk data updates

### **12. Error Handling**

#### **Database Errors**
```python
try:
    result = db.execute_query(query, params)
    return result
except Exception as e:
    print(f"Database error: {e}")
    return None
```

#### **API Error Responses**
```python
try:
    # API logic
    return jsonify({"success": True, "data": result})
except Exception as e:
    print(f"API error: {e}")
    return jsonify({"success": False, "error": str(e)}), 500
```

### **13. User Experience Standards**

#### **Loading States**
- **Show loading indicators** for API calls
- **Disable buttons** during form submission
- **Progress feedback** for long operations

#### **Error Messages**
- **User-friendly language** (no technical jargon)
- **Specific guidance** on how to fix issues
- **Consistent styling** with Bootstrap alerts

#### **Responsive Design**
- **Mobile-first approach** with Bootstrap grid
- **Touch-friendly targets** (minimum 44px)
- **Readable text** on all screen sizes
- **Collapsible sections** for mobile space efficiency

### **14. Code Quality Standards**

#### **Documentation**
- **README.md** with setup and usage instructions
- **Code comments** for complex logic
- **API documentation** for endpoints
- **Database schema documentation**

#### **Testing**
- **Test database migrations** before production
- **Validate all forms** with edge cases
- **Test responsive design** on multiple devices
- **Security testing** for common vulnerabilities

### **15. User Authentication & Session Management**

#### **Flask-Login Integration**
```python
# User class must inherit from UserMixin
class User(UserMixin):
    def __init__(self, user_data):
        self.id = user_data["id"]
        self.username = user_data["username"]
        self.email = user_data["email"]
        self.is_admin = user_data["is_admin"]
        # Add tenant_id for multi-tenant apps
        self.tenant_id = user_data.get("tenant_id")
        self.is_tenant_owner = user_data.get("is_tenant_owner", False)
        self.email_verified = user_data.get("email_verified", False)
    
    @property
    def is_active(self):
        return True  # All users are active by default
    
    def get_id(self):
        return str(self.id)
```

#### **Session Configuration**
```python
# In app.py
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True  # Production only
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
```

#### **Authentication Decorators**
```python
# Standard decorators
@login_required
def protected_route():
    pass

# Optional: subscription-gated routes (implement when you add billing UI)
# @subscription_required
# def premium_feature():
#     pass

# Admin-only routes: check current_user.is_admin in the view, or use security.admin_required on JSON APIs
```

### **16. Email System Standards**

#### **Email Template Structure**
```html
<!-- === LICENSE HEADER START ===
Copyright (c) 2025 Robert Brake
This file is part of a proprietary software project.
Unauthorized use, modification, or distribution is strictly prohibited.
=== LICENSE HEADER END === -->

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Email Subject - App Name</title>
    <style>
        /* Inline CSS for email compatibility */
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .header { background-color: #6c5ce7; color: white; padding: 20px; text-align: center; }
        .content { background-color: #f8f9fa; padding: 30px; }
        .button { display: inline-block; background-color: #6c5ce7; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; }
    </style>
</head>
<body>
    <!-- Email content -->
</body>
</html>
```

#### **Email configuration**
Transactional email is implemented in **`email_service.py`** (Mailgun API → SendGrid API → SMTP). Configure the corresponding environment variables in `.env`; you do **not** need `Flask-Mail` for the template’s mail paths.

### **17. Frontend Theme System**

#### **CSS Custom Properties for Theming**
```css
:root {
    /* Light theme */
    --primary-color: #6c5ce7;
    --secondary-color: #a29bfe;
    --bg-primary: #ffffff;
    --bg-secondary: #f8f9fa;
    --text-primary: #2d3436;
    --text-secondary: #636e72;
    --border-color: #ddd;
}

[data-theme="dark"] {
    /* Dark theme */
    --primary-color: #a29bfe;
    --secondary-color: #6c5ce7;
    --bg-primary: #2d3436;
    --bg-secondary: #636e72;
    --text-primary: #ffffff;
    --text-secondary: #ddd;
    --border-color: #636e72;
}
```

#### **Theme Toggle Implementation**
```javascript
// Theme toggle functionality
function toggleTheme() {
    const currentTheme = localStorage.getItem('theme') || 'auto';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    localStorage.setItem('theme', newTheme);
    applyTheme(newTheme);
}

function applyTheme(theme) {
    if (theme === 'auto') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.body.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
    } else {
        document.body.setAttribute('data-theme', theme);
    }
}
```

### **18. Static Assets Management**

#### **Static files (this template)**
The starter ships **`favicon.svg`**, **`css/styles.css`**, and **`js/theme.js`**. Add logos, Open Graph images, and `apple-touch-icon` when you brand the site; reference them from `base.html` when present.

#### **Favicon (SVG in template)**
```html
<link rel="icon" type="image/svg+xml" href="{{ url_for('static', filename='favicon.svg') }}">
```

### **19. SEO and Schema Markup**

#### **Required Meta Tags**
```html
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{% block description %}App description{% endblock %}">
    <meta name="keywords" content="{% block keywords %}app, keywords{% endblock %}">
    <meta name="author" content="Robert Brake">
    <meta name="robots" content="index, follow">
    
    <!-- Open Graph -->
    <meta property="og:title" content="{% block og_title %}{{ self.title() }}{% endblock %}">
    <meta property="og:description" content="{% block og_description %}{{ self.description() }}{% endblock %}">
    <meta property="og:image" content="{{ url_for('static', filename='facebook_cover.png', _external=True) }}">
    <meta property="og:url" content="{{ request.url }}">
    <meta property="og:type" content="website">
    
    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{% block twitter_title %}{{ self.title() }}{% endblock %}">
    <meta name="twitter:description" content="{% block twitter_description %}{{ self.description() }}{% endblock %}">
    <meta name="twitter:image" content="{{ url_for('static', filename='twitter_profile.png', _external=True) }}">
</head>
```

#### **Schema.org Markup**
```html
<!-- Footer navigation schema -->
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "SiteNavigationElement",
    "name": "Footer Navigation",
    "url": "{{ request.url_root }}",
    "mainEntity": [
        {
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "About",
                    "url": "{{ url_for('about', _external=True) }}"
                }
            ]
        }
    ]
}
</script>
```

### **20. Error Handling Patterns**

#### **Custom Error Pages**
```python
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('errors/500.html'), 500

@app.errorhandler(403)
def forbidden_error(error):
    return render_template('errors/403.html'), 403
```

#### **Error Template Structure**
```html
{% extends "base.html" %}
{% block title %}Error {{ error_code }} - App Name{% endblock %}
{% block content %}
<div class="error-container text-center">
    <h1 class="display-1">{{ error_code }}</h1>
    <h2>{{ error_title }}</h2>
    <p class="lead">{{ error_message }}</p>
    <a href="{{ url_for('index') }}" class="btn btn-primary">Return Home</a>
</div>
{% endblock %}
```

### **21. Form Handling Standards**

#### **CSRF Protection**
```python
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app)

# In templates (hidden input name must be csrf_token for Flask-WTF)
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <!-- form fields -->
</form>
```

#### **Form Validation**
```python
from wtforms import Form, StringField, validators

class ContactForm(Form):
    name = StringField('Name', [validators.Length(min=1, max=100)])
    email = StringField('Email', [validators.Email(), validators.Length(max=120)])
    message = TextAreaField('Message', [validators.Length(min=1, max=1000)])
```

### **22. API Response Standards**

#### **Consistent JSON Responses**
```python
# Success response
def success_response(data=None, message="Success", status_code=200):
    response = {
        "success": True,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    }
    if data is not None:
        response["data"] = data
    return jsonify(response), status_code

# Error response
def error_response(message="Error", details=None, status_code=400):
    response = {
        "success": False,
        "error": message,
        "timestamp": datetime.utcnow().isoformat()
    }
    if details:
        response["details"] = details
    return jsonify(response), status_code
```

### **23. Logging Standards**

#### **Structured Logging**
```python
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Usage
logger.info(f"User {user_id} performed action: {action}")
logger.error(f"Database error: {str(e)}", exc_info=True)
```

### **24. Maintenance Guidelines**

#### **Regular Tasks**
- **Monitor error logs** for issues
- **Update dependencies** regularly
- **Backup database** before major changes
- **Test schema changes** in staging (extend `setup_database.py` idempotently)
- **Check security logs** for suspicious activity
- **Verify email functionality** monthly
- **Test theme switching** on all pages

#### **Code Review Checklist**
- [ ] Security measures implemented
- [ ] Database queries use parameters
- [ ] Error handling is comprehensive
- [ ] UI is responsive and accessible
- [ ] Performance optimizations applied
- [ ] Debug code removed
- [ ] Documentation updated
- [ ] Email templates tested
- [ ] Theme switching works
- [ ] SEO meta tags present
- [ ] Schema markup included
- [ ] Static assets optimized

---

## 🚀 **Quick Start Checklist**

When starting a new project from this template:

1. **Run** `init_new_project.sh` (or edit `website_setup.sh`) and copy `.env.example` → `.env`
2. **Extend `setup_database.py`** when you add tables or columns (keep `init_db()` idempotent)
3. **Confirm** `app/app.py` startup lock + `init_db()` behavior matches your hosting (Gunicorn workers)
4. **Implement security**: rate limits, CSRF on POST forms, `bleach` where users supply HTML
5. **Use** `database.py` / `execute_query` with parameters only
6. **Customize** `base.html`, theme, and legal pages
7. **Wire email** (Mailgun / SendGrid / SMTP) and test verification + password reset
8. **Add static assets** (OG images, icons) as needed
9. **Tune SEO** in `base.html` and public routes
10. **Deploy** via `deployment_items/<slug>_setup.sh` and `DEPLOYMENT.md`
11. **Add caching** only when you have measured need (no `cache_manager.py` in the starter)
12. **Error pages** already exist under `app/templates/errors/` — adjust copy
13. **Test** auth, email, Stripe webhook URL, and production config before go-live

---

*These guidelines ensure consistency, security, and maintainability across all your web applications.*
