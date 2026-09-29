"""CRM: leads become accounts when contacted, then deals when sold."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path

from psycopg.types.json import Json

import db
import security

ROOT = Path(__file__).resolve().parent
CRM_UPLOAD_DIR = ROOT / "data" / "uploads" / "crm"
DEFAULT_MONTHLY_TARGET = 10000.0

SERVICES = {
    "medical": "Health Insurance",
    "motor": "Motor Insurance",
    "wiba": "WIBA",
    "property": "Property Insurance",
    "group_life": "Group Life",
    "money": "Money Insurance",
    "other": "Other",
}
COVER_TO_SERVICE = {label.lower(): key for key, label in SERVICES.items()}
COVER_TO_SERVICE["health insurance"] = "medical"

CLIENT_TYPES = {"individual", "corporate"}
LEAD_STATUSES = {"new", "contacted", "quoted", "won", "closed"}
FILE_KINDS = {
    "quotation",
    "logbook",
    "pin",
    "national_id",
    "cert_incorporation",
    "cheque",
    "valuation",
}
ALLOWED_FILE_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_BYTES = 10 * 1024 * 1024
RENEWAL_WINDOW_DAYS = 30


def money(value) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(Decimal(str(value).replace(",", "").strip() or "0"))
    except (InvalidOperation, ValueError):
        return 0.0


def fmt_date(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def parse_date(value: str):
    text = (value or "").strip()[:10]
    if len(text) < 8:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _invoice_paid_on(row: dict):
    return row.get("paid_at") or (row.get("updated_at").date() if isinstance(row.get("updated_at"), datetime) else date.today())


def _sync_paid_invoice(conn, row: dict) -> None:
    if (row.get("status") or "") != "paid":
        return
    deal_id = row.get("deal_id")
    if not deal_id:
        return
    number = row.get("number") or ""
    marker = f"Invoice {number}"
    existing = conn.execute(
        "SELECT id FROM crm_payments WHERE deal_id = %s AND notes = %s",
        (deal_id, marker),
    ).fetchone()
    if existing:
        return
    deal = conn.execute("SELECT id FROM crm_deals WHERE id = %s", (deal_id,)).fetchone()
    if not deal:
        return
    conn.execute(
        """
        INSERT INTO crm_payments (id, deal_id, method, mpesa_code, amount, paid_at, notes, created_by)
        VALUES (%s, %s, 'other', '', %s, %s, %s, %s)
        """,
        (
            uuid.uuid4().hex[:12],
            deal_id,
            money(row.get("amount")),
            _invoice_paid_on(row),
            marker,
            row.get("created_by"),
        ),
    )


def _sum_revenue(conn, start=None, owner_id: str | None = None) -> float:
    pay_sql = "SELECT p.amount AS n FROM crm_payments p JOIN crm_deals d ON d.id = p.deal_id WHERE 1=1"
    inv_sql = (
        "SELECT i.amount AS n FROM crm_invoices i "
        "WHERE i.status = 'paid' AND i.deal_id IS NULL"
    )
    pay_args: list = []
    inv_args: list = []
    if start:
        pay_sql += " AND p.paid_at >= %s"
        inv_sql += " AND COALESCE(i.paid_at, i.updated_at::date) >= %s"
        pay_args.append(start)
        inv_args.append(start)
    if owner_id:
        pay_sql += " AND d.owner_id = %s"
        inv_sql += " AND i.created_by = %s"
        pay_args.append(owner_id)
        inv_args.append(owner_id)
    row = conn.execute(
        f"SELECT COALESCE(SUM(n), 0) AS n FROM ({pay_sql} UNION ALL {inv_sql}) t",
        tuple(pay_args + inv_args),
    ).fetchone()
    return money(row["n"])


def _staff_revenue(conn, start, owner_id: str | None = None) -> list:
    pay_sql = (
        "SELECT d.owner_id AS owner_id, p.amount AS n, p.deal_id AS deal_id "
        "FROM crm_payments p JOIN crm_deals d ON d.id = p.deal_id WHERE p.paid_at >= %s"
    )
    inv_sql = (
        "SELECT i.created_by AS owner_id, i.amount AS n, i.id AS deal_id "
        "FROM crm_invoices i WHERE i.status = 'paid' AND i.deal_id IS NULL "
        "AND COALESCE(i.paid_at, i.updated_at::date) >= %s"
    )
    args: list = [start]
    if owner_id:
        pay_sql += " AND d.owner_id = %s"
        args.append(owner_id)
    args.append(start)
    if owner_id:
        inv_sql += " AND i.created_by = %s"
        args.append(owner_id)
    return conn.execute(
        f"""
        SELECT owner_id, COALESCE(SUM(n), 0) AS revenue, COUNT(DISTINCT deal_id) AS deals
        FROM ({pay_sql} UNION ALL {inv_sql}) t
        GROUP BY owner_id
        ORDER BY revenue DESC
        """,
        tuple(args),
    ).fetchall()


def _month_series(conn, start, owner_id: str | None = None) -> list:
    pay_sql = (
        "SELECT to_char(date_trunc('month', p.paid_at), 'YYYY-MM') AS month, p.amount AS n "
        "FROM crm_payments p JOIN crm_deals d ON d.id = p.deal_id WHERE p.paid_at >= %s"
    )
    inv_sql = (
        "SELECT to_char(date_trunc('month', COALESCE(i.paid_at, i.updated_at::date)), 'YYYY-MM') AS month, i.amount AS n "
        "FROM crm_invoices i WHERE i.status = 'paid' AND i.deal_id IS NULL "
        "AND COALESCE(i.paid_at, i.updated_at::date) >= %s"
    )
    args: list = [start]
    if owner_id:
        pay_sql += " AND d.owner_id = %s"
        args.append(owner_id)
    args.append(start)
    if owner_id:
        inv_sql += " AND i.created_by = %s"
        args.append(owner_id)
    return conn.execute(
        f"""
        SELECT month, COALESCE(SUM(n), 0) AS revenue
        FROM ({pay_sql} UNION ALL {inv_sql}) t
        GROUP BY 1
        ORDER BY 1
        """,
        tuple(args),
    ).fetchall()


def service_from_cover(cover: str) -> str:
    key = COVER_TO_SERVICE.get((cover or "").strip().lower())
    return key if key in SERVICES else "other"


def cover_from_service(service: str) -> str:
    return SERVICES.get(service, "Other")


def sanitize_details(service: str, client_type: str, details) -> dict:
    data = details if isinstance(details, dict) else {}
    limits_in = data.get("limits") if isinstance(data.get("limits"), dict) else {}
    out: dict = {}
    if service == "medical":
        out["limits"] = {
            "inpatient": str(limits_in.get("inpatient") or "")[:40],
            "outpatient": str(limits_in.get("outpatient") or "")[:40],
            "dental": str(limits_in.get("dental") or "")[:40],
            "optical": str(limits_in.get("optical") or "")[:40],
            "maternity": str(limits_in.get("maternity") or "")[:40],
        }
        if client_type == "individual":
            out["dob"] = str(data.get("dob") or "")[:12]
        else:
            out["population"] = str(data.get("population") or "")[:12]
            cat = str(data.get("category") or "A").upper()[:1]
            out["category"] = cat if cat in {"A", "B"} else "A"
    elif service == "wiba":
        out["population"] = str(data.get("population") or "")[:12]
        out["cover_amount"] = str(data.get("cover_amount") or data.get("amount") or "")[:40]
    elif service == "motor":
        veh = data.get("vehicle") if isinstance(data.get("vehicle"), dict) else data
        out["vehicle"] = {
            key: str(veh.get(key) or "")[:80]
            for key in ("registration", "make", "model", "year", "chassis", "engine", "value", "use")
        }
        out["installment"] = bool(data.get("installment"))
    if data.get("premium") not in (None, ""):
        out["premium"] = str(data.get("premium") or "")[:40]
    return out


def json_obj(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def init_crm_schema() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS crm_accounts (
        id TEXT PRIMARY KEY,
        client_type TEXT NOT NULL DEFAULT 'individual',
        name TEXT NOT NULL,
        email TEXT NOT NULL DEFAULT '',
        mobile TEXT NOT NULL DEFAULT '',
        kra_pin TEXT NOT NULL DEFAULT '',
        dob DATE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS crm_leads (
        id TEXT PRIMARY KEY,
        account_id TEXT REFERENCES crm_accounts (id),
        owner_id TEXT REFERENCES users (id),
        service TEXT NOT NULL DEFAULT 'other',
        client_type TEXT NOT NULL DEFAULT 'individual',
        name TEXT NOT NULL,
        email TEXT NOT NULL DEFAULT '',
        mobile TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'website',
        status TEXT NOT NULL DEFAULT 'new',
        message TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS crm_deals (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES crm_accounts (id),
        lead_id TEXT REFERENCES crm_leads (id),
        owner_id TEXT REFERENCES users (id),
        service TEXT NOT NULL,
        client_type TEXT NOT NULL DEFAULT 'individual',
        insurer TEXT NOT NULL DEFAULT '',
        premium NUMERIC(14, 2) NOT NULL DEFAULT 0,
        vehicle_value NUMERIC(14, 2) NOT NULL DEFAULT 0,
        inception_date DATE,
        expiry_date DATE,
        installment BOOLEAN NOT NULL DEFAULT FALSE,
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS crm_files (
        id TEXT PRIMARY KEY,
        lead_id TEXT REFERENCES crm_leads (id),
        deal_id TEXT REFERENCES crm_deals (id),
        account_id TEXT REFERENCES crm_accounts (id),
        kind TEXT NOT NULL,
        original_name TEXT NOT NULL DEFAULT '',
        stored_name TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS crm_payments (
        id TEXT PRIMARY KEY,
        deal_id TEXT NOT NULL REFERENCES crm_deals (id) ON DELETE CASCADE,
        method TEXT NOT NULL DEFAULT 'mpesa',
        mpesa_code TEXT NOT NULL DEFAULT '',
        amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
        paid_at DATE NOT NULL DEFAULT CURRENT_DATE,
        notes TEXT NOT NULL DEFAULT '',
        created_by TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS crm_renewals (
        id TEXT PRIMARY KEY,
        deal_id TEXT NOT NULL REFERENCES crm_deals (id) ON DELETE CASCADE,
        due_date DATE NOT NULL,
        notice_sent_at TIMESTAMP,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS crm_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS crm_invoices (
        id TEXT PRIMARY KEY,
        number TEXT UNIQUE NOT NULL,
        account_id TEXT REFERENCES crm_accounts (id),
        deal_id TEXT REFERENCES crm_deals (id),
        client_name TEXT NOT NULL,
        client_email TEXT NOT NULL DEFAULT '',
        client_mobile TEXT NOT NULL DEFAULT '',
        client_type TEXT NOT NULL DEFAULT 'individual',
        service TEXT NOT NULL DEFAULT 'other',
        description TEXT NOT NULL DEFAULT '',
        amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'unpaid',
        due_date DATE,
        notes TEXT NOT NULL DEFAULT '',
        created_by TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_crm_leads_status ON crm_leads (status, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_crm_deals_expiry ON crm_deals (expiry_date);
    CREATE INDEX IF NOT EXISTS idx_crm_payments_deal ON crm_payments (deal_id, paid_at);
    CREATE INDEX IF NOT EXISTS idx_crm_invoices_created ON crm_invoices (created_at DESC);
    """
    with db.pool().connection() as conn:
        conn.execute(sql)
        conn.execute(
            """
            INSERT INTO crm_settings (key, value) VALUES ('monthly_target', %s)
            ON CONFLICT (key) DO NOTHING
            """,
            (str(int(DEFAULT_MONTHLY_TARGET)),),
        )
        conn.execute("ALTER TABLE crm_invoices ADD COLUMN IF NOT EXISTS paid_at DATE")
        conn.execute(
            """
            UPDATE crm_invoices
            SET paid_at = COALESCE(paid_at, updated_at::date, CURRENT_DATE)
            WHERE status = 'paid' AND paid_at IS NULL
            """
        )
        conn.commit()
    CRM_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def migrate_requests_to_leads() -> None:
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT * FROM service_requests ORDER BY created_at ASC").fetchall()
        existing = {
            row["id"]
            for row in conn.execute("SELECT id FROM crm_leads").fetchall()
        }
        for row in rows:
            if row["id"] in existing:
                continue
            service = service_from_cover(row.get("cover") or "")
            conn.execute(
                """
                INSERT INTO crm_leads (
                    id, owner_id, service, client_type, name, email, mobile, source,
                    status, message, notes, details, created_at, updated_at
                ) VALUES (%s, NULL, %s, 'individual', %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb, %s, %s)
                """,
                (
                    row["id"],
                    service,
                    row.get("name") or "",
                    row.get("email") or "",
                    row.get("mobile") or "",
                    row.get("source") or "website",
                    row.get("status") or "new",
                    row.get("message") or "",
                    row.get("notes") or "",
                    row.get("created_at"),
                    row.get("updated_at") or row.get("created_at"),
                ),
            )
            status = row.get("status") or "new"
            if status in {"contacted", "quoted", "won"}:
                lead = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (row["id"],)).fetchone()
                account_id = _ensure_account(conn, lead)
                conn.execute(
                    "UPDATE crm_leads SET account_id = %s, updated_at = NOW() WHERE id = %s",
                    (account_id, row["id"]),
                )
                if status == "won":
                    lead = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (row["id"],)).fetchone()
                    _ensure_deal(conn, lead)
        conn.commit()


