"""Amiri Insurance Flask app.

templates/  — HTML pages
static/     — css, js, img, lib, uploads
"""

from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote, urlparse

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import WSGIRequestHandler
from werkzeug.utils import secure_filename

import db
import mail
import crm
import security

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = ROOT / "static" / "uploads" / "blog"
UPLOAD_URL = "/static/uploads/blog/"

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
PROTECTED_TEMPLATES = {"admin.html", "admin-blog.html", "post-blog.html", "invoice.html"}
PAGE_ROUTES = {
    "about": "about.html",
    "partners": "partners.html",
    "cover": "service.html",
    "services": "service.html",
    "health": "health.html",
    "motor": "mortorvehicle.html",
    "property": "property.html",
    "group-life": "lifeassurance.html",
    "wiba": "wiba.html",
    "money": "moneyinsurance.html",
    "quote": "appointment.html",
    "appointment": "appointment.html",
    "insights": "blog.html",
    "blog": "blog.html",
    "contact": "contact.html",
    "team": "team.html",
    "testimonials": "testimonial.html",
    "features": "feature.html",
    "blogs": "blogs.html",
}
LEGACY_HTML_REDIRECTS = {
    "index.html": "/",
    "about.html": "/about",
    "clients.html": "/about",
    "partners.html": "/partners",
    "service.html": "/cover",
    "health.html": "/health",
    "mortorvehicle.html": "/motor",
    "property.html": "/property",
    "lifeassurance.html": "/group-life",
    "wiba.html": "/wiba",
    "moneyinsurance.html": "/money",
    "appointment.html": "/quote",
    "blog.html": "/insights",
    "blogs.html": "/insights",
    "blog-listing.html": "/insights",
    "blog-post.html": "/insights/post",
    "contact.html": "/contact",
    "team.html": "/team",
    "testimonial.html": "/testimonials",
    "feature.html": "/features",
    "admin.html": "/admin",
    "admin-login.html": "/admin/login",
    "admin-blog.html": "/admin",
    "post-blog.html": "/admin/post",
}
LOGIN_NEXT = {
    "admin.html": "/admin",
    "post-blog.html": "/admin/post",
    "admin-blog.html": "/admin",
}
COVER_TYPES = {
    "Health Insurance",
    "Motor Insurance",
    "Property Insurance",
    "Group Life",
    "WIBA",
    "Money Insurance",
    "Other",
}
REQUEST_STATUSES = {"new", "contacted", "quoted", "won", "closed"}


load_dotenv(ROOT / ".env")

WEAK_SECRETS = {"", "change-this-to-a-long-random-string", "secret", "changeme"}
WEAK_ADMIN_PASSWORDS = {"", "admin@amiri123", "admin", "password"}


def env_flag(name: str, default: str = "0") -> bool:
    return (os.environ.get(name) or default).strip().lower() in {"1", "true", "yes", "on"}


def running_production() -> bool:
    env = (os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or "").strip().lower()
    return env == "production"


def assert_deploy_ready() -> None:
    if not running_production():
        return
    secret = (os.environ.get("SECRET_KEY") or "").strip()
    if secret in WEAK_SECRETS or len(secret) < 24:
        raise RuntimeError("Set SECRET_KEY to a long random string before deploying.")
    password = (os.environ.get("ADMIN_PASSWORD") or "").strip()
    if password in WEAK_ADMIN_PASSWORDS:
        raise RuntimeError("Set a strong ADMIN_PASSWORD before deploying.")
    if not (os.environ.get("DATABASE_URL") or "").strip():
        raise RuntimeError("Set DATABASE_URL before deploying.")


class QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        if self.path.startswith("/json/"):
            return
        super().log_request(code, size)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.url_map.strict_slashes = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "admin")
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
_public_url = (os.environ.get("PUBLIC_URL") or "").rstrip("/")
_https = (
    running_production()
    or _public_url.startswith("https://")
    or env_flag("SESSION_COOKIE_SECURE")
)
app.config["PUBLIC_URL"] = _public_url
app.config["PREFERRED_URL_SCHEME"] = "https" if _https else "http"
app.config["SESSION_COOKIE_SECURE"] = _https
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=int(os.environ.get("SESSION_HOURS") or "12"))
IDLE_MINUTES = int(os.environ.get("SESSION_IDLE_MINUTES") or "60")
if env_flag("BEHIND_PROXY", "1"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

_db_ready = False


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers.pop("Server", None)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://code.jquery.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "connect-src 'self'; frame-ancestors 'self'"
    )
    if _https or running_production():
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.before_request
def block_private_uploads():
    if security.is_private_upload_path(request.path):
        abort(404)


@app.before_request
def enforce_csrf_and_session():
    if request.path.startswith("/static"):
        return
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        public = request.path in {"/api/auth/login", "/api/auth/mfa", "/api/requests", "/api/subscribers", "/api/form-token"}
        cron = request.path.startswith("/api/cron/")
        if not public and not cron and not security.csrf_allowed(request, os.environ.get("ALLOWED_HOSTS") or ""):
            return jsonify({"success": False, "message": "Rejected cross-site request."}), 403
    if not logged_in():
        return
    now = int(datetime.now().timestamp())
    last = int(session.get("last_seen") or now)
    if now - last > IDLE_MINUTES * 60:
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "Session expired. Sign in again."}), 401
        return redirect("/admin/login")
    session["last_seen"] = now
    try:
        user = db.find_user_by_username(str(session.get("admin_username") or ""))
    except Exception:
        return
    if not user or not user.get("active"):
        session.clear()
        return
    if int(session.get("session_version") or 0) != int(user.get("session_version") or 1):
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "Session expired. Sign in again."}), 401
        return redirect("/admin/login")


