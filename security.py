# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

import os
import re
import secrets
import logging
import json
from functools import wraps
from datetime import date
from flask import request, jsonify, current_app, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bleach
from datetime import datetime, timedelta
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Custom key function for rate limiting - use user ID if authenticated, otherwise IP
def get_rate_limit_key():
    """Get rate limit key - use user ID if authenticated, otherwise IP"""
    from flask_login import current_user
    if current_user.is_authenticated:
        return f"user_{current_user.id}"
    return get_remote_address()

# Initialize rate limiter with Redis storage (falls back to memory if Redis unavailable)
# Redis ensures rate limits are shared across all Gunicorn workers
def get_storage_uri():
    """Get Redis storage URI from environment, fallback to memory"""
    redis_host = os.environ.get('REDIS_HOST', 'localhost')
    redis_port = os.environ.get('REDIS_PORT', '6379')
    redis_db = os.environ.get('REDIS_DB', '0')
    redis_password = os.environ.get('REDIS_PASSWORD', '')
    
    # If Redis is explicitly disabled, use memory
    if os.environ.get('REDIS_ENABLED', 'true').lower() == 'false':
        return 'memory://'
    
    # Build Redis URI (URL-encode password to handle special characters like #, $, etc.)
    if redis_password:
        # URL-encode the password to handle special characters
        encoded_password = quote(redis_password, safe='')
        redis_uri = f'redis://:{encoded_password}@{redis_host}:{redis_port}/{redis_db}'
    else:
        redis_uri = f'redis://{redis_host}:{redis_port}/{redis_db}'
    
    # Test Redis connection
    try:
        import redis as redis_client
        r = redis_client.Redis(
            host=redis_host,
            port=int(redis_port),
            db=int(redis_db),
            password=redis_password if redis_password else None,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=False
        )
        r.ping()
        logger.info(f"✅ Redis connection successful: {redis_host}:{redis_port}")
        return redis_uri
    except ImportError:
        logger.warning("⚠️  Redis package not installed, falling back to in-memory storage")
        return 'memory://'
    except Exception as e:
        logger.warning(f"⚠️  Redis connection failed ({e}), falling back to in-memory storage")
        return 'memory://'

limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=get_storage_uri()
)

MONITORING_PATHS = frozenset(
    {
        "/api/healthz",
        "/healthz",
        "/robots.txt",
        "/favicon.ico",
    }
)


@limiter.request_filter
def exempt_admin_from_rate_limit():
    """Exempt monitoring probes and the site admin from rate limiting."""
    path = (request.path or "").rstrip("/") or "/"
    if path in MONITORING_PATHS or path.endswith("/healthz"):
        return True
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            if getattr(current_user, "is_site_admin", False) or getattr(
                current_user, "username", None
            ) == "user_1" or getattr(current_user, "id", None) == 1:
                return True
    except Exception:
        return False
    return False

def init_security(app):
    """Initialize security components with the Flask app"""
    limiter.init_app(app)
    
    # Configure CSRF protection
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour
    app.config['WTF_CSRF_SSL_STRICT'] = False  # Set to True in production with HTTPS
    
    # Configure session security
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    
    logger.info("Security components initialized")

def rate_limit(limit_string):
    """Decorator for rate limiting endpoints using Flask-Limiter"""
    return limiter.limit(limit_string)

def require_csrf(f):
    """Decorator for CSRF protection"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            from flask_wtf.csrf import validate_csrf
            try:
                validate_csrf(request.form.get('csrf_token') or request.headers.get('X-CSRF-Token'))
            except Exception as e:
                logger.warning(f"CSRF token validation failed for {request.endpoint}: {e}")
                return jsonify({
                    "success": False,
                    "error": "Invalid CSRF token",
                    "timestamp": datetime.utcnow().isoformat()
                }), 403
        return f(*args, **kwargs)
    return decorated_function

def validate_csrf_token(token):
    """Validate CSRF token"""
    try:
        from itsdangerous import URLSafeTimedSerializer
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        serializer.loads(token, max_age=3600)  # 1 hour max age
        return True
    except Exception as e:
        logger.warning(f"CSRF token validation error: {e}")
        return False

def generate_csrf_token():
    """Generate a CSRF token"""
    from itsdangerous import URLSafeTimedSerializer
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(secrets.token_urlsafe(32))

def sanitize_input(text, max_length=1000):
    """Sanitize user input using bleach"""
    if not text:
        return ""
    
    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length]
    
    # Allowed HTML tags and attributes
    allowed_tags = ['b', 'i', 'em', 'strong', 'p', 'br']
    allowed_attributes = {}
    
    # Clean the text
    cleaned = bleach.clean(text, tags=allowed_tags, attributes=allowed_attributes, strip=True)
    
    return cleaned.strip()

def validate_password(password):
    """Validate password strength"""
    if not password:
        return False, "Password is required"
    
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    
    return True, "Password is valid"

def validate_email(email):
    """Validate email format"""
    if not email:
        return False, "Email is required"
    
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False, "Invalid email format"
    
    if len(email) > 254:  # RFC 5321 limit
        return False, "Email address is too long"
    
    return True, "Email is valid"

def validate_work_email(email):
    """Legacy name: validates any normal email (template apps are not domain-locked)."""
    return validate_email(email)

def validate_personal_email(email):
    """Validate personal email (optional, must be unique if provided)"""
    if not email or not email.strip():
        return True, "Personal email is optional"
    
    # Validate email format
    email_valid, email_error = validate_email(email)
    if not email_valid:
        return False, email_error
    
    return True, "Personal email is valid"

def validate_work_day_data(data, user_id=None, work_day_id=None):
    """Reserved for domain-specific work-day forms; template stack does not use this."""
    return True, []


def log_security_event(event_type, user_id=None, details=None):
    """Log security events for monitoring"""
    log_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'event_type': event_type,
        'user_id': user_id,
        'ip_address': get_remote_address(),
        'user_agent': request.headers.get('User-Agent', ''),
        'details': details or {}
    }
    
    logger.warning(f"Security event: {log_data}")
    # Persist to security_events table
    try:
        from database import execute_query
        execute_query(
            """
            INSERT INTO security_events (event_type, user_id, ip_address, user_agent, details)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                event_type,
                user_id,
                log_data['ip_address'],
                log_data['user_agent'],
                json.dumps(log_data['details'])
            ),
            fetch_all=False
        )
    except Exception as e:
        logger.error(f"Failed to write security event to DB: {e}")

def admin_required(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask_login import current_user
        if not current_user.is_authenticated or not getattr(
            current_user, "is_site_admin", False
        ):
            log_security_event('unauthorized_admin_access', current_user.id if current_user.is_authenticated else None)
            return jsonify({
                "success": False,
                "error": "Admin privileges required",
                "timestamp": datetime.utcnow().isoformat()
            }), 403
        return f(*args, **kwargs)
    return decorated_function

def login_required_with_logging(f):
    """Enhanced login required decorator with security logging"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask_login import current_user
        if not current_user.is_authenticated:
            log_security_event('unauthorized_access_attempt', details={'endpoint': request.endpoint})
            return jsonify({
                "success": False,
                "error": "Authentication required",
                "timestamp": datetime.utcnow().isoformat()
            }), 401
        return f(*args, **kwargs)
    return decorated_function
