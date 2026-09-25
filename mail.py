"""Transactional email through Brevo."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from html import escape

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_CONTACT_URL = "https://api.brevo.com/v3/contacts"

OFFICE_PHONE = "+254 746 158 002"
OFFICE_EMAIL = "info@amiriinsuranceagency.com"
SITE_NAME = "Amiri Insurance"


def _api_key() -> str:
    return (os.environ.get("BREVO_API_KEY") or "").strip()


def sender() -> dict:
    return {
        "name": os.environ.get("BREVO_SENDER_NAME") or SITE_NAME,
        "email": os.environ.get("BREVO_SENDER_EMAIL") or OFFICE_EMAIL,
    }


def notify_emails(extra: list[str] | None = None) -> list[str]:
    found = set()
    primary = (os.environ.get("BREVO_NOTIFY_EMAIL") or OFFICE_EMAIL).strip().lower()
    if primary:
        found.add(primary)
    for item in extra or []:
        email = (item or "").strip().lower()
        if email and "@" in email:
            found.add(email)
    return sorted(found)


def wrap_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f4f7fb;font-family:'Segoe UI',Arial,sans-serif;color:#1c2b3a;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f7fb;padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #e6edf4;">
        <tr><td style="background:#061525;padding:22px 28px;color:#ffffff;">
          <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#f3c453;">Amiri Insurance</div>
          <div style="font-size:22px;font-weight:700;margin-top:6px;">{escape(title)}</div>
        </td></tr>
        <tr><td style="padding:28px;font-size:16px;line-height:1.6;color:#1c2b3a;">{body}</td></tr>
        <tr><td style="padding:0 28px 28px;font-size:14px;color:#5a6a7a;">
          Utalii House, 3rd Floor, Wing B, Nairobi<br>
          <a href="tel:+254746158002" style="color:#1a6fe8;">{OFFICE_PHONE}</a> ·
          <a href="mailto:{OFFICE_EMAIL}" style="color:#1a6fe8;">{OFFICE_EMAIL}</a>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def send_email(to_email: str, subject: str, html: str, reply_to: str = "") -> bool:
    key = _api_key()
    if not key or not to_email:
        if not key:
            print("Brevo skipped: set BREVO_API_KEY in .env")
        return False
    payload = {
        "sender": sender(),
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BREVO_SEND_URL,
        data=data,
        headers={"api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            return 200 <= res.status < 300
    except urllib.error.HTTPError as exc:
        exc.read()
        print(f"Brevo send failed ({exc.code})")
        return False
    except OSError:
        print("Brevo send failed")
        return False


_email_slots = threading.Semaphore(8)


def send_email_async(to_email: str, subject: str, html: str, reply_to: str = "") -> None:
    def run() -> None:
        if not _email_slots.acquire(blocking=False):
            print("Email skipped: send queue is full")
            return
        try:
            send_email(to_email, subject, html, reply_to)
        finally:
            _email_slots.release()

    threading.Thread(target=run, daemon=True).start()


def add_brevo_contact(email: str) -> None:
    key = _api_key()
    if not key or not email:
        return
    payload = {"email": email, "updateEnabled": True}
    list_id = (os.environ.get("BREVO_LIST_ID") or "").strip()
    if list_id.isdigit():
        payload["listIds"] = [int(list_id)]
    req = urllib.request.Request(
        BREVO_CONTACT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=12)
    except urllib.error.HTTPError as exc:
        if exc.code not in {204, 201, 400}:
            print(f"Brevo contact failed ({exc.code})")
    except OSError as exc:
        print(f"Brevo contact failed: {exc}")


def notify_quote(item: dict, team: list[str]) -> None:
    name = escape(item.get("name") or "there")
    cover = escape(item.get("cover") or "cover")
    email = item.get("email") or ""
    mobile = escape(item.get("mobile") or "—")
    message = escape(item.get("message") or "No extra notes.")
    when = " ".join(part for part in [item.get("prefDate") or "", item.get("prefTime") or ""] if part) or "—"
    team_html = wrap_html(
        "New quote request",
        f"<p><strong>{name}</strong> asked for <strong>{cover}</strong>.</p>"
        f"<p>Email: {escape(email)}<br>Mobile: {mobile}<br>Preferred time: {escape(when)}</p>"
        f"<p>{message}</p>"
        f"<p>Open the admin workspace to call, WhatsApp, or update the status.</p>",
    )
    for dest in team:
        send_email_async(dest, f"New quote: {item.get('cover') or 'cover'} — {item.get('name')}", team_html, reply_to=email)
    if email:
        client_html = wrap_html(
            "We received your request",
            f"<p>Hi {name},</p>"
            f"<p>Thank you for requesting <strong>{cover}</strong>. We will get back immediately.</p>"
            f"<p>If you need us sooner, call or WhatsApp {OFFICE_PHONE}.</p>",
        )
        send_email_async(email, f"Amiri Insurance — we received your {item.get('cover') or 'cover'} request", client_html)


def notify_newsletter(email: str, created: bool, team: list[str]) -> None:
    threading.Thread(target=add_brevo_contact, args=(email,), daemon=True).start()
    if not created:
        return
    client_html = wrap_html(
        "You are on the list",
        "<p>Thank you for joining the Amiri newsletter. We will send insurance news and practical tips once in a while.</p>",
    )
    send_email_async(email, "Amiri Insurance — newsletter confirmation", client_html)
    team_html = wrap_html("New newsletter subscriber", f"<p>{escape(email)} joined the newsletter.</p>")
    for dest in team:
        send_email_async(dest, "New newsletter subscriber", team_html)


def notify_new_user(user: dict, login_url: str) -> None:
    email = user.get("email") or ""
    if not email:
        return
    name = escape(user.get("name") or user.get("username") or "there")
    html = wrap_html(
        "Your Amiri admin access",
        f"<p>Hi {name},</p>"
        f"<p>You can now manage Amiri Insurance as <strong>{escape(user.get('role') or 'manager')}</strong>.</p>"
        f"<p>Username: <strong>{escape(user.get('username') or '')}</strong><br>"
        f"Sign in: <a href=\"{escape(login_url)}\" style=\"color:#1a6fe8;\">{escape(login_url)}</a></p>"
        f"<p>Use the password you were given when your account was created.</p>",
    )
    send_email_async(email, "Amiri Insurance — admin access", html)


def notify_status(item: dict, previous: str) -> None:
    email = item.get("email") or ""
    status = item.get("status") or ""
    if not email or status == previous or status in {"new", "closed"}:
        return
    name = escape(item.get("name") or "there")
    cover = escape(item.get("cover") or "your cover")
    copy = {
        "contacted": f"<p>Hi {name},</p><p>We are following up on your <strong>{cover}</strong> request. If we missed you, call or WhatsApp {OFFICE_PHONE}.</p>",
        "quoted": f"<p>Hi {name},</p><p>Your <strong>{cover}</strong> quote is being prepared and we will walk you through it shortly. Call {OFFICE_PHONE} if you want to talk now.</p>",
        "won": f"<p>Hi {name},</p><p>Welcome. Your <strong>{cover}</strong> is in good hands with Amiri Insurance. Keep this email, and call us anytime on {OFFICE_PHONE}.</p>",
    }.get(status)
    if not copy:
        return
    send_email_async(email, f"Amiri Insurance — update on your {item.get('cover') or 'cover'}", wrap_html("An update on your cover", copy))


def notify_renewal(item: dict, quote_body: str, team: list[str]) -> None:
    name = escape(item.get("name") or "there")
    cover = escape(item.get("cover") or "your cover")
    due = escape(item.get("dueDate") or item.get("due_date") or "")
    email = item.get("email") or ""
    client_html = wrap_html(
        "Your cover is due for renewal",
        f"<p>Hi {name},</p>"
        f"<p>Your <strong>{cover}</strong> is due for renewal on <strong>{due}</strong>.</p>"
        f"{quote_body}"
        f"<p>Reply to this email or call {OFFICE_PHONE} to confirm your renewal.</p>",
    )
    team_html = wrap_html(
        "Renewal notice sent",
        f"<p><strong>{name}</strong> — {cover} renews on {due}.</p>"
        f"{quote_body}"
        f"<p>Email: {escape(email)}<br>Mobile: {escape(item.get('mobile') or '—')}</p>",
    )
    if email:
        send_email_async(email, f"Amiri Insurance — {item.get('cover') or 'cover'} renewal notice", client_html)
    for dest in team:
        send_email_async(dest, f"Renewal due: {item.get('cover') or 'cover'} — {item.get('name')}", team_html)


def notify_invoice(invoice: dict, team: list[str] | None = None) -> tuple[bool, str]:
    email = (invoice.get("clientEmail") or invoice.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return False, "Add a client email, then send the invoice."
    if not _api_key():
        return False, "Email is not configured. Set BREVO_API_KEY in .env."
    pay = invoice.get("payTo") or {}
    try:
        amount_txt = f"{float(invoice.get('amount') or 0):,.0f}"
    except (TypeError, ValueError):
        amount_txt = "0"
    name = escape(invoice.get("clientName") or "client")
    number = escape(invoice.get("number") or "")
    cover = escape(invoice.get("cover") or "cover")
    description = escape(invoice.get("description") or cover)
    due = escape(invoice.get("dueDate") or "Upon receipt")
    bank = escape(pay.get("bank") or "KCB Bank")
    account_name = escape(pay.get("accountName") or "AMIRI INSURANCE AGENCY")
    account_number = escape(pay.get("accountNumber") or "1272842827")
    notes = escape(invoice.get("notes") or "")
    notes_html = (
        f"<p style='margin:16px 0 0;padding:12px 14px;background:#f7fafc;border-radius:10px;color:#5a6a7a;'>"
        f"<strong style='display:block;color:#0b4a73;font-size:12px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;'>Notes</strong>{notes}</p>"
        if notes
        else ""
    )
    body = (
        f"<p>Hi {name},</p>"
        f"<p>Please find invoice <strong>{number}</strong> from Amiri Insurance Agency.</p>"
        "<table role='presentation' width='100%' cellspacing='0' cellpadding='0' "
        "style='margin:16px 0;background:#f7fafc;border:1px solid #e6eef5;border-radius:12px;'>"
        "<tr>"
        f"<td style='padding:14px 16px;font-size:13px;color:#5a6a7a;'>Cover<br><strong style='color:#12263a;font-size:15px;'>{cover}</strong></td>"
        f"<td style='padding:14px 16px;font-size:13px;color:#5a6a7a;'>Due<br><strong style='color:#12263a;font-size:15px;'>{due}</strong></td>"
        f"<td style='padding:14px 16px;font-size:13px;color:#5a6a7a;text-align:right;'>Amount due<br><strong style='color:#0b4a73;font-size:18px;'>KES {amount_txt}</strong></td>"
        "</tr></table>"
        f"<p style='margin:0 0 14px;color:#5a6a7a;'>{description}</p>"
        "<div style='border:1px solid #e6eef5;border-left:4px solid #1572B7;border-radius:12px;padding:14px 16px;background:#fbfdff;'>"
        "<div style='font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#1572B7;font-weight:700;margin-bottom:6px;'>Payment details</div>"
        f"<div style='font-size:16px;font-weight:700;color:#0b4a73;'>{account_name}</div>"
        f"<div style='color:#5a6a7a;'>{bank} · Account {account_number}</div></div>"
        f"{notes_html}"
        f"<p>Reply to this email or call {OFFICE_PHONE} if you have a question.</p>"
    )
    html = wrap_html(f"Invoice {invoice.get('number') or ''}", body)
    ok = send_email(email, f"Amiri Insurance — invoice {invoice.get('number') or ''}", html)
    if not ok:
        return False, "Could not send the invoice email. Check Brevo and try again."
    team_html = wrap_html(
        "Invoice emailed",
        f"<p>Invoice <strong>{number}</strong> was sent to {escape(email)}.</p>"
        f"<p>{name} · {cover} · KES {amount_txt}</p>",
    )
    for dest in team or []:
        if dest and dest != email:
            send_email_async(dest, f"Invoice sent: {invoice.get('number')} — {invoice.get('clientName')}", team_html)
    return True, f"Invoice emailed to {email}."