@app.before_request
def ensure_db():
    global _db_ready
    if request.path.startswith("/static") or request.path.startswith("/json/"):
        return
    needs_db = request.path.startswith("/api/") or request.path.startswith("/admin")
    if _db_ready:
        return
    if not needs_db:
        return
    try:
        db.init_db()
        _db_ready = True
    except Exception:
        if request.path.startswith("/api/auth/"):
            return
        if request.path.startswith("/api/"):
            return jsonify({
                "success": False,
                "message": "PostgreSQL is not ready. Check DATABASE_URL in .env and that the amiri database exists.",
            }), 503
        if request.path.startswith("/admin") and request.path != "/admin/login":
            return redirect("/admin/login")


def logged_in() -> bool:
    return session.get("admin_logged_in") is True


def hydrate_session_user() -> None:
    if not logged_in():
        return
    if session.get("admin_role") and session.get("admin_user_id"):
        return
    try:
        user = db.find_user_by_username(str(session.get("admin_username") or ""))
    except Exception:
        return
    if not user:
        session.clear()
        return
    session["admin_role"] = user.get("role") or "manager"
    session["admin_user_id"] = user["id"]
    session["admin_name"] = user.get("name") or user["username"]
    session["admin_username"] = user["username"]


def current_role() -> str:
    hydrate_session_user()
    return str(session.get("admin_role") or "")


def is_admin() -> bool:
    return logged_in() and current_role() == "admin"


def complete_login(user: dict) -> None:
    session.clear()
    session["admin_logged_in"] = True
    session["admin_username"] = user["username"]
    session["admin_name"] = user.get("name") or user["username"]
    session["admin_role"] = user.get("role") or "manager"
    session["admin_user_id"] = user["id"]
    session["session_version"] = int(user.get("session_version") or 1)
    session["last_seen"] = int(datetime.now().timestamp())
    session.permanent = True


