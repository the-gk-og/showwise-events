# ShowWise Events — Website

Flask-based website for ShowWise Events.

## Setup

```bash
# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure email (see below), then run
python app.py
```

Then open http://localhost:5000 in your browser.

## Email Configuration

The contact form sends enquiries to **Events@showwise.app**.

Set these environment variables before running the app:

```bash
export MAIL_SERVER=smtp.your-provider.com
export MAIL_PORT=587
export MAIL_USERNAME=your-sending-address@domain.com
export MAIL_PASSWORD=your-password-or-app-password
export SECRET_KEY=a-long-random-secret-string
```

**Common SMTP settings:**

| Provider | MAIL_SERVER | MAIL_PORT |
|---|---|---|
| Gmail (App Password) | smtp.gmail.com | 587 |
| Outlook / Microsoft 365 | smtp.office365.com | 587 |
| Zoho Mail | smtp.zoho.com | 587 |
| Cloudflare Email | smtp.cloudflare.com | 587 |

> **Gmail tip:** Use an App Password (not your account password). Go to Google Account → Security → 2-Step Verification → App Passwords.

If email sending fails, the site shows an error flash directing users to email Events@showwise.app directly.

## Email Addresses

- **Events@showwise.app** — receives all contact form submissions
- **info@showwise.app** — displayed in footer and contact page for general enquiries

## Structure

```
showwise-events/
├── app.py                  # Flask app & routes
├── requirements.txt
├── templates/
│   ├── base.html           # Shared nav, footer, layout
│   ├── index.html          # Homepage
│   ├── services.html       # Services page
│   ├── about.html          # About page
│   └── contact.html        # Contact form
└── static/
    ├── css/style.css       # All styles
    ├── js/main.js          # JS (nav, scroll animations)
    └── img/logo.png        # ShowWise Events logo
```

## Production

```bash
pip install gunicorn
gunicorn app:app
```

