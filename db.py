"""PostgreSQL access for Amiri Insurance."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
POSTS_FILE = DATA_DIR / "blog-posts.json"
REQUESTS_FILE = DATA_DIR / "service-requests.json"
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"

USER_ROLES = {"admin", "manager"}

_pool: ConnectionPool | None = None


def database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "postgresql://amiri:amiri@127.0.0.1:5432/amiri").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    extras = []
    if "connect_timeout" not in url:
        extras.append("connect_timeout=2")
    ssl_mode = (os.environ.get("DATABASE_SSL") or "").strip().lower()
    if ssl_mode in {"1", "true", "yes", "on", "require"} and "sslmode" not in url:
        extras.append("sslmode=require")
    if extras:
        url += ("&" if "?" in url else "?") + "&".join(extras)
    return url


def pool() -> ConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = ConnectionPool(
            conninfo=database_url(),
            min_size=0,
            max_size=8,
            timeout=3,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        _pool.open()
    return _pool


def fmt_ts(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value)
    return text[:19] if len(text) >= 19 else text


def parse_ts(value: str):
    text = (value or "").strip()
    if not text:
        return datetime.now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if fmt.endswith("%S") else text[:10], fmt)
        except ValueError:
            continue
    return datetime.now()


def request_to_api(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "mobile": row.get("mobile") or "",
        "cover": row["cover"],
        "message": row.get("message") or "",
        "prefDate": row.get("pref_date") or "",
        "prefTime": row.get("pref_time") or "",
        "source": row.get("source") or "website",
        "status": row.get("status") or "new",
        "notes": row.get("notes") or "",
        "createdAt": fmt_ts(row.get("created_at")),
        "updatedAt": fmt_ts(row.get("updated_at")),
    }


def user_to_api(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "name": row.get("name") or "",
        "email": row.get("email") or "",
        "role": row.get("role") or "manager",
        "active": bool(row.get("active", True)),
        "mfaEnabled": bool(row.get("mfa_enabled")),
        "sessionVersion": int(row.get("session_version") or 1),
        "createdAt": fmt_ts(row.get("created_at")),
        "updatedAt": fmt_ts(row.get("updated_at")),
    }


def post_to_api(row: dict) -> dict:
    data = row.get("data") or {}
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("id", row["id"])
    data.setdefault("slug", row.get("slug") or "")
    data.setdefault("status", row.get("status") or "pending")
    data.setdefault("title", row.get("title") or "")
    return data


def init_schema() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'manager',
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS service_requests (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        mobile TEXT NOT NULL DEFAULT '',
        cover TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        pref_date TEXT NOT NULL DEFAULT '',
        pref_time TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'website',
        status TEXT NOT NULL DEFAULT 'new',
        notes TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS subscribers (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS posts (
        id TEXT PRIMARY KEY,
        slug TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        title TEXT NOT NULL DEFAULT '',
        data JSONB NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_requests_created ON service_requests (created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_posts_status ON posts (status);
    ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret TEXT NOT NULL DEFAULT '';
    ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 1;
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        actor_id TEXT,
        action TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        ip TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """
    with pool().connection() as conn:
        conn.execute(sql)
        conn.commit()
    import crm
    crm.init_crm_schema()


def _read_json_list(path: Path) -> list:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def seed_and_import() -> None:
    username = (os.environ.get("ADMIN_USERNAME") or "admin").strip() or "admin"
    password = (os.environ.get("ADMIN_PASSWORD") or "").strip()
    with pool().connection() as conn:
        user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if user_count == 0:
            if len(password) < 12 or password.lower() in {"admin", "password", "admin@amiri123"}:
                raise RuntimeError("Set ADMIN_PASSWORD to 12+ characters before creating the first admin.")
            conn.execute(
                """
                INSERT INTO users (id, username, name, email, password_hash, role, active)
                VALUES (%s, %s, %s, %s, %s, 'admin', TRUE)
                """,
                (
                    uuid.uuid4().hex[:12],
                    username.lower(),
                    "Administrator",
                    "",
                    generate_password_hash(password),
                ),
            )
        req_count = conn.execute("SELECT COUNT(*) AS n FROM service_requests").fetchone()["n"]
        if req_count == 0:
            for item in _read_json_list(REQUESTS_FILE):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                conn.execute(
                    """
                    INSERT INTO service_requests (
                        id, name, email, mobile, cover, message, pref_date, pref_time,
                        source, status, notes, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(item.get("id")),
                        item.get("name") or "",
                        item.get("email") or "",
                        item.get("mobile") or "",
                        item.get("cover") or "Other",
                        item.get("message") or "",
                        item.get("prefDate") or "",
                        item.get("prefTime") or "",
                        item.get("source") or "website",
                        item.get("status") or "new",
                        item.get("notes") or "",
                        parse_ts(str(item.get("createdAt") or "")),
                        parse_ts(str(item.get("updatedAt") or item.get("createdAt") or "")),
                    ),
                )
        sub_count = conn.execute("SELECT COUNT(*) AS n FROM subscribers").fetchone()["n"]
        if sub_count == 0:
            for item in _read_json_list(SUBSCRIBERS_FILE):
                if not isinstance(item, dict) or not item.get("email"):
                    continue
                conn.execute(
                    """
                    INSERT INTO subscribers (id, email, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    """,
                    (
                        str(item.get("id") or uuid.uuid4().hex[:12]),
                        str(item.get("email")).strip().lower(),
                        parse_ts(str(item.get("createdAt") or "")),
                    ),
                )
        post_count = conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]
        if post_count == 0:
            for item in _read_json_list(POSTS_FILE):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                conn.execute(
                    """
                    INSERT INTO posts (id, slug, status, title, data, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(item.get("id")),
                        item.get("slug") or "",
                        item.get("status") or "pending",
                        item.get("title") or "",
                        Json(item),
                        parse_ts(str(item.get("createdAt") or "")),
                    ),
                )
        conn.commit()
    import crm
    crm.migrate_requests_to_leads()


def init_db() -> None:
    init_schema()
    seed_and_import()


def find_user_by_username(username: str) -> dict | None:
    with pool().connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(%s)",
            (username.strip(),),
        ).fetchone()
    return dict(row) if row else None