def login_required_api(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return jsonify({"success": False, "message": "Authentication required"}), 401
        return fn(*args, **kwargs)

    return wrapper


def admin_required_api(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return jsonify({"success": False, "message": "Authentication required"}), 401
        if not is_admin():
            return jsonify({"success": False, "message": "Only an admin can manage users"}), 403
        return fn(*args, **kwargs)

    return wrapper


def template_exists(name: str) -> bool:
    return (ROOT / "templates" / name).is_file()


def read_posts() -> list:
    return db.read_posts()


def read_requests() -> list:
    return db.read_requests()


def read_subscribers() -> list:
    return db.read_subscribers()


def clean_text(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()[:limit]


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    return digits[:15]


def request_from_payload(data: dict) -> dict:
    if data.get("website"):
        raise ValueError("Invalid submission")
    name = clean_text(str(data.get("name") or ""), 80)
    email = clean_text(str(data.get("email") or ""), 120).lower()
    mobile = normalize_phone(str(data.get("mobile") or data.get("phone") or ""))
    cover = clean_text(str(data.get("cover") or data.get("insuranceType") or ""), 40)
    message = clean_text(str(data.get("message") or ""), 1000)
    pref_date = clean_text(str(data.get("prefDate") or ""), 20)
    pref_time = clean_text(str(data.get("prefTime") or ""), 20)
    source = clean_text(str(data.get("source") or "website"), 40)
    errors = []
    if len(name) < 2:
        errors.append("Name is required")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        errors.append("A valid email is required")
    if cover not in COVER_TYPES:
        cover = "Other"
    if len(mobile) < 9:
        mobile = ""
    if errors:
        raise ValueError(json.dumps(errors))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "email": email,
        "mobile": mobile,
        "cover": cover,
        "message": message,
        "prefDate": pref_date,
        "prefTime": pref_time,
        "source": source,
        "status": "new",
        "notes": "",
        "createdAt": now,
        "updatedAt": now,
    }


def team_notify_emails() -> list[str]:
    extra = []
    try:
        extra = [
            user.get("email") or ""
            for user in db.list_users()
            if user.get("active") and user.get("role") == "admin" and user.get("email")
        ]
    except Exception:
        extra = []
    return mail.notify_emails(extra)


def published_posts() -> list:
    return [
        security.sanitize_public_post(p)
        for p in db.read_posts()
        if isinstance(p, dict) and p.get("status") == "published"
    ]


def request_ip() -> str:
    return security.client_ip(request, env_flag("BEHIND_PROXY", "1"))


def too_many(kind: str, limit: int, window: int = 900):
    bucket = f"{kind}:{request_ip()}"
    if security.rate_limited(bucket, limit, window):
        return jsonify({"success": False, "message": "Too many attempts. Please wait and try again."}), 429
    return None


def site_base_url() -> str:
    return security.public_base_url(
        app.config.get("PUBLIC_URL") or "",
        request.host,
        request.host_url,
        os.environ.get("ALLOWED_HOSTS") or "",
    )


def slugify(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", (title or "").strip()).strip("-").lower()
    return slug or "post"


def sanitize_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if len(value) > 500:
        value = value[:500]
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value


def save_upload(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        return ""
    filename = secure_filename(file_storage.filename)
    raw = file_storage.read()
    file_storage.stream.seek(0)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("File too large. Maximum size is 5MB.")
    sniffed = security.sniff_upload(raw)
    if not sniffed or sniffed not in ALLOWED_IMAGE_EXT:
        raise ValueError("Invalid file type. Use JPG, PNG, GIF, or WebP.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}_{int(datetime.now().timestamp())}{sniffed}"
    (UPLOAD_DIR / stored).write_bytes(raw)
    return UPLOAD_URL + stored


def post_from_form() -> dict:
    title = (request.form.get("title") or "").strip()
    content = request.form.get("content") or ""
    author = (request.form.get("author") or "").strip()
    category = (request.form.get("category") or "").strip()
    errors = []
    if not title:
        errors.append("Blog title is required")
    if not content.strip():
        errors.append("Blog content is required")
    if not author:
        errors.append("Author name is required")
    if not category:
        errors.append("Category is required")
    image_path = ""
    if "image" in request.files:
        try:
            image_path = save_upload(request.files["image"])
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError(json.dumps(errors))
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "content": security.sanitize_html(content),
        "excerpt": (request.form.get("excerpt") or "").strip(),
        "author": author,
        "authorBio": (request.form.get("authorBio") or "").strip()[:800],
        "authorSocial": {
            "linkedin": sanitize_url(request.form.get("authorLinkedin") or ""),
            "twitter": sanitize_url(request.form.get("authorTwitter") or ""),
            "website": sanitize_url(request.form.get("authorWebsite") or ""),
        },
        "category": category,
        "tags": (request.form.get("tags") or "").strip(),
        "image": image_path,
        "publishDate": (request.form.get("publishDate") or "").strip()
        or datetime.now().strftime("%Y-%m-%d"),
        "metaDescription": (request.form.get("metaDescription") or "").strip(),
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": (request.form.get("status") or "pending").strip() or "pending",
        "slug": slugify(title),
    }


def render_page(template: str):
    if template in PROTECTED_TEMPLATES and not logged_in():
        nxt = LOGIN_NEXT.get(template, "/admin")
        return redirect("/admin/login?next=" + quote(nxt))
    if not template_exists(template):
        abort(404)
    return render_template(template)


def redirect_with_query(path: str):
    query = request.query_string.decode("utf-8")
    if query:
        return redirect(f"{path}?{query}", 301)
    return redirect(path, 301)


@app.get("/api/auth/status")
def auth_status():
    hydrate_session_user()
    return jsonify(
        {
            "success": True,
            "logged_in": logged_in(),
            "username": session.get("admin_username"),
            "name": session.get("admin_name"),
            "role": session.get("admin_role"),
            "user_id": session.get("admin_user_id"),
        }
    )


@app.post("/api/auth/login")
def auth_login():
    blocked = too_many("login", 5, 900)
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()
    try:
        user = db.authenticate_user(username, password)
    except Exception:
        return jsonify({"success": False, "message": "Could not reach the database. Start PostgreSQL and try again."}), 503
    if not user:
        return jsonify({"success": False, "message": "Invalid username or password"}), 401
    security.clear_rate(f"login:{request_ip()}")
    session.clear()
    session["mfa_pending"] = user["id"]
    session["last_seen"] = int(datetime.now().timestamp())
    if user.get("mfa_enabled") and user.get("mfa_secret"):
        return jsonify({"success": True, "mfaRequired": True, "message": "Enter the 6-digit code from your authenticator."})
    secret = security.new_totp_secret()
    session["mfa_setup_secret"] = secret
    return jsonify({
        "success": True,
        "mfaSetup": True,
        "secret": secret,
        "otpauth": security.otpauth_url(user["username"], secret),
        "message": "Scan this code in Google Authenticator or Authy, then enter the 6-digit code.",
    })


@app.post("/api/auth/mfa")
def auth_mfa():
    blocked = too_many("mfa", 8, 900)
    if blocked:
        return blocked
    user_id = session.get("mfa_pending")
    if not user_id:
        return jsonify({"success": False, "message": "Sign in with your password first."}), 401
    data = request.get_json(silent=True) or {}
    code = str(data.get("code") or "")
    try:
        with db.pool().connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        user = dict(row) if row else None
    except Exception:
        return jsonify({"success": False, "message": "Could not reach the database."}), 503
    if not user or not user.get("active"):
        session.clear()
        return jsonify({"success": False, "message": "Account is not available."}), 401
    setup_secret = session.get("mfa_setup_secret") or ""
    secret = setup_secret or (user.get("mfa_secret") or "")
    if not security.totp_valid(secret, code):
        return jsonify({"success": False, "message": "That code is not valid. Try the next one."}), 401
    if setup_secret:
        db.set_user_mfa(user["id"], setup_secret, True)
        user["mfa_enabled"] = True
        user["mfa_secret"] = setup_secret
    db.write_audit(user["id"], "login", user["username"], ip=request_ip())
    complete_login(user)
    return jsonify({"success": True, "message": "Login successful"})


@app.route("/api/auth/logout", methods=["POST", "DELETE"])
@app.route("/logout", methods=["GET", "POST"])
def auth_logout():
    if request.method == "GET" and request.path == "/logout":
        return redirect("/admin/login")
    session.clear()
    if request.path.startswith("/api/"):
        return jsonify({"success": True, "message": "Logged out successfully"})
    return redirect("/admin/login")


@app.get("/api/posts")
def list_public_posts():
    return jsonify(published_posts())


@app.get("/api/posts/<post_id>")
def get_public_post(post_id: str):
    for post in published_posts():
        if str(post.get("id")) == post_id or str(post.get("slug")) == post_id:
            return jsonify(post)
    return jsonify({"success": False, "message": "Post not found"}), 404


@app.post("/api/posts")
@login_required_api
def create_post():
    try:
        post = post_from_form()
    except ValueError as exc:
        try:
            errors = json.loads(str(exc))
        except json.JSONDecodeError:
            errors = [str(exc)]
        return jsonify({"success": False, "message": "Validation failed", "errors": errors}), 400
    db.insert_post(post)
    return jsonify(
        {
            "success": True,
            "message": "Blog post saved. Review it in the admin dashboard to publish.",
            "postId": post["id"],
        }
    )


@app.get("/api/form-token")
def issue_form_token():
    return jsonify({"token": security.form_token()})


@app.post("/api/requests")
def create_request():
    blocked = too_many("quote", 8, 900)
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    if not security.form_token_valid(str(data.get("formToken") or "")):
        return jsonify({"success": False, "message": "Refresh the page and try again."}), 400
    try:
        item = request_from_payload(data)
    except ValueError as exc:
        try:
            errors = json.loads(str(exc))
        except json.JSONDecodeError:
            errors = [str(exc)]
        return jsonify({"success": False, "message": "Please check the form.", "errors": errors}), 400
    db.insert_request(item)
    crm.create_lead_from_request(item)
    mail.notify_quote(item, team_notify_emails())
    return jsonify(
        {
            "success": True,
            "message": "We received your request and will get back immediately.",
            "id": item["id"],
        }
    )


@app.get("/api/admin/requests")
@login_required_api
def admin_list_requests():
    return jsonify(security.paginate(
        db.read_requests(),
        int(request.args.get("page") or 1),
        int(request.args.get("limit") or 200),
    ))


@app.patch("/api/admin/requests/<req_id>")
@login_required_api
def admin_update_request(req_id: str):
    data = request.get_json(silent=True) or {}
    current = next((item for item in db.read_requests() if str(item.get("id")) == req_id), None)
    if not current:
        return jsonify({"success": False, "message": "Request not found"}), 404
    status = clean_text(str(data.get("status") or current.get("status") or "new"), 20)
    if status not in REQUEST_STATUSES:
        return jsonify({"success": False, "message": "Invalid status"}), 400
    notes = clean_text(str(data.get("notes") or ""), 2000) if "notes" in data else None
    item = db.update_request(req_id, status, notes)
    lead = None
    if item:
        if not crm.get_lead(req_id):
            crm.create_lead_from_request(item)
        lead = crm.apply_lead_status(req_id, status, notes)
        mail.notify_status(item, current.get("status") or "")
    return jsonify({"success": True, "request": item, "lead": lead})


@app.delete("/api/admin/requests/<req_id>")
@login_required_api
def admin_delete_request(req_id: str):
    if not db.delete_request(req_id):
        return jsonify({"success": False, "message": "Request not found"}), 404
    return jsonify({"success": True, "message": "Request removed"})


@app.post("/api/subscribers")
def create_subscriber():
    blocked = too_many("newsletter", 8, 900)
    if blocked:
        return blocked
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    if data.get("website"):
        return jsonify({"success": True, "message": "Thank you for subscribing."})
    token = str(data.get("formToken") or data.get("token") or "")
    if not security.form_token_valid(token):
        return jsonify({"success": False, "message": "Refresh the page and try again."}), 400
    email = clean_text(str(data.get("email") or data.get("EMAIL") or ""), 120).lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"success": False, "message": "Enter a valid email."}), 400
    _, created = db.add_subscriber(email)
    mail.notify_newsletter(email, created, team_notify_emails())
    if not created:
        return jsonify({"success": True, "message": "You are already on the list."})
    return jsonify({"success": True, "message": "Thank you for subscribing. We will keep you posted."})


@app.get("/api/admin/subscribers")
@login_required_api
def admin_list_subscribers():
    return jsonify(security.paginate(
        db.read_subscribers(),
        int(request.args.get("page") or 1),
        int(request.args.get("limit") or 200),
    ))


@app.get("/api/admin/overview")
@login_required_api
def admin_overview():
    posts = read_posts()
    bookings = read_requests()
    subscribers = read_subscribers()
    return jsonify(
        {
            "requests": {
                "total": len(bookings),
                "new": sum(1 for row in bookings if row.get("status") == "new"),
                "contacted": sum(1 for row in bookings if row.get("status") == "contacted"),
                "quoted": sum(1 for row in bookings if row.get("status") == "quoted"),
                "won": sum(1 for row in bookings if row.get("status") == "won"),
            },
            "posts": {
                "total": len(posts),
                "pending": sum(1 for row in posts if row.get("status") == "pending"),
                "published": sum(1 for row in posts if row.get("status") == "published"),
                "draft": sum(1 for row in posts if row.get("status") == "draft"),
            },
            "subscribers": len(subscribers),
            "recentRequests": sorted(
                bookings, key=lambda row: str(row.get("createdAt") or ""), reverse=True
            )[:6],
        }
    )


@app.get("/api/admin/posts")
@login_required_api
def admin_list_posts():
    return jsonify(security.paginate(
        db.read_posts(),
        int(request.args.get("page") or 1),
        int(request.args.get("limit") or 200),
    ))


@app.put("/api/admin/posts")
@login_required_api
def admin_save_posts():
    posts = request.get_json(silent=True)
    if not isinstance(posts, list):
        return jsonify({"success": False, "message": "Invalid JSON data"}), 400
    cleaned = []
    for item in posts:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        row = dict(item)
        row["content"] = security.sanitize_html(str(row.get("content") or ""))
        row["title"] = security.plain_text(str(row.get("title") or ""), 160)
        if row.get("status") == "published" and not is_admin():
            row["status"] = "pending"
        cleaned.append(row)
    db.replace_posts(cleaned)
    return jsonify({"success": True, "message": "Blog posts saved successfully"})


@app.get("/api/admin/users")
@admin_required_api
def admin_list_users():
    return jsonify(db.list_users())


@app.post("/api/admin/users")
@admin_required_api
def admin_create_user():
    data = request.get_json(silent=True) or {}
    username = clean_text(str(data.get("username") or ""), 40).lower()
    password = str(data.get("password") or "")
    name = clean_text(str(data.get("name") or ""), 80)
    email = clean_text(str(data.get("email") or ""), 120).lower()
    role = clean_text(str(data.get("role") or "manager"), 20)
    if len(username) < 3 or not re.match(r"^[a-z0-9._-]+$", username):
        return jsonify({"success": False, "message": "Use a username of at least 3 letters or numbers"}), 400
    if len(password) < 12:
        return jsonify({"success": False, "message": "Password must be at least 12 characters"}), 400
    if role not in db.USER_ROLES:
        role = "manager"
    try:
        user = db.create_user(username, password, name or username, email, role)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    mail.notify_new_user(user, site_base_url() + "/admin/login")
    return jsonify({"success": True, "user": user, "message": "User added"})


@app.patch("/api/admin/users/<user_id>")
@admin_required_api
def admin_update_user(user_id: str):
    data = request.get_json(silent=True) or {}
    fields = {}
    if "name" in data:
        fields["name"] = clean_text(str(data.get("name") or ""), 80)
    if "email" in data:
        fields["email"] = clean_text(str(data.get("email") or ""), 120).lower()
    if "role" in data:
        fields["role"] = clean_text(str(data.get("role") or ""), 20)
    if "active" in data:
        fields["active"] = bool(data.get("active"))
    if data.get("resetMfa"):
        fields["resetMfa"] = True
    if data.get("password"):
        password = str(data.get("password") or "")
        if len(password) < 12:
            return jsonify({"success": False, "message": "Password must be at least 12 characters"}), 400
        fields["password"] = password
    try:
        user = db.update_user(user_id, fields)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404
    return jsonify({"success": True, "user": user})


@app.delete("/api/admin/users/<user_id>")
@admin_required_api
def admin_delete_user(user_id: str):
    try:
        db.delete_user(user_id, str(session.get("admin_user_id") or ""))
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "message": "User removed"})


