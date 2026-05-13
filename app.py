from flask import Flask, render_template, request, flash, redirect, url_for, abort
from flask_mail import Mail, Message
from collections import defaultdict
import os
import time
import requests as http_requests
import logging

# ── App setup ────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-production')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Email configuration ──────────────────────────────────────────────────────
# Required env vars:
#   MAIL_SERVER      e.g. smtp.office365.com
#   MAIL_PORT        e.g. 587
#   MAIL_USERNAME    the sending address
#   MAIL_PASSWORD    SMTP password / app password
app.config['MAIL_SERVER']        = os.environ.get('MAIL_SERVER', 'smtp.office365.com')
app.config['MAIL_PORT']          = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']       = True
app.config['MAIL_USE_SSL']       = False
app.config['MAIL_USERNAME']      = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD']      = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = ('ShowWise Events Website', os.environ.get('MAIL_USERNAME', ''))

EVENTS_EMAIL = 'Events@showwise.app'

# ── Cloudflare Turnstile ─────────────────────────────────────────────────────
# Get these from: https://dash.cloudflare.com → Turnstile
# TURNSTILE_SITE_KEY   → goes in the HTML template
# TURNSTILE_SECRET_KEY → used server-side to verify the token
TURNSTILE_SITE_KEY   = os.environ.get('TURNSTILE_SITE_KEY', '')
TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY', '')
TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'

mail = Mail(app)

# ── Rate limiting (in-memory) ─────────────────────────────────────────────────
# Tracks (timestamp, count) per IP. Simple sliding-window approach.
# For multi-worker deployments, swap this for Redis via flask-limiter.
_rate_store: dict[str, list[float]] = defaultdict(list)

RATE_LIMIT        = 5     # max submissions per IP
RATE_WINDOW       = 3600  # within this many seconds (1 hour)
RATE_BLOCK_AFTER  = 10    # hard-block IP if they exceed this many attempts


def get_client_ip() -> str:
    """
    Always trust CF-Connecting-IP when behind Cloudflare Tunnel.
    Fall back to X-Forwarded-For, then REMOTE_ADDR.
    Never trust X-Forwarded-For from arbitrary proxies without CF in front.
    """
    cf_ip = request.headers.get('CF-Connecting-IP')
    if cf_ip:
        return cf_ip.strip()
    xfwd = request.headers.get('X-Forwarded-For')
    if xfwd:
        return xfwd.split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'


def check_rate_limit(ip: str) -> tuple[bool, bool]:
    """
    Returns (is_rate_limited, is_hard_blocked).
    Cleans up old entries as it goes.
    """
    now = time.time()
    window_start = now - RATE_WINDOW
    timestamps = _rate_store[ip]

    # Prune old entries
    _rate_store[ip] = [t for t in timestamps if t > window_start]
    count = len(_rate_store[ip])

    if count >= RATE_BLOCK_AFTER:
        return True, True
    if count >= RATE_LIMIT:
        return True, False
    return False, False


def record_attempt(ip: str) -> None:
    _rate_store[ip].append(time.time())


def verify_turnstile(token: str, ip: str) -> bool:
    """
    Verify a Turnstile token with Cloudflare's siteverify endpoint.
    Returns True if valid, False otherwise.
    Skips verification if no secret key is configured (dev mode).
    """
    if not TURNSTILE_SECRET_KEY:
        logger.warning("Turnstile secret key not set — skipping verification (dev mode)")
        return True
    try:
        resp = http_requests.post(
            TURNSTILE_VERIFY_URL,
            data={
                'secret':   TURNSTILE_SECRET_KEY,
                'response': token,
                'remoteip': ip,
            },
            timeout=5,
        )
        result = resp.json()
        if not result.get('success'):
            logger.warning("Turnstile verification failed: %s", result.get('error-codes'))
        return result.get('success', False)
    except Exception as e:
        logger.error("Turnstile request error: %s", e)
        return False


# ── Security headers ──────────────────────────────────────────────────────────

@app.after_request
def set_security_headers(response):
    # Don't cache pages that might contain flash messages
    if request.method == 'POST':
        response.headers['Cache-Control'] = 'no-store'

    response.headers['X-Content-Type-Options']  = 'nosniff'
    response.headers['X-Frame-Options']          = 'SAMEORIGIN'
    response.headers['Referrer-Policy']          = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']       = 'geolocation=(), microphone=(), camera=()'

    # Content Security Policy
    # Turnstile needs challenges.cloudflare.com; fonts from Google
    csp = (
        "default-src 'self'; "
        "script-src 'self' https://challenges.cloudflare.com; "
        "frame-src https://challenges.cloudflare.com; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    response.headers['Content-Security-Policy'] = csp

    return response


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/services')
def services():
    return render_template('services.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        client_ip = get_client_ip()

        # ── Rate limiting ────────────────────────────────────────────────────
        limited, hard_blocked = check_rate_limit(client_ip)
        record_attempt(client_ip)

        if hard_blocked:
            logger.warning("Hard-blocked IP %s attempted contact form", client_ip)
            abort(429)

        if limited:
            logger.warning("Rate-limited IP %s on contact form", client_ip)
            flash("Too many submissions from your connection. Please try again later or email us directly at Events@showwise.app.", 'error')
            return redirect(url_for('contact'))

        # ── Turnstile verification ───────────────────────────────────────────
        turnstile_token = request.form.get('cf-turnstile-response', '')
        if not verify_turnstile(turnstile_token, client_ip):
            logger.warning("Turnstile failed for IP %s", client_ip)
            flash("Security check failed. Please try again.", 'error')
            return redirect(url_for('contact'))

        # ── Form data ────────────────────────────────────────────────────────
        name    = request.form.get('name', '').strip()[:200]
        email   = request.form.get('email', '').strip()[:200]
        service = request.form.get('service', '').strip()
        message = request.form.get('message', '').strip()[:5000]

        if not name or not email or not message:
            flash("Please fill in all required fields.", 'error')
            return redirect(url_for('contact'))

        service_labels = {
            'consulting': 'AV / Technical Consulting',
            'operators':  'Operators (Audio, Lighting, Vision)',
            'management': 'Event Management & Operations',
            'hire':       'Hire & Supplier Connections',
            'other':      'Something else / Not sure',
        }
        service_label = service_labels.get(service, 'Not specified')

        body = (
            f"New enquiry from the ShowWise Events website.\n\n"
            f"Name:    {name}\n"
            f"Email:   {email}\n"
            f"Service: {service_label}\n"
            f"IP:      {client_ip}\n\n"
            f"Message:\n{message}\n"
        )

        # ── Send email ───────────────────────────────────────────────────────
        try:
            msg = Message(
                subject=f"[ShowWise Events] Enquiry from {name}",
                recipients=[EVENTS_EMAIL],
                reply_to=email,
                body=body,
            )
            mail.send(msg)
            logger.info("Contact form sent from %s (%s)", email, client_ip)
            flash(f"Thanks {name}, we'll be in touch shortly!", 'success')
        except Exception as e:
            logger.error("Mail send failed: %s", e)
            flash("Your message couldn't be sent right now — please email us directly at Events@showwise.app.", 'error')

        return redirect(url_for('contact'))

    return render_template('contact.html', turnstile_site_key=TURNSTILE_SITE_KEY)


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(429)
def too_many_requests(e):
    return render_template('429.html'), 429


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


if __name__ == '__main__':
    app.run(debug=True)