_DUMMY_HASH = generate_password_hash("amiri-dummy-not-a-real-account")


def authenticate_user(username: str, password: str) -> dict | None:
    user = find_user_by_username(username)
    hashed = (user or {}).get("password_hash") or _DUMMY_HASH
    ok = check_password_hash(hashed, password)
    if not user or not user.get("active") or not ok:
        return None
    return user


def set_user_mfa(user_id: str, secret: str, enabled: bool) -> None:
    with pool().connection() as conn:
        conn.execute(
            "UPDATE users SET mfa_secret = %s, mfa_enabled = %s, updated_at = NOW() WHERE id = %s",
            (secret if enabled else "", enabled, user_id),
        )
        conn.commit()


def bump_session_version(user_id: str) -> int:
    with pool().connection() as conn:
        conn.execute(
            "UPDATE users SET session_version = session_version + 1, updated_at = NOW() WHERE id = %s",
            (user_id,),
        )
        row = conn.execute("SELECT session_version FROM users WHERE id = %s", (user_id,)).fetchone()
        conn.commit()
    return int(row["session_version"]) if row else 1


def write_audit(actor_id: str | None, action: str, target: str = "", detail: str = "", ip: str = "") -> None:
    with pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_events (id, actor_id, action, target, detail, ip)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (uuid.uuid4().hex[:12], actor_id, action[:80], target[:120], detail[:400], ip[:80]),
        )
        conn.commit()


def list_users() -> list[dict]:
    with pool().connection() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
    return [user_to_api(row) for row in rows]


def create_user(username: str, password: str, name: str, email: str, role: str) -> dict:
    role = role if role in USER_ROLES else "manager"
    user_id = uuid.uuid4().hex[:12]
    with pool().connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE lower(username) = lower(%s)",
            (username,),
        ).fetchone()
        if existing:
            raise ValueError("That username is already taken")
        conn.execute(
            """
            INSERT INTO users (id, username, name, email, password_hash, role, active)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            """,
            (user_id, username.lower(), name, email, generate_password_hash(password), role),
        )
        row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        conn.commit()
    return user_to_api(row)


def update_user(user_id: str, fields: dict) -> dict | None:
    allowed = {}
    if "name" in fields:
        allowed["name"] = fields["name"]
    if "email" in fields:
        allowed["email"] = fields["email"]
    if "role" in fields and fields["role"] in USER_ROLES:
        allowed["role"] = fields["role"]
    if "active" in fields:
        allowed["active"] = bool(fields["active"])
    bump_session = False
    if fields.get("password"):
        allowed["password_hash"] = generate_password_hash(str(fields["password"]))
        bump_session = True
    if fields.get("resetMfa"):
        allowed["mfa_secret"] = ""
        allowed["mfa_enabled"] = False
        bump_session = True
    if not allowed:
        with pool().connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        return user_to_api(row) if row else None
    sets = ", ".join(f"{key} = %s" for key in allowed)
    if bump_session:
        sets += ", session_version = session_version + 1"
    values = list(allowed.values()) + [user_id]
    with pool().connection() as conn:
        if allowed.get("role") == "manager" or allowed.get("active") is False:
            current = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
            if current and current["role"] == "admin":
                admins = conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = TRUE AND id <> %s",
                    (user_id,),
                ).fetchone()["n"]
                if admins < 1 and (allowed.get("role") == "manager" or allowed.get("active") is False):
                    raise ValueError("Keep at least one active admin")
        conn.execute(
            f"UPDATE users SET {sets}, updated_at = NOW() WHERE id = %s",
            values,
        )
        row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        conn.commit()
    return user_to_api(row) if row else None