def process_due_renewals(only_id: str | None = None) -> int:
    sent = 0
    if not mail._api_key():
        return 0
    team = team_notify_emails()
    for row in crm.due_renewals(force=bool(only_id)):
        if only_id and row.get("id") != only_id:
            continue
        deal = {
            "service": row.get("service"),
            "premium": row.get("premium"),
            "details": row.get("details"),
            "inception_date": row.get("inception_date"),
            "expiry_date": row.get("expiry_date"),
            "client_type": row.get("client_type"),
            "insurer": row.get("insurer"),
        }
        try:
            body = crm.quote_html(deal, {"name": row.get("name") or ""})
            mail.notify_renewal(
                {
                    "name": row.get("name") or "",
                    "email": row.get("email") or "",
                    "mobile": row.get("mobile") or "",
                    "cover": crm.cover_from_service(row.get("service") or ""),
                    "dueDate": crm.fmt_date(row.get("due_date")),
                },
                body,
                team,
            )
            crm.mark_renewal_sent(row["id"])
            sent += 1
        except Exception:
            print("Renewal notice failed", row.get("id"))
    return sent


def crm_payload(data: dict) -> dict:
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    return {
        "name": clean_text(str(data.get("name") or ""), 80),
        "email": clean_text(str(data.get("email") or ""), 120).lower(),
        "mobile": normalize_phone(str(data.get("mobile") or data.get("phone") or "")),
        "service": clean_text(str(data.get("service") or ""), 40),
        "clientType": clean_text(str(data.get("clientType") or data.get("client_type") or "individual"), 20),
        "ownerId": clean_text(str(data.get("ownerId") or ""), 20) or None,
        "source": clean_text(str(data.get("source") or "staff"), 40),
        "message": clean_text(str(data.get("message") or ""), 1000),
        "notes": clean_text(str(data.get("notes") or ""), 2000),
        "status": clean_text(str(data.get("status") or ""), 20),
        "details": details,
        "insurer": clean_text(str(data.get("insurer") or ""), 80),
        "premium": data.get("premium"),
        "vehicleValue": data.get("vehicleValue"),
        "inceptionDate": clean_text(str(data.get("inceptionDate") or ""), 12),
        "expiryDate": clean_text(str(data.get("expiryDate") or ""), 12),
        "installment": bool(data.get("installment")),
        "kraPin": clean_text(str(data.get("kraPin") or ""), 20),
        "dob": clean_text(str(data.get("dob") or ""), 12),
    }