def staff_map(conn=None) -> dict:
    def load(cur):
        rows = cur.execute("SELECT id, username, name FROM users").fetchall()
        return {row["id"]: (row.get("name") or row["username"] or "") for row in rows}

    if conn is not None:
        return load(conn)
    with db.pool().connection() as owned:
        return load(owned)


def list_staff() -> list[dict]:
    with db.pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, username, name FROM users WHERE active = TRUE ORDER BY name ASC, username ASC"
        ).fetchall()
    return [
        {"id": row["id"], "username": row["username"], "name": row.get("name") or row["username"]}
        for row in rows
    ]


def file_to_api(row: dict) -> dict:
    return {
        "id": row["id"],
        "leadId": row.get("lead_id") or "",
        "dealId": row.get("deal_id") or "",
        "accountId": row.get("account_id") or "",
        "kind": row.get("kind") or "",
        "name": row.get("original_name") or "",
        "url": f"/api/admin/crm/files/{row['id']}",
        "createdAt": db.fmt_ts(row.get("created_at")),
    }


def payment_to_api(row: dict) -> dict:
    return {
        "id": row["id"],
        "dealId": row["deal_id"],
        "method": row.get("method") or "mpesa",
        "mpesaCode": row.get("mpesa_code") or "",
        "amount": money(row.get("amount")),
        "paidAt": fmt_date(row.get("paid_at")),
        "notes": row.get("notes") or "",
        "createdAt": db.fmt_ts(row.get("created_at")),
    }