def delete_user(user_id: str, actor_id: str) -> None:
    if user_id == actor_id:
        raise ValueError("You cannot delete your own account")
    with pool().connection() as conn:
        current = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        if not current:
            raise ValueError("User not found")
        if current["role"] == "admin":
            admins = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = TRUE AND id <> %s",
                (user_id,),
            ).fetchone()["n"]
            if admins < 1:
                raise ValueError("Keep at least one active admin")
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()


def read_requests() -> list[dict]:
    with pool().connection() as conn:
        rows = conn.execute("SELECT * FROM service_requests ORDER BY created_at DESC").fetchall()
    return [request_to_api(row) for row in rows]


def insert_request(item: dict) -> dict:
    with pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO service_requests (
                id, name, email, mobile, cover, message, pref_date, pref_time,
                source, status, notes, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            (
                item["id"],
                item["name"],
                item["email"],
                item.get("mobile") or "",
                item["cover"],
                item.get("message") or "",
                item.get("prefDate") or "",
                item.get("prefTime") or "",
                item.get("source") or "website",
                item.get("status") or "new",
                item.get("notes") or "",
            ),
        )
        row = conn.execute("SELECT * FROM service_requests WHERE id = %s", (item["id"],)).fetchone()
        conn.commit()
    return request_to_api(row)


def update_request(req_id: str, status: str, notes: str | None) -> dict | None:
    with pool().connection() as conn:
        current = conn.execute("SELECT * FROM service_requests WHERE id = %s", (req_id,)).fetchone()
        if not current:
            return None
        next_notes = current.get("notes") or "" if notes is None else notes
        conn.execute(
            """
            UPDATE service_requests
            SET status = %s, notes = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (status, next_notes, req_id),
        )
        row = conn.execute("SELECT * FROM service_requests WHERE id = %s", (req_id,)).fetchone()
        conn.commit()
    return request_to_api(row)


def delete_request(req_id: str) -> bool:
    with pool().connection() as conn:
        cur = conn.execute("DELETE FROM service_requests WHERE id = %s", (req_id,))
        conn.commit()
        return cur.rowcount > 0


def read_subscribers() -> list[dict]:
    with pool().connection() as conn:
        rows = conn.execute("SELECT * FROM subscribers ORDER BY created_at DESC").fetchall()
    return [
        {"id": row["id"], "email": row["email"], "createdAt": fmt_ts(row.get("created_at"))}
        for row in rows
    ]


def add_subscriber(email: str) -> tuple[dict | None, bool]:
    with pool().connection() as conn:
        existing = conn.execute(
            "SELECT * FROM subscribers WHERE lower(email) = lower(%s)",
            (email,),
        ).fetchone()
        if existing:
            return (
                {"id": existing["id"], "email": existing["email"], "createdAt": fmt_ts(existing.get("created_at"))},
                False,
            )
        sub_id = uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO subscribers (id, email, created_at) VALUES (%s, %s, NOW())",
            (sub_id, email),
        )
        row = conn.execute("SELECT * FROM subscribers WHERE id = %s", (sub_id,)).fetchone()
        conn.commit()
    return {"id": row["id"], "email": row["email"], "createdAt": fmt_ts(row.get("created_at"))}, True


def read_posts() -> list[dict]:
    with pool().connection() as conn:
        rows = conn.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    return [post_to_api(row) for row in rows]


def insert_post(post: dict) -> dict:
    with pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO posts (id, slug, status, title, data, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (post["id"], post.get("slug") or "", post.get("status") or "pending", post.get("title") or "", Json(post)),
        )
        conn.commit()
    return post


def get_post(post_id: str) -> dict | None:
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = %s", (post_id,)).fetchone()
    return post_to_api(row) if row else None


def update_post(post: dict) -> dict:
    with pool().connection() as conn:
        conn.execute(
            "UPDATE posts SET slug = %s, status = %s, title = %s, data = %s WHERE id = %s",
            (post.get("slug") or "", post.get("status") or "pending", post.get("title") or "", Json(post), post["id"]),
        )
        conn.commit()
    return post


def replace_posts(posts: list) -> None:
    with pool().connection() as conn:
        conn.execute("DELETE FROM posts")
        for item in posts:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            conn.execute(
                """
                INSERT INTO posts (id, slug, status, title, data, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    str(item.get("id")),
                    item.get("slug") or "",
                    item.get("status") or "pending",
                    item.get("title") or "",
                    Json(item),
                    parse_ts(str(item.get("createdAt") or "")),
                ),
            )
        conn.commit()