@app.get("/api/admin/staff")
@login_required_api
def admin_staff():
    return jsonify(crm.list_staff())


def scoped_leads():
    role, actor = current_role(), session.get("admin_user_id")
    rows = [row for row in crm.list_leads() if security.can_see_owner(role, actor, row.get("ownerId"))]
    return security.paginate(rows, int(request.args.get("page") or 1), int(request.args.get("limit") or 200))


def scoped_deals():
    role, actor = current_role(), session.get("admin_user_id")
    rows = [row for row in crm.list_deals() if security.can_see_owner(role, actor, row.get("ownerId"))]
    return security.paginate(rows, int(request.args.get("page") or 1), int(request.args.get("limit") or 200))


def scoped_accounts():
    role, actor = current_role(), session.get("admin_user_id")
    if role == "admin":
        return security.paginate(crm.list_accounts(), int(request.args.get("page") or 1), int(request.args.get("limit") or 200))
    allowed = {row.get("accountId") for row in crm.list_leads() + crm.list_deals() if security.can_see_owner(role, actor, row.get("ownerId"))}
    rows = [row for row in crm.list_accounts() if row.get("id") in allowed]
    return security.paginate(rows, int(request.args.get("page") or 1), int(request.args.get("limit") or 200))


def scoped_invoices():
    role, actor = current_role(), session.get("admin_user_id")
    rows = crm.list_invoices()
    if role != "admin":
        rows = [row for row in rows if (row.get("createdBy") or actor) == actor]
    return security.paginate(rows, int(request.args.get("page") or 1), int(request.args.get("limit") or 200))