def account_to_api(row: dict, extras: dict | None = None) -> dict:
    payload = {
        "id": row["id"],
        "clientType": row.get("client_type") or "individual",
        "name": row.get("name") or "",
        "email": row.get("email") or "",
        "mobile": row.get("mobile") or "",
        "kraPin": row.get("kra_pin") or "",
        "dob": fmt_date(row.get("dob")),
        "createdAt": db.fmt_ts(row.get("created_at")),
        "updatedAt": db.fmt_ts(row.get("updated_at")),
    }
    if extras:
        payload.update(extras)
    return payload


def lead_to_api(row: dict, names: dict | None = None, files: list | None = None) -> dict:
    names = names or {}
    return {
        "id": row["id"],
        "accountId": row.get("account_id") or "",
        "ownerId": row.get("owner_id") or "",
        "ownerName": names.get(row.get("owner_id") or "") or "",
        "service": row.get("service") or "other",
        "cover": cover_from_service(row.get("service") or "other"),
        "clientType": row.get("client_type") or "individual",
        "name": row.get("name") or "",
        "email": row.get("email") or "",
        "mobile": row.get("mobile") or "",
        "source": row.get("source") or "website",
        "status": row.get("status") or "new",
        "message": row.get("message") or "",
        "notes": row.get("notes") or "",
        "details": json_obj(row.get("details")),
        "files": files or [],
        "createdAt": db.fmt_ts(row.get("created_at")),
        "updatedAt": db.fmt_ts(row.get("updated_at")),
    }


def deal_to_api(
    row: dict,
    names: dict | None = None,
    files: list | None = None,
    payments: list | None = None,
    account: dict | None = None,
    renewal: dict | None = None,
) -> dict:
    names = names or {}
    paid = sum(item["amount"] for item in (payments or []))
    return {
        "id": row["id"],
        "accountId": row["account_id"],
        "leadId": row.get("lead_id") or "",
        "ownerId": row.get("owner_id") or "",
        "ownerName": names.get(row.get("owner_id") or "") or "",
        "accountName": (account or {}).get("name") or "",
        "accountEmail": (account or {}).get("email") or "",
        "accountMobile": (account or {}).get("mobile") or "",
        "service": row.get("service") or "other",
        "cover": cover_from_service(row.get("service") or "other"),
        "clientType": row.get("client_type") or "individual",
        "insurer": row.get("insurer") or "",
        "premium": money(row.get("premium")),
        "vehicleValue": money(row.get("vehicle_value")),
        "inceptionDate": fmt_date(row.get("inception_date")),
        "expiryDate": fmt_date(row.get("expiry_date")),
        "installment": bool(row.get("installment")),
        "details": json_obj(row.get("details")),
        "paid": paid,
        "files": files or [],
        "payments": payments or [],
        "renewal": renewal,
        "createdAt": db.fmt_ts(row.get("created_at")),
        "updatedAt": db.fmt_ts(row.get("updated_at")),
    }


def _files_for(conn, lead_id: str | None = None, deal_id: str | None = None) -> list:
    if lead_id:
        rows = conn.execute(
            "SELECT * FROM crm_files WHERE lead_id = %s ORDER BY created_at DESC",
            (lead_id,),
        ).fetchall()
    elif deal_id:
        rows = conn.execute(
            "SELECT * FROM crm_files WHERE deal_id = %s OR lead_id = (SELECT lead_id FROM crm_deals WHERE id = %s) ORDER BY created_at DESC",
            (deal_id, deal_id),
        ).fetchall()
    else:
        return []
    return [file_to_api(row) for row in rows]


def _payments_for(conn, deal_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM crm_payments WHERE deal_id = %s ORDER BY paid_at DESC, created_at DESC",
        (deal_id,),
    ).fetchall()
    return [payment_to_api(row) for row in rows]


def _ensure_account(conn, lead: dict) -> str:
    email = (lead.get("email") or "").strip().lower()
    mobile = (lead.get("mobile") or "").strip()
    row = None
    if email:
        row = conn.execute(
            "SELECT * FROM crm_accounts WHERE lower(email) = %s LIMIT 1",
            (email,),
        ).fetchone()
    if not row and mobile:
        row = conn.execute(
            "SELECT * FROM crm_accounts WHERE mobile = %s AND mobile <> '' LIMIT 1",
            (mobile,),
        ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE crm_accounts
            SET name = CASE WHEN name = '' THEN %s ELSE name END,
                email = CASE WHEN email = '' THEN %s ELSE email END,
                mobile = CASE WHEN mobile = '' THEN %s ELSE mobile END,
                client_type = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (lead.get("name") or "", email, mobile, lead.get("client_type") or "individual", row["id"]),
        )
        return row["id"]
    account_id = uuid.uuid4().hex[:12]
    details = json_obj(lead.get("details"))
    dob = parse_date(str(details.get("dob") or ""))
    conn.execute(
        """
        INSERT INTO crm_accounts (id, client_type, name, email, mobile, dob)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            account_id,
            lead.get("client_type") or "individual",
            lead.get("name") or "Client",
            email,
            mobile,
            dob,
        ),
    )
    return account_id


def _ensure_deal(conn, lead: dict) -> dict:
    existing = conn.execute("SELECT * FROM crm_deals WHERE lead_id = %s", (lead["id"],)).fetchone()
    if existing:
        return dict(existing)
    details = json_obj(lead.get("details"))
    premium = money(details.get("premium") or (details.get("vehicle") or {}).get("premium") or details.get("cover_amount"))
    vehicle_value = money((details.get("vehicle") or {}).get("value"))
    today = date.today()
    try:
        expiry = today.replace(year=today.year + 1)
    except ValueError:
        expiry = date(today.year + 1, 2, 28)
    deal_id = uuid.uuid4().hex[:12]
    conn.execute(
        """
        INSERT INTO crm_deals (
            id, account_id, lead_id, owner_id, service, client_type, premium,
            vehicle_value, inception_date, expiry_date, installment, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            deal_id,
            lead["account_id"],
            lead["id"],
            lead.get("owner_id"),
            lead.get("service") or "other",
            lead.get("client_type") or "individual",
            premium,
            vehicle_value,
            today,
            expiry,
            bool(details.get("installment")),
            Json(details),
        ),
    )
    conn.execute(
        "UPDATE crm_files SET deal_id = %s, account_id = %s WHERE lead_id = %s",
        (deal_id, lead["account_id"], lead["id"]),
    )
    conn.execute(
        """
        INSERT INTO crm_renewals (id, deal_id, due_date, status)
        VALUES (%s, %s, %s, 'pending')
        """,
        (uuid.uuid4().hex[:12], deal_id, expiry),
    )
    return dict(conn.execute("SELECT * FROM crm_deals WHERE id = %s", (deal_id,)).fetchone())


