# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

# app.py
# Main Flask application with multi-user support and security.

import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_login import LoginManager, current_user
from flask_compress import Compress
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

# Import our modules (from parent directory)
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_manager
from security import init_security, rate_limit, log_security_event
from auth import User, UserManager

# Load environment variables from project root (reliable when CWD differs, e.g. in containers)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, '.env'))

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)

# Suppress Flask-Limiter warnings (only show if Redis fails)
import warnings
warnings.filterwarnings("ignore", message="Using the in-memory storage for tracking rate limits")

logger = logging.getLogger(__name__)

def create_app():
    """Application factory pattern"""
    import os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_path = os.path.join(_root, 'app', 'static')
    template_path = os.path.join(_root, 'app', 'templates')
    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get(
        'MAIL_DEFAULT_SENDER',
        os.environ.get('NO_REPLY', 'noreply@example.com'),
    )
    
    # Session configuration
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Initialize extensions
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    Compress(app)
    csrf = CSRFProtect(app)
    
    # Initialize security
    init_security(app)
    
    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return UserManager.get_user_by_id(int(user_id))
    
    # Register blueprints
    from routes import auth_bp, main_bp, api_bp, admin_bp
    from work_logs_routes import work_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(admin_bp)
    app.register_blueprint(work_bp)

    @app.route('/favicon.ico')
    def favicon_legacy():
        """Default browser request is /favicon.ico; static file was invalid placeholder."""
        return app.send_static_file('favicon.svg')
    
    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return render_template('errors/500.html'), 500
    
    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html'), 403
    
    # Custom rate limit error handler for Flask-Limiter
    from flask_limiter.errors import RateLimitExceeded
    
    @app.errorhandler(RateLimitExceeded)
    def ratelimit_error(e):
        """Handle rate limit errors with descriptive messages"""
        try:
            # Flask-Limiter provides retry_after in seconds
            retry_seconds = getattr(e, 'retry_after', None)
            if retry_seconds:
                retry_minutes = (retry_seconds + 59) // 60  # Round up to nearest minute
                message = f"Too many requests. Please try again in {retry_minutes} minute{'s' if retry_minutes != 1 else ''}."
            else:
                message = "Too many requests. Please try again in a few minutes."
        except:
            message = "Too many requests. Please try again in a few minutes."
        
        # If it's an AJAX request, return JSON
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'error': message,
                'timestamp': datetime.utcnow().isoformat()
            }), 429
        
        # Otherwise, flash a message and redirect
        flash(message, 'error')
        return redirect(request.referrer if request.referrer else url_for('main.dashboard'))
    
    @app.errorhandler(429)
    def too_many_requests(error):
        """Handle standard 429 errors"""
        message = "Too many requests. Please try again in a few minutes."
        
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'error': message,
                'timestamp': datetime.utcnow().isoformat()
            }), 429
        
        flash(message, 'error')
        return redirect(request.referrer if request.referrer else url_for('main.dashboard'))
    
    # Template context processors
    @app.context_processor
    def inject_user():
        return dict(current_user=current_user)
    
    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)

    # Public contact emails (from environment)
    @app.context_processor
    def inject_public_emails():
        domain = (os.environ.get('DOMAIN_NAME') or 'example.com').strip()
        return dict(
            ADMIN_EMAIL=os.environ.get('ADMIN_EMAIL', f'admin@{domain}'),
            REGISTRATION_EMAIL=os.environ.get('REGISTRATION_EMAIL', f'registration@{domain}'),
            CONTACT_US_EMAIL=os.environ.get('CONTACT_US_EMAIL', f'contact@{domain}'),
            FEATURES_EMAIL=os.environ.get('FEATURES_EMAIL', f'features@{domain}'),
            FEEDBACK_EMAIL=os.environ.get('FEEDBACK_EMAIL', f'feedback@{domain}'),
            PRIVACY_EMAIL=os.environ.get('PRIVACY_EMAIL', f'privacy@{domain}'),
            SUPPORT_EMAIL=os.environ.get('SUPPORT_EMAIL', f'support@{domain}'),
            TERMS_EMAIL=os.environ.get('TERMS_EMAIL', f'terms@{domain}'),
        )

    @app.context_processor
    def inject_app_name():
        return dict(app_name=os.environ.get('APP_NAME', 'Web App'))
    
    # reCAPTCHA site key for templates
    @app.context_processor
    def inject_recaptcha_keys():
        return dict(
            RECAPTCHA_SITE_KEY=os.environ.get('RECAPTCHA_SITE_KEY') or os.environ.get('RECAPTCHA_PUBLIC_KEY')
        )
    
    # Cache-busting version for static assets (bump ASSETS_VERSION in .env when deploying CSS/JS changes)
    @app.context_processor
    def inject_assets_version():
        return dict(assets_version=os.environ.get('ASSETS_VERSION', '1'))
    
    # Canonical URL context processor for SEO
    @app.context_processor
    def inject_canonical_url():
        """Generate normalized canonical URL for the current page"""
        endpoint = request.endpoint
        if endpoint:
            try:
                # Use url_for to generate clean URL without query parameters
                canonical = url_for(endpoint, _external=True)
            except:
                # Fallback: remove query parameters from current URL
                canonical = request.url.split('?')[0]
        else:
            # Fallback: remove query parameters from current URL
            canonical = request.url.split('?')[0]
        return dict(canonical_url=canonical)
    
    # Initialize database when app is created
    # Only one worker should do this (use file lock to prevent multiple workers from running it)
    import fcntl
    import time
    import atexit
    
    lock_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs', 'db_init.lock')
    lock_file = None
    _db_init_lock_held = False
    
    try:
        # Try to acquire exclusive lock (non-blocking)
        lock_file = open(lock_file_path, 'w')
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # We got the lock - this worker will initialize the database
            _db_init_lock_held = True
            logger.info("Acquired database initialization lock - this worker will initialize the database")
            try:
                from setup_database import init_db
                init_db()
                logger.info("Database initialization completed by this worker")
                # Keep lock for a few seconds to ensure other workers have started and see it
                # Gunicorn workers typically start within 1-2 seconds of each other
                time.sleep(3)
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                # Don't exit here - let the app start even if DB init fails
            finally:
                # Release the lock
                if _db_init_lock_held:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    _db_init_lock_held = False
                lock_file.close()
                # Clean up lock file
                try:
                    if os.path.exists(lock_file_path):
                        os.remove(lock_file_path)
                except:
                    pass
        except BlockingIOError:
            # Another worker has the lock - wait a moment and check if initialization is done
            lock_file.close()
            time.sleep(0.5)  # Brief wait for the other worker to finish
            # Check if lock file still exists (if it does, initialization might still be in progress)
            if os.path.exists(lock_file_path):
                logger.info("Another worker is initializing the database - skipping initialization")
            else:
                # Lock was released, but we'll skip anyway to avoid race conditions
                logger.info("Database initialization was completed by another worker - skipping")
    except Exception as e:
        logger.warning(f"Could not acquire database initialization lock: {e} - attempting initialization anyway")
        # Fallback: try to initialize if lock fails (for development or if fcntl not available)
        try:
            from setup_database import init_db
            init_db()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    # Ensure lock is released on exit
    def cleanup_lock():
        global _db_init_lock_held, lock_file
        if _db_init_lock_held and lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except:
                pass
            _db_init_lock_held = False
        try:
            if os.path.exists(lock_file_path):
                os.remove(lock_file_path)
        except:
            pass
    
    atexit.register(cleanup_lock)
    
    # Register shutdown handler to close database pool gracefully
    import signal
    import sys
    
    # Flag to prevent multiple close attempts
    _pool_closed = False
    
    def close_database_pool(signum=None, frame=None):
        """Close database connection pool on application shutdown"""
        global _pool_closed
        if _pool_closed:
            return
        _pool_closed = True
        
        try:
            from database import db_manager
            logger.info("Closing database connection pool...")
            db_manager.close()
        except Exception as e:
            logger.error(f"Error closing database pool: {e}")
        if signum:
            sys.exit(0)
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, close_database_pool)
    signal.signal(signal.SIGINT, close_database_pool)
    
    # Also register atexit as backup
    import atexit
    atexit.register(close_database_pool)
    
    return app

# Create the app
app = create_app()

if __name__ == "__main__":
    # Run the app (database initialization now happens in create_app())
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5099))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    logger.info("Starting %s on %s:%s", os.environ.get("APP_NAME", "Web App"), host, port)
    print(f"🚀 Starting {os.environ.get('APP_NAME', 'Web App')} on {host}:{port}")
    
    app.run(host=host, port=port, debug=debug)