def deny_unless_owner(owner_id):
    if security.can_see_owner(current_role(), session.get("admin_user_id"), owner_id):
        return None
    return jsonify({"success": False, "message": "You cannot open that record."}), 403


def deny_unless_account(account_id):
    if is_admin():
        return None
    actor = session.get("admin_user_id")
    allowed = {
        row.get("accountId")
        for row in crm.list_leads() + crm.list_deals()
        if security.can_see_owner(current_role(), actor, row.get("ownerId"))
    }
    if account_id in allowed:
        return None
    return jsonify({"success": False, "message": "You cannot open that record."}), 403


@app.get("/api/admin/crm/dashboard")
@login_required_api
def crm_dashboard():
    owner = None if is_admin() else session.get("admin_user_id")
    return jsonify(crm.dashboard(owner))


@app.get("/api/admin/crm/leads")
@login_required_api
def crm_list_leads():
    return jsonify(scoped_leads())


@app.post("/api/admin/crm/leads")
@login_required_api
def crm_create_lead():
    data = crm_payload(request.get_json(silent=True) or {})
    if not is_admin():
        data["ownerId"] = session.get("admin_user_id")
    try:
        lead = crm.create_lead(data, session.get("admin_user_id"))
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "lead": lead})


@app.get("/api/admin/crm/leads/<lead_id>")
@login_required_api
def crm_get_lead(lead_id: str):
    lead = crm.get_lead(lead_id)
    if not lead:
        return jsonify({"success": False, "message": "Lead not found"}), 404
    denied = deny_unless_owner(lead.get("ownerId"))
    if denied:
        return denied
    return jsonify(lead)


@app.patch("/api/admin/crm/leads/<lead_id>")
@login_required_api
def crm_update_lead(lead_id: str):
    data = request.get_json(silent=True) or {}
    payload = {}
    full = crm_payload(data)
    for key in ("name", "email", "mobile", "service", "clientType", "ownerId", "message", "notes", "status", "details", "kraPin", "dob"):
        if key in data or (key == "clientType" and "client_type" in data):
            payload[key] = full[key]
    previous = crm.get_lead(lead_id)
    if previous:
        denied = deny_unless_owner(previous.get("ownerId"))
        if denied:
            return denied
    if not is_admin():
        payload["ownerId"] = session.get("admin_user_id")
    try:
        lead = crm.update_lead(lead_id, payload, session.get("admin_user_id"))
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    if not lead:
        return jsonify({"success": False, "message": "Lead not found"}), 404
    if previous and lead.get("status") != previous.get("status"):
        mail.notify_status(
            {"name": lead["name"], "email": lead["email"], "cover": lead["cover"], "status": lead["status"]},
            previous.get("status") or "",
        )
    return jsonify({"success": True, "lead": lead})


@app.get("/api/admin/crm/accounts")
@login_required_api
def crm_list_accounts():
    return jsonify(scoped_accounts())


@app.get("/api/admin/crm/accounts/<account_id>")
@login_required_api
def crm_get_account(account_id: str):
    account = crm.get_account(account_id)
    if not account:
        return jsonify({"success": False, "message": "Account not found"}), 404
    denied = deny_unless_account(account_id)
    if denied:
        return denied
    return jsonify(account)


@app.patch("/api/admin/crm/accounts/<account_id>")
@login_required_api
def crm_update_account(account_id: str):
    denied = deny_unless_account(account_id)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    account = crm.update_account(account_id, crm_payload(data))
    if not account:
        return jsonify({"success": False, "message": "Account not found"}), 404
    return jsonify({"success": True, "account": account})


@app.get("/api/admin/crm/deals")
@login_required_api
def crm_list_deals():
    return jsonify(scoped_deals())


@app.get("/api/admin/crm/deals/<deal_id>")
@login_required_api
def crm_get_deal(deal_id: str):
    deal = crm.get_deal(deal_id)
    if not deal:
        return jsonify({"success": False, "message": "Deal not found"}), 404
    denied = deny_unless_owner(deal.get("ownerId"))
    if denied:
        return denied
    return jsonify(deal)


@app.patch("/api/admin/crm/deals/<deal_id>")
@login_required_api
def crm_update_deal(deal_id: str):
    data = request.get_json(silent=True) or {}
    payload = {}
    full = crm_payload(data)
    for key in ("service", "clientType", "ownerId", "insurer", "premium", "vehicleValue", "inceptionDate", "expiryDate", "installment", "details", "kraPin", "dob"):
        if key in data:
            payload[key] = full[key]
    current = crm.get_deal(deal_id)
    if current:
        denied = deny_unless_owner(current.get("ownerId"))
        if denied:
            return denied
    if not is_admin():
        payload["ownerId"] = session.get("admin_user_id")
    deal = crm.update_deal(deal_id, payload)
    if not deal:
        return jsonify({"success": False, "message": "Deal not found"}), 404
    return jsonify({"success": True, "deal": deal})


@app.post("/api/admin/crm/deals/<deal_id>/payments")
@login_required_api
def crm_add_payment(deal_id: str):
    current = crm.get_deal(deal_id)
    if not current:
        return jsonify({"success": False, "message": "Deal not found"}), 404
    denied = deny_unless_owner(current.get("ownerId"))
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        deal = crm.add_payment(
            deal_id,
            {
                "method": data.get("method") or "mpesa",
                "mpesaCode": clean_text(str(data.get("mpesaCode") or ""), 40),
                "amount": data.get("amount"),
                "paidAt": clean_text(str(data.get("paidAt") or ""), 12),
                "notes": clean_text(str(data.get("notes") or ""), 400),
            },
            session.get("admin_user_id"),
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "deal": deal})