def create_lead_from_request(item: dict, owner_id: str | None = None) -> dict:
    lead_id = item["id"]
    service = service_from_cover(item.get("cover") or "")
    with db.pool().connection() as conn:
        existing = conn.execute("SELECT id FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO crm_leads (
                    id, owner_id, service, client_type, name, email, mobile, source,
                    status, message, notes, details
                ) VALUES (%s, %s, %s, 'individual', %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
                """,
                (
                    lead_id,
                    owner_id,
                    service,
                    item.get("name") or "",
                    item.get("email") or "",
                    item.get("mobile") or "",
                    item.get("source") or "website",
                    item.get("status") or "new",
                    item.get("message") or "",
                    item.get("notes") or "",
                ),
            )
        row = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
        conn.commit()
    return lead_to_api(row, staff_map())


def create_lead(payload: dict, actor_id: str | None) -> dict:
    name = (payload.get("name") or "").strip()
    if len(name) < 2:
        raise ValueError("Name is required")
    service = payload.get("service") if payload.get("service") in SERVICES else "other"
    client_type = payload.get("clientType") if payload.get("clientType") in CLIENT_TYPES else "individual"
    lead_id = uuid.uuid4().hex[:12]
    owner_id = payload.get("ownerId") or actor_id or None
    details = sanitize_details(service, client_type, payload.get("details"))
    with db.pool().connection() as conn:
        if owner_id:
            staff = conn.execute("SELECT id FROM users WHERE id = %s", (owner_id,)).fetchone()
            if not staff:
                owner_id = actor_id
        conn.execute(
            """
            INSERT INTO crm_leads (
                id, owner_id, service, client_type, name, email, mobile, source,
                status, message, notes, details
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new', %s, %s, %s)
            """,
            (
                lead_id,
                owner_id,
                service,
                client_type,
                name,
                (payload.get("email") or "").strip().lower(),
                (payload.get("mobile") or "").strip(),
                (payload.get("source") or "staff")[:40],
                (payload.get("message") or "")[:1000],
                (payload.get("notes") or "")[:2000],
                Json(details),
            ),
        )
        row = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
        conn.commit()
    return get_lead(lead_id)


def get_lead(lead_id: str) -> dict | None:
    with db.pool().connection() as conn:
        row = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
        if not row:
            return None
        files = _files_for(conn, lead_id=lead_id)
        names = staff_map(conn)
    return lead_to_api(row, names, files)


def list_leads() -> list[dict]:
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT * FROM crm_leads ORDER BY created_at DESC").fetchall()
        files = conn.execute("SELECT * FROM crm_files").fetchall()
        names = staff_map(conn)
    by_lead: dict[str, list] = {}
    for item in files:
        by_lead.setdefault(item.get("lead_id") or "", []).append(file_to_api(item))
    return [lead_to_api(row, names, by_lead.get(row["id"], [])) for row in rows]


def update_lead(lead_id: str, payload: dict, actor_id: str | None) -> dict | None:
    with db.pool().connection() as conn:
        current = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
        if not current:
            return None
        service = payload.get("service") if payload.get("service") in SERVICES else current["service"]
        client_type = payload.get("clientType") if payload.get("clientType") in CLIENT_TYPES else current["client_type"]
        status = payload.get("status") if payload.get("status") in LEAD_STATUSES else current["status"]
        owner_id = payload.get("ownerId") if "ownerId" in payload else current.get("owner_id")
        if owner_id == "":
            owner_id = None
        details = sanitize_details(service, client_type, payload.get("details") if "details" in payload else json_obj(current.get("details")))
        name = (payload.get("name") or current["name"]).strip() or current["name"]
        email = (payload.get("email") if "email" in payload else current["email"]) or ""
        mobile = (payload.get("mobile") if "mobile" in payload else current["mobile"]) or ""
        notes = payload.get("notes") if "notes" in payload else current.get("notes") or ""
        message = payload.get("message") if "message" in payload else current.get("message") or ""
        conn.execute(
            """
            UPDATE crm_leads
            SET owner_id = %s, service = %s, client_type = %s, name = %s, email = %s, mobile = %s,
                message = %s, notes = %s, details = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (owner_id, service, client_type, name, email.strip().lower(), mobile, message, notes, Json(details), lead_id),
        )
        if status != current["status"]:
            _apply_status(conn, lead_id, status, notes)
        elif status in {"contacted", "quoted", "won"} and not current.get("account_id"):
            _apply_status(conn, lead_id, status, notes)
        kra = (payload.get("kraPin") or "").strip()
        dob = parse_date(str(payload.get("dob") or details.get("dob") or ""))
        account_row = conn.execute("SELECT account_id FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
        if account_row and account_row.get("account_id") and (kra or dob):
            conn.execute(
                """
                UPDATE crm_accounts
                SET kra_pin = CASE WHEN %s = '' THEN kra_pin ELSE %s END,
                    dob = COALESCE(%s, dob),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (kra, kra, dob, account_row["account_id"]),
            )
        conn.commit()
    lead = get_lead(lead_id)
    _sync_request(lead_id, lead["status"] if lead else status, notes)
    return lead


def apply_lead_status(lead_id: str, status: str, notes: str | None = None) -> dict | None:
    if status not in LEAD_STATUSES:
        raise ValueError("Invalid status")
    with db.pool().connection() as conn:
        current = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
        if not current:
            return None
        previous = current["status"]
        lead = _apply_status(conn, lead_id, status, notes)
        conn.commit()
    _sync_request(lead_id, status, notes)
    if lead:
        lead["previousStatus"] = previous
    return get_lead(lead_id)


def _apply_status(conn, lead_id: str, status: str, notes: str | None):
    current = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
    next_notes = current.get("notes") or "" if notes is None else notes
    conn.execute(
        "UPDATE crm_leads SET status = %s, notes = %s, updated_at = NOW() WHERE id = %s",
        (status, next_notes, lead_id),
    )
    lead = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
    if status in {"contacted", "quoted", "won"}:
        account_id = _ensure_account(conn, lead)
        conn.execute(
            "UPDATE crm_leads SET account_id = %s, updated_at = NOW() WHERE id = %s",
            (account_id, lead_id),
        )
        lead = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
    if status == "won":
        _ensure_deal(conn, lead)
        lead = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (lead_id,)).fetchone()
    return lead


def _sync_request(lead_id: str, status: str, notes: str | None) -> None:
    try:
        db.update_request(lead_id, status, notes)
    except Exception:
        return


def list_accounts() -> list[dict]:
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT * FROM crm_accounts ORDER BY updated_at DESC").fetchall()
        deals = conn.execute(
            """
            SELECT account_id, COUNT(*) AS deals, COALESCE(SUM(premium), 0) AS premium
            FROM crm_deals GROUP BY account_id
            """
        ).fetchall()
        leads = conn.execute(
            "SELECT account_id, COUNT(*) AS leads FROM crm_leads WHERE account_id IS NOT NULL GROUP BY account_id"
        ).fetchall()
    deal_map = {row["account_id"]: row for row in deals}
    lead_map = {row["account_id"]: row["leads"] for row in leads}
    result = []
    for row in rows:
        extra = deal_map.get(row["id"]) or {}
        result.append(
            account_to_api(
                row,
                {
                    "deals": int(extra.get("deals") or 0),
                    "leads": int(lead_map.get(row["id"]) or 0),
                    "premium": money(extra.get("premium")),
                },
            )
        )
    return result


def get_account(account_id: str) -> dict | None:
    with db.pool().connection() as conn:
        row = conn.execute("SELECT * FROM crm_accounts WHERE id = %s", (account_id,)).fetchone()
        if not row:
            return None
        leads = conn.execute(
            "SELECT * FROM crm_leads WHERE account_id = %s ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        deals = conn.execute(
            "SELECT * FROM crm_deals WHERE account_id = %s ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        names = staff_map(conn)
    payload = account_to_api(row)
    payload["leads"] = [lead_to_api(item, names) for item in leads]
    payload["deals"] = [deal_to_api(item, names, account=row) for item in deals]
    return payload


def update_account(account_id: str, payload: dict) -> dict | None:
    with db.pool().connection() as conn:
        current = conn.execute("SELECT * FROM crm_accounts WHERE id = %s", (account_id,)).fetchone()
        if not current:
            return None
        client_type = payload.get("clientType") if payload.get("clientType") in CLIENT_TYPES else current["client_type"]
        conn.execute(
            """
            UPDATE crm_accounts
            SET client_type = %s, name = %s, email = %s, mobile = %s, kra_pin = %s, dob = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (
                client_type,
                (payload.get("name") or current["name"]).strip(),
                (payload.get("email") if "email" in payload else current["email"] or "").strip().lower(),
                payload.get("mobile") if "mobile" in payload else current["mobile"] or "",
                payload.get("kraPin") if "kraPin" in payload else current.get("kra_pin") or "",
                parse_date(str(payload.get("dob") or current.get("dob") or "")),
                account_id,
            ),
        )
        conn.commit()
    return get_account(account_id)


def list_deals() -> list[dict]:
    with db.pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT d.*, a.name AS account_name, a.email AS account_email, a.mobile AS account_mobile
            FROM crm_deals d
            JOIN crm_accounts a ON a.id = d.account_id
            ORDER BY d.created_at DESC
            """
        ).fetchall()
        names = staff_map(conn)
        payments = conn.execute("SELECT deal_id, COALESCE(SUM(amount), 0) AS paid FROM crm_payments GROUP BY deal_id").fetchall()
        renewals = conn.execute(
            """
            SELECT r.* FROM crm_renewals r
            INNER JOIN (
                SELECT deal_id, MAX(created_at) AS created_at
                FROM crm_renewals
                GROUP BY deal_id
            ) latest ON latest.deal_id = r.deal_id AND latest.created_at = r.created_at
            """
        ).fetchall()
    paid_map = {row["deal_id"]: money(row["paid"]) for row in payments}
    renew_map = {row["deal_id"]: dict(row) for row in renewals}
    result = []
    for row in rows:
        api = deal_to_api(
            row,
            names,
            account={"name": row.get("account_name"), "email": row.get("account_email"), "mobile": row.get("account_mobile")},
            renewal=_renewal_api(renew_map.get(row["id"])),
        )
        api["paid"] = paid_map.get(row["id"], 0.0)
        result.append(api)
    return result


def _renewal_api(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "dueDate": fmt_date(row.get("due_date")),
        "noticeSentAt": db.fmt_ts(row.get("notice_sent_at")),
        "status": row.get("status") or "pending",
    }


def get_deal(deal_id: str) -> dict | None:
    with db.pool().connection() as conn:
        row = conn.execute("SELECT * FROM crm_deals WHERE id = %s", (deal_id,)).fetchone()
        if not row:
            return None
        account = conn.execute("SELECT * FROM crm_accounts WHERE id = %s", (row["account_id"],)).fetchone()
        files = _files_for(conn, deal_id=deal_id)
        payments = _payments_for(conn, deal_id)
        renewal = conn.execute(
            "SELECT * FROM crm_renewals WHERE deal_id = %s ORDER BY created_at DESC LIMIT 1",
            (deal_id,),
        ).fetchone()
        names = staff_map(conn)
    return deal_to_api(row, names, files, payments, account, _renewal_api(renewal))


def update_deal(deal_id: str, payload: dict) -> dict | None:
    with db.pool().connection() as conn:
        current = conn.execute("SELECT * FROM crm_deals WHERE id = %s", (deal_id,)).fetchone()
        if not current:
            return None
        service = payload.get("service") if payload.get("service") in SERVICES else current["service"]
        client_type = payload.get("clientType") if payload.get("clientType") in CLIENT_TYPES else current["client_type"]
        details = sanitize_details(service, client_type, payload.get("details") if "details" in payload else json_obj(current.get("details")))
        inception = parse_date(str(payload.get("inceptionDate") or current.get("inception_date") or ""))
        expiry = parse_date(str(payload.get("expiryDate") or current.get("expiry_date") or ""))
        owner_id = payload.get("ownerId") if "ownerId" in payload else current.get("owner_id")
        if owner_id == "":
            owner_id = None
        conn.execute(
            """
            UPDATE crm_deals
            SET owner_id = %s, service = %s, client_type = %s, insurer = %s, premium = %s,
                vehicle_value = %s, inception_date = %s, expiry_date = %s, installment = %s,
                details = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (
                owner_id,
                service,
                client_type,
                (payload.get("insurer") if "insurer" in payload else current.get("insurer") or "")[:80],
                money(payload["premium"]) if "premium" in payload else current.get("premium") or 0,
                money(payload["vehicleValue"]) if "vehicleValue" in payload else current.get("vehicle_value") or 0,
                inception,
                expiry,
                bool(payload["installment"]) if "installment" in payload else bool(current.get("installment")),
                Json(details),
                deal_id,
            ),
        )
        if expiry:
            conn.execute(
                """
                UPDATE crm_renewals SET due_date = %s
                WHERE deal_id = %s AND status = 'pending'
                """,
                (expiry, deal_id),
            )
        if payload.get("kraPin") or payload.get("dob"):
            conn.execute(
                """
                UPDATE crm_accounts SET kra_pin = COALESCE(NULLIF(%s, ''), kra_pin),
                    dob = COALESCE(%s, dob), updated_at = NOW()
                WHERE id = %s
                """,
                (payload.get("kraPin") or "", parse_date(str(payload.get("dob") or "")), current["account_id"]),
            )
        conn.commit()
    return get_deal(deal_id)


def add_payment(deal_id: str, payload: dict, actor_id: str | None) -> dict:
    amount = money(payload.get("amount"))
    if amount <= 0:
        raise ValueError("Enter a payment amount")
    method = (payload.get("method") or "mpesa").strip().lower()
    if method not in {"mpesa", "cheque", "other"}:
        method = "mpesa"
    paid_at = parse_date(str(payload.get("paidAt") or "")) or date.today()
    pay_id = uuid.uuid4().hex[:12]
    with db.pool().connection() as conn:
        deal = conn.execute("SELECT id FROM crm_deals WHERE id = %s", (deal_id,)).fetchone()
        if not deal:
            raise ValueError("Deal not found")
        conn.execute(
            """
            INSERT INTO crm_payments (id, deal_id, method, mpesa_code, amount, paid_at, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                pay_id,
                deal_id,
                method,
                (payload.get("mpesaCode") or "")[:40],
                amount,
                paid_at,
                (payload.get("notes") or "")[:400],
                actor_id,
            ),
        )
        conn.commit()
    return get_deal(deal_id)


def extract_logbook_fields(path: Path) -> dict:
    try:
        raw = security.decrypt_bytes(path.read_bytes())
    except (OSError, ValueError):
        return {}
    text = re.sub(rb"[^\x20-\x7E\n\r]", b" ", raw).decode("ascii", errors="ignore")
    text = re.sub(r"\s+", " ", text)
    if len(text.strip()) < 8:
        return {}
    plate = re.search(r"\bK[A-Z]{2}\s?\d{3}[A-Z]\b", text, re.I)
    year = re.search(r"\b(19|20)\d{2}\b", text)
    chassis = re.search(r"\b[A-HJ-NPR-Z0-9]{11,17}\b", text)
    fields = {}
    if plate:
        fields["registration"] = plate.group(0).upper().replace("  ", " ")
    if year:
        fields["year"] = year.group(0)
    if chassis:
        fields["chassis"] = chassis.group(0).upper()
    return fields


def save_file(parent: dict, kind: str, file_storage, actor_id: str | None = None) -> dict:
    if kind not in FILE_KINDS:
        raise ValueError("Unknown document type")
    if not file_storage or not file_storage.filename:
        raise ValueError("Choose a file")
    from werkzeug.utils import secure_filename

    filename = secure_filename(file_storage.filename)
    raw = file_storage.read()
    file_storage.stream.seek(0)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("File too large. Maximum is 10MB.")
    sniffed = security.sniff_upload(raw)
    if not sniffed or sniffed not in ALLOWED_FILE_EXT:
        raise ValueError("Use PDF, JPG, or PNG")
    stored = f"{uuid.uuid4().hex}{sniffed}"
    CRM_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = CRM_UPLOAD_DIR / stored
    dest.write_bytes(security.encrypt_bytes(raw))
    file_id = uuid.uuid4().hex[:12]
    extracted = extract_logbook_fields(dest) if kind == "logbook" else {}
    with db.pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO crm_files (id, lead_id, deal_id, account_id, kind, original_name, stored_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                file_id,
                parent.get("leadId") or None,
                parent.get("dealId") or None,
                parent.get("accountId") or None,
                kind,
                filename,
                stored,
            ),
        )
        if extracted and parent.get("leadId"):
            lead = conn.execute("SELECT * FROM crm_leads WHERE id = %s", (parent["leadId"],)).fetchone()
            if lead:
                details = json_obj(lead.get("details"))
                vehicle = details.get("vehicle") if isinstance(details.get("vehicle"), dict) else {}
                vehicle.update({key: value for key, value in extracted.items() if value})
                details["vehicle"] = vehicle
                conn.execute(
                    "UPDATE crm_leads SET details = %s, updated_at = NOW() WHERE id = %s",
                    (Json(details), parent["leadId"]),
                )
        if extracted and parent.get("dealId"):
            deal = conn.execute("SELECT * FROM crm_deals WHERE id = %s", (parent["dealId"],)).fetchone()
            if deal:
                details = json_obj(deal.get("details"))
                vehicle = details.get("vehicle") if isinstance(details.get("vehicle"), dict) else {}
                vehicle.update({key: value for key, value in extracted.items() if value})
                details["vehicle"] = vehicle
                conn.execute(
                    "UPDATE crm_deals SET details = %s, updated_at = NOW() WHERE id = %s",
                    (Json(details), parent["dealId"]),
                )
        conn.commit()
    return {"file": {"id": file_id, "kind": kind, "name": filename, "url": f"/api/admin/crm/files/{file_id}"}, "extracted": extracted}


def get_file(file_id: str) -> dict | None:
    with db.pool().connection() as conn:
        row = conn.execute("SELECT * FROM crm_files WHERE id = %s", (file_id,)).fetchone()
    return dict(row) if row else None


def dashboard(owner_id: str | None = None) -> dict:
    today = date.today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    year_ago = today.replace(year=today.year - 1, day=1)
    owner_sql = " AND d.owner_id = %s" if owner_id else ""
    lead_sql = " AND owner_id = %s" if owner_id else ""
    owner_args = (owner_id,) if owner_id else ()
    with db.pool().connection() as conn:
        names = staff_map(conn)
        total = _sum_revenue(conn, owner_id=owner_id)
        monthly = _sum_revenue(conn, start=month_start, owner_id=owner_id)
        staff_rows = _staff_revenue(conn, month_start, owner_id)
        series = _month_series(conn, year_ago, owner_id)
        leads = conn.execute(
            "SELECT status, COUNT(*) AS n FROM crm_leads WHERE 1=1" + lead_sql + " GROUP BY status",
            owner_args,
        ).fetchall()
        due = conn.execute(
            """
            SELECT d.*, a.name AS account_name, a.email AS account_email, a.mobile AS account_mobile,
                   r.id AS renewal_id, r.due_date, r.notice_sent_at, r.status AS renewal_status
            FROM crm_deals d
            JOIN crm_accounts a ON a.id = d.account_id
            JOIN crm_renewals r ON r.deal_id = d.id
            WHERE r.status = 'pending'
              AND r.due_date <= %s
              AND r.due_date >= %s
            """
            + owner_sql
            + """
            ORDER BY r.due_date ASC
            """,
            (today + timedelta(days=RENEWAL_WINDOW_DAYS), today - timedelta(days=14), *owner_args),
        ).fetchall()
        open_leads = conn.execute(
            "SELECT COUNT(*) AS n FROM crm_leads WHERE status IN ('new', 'contacted', 'quoted')" + lead_sql,
            owner_args,
        ).fetchone()["n"]
        if owner_id:
            clients = conn.execute(
                """
                SELECT COUNT(*) AS n FROM (
                    SELECT account_id FROM crm_leads WHERE owner_id = %s AND account_id IS NOT NULL
                    UNION
                    SELECT account_id FROM crm_deals WHERE owner_id = %s AND account_id IS NOT NULL
                ) t
                """,
                (owner_id, owner_id),
            ).fetchone()["n"]
        else:
            clients = conn.execute("SELECT COUNT(*) AS n FROM crm_accounts").fetchone()["n"]
        year_staff = _staff_revenue(conn, year_start, owner_id)
        target_row = conn.execute("SELECT value FROM crm_settings WHERE key = 'monthly_target'").fetchone()
    target = money(target_row["value"]) if target_row else DEFAULT_MONTHLY_TARGET
    if target <= 0:
        target = DEFAULT_MONTHLY_TARGET
    monthly_val = money(monthly)
    percent = round((monthly_val / target) * 100, 1) if target else 0.0
    series_map = {row["month"]: money(row["revenue"]) for row in series}
    month_cursor = today.replace(day=1)
    filled = []
    for step in range(11, -1, -1):
        year = month_cursor.year
        month = month_cursor.month - step
        while month <= 0:
            month += 12
            year -= 1
        key = f"{year:04d}-{month:02d}"
        filled.append({"month": key, "revenue": series_map.get(key, 0.0), "target": target})
    year_total = sum(money(row["revenue"]) for row in year_staff) or 0.0
    yearly = [
        {
            "ownerId": row["owner_id"] or "",
            "name": names.get(row["owner_id"] or "") or "Unassigned",
            "revenue": money(row["revenue"]),
            "percent": round((money(row["revenue"]) / year_total) * 100, 1) if year_total else 0.0,
        }
        for row in year_staff
    ]
    lead_counts = {row["status"]: int(row["n"]) for row in leads}
    staff = [
        {
            "ownerId": row["owner_id"] or "",
            "name": names.get(row["owner_id"] or "") or "Unassigned",
            "revenue": money(row["revenue"]),
            "deals": int(row["deals"]),
        }
        for row in staff_rows
    ]
    renewals = []
    for row in due:
        renewals.append(
            {
                "dealId": row["id"],
                "renewalId": row["renewal_id"],
                "name": row.get("account_name") or "",
                "email": row.get("account_email") or "",
                "mobile": row.get("account_mobile") or "",
                "cover": cover_from_service(row.get("service") or ""),
                "premium": money(row.get("premium")),
                "dueDate": fmt_date(row.get("due_date")),
                "noticeSentAt": db.fmt_ts(row.get("notice_sent_at")),
                "ownerId": row.get("owner_id") or "",
                "ownerName": names.get(row.get("owner_id") or "") or "Unassigned",
            }
        )
    return {
        "totalRevenue": money(total),
        "monthlyRevenue": monthly_val,
        "openLeads": int(open_leads),
        "clientCount": int(clients),
        "target": target,
        "percent": percent,
        "renewalsDue": len(renewals),
        "pipeline": {
            "new": lead_counts.get("new", 0),
            "contacted": lead_counts.get("contacted", 0),
            "quoted": lead_counts.get("quoted", 0),
            "won": lead_counts.get("won", 0),
        },
        "staffRevenue": staff,
        "yearlyStaff": yearly,
        "monthlySeries": filled,
        "renewals": renewals,
    }


def quote_html(deal: dict, account: dict) -> str:
    details = json_obj(deal.get("details"))
    limits = details.get("limits") if isinstance(details.get("limits"), dict) else {}
    vehicle = details.get("vehicle") if isinstance(details.get("vehicle"), dict) else {}

    def hx(value) -> str:
        return escape(str(value or ""))

    lines = [
        f"<p>Client: <strong>{hx(account.get('name'))}</strong> ({hx(deal.get('client_type'))})</p>",
        f"<p>Cover: <strong>{hx(cover_from_service(deal.get('service') or ''))}</strong></p>",
        f"<p>Premium: <strong>KES {money(deal.get('premium')):,.0f}</strong></p>",
        f"<p>Period: {hx(fmt_date(deal.get('inception_date')))} to {hx(fmt_date(deal.get('expiry_date')))}</p>",
    ]
    if deal.get("insurer"):
        lines.append(f"<p>Insurer: {hx(deal.get('insurer'))}</p>")
    if limits:
        lines.append(
            "<p>Limits — inpatient {inpatient}, outpatient {outpatient}, dental {dental}, optical {optical}, maternity {maternity}</p>".format(
                **{key: hx(limits.get(key) or "—") for key in ("inpatient", "outpatient", "dental", "optical", "maternity")}
            )
        )
    if details.get("population"):
        lines.append(f"<p>Population: {hx(details.get('population'))}</p>")
    if details.get("category"):
        lines.append(f"<p>Category: {hx(details.get('category'))}</p>")
    if vehicle:
        lines.append(
            f"<p>Vehicle: {hx(vehicle.get('make'))} {hx(vehicle.get('model'))} {hx(vehicle.get('registration'))} · value KES {hx(vehicle.get('value') or '—')}</p>"
        )
    if details.get("cover_amount"):
        lines.append(f"<p>WIBA amount: {hx(details.get('cover_amount'))}</p>")
    return "".join(lines)


def due_renewals(force: bool = False) -> list[dict]:
    today = date.today()
    with db.pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT r.*, d.id AS deal_pk, d.service, d.premium, d.details, d.inception_date, d.expiry_date,
                   d.client_type, d.insurer, d.owner_id,
                   a.name, a.email, a.mobile
            FROM crm_renewals r
            JOIN crm_deals d ON d.id = r.deal_id
            JOIN crm_accounts a ON a.id = d.account_id
            WHERE r.status = 'pending'
              AND r.due_date <= %s
              AND r.due_date >= %s
              AND (r.notice_sent_at IS NULL OR %s)
            ORDER BY r.due_date ASC
            """,
            (today + timedelta(days=RENEWAL_WINDOW_DAYS), today - timedelta(days=14), force),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_renewal_sent(renewal_id: str) -> None:
    with db.pool().connection() as conn:
        conn.execute(
            "UPDATE crm_renewals SET notice_sent_at = NOW(), status = 'sent' WHERE id = %s",
            (renewal_id,),
        )
        conn.commit()


def invoice_pay_to() -> dict:
    return {
        "bank": os.environ.get("INVOICE_BANK") or "KCB Bank",
        "accountName": os.environ.get("INVOICE_ACCOUNT_NAME") or "AMIRI INSURANCE AGENCY",
        "accountNumber": os.environ.get("INVOICE_ACCOUNT_NUMBER") or "1272842827",
    }


def get_monthly_target() -> float:
    with db.pool().connection() as conn:
        row = conn.execute("SELECT value FROM crm_settings WHERE key = 'monthly_target'").fetchone()
    value = money(row["value"]) if row else DEFAULT_MONTHLY_TARGET
    return value if value > 0 else DEFAULT_MONTHLY_TARGET


def set_monthly_target(value) -> float:
    amount = money(value)
    if amount <= 0:
        raise ValueError("Target must be greater than zero")
    with db.pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO crm_settings (key, value) VALUES ('monthly_target', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (str(amount),),
        )
        conn.commit()
    return amount


def invoice_to_api(row: dict) -> dict:
    return {
        "id": row["id"],
        "number": row["number"],
        "accountId": row.get("account_id") or "",
        "dealId": row.get("deal_id") or "",
        "clientName": row.get("client_name") or "",
        "clientEmail": row.get("client_email") or "",
        "clientMobile": row.get("client_mobile") or "",
        "clientType": row.get("client_type") or "individual",
        "service": row.get("service") or "other",
        "cover": cover_from_service(row.get("service") or "other"),
        "description": row.get("description") or "",
        "amount": money(row.get("amount")),
        "status": row.get("status") or "unpaid",
        "dueDate": fmt_date(row.get("due_date")),
        "notes": row.get("notes") or "",
        "createdAt": db.fmt_ts(row.get("created_at")),
        "createdBy": row.get("created_by") or "",
        "payTo": invoice_pay_to(),
    }


def list_invoices() -> list[dict]:
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT * FROM crm_invoices ORDER BY created_at DESC").fetchall()
    return [invoice_to_api(row) for row in rows]


def get_invoice(invoice_id: str) -> dict | None:
    with db.pool().connection() as conn:
        row = conn.execute(
            "SELECT * FROM crm_invoices WHERE id = %s OR number = %s",
            (invoice_id, invoice_id),
        ).fetchone()
    return invoice_to_api(row) if row else None


def _next_invoice_number(conn) -> str:
    year = date.today().year
    prefix = f"AMI-{year}-"
    row = conn.execute(
        "SELECT number FROM crm_invoices WHERE number LIKE %s ORDER BY number DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    n = 1
    if row:
        try:
            n = int(str(row["number"]).split("-")[-1]) + 1
        except ValueError:
            n = 1
    return f"{prefix}{n:04d}"


def create_invoice(payload: dict, actor_id: str | None) -> dict:
    name = (payload.get("clientName") or payload.get("name") or "").strip()
    if len(name) < 2:
        raise ValueError("Client name is required")
    amount = money(payload.get("amount"))
    if amount <= 0:
        raise ValueError("Enter an invoice amount")
    service = payload.get("service") if payload.get("service") in SERVICES else "other"
    client_type = payload.get("clientType") if payload.get("clientType") in CLIENT_TYPES else "individual"
    status = payload.get("status") if payload.get("status") in {"unpaid", "paid", "void"} else "unpaid"
    invoice_id = uuid.uuid4().hex[:12]
    paid_at = date.today() if status == "paid" else None
    with db.pool().connection() as conn:
        number = _next_invoice_number(conn)
        conn.execute(
            """
            INSERT INTO crm_invoices (
                id, number, account_id, deal_id, client_name, client_email, client_mobile,
                client_type, service, description, amount, status, due_date, notes, created_by, paid_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                invoice_id,
                number,
                payload.get("accountId") or None,
                payload.get("dealId") or None,
                name,
                (payload.get("clientEmail") or payload.get("email") or "").strip().lower(),
                (payload.get("clientMobile") or payload.get("mobile") or "").strip(),
                client_type,
                service,
                (payload.get("description") or "")[:2000],
                amount,
                status,
                parse_date(str(payload.get("dueDate") or "")),
                (payload.get("notes") or "")[:2000],
                actor_id,
                paid_at,
            ),
        )
        row = conn.execute("SELECT * FROM crm_invoices WHERE id = %s", (invoice_id,)).fetchone()
        if row:
            _sync_paid_invoice(conn, dict(row))
        conn.commit()
    return get_invoice(invoice_id)


def update_invoice(invoice_id: str, payload: dict) -> dict | None:
    with db.pool().connection() as conn:
        current = conn.execute("SELECT * FROM crm_invoices WHERE id = %s", (invoice_id,)).fetchone()
        if not current:
            return None
        status = payload.get("status") if payload.get("status") in {"unpaid", "paid", "void"} else current["status"]
        amount = money(payload["amount"]) if "amount" in payload else current["amount"]
        paid_at = current.get("paid_at")
        if status == "paid":
            paid_at = paid_at or date.today()
        else:
            paid_at = None
        conn.execute(
            """
            UPDATE crm_invoices
            SET client_name = %s, client_email = %s, client_mobile = %s, client_type = %s,
                service = %s, description = %s, amount = %s, status = %s, due_date = %s,
                notes = %s, paid_at = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (
                (payload.get("clientName") or current["client_name"]).strip(),
                (payload.get("clientEmail") if "clientEmail" in payload else current["client_email"] or ""),
                (payload.get("clientMobile") if "clientMobile" in payload else current["client_mobile"] or ""),
                payload.get("clientType") if payload.get("clientType") in CLIENT_TYPES else current["client_type"],
                payload.get("service") if payload.get("service") in SERVICES else current["service"],
                payload.get("description") if "description" in payload else current["description"] or "",
                amount,
                status,
                parse_date(str(payload.get("dueDate") or current.get("due_date") or "")),
                payload.get("notes") if "notes" in payload else current.get("notes") or "",
                paid_at,
                invoice_id,
            ),
        )
        row = conn.execute("SELECT * FROM crm_invoices WHERE id = %s", (invoice_id,)).fetchone()
        if row:
            _sync_paid_invoice(conn, dict(row))
        conn.commit()
    return get_invoice(invoice_id)