@app.post("/api/admin/crm/files")
@login_required_api
def crm_upload_file():
    kind = clean_text(str(request.form.get("kind") or ""), 40)
    parent = {
        "leadId": clean_text(str(request.form.get("leadId") or ""), 20) or None,
        "dealId": clean_text(str(request.form.get("dealId") or ""), 20) or None,
        "accountId": clean_text(str(request.form.get("accountId") or ""), 20) or None,
    }
    if not parent["leadId"] and not parent["dealId"]:
        return jsonify({"success": False, "message": "Attach the file to a lead or deal"}), 400
    if parent["leadId"]:
        lead = crm.get_lead(parent["leadId"])
        denied = deny_unless_owner((lead or {}).get("ownerId"))
        if denied:
            return denied
    if parent["dealId"]:
        deal = crm.get_deal(parent["dealId"])
        denied = deny_unless_owner((deal or {}).get("ownerId"))
        if denied:
            return denied
    upload = request.files.get("file")
    try:
        result = crm.save_file(parent, kind, upload)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, **result})


@app.get("/api/admin/crm/files/<file_id>")
@login_required_api
def crm_download_file(file_id: str):
    row = crm.get_file(file_id)
    if not row:
        abort(404)
    owner = ""
    if row.get("lead_id"):
        lead = crm.get_lead(row["lead_id"])
        owner = (lead or {}).get("ownerId") or ""
    elif row.get("deal_id"):
        deal = crm.get_deal(row["deal_id"])
        owner = (deal or {}).get("ownerId") or ""
    denied = deny_unless_owner(owner)
    if denied:
        return denied
    stored = row.get("stored_name") or ""
    if ".." in stored or "/" in stored or "\\" in stored:
        abort(404)
    path = crm.CRM_UPLOAD_DIR / stored
    if not path.is_file():
        abort(404)
    try:
        payload = security.decrypt_bytes(path.read_bytes())
    except ValueError:
        abort(404)
    name = secure_filename(row.get("original_name") or stored) or "document"
    db.write_audit(session.get("admin_user_id"), "file_download", file_id, name, request_ip())
    return Response(
        payload,
        mimetype="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/admin/crm/renewals/<renewal_id>/send")
@login_required_api
def crm_send_renewal(renewal_id: str):
    rows = [row for row in crm.due_renewals(force=True) if row["id"] == renewal_id]
    if not rows:
        return jsonify({"success": False, "message": "Renewal not found or not due"}), 404
    denied = deny_unless_owner(rows[0].get("owner_id") or rows[0].get("ownerId"))
    if denied:
        return denied
    process_due_renewals(only_id=renewal_id)
    return jsonify({"success": True, "message": "Renewal notice sent"})


def invoice_payload(data: dict) -> dict:
    return {
        "clientName": clean_text(str(data.get("clientName") or data.get("name") or ""), 80),
        "clientEmail": clean_text(str(data.get("clientEmail") or data.get("email") or ""), 120).lower(),
        "clientMobile": normalize_phone(str(data.get("clientMobile") or data.get("mobile") or data.get("phone") or "")),
        "clientType": clean_text(str(data.get("clientType") or "individual"), 20),
        "service": clean_text(str(data.get("service") or "other"), 40),
        "description": clean_text(str(data.get("description") or ""), 2000),
        "amount": data.get("amount"),
        "status": clean_text(str(data.get("status") or "unpaid"), 20),
        "dueDate": clean_text(str(data.get("dueDate") or ""), 12),
        "notes": clean_text(str(data.get("notes") or ""), 2000),
        "accountId": clean_text(str(data.get("accountId") or ""), 20) or None,
        "dealId": clean_text(str(data.get("dealId") or ""), 20) or None,
    }


@app.patch("/api/admin/crm/settings")
@admin_required_api
def crm_update_settings():
    data = request.get_json(silent=True) or {}
    if "monthlyTarget" not in data and "target" not in data:
        return jsonify({"success": False, "message": "Nothing to update"}), 400
    try:
        target = crm.set_monthly_target(data.get("monthlyTarget", data.get("target")))
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "monthlyTarget": target})


@app.get("/api/admin/crm/invoices")
@login_required_api
def crm_list_invoices():
    return jsonify({"invoices": scoped_invoices(), "payTo": crm.invoice_pay_to()})


@app.post("/api/admin/crm/invoices")
@login_required_api
def crm_create_invoice():
    data = invoice_payload(request.get_json(silent=True) or {})
    try:
        invoice = crm.create_invoice(data, session.get("admin_user_id"))
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, "invoice": invoice})


def deny_invoice(invoice):
    if is_admin() or (invoice.get("createdBy") or session.get("admin_user_id")) == session.get("admin_user_id"):
        return None
    return jsonify({"success": False, "message": "You cannot open that invoice."}), 403


@app.get("/api/admin/crm/invoices/<invoice_id>")
@login_required_api
def crm_get_invoice(invoice_id: str):
    invoice = crm.get_invoice(invoice_id)
    if not invoice:
        return jsonify({"success": False, "message": "Invoice not found"}), 404
    denied = deny_invoice(invoice)
    if denied:
        return denied
    return jsonify(invoice)


@app.patch("/api/admin/crm/invoices/<invoice_id>")
@login_required_api
def crm_update_invoice(invoice_id: str):
    data = request.get_json(silent=True) or {}
    full = invoice_payload(data)
    payload = {}
    aliases = {
        "name": "clientName",
        "email": "clientEmail",
        "mobile": "clientMobile",
        "phone": "clientMobile",
    }
    for key, value in full.items():
        if key in data:
            payload[key] = value
    for alias, dest in aliases.items():
        if alias in data:
            payload[dest] = full[dest]
    current = crm.get_invoice(invoice_id)
    if current:
        denied = deny_invoice(current)
        if denied:
            return denied
    invoice = crm.update_invoice(invoice_id, payload or full)
    if not invoice:
        return jsonify({"success": False, "message": "Invoice not found"}), 404
    return jsonify({"success": True, "invoice": invoice})


@app.post("/api/admin/crm/invoices/<invoice_id>/send")
@login_required_api
def crm_send_invoice(invoice_id: str):
    invoice = crm.get_invoice(invoice_id)
    if not invoice:
        return jsonify({"success": False, "message": "Invoice not found"}), 404
    denied = deny_invoice(invoice)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    override = clean_text(str(data.get("clientEmail") or data.get("email") or ""), 120).lower()
    if override:
        invoice = {**invoice, "clientEmail": override}
    ok, message = mail.notify_invoice(invoice, team_notify_emails())
    if not ok:
        status = 400 if "email" in message.lower() or "configured" in message.lower() else 502
        return jsonify({"success": False, "message": message}), status
    return jsonify({"success": True, "message": message})


@app.get("/api/cron/renewals")
def cron_renewals():
    token = (os.environ.get("CRON_TOKEN") or "").strip()
    provided = (request.headers.get("X-Cron-Token") or "").strip()
    if not token or provided != token:
        abort(404)
    sent = process_due_renewals()
    return jsonify({"success": True, "sent": sent})


@app.get("/healthz")
def healthz():
    expected = (os.environ.get("HEALTH_TOKEN") or "").strip()
    if expected and (request.headers.get("X-Health-Token") or "").strip() != expected:
        abort(404)
    try:
        with db.pool().connection() as conn:
            conn.execute("SELECT 1")
        return jsonify({"ok": True, "db": True}), 200
    except Exception:
        return jsonify({"ok": False, "db": False}), 503


@app.get("/robots.txt")
def robots():
    return send_from_directory(ROOT, "robots.txt")


@app.get("/sitemap.xml")
def sitemap():
    return send_from_directory(ROOT, "sitemap.xml")


@app.get("/uploads/<path:filename>")
def legacy_uploads(filename: str):
    if filename.replace("\\", "/").lower().startswith("crm"):
        abort(404)
    return send_from_directory(ROOT / "static" / "uploads", filename)


@app.get("/css/<path:filename>")
def legacy_css(filename: str):
    return redirect("/static/css/" + filename, 301)


@app.get("/js/<path:filename>")
def legacy_js(filename: str):
    return redirect("/static/js/" + filename, 301)


@app.get("/img/<path:filename>")
def legacy_img(filename: str):
    return redirect("/static/img/" + filename, 301)


@app.get("/lib/<path:filename>")
def legacy_lib(filename: str):
    return redirect("/static/lib/" + filename, 301)


@app.get("/")
def home():
    return render_page("index.html")


@app.get("/admin")
def admin_home():
    return render_page("admin.html")


@app.get("/admin/invoices/<invoice_id>")
def invoice_print_page(invoice_id: str):
    if not logged_in():
        return redirect("/admin/login?next=" + quote("/admin/invoices/" + invoice_id))
    invoice = crm.get_invoice(invoice_id)
    if not invoice:
        abort(404)
    if deny_invoice(invoice):
        abort(403)
    return render_template("invoice.html", invoice=invoice)


@app.get("/admin/login")
def admin_login_page():
    if logged_in():
        nxt = security.safe_next_path(request.args.get("next") or "")
        return redirect(nxt)
    return render_page("admin-login.html")


@app.get("/admin/post")
def admin_new_post():
    return render_page("post-blog.html")


@app.get("/insights/post")
def insight_post():
    return render_page("blog-post.html")


@app.get("/admin/<path:legacy>")
def admin_legacy(legacy: str):
    name = legacy.rsplit("/", 1)[-1]
    if name in {"index.html", "admin.html", "admin-blog.html"}:
        return redirect_with_query("/admin")
    if name in {"login.html", "admin-login.html"}:
        return redirect_with_query("/admin/login")
    if name in {"post-blog.html", "post.html"}:
        return redirect_with_query("/admin/post")
    if name in LEGACY_HTML_REDIRECTS:
        return redirect_with_query(LEGACY_HTML_REDIRECTS[name])
    slug = name[:-5] if name.endswith(".html") else name
    if slug in PAGE_ROUTES:
        return redirect_with_query("/" + slug)
    abort(404)


@app.get("/<slug>")
def public_page(slug: str):
    if slug in {"favicon.ico"}:
        return redirect(url_for("static", filename="img/icon/icon-02-primary.png"))
    if slug == "clients":
        return redirect("/about", 301)
    if slug.endswith(".html"):
        target = LEGACY_HTML_REDIRECTS.get(slug, "/" + slug[:-5])
        return redirect_with_query(target)
    template = PAGE_ROUTES.get(slug)
    if not template:
        abort(404)
    return render_page(template)


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


def boot() -> None:
    assert_deploy_ready()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    security.relocate_crm_uploads()
    security.encrypt_crm_files()
    try:
        db.init_db()
        print("PostgreSQL ready")
    except Exception as exc:
        print("PostgreSQL not ready:", exc)


if __name__ == "__main__":
    boot()
    app.run(
        host=os.environ.get("FLASK_HOST") or "127.0.0.1",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        request_handler=QuietRequestHandler,
    )
