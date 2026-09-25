"""Request limits, HTML sanitizing, TOTP, uploads, and private files."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import shutil
import struct
import time
from collections import defaultdict
import re
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent
PRIVATE_CRM_DIR = ROOT / "data" / "uploads" / "crm"
LEGACY_CRM_DIR = ROOT / "static" / "uploads" / "crm"

ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "h1",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "blockquote",
    "a",
    "span",
    "div",
    "img",
}
VOID_TAGS = {"br", "img"}
SKIP_TAGS = {"script", "style", "iframe", "object", "embed", "link", "meta", "form"}

_rate_hits: dict[str, list[float]] = defaultdict(list)
_rate_lock = Lock()


def relocate_crm_uploads() -> Path:
    PRIVATE_CRM_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_CRM_DIR.is_dir():
        for item in LEGACY_CRM_DIR.iterdir():
            if not item.is_file():
                continue
            dest = PRIVATE_CRM_DIR / item.name
            if dest.exists():
                item.unlink()
            else:
                shutil.move(str(item), str(dest))
    return PRIVATE_CRM_DIR


def is_private_upload_path(path: str) -> bool:
    value = (path or "").lower()
    return value.startswith("/static/uploads/crm") or value.startswith("/uploads/crm")


def client_ip(request, behind_proxy: bool) -> str:
    remote = (request.remote_addr or "unknown")[:80]
    if behind_proxy and remote in {"127.0.0.1", "::1"}:
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if forwarded:
            return forwarded[:80]
    return remote


def rate_limited(bucket: str, limit: int, window: int) -> bool:
    now = time.time()
    with _rate_lock:
        hits = [stamp for stamp in _rate_hits[bucket] if now - stamp < window]
        if len(hits) >= limit:
            _rate_hits[bucket] = hits
            return True
        hits.append(now)
        _rate_hits[bucket] = hits
        return False


def clear_rate(bucket: str) -> None:
    with _rate_lock:
        _rate_hits.pop(bucket, None)


def safe_next_path(raw: str, fallback: str = "/admin") -> str:
    nxt = (raw or "").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        return fallback
    if any(ch in nxt for ch in ("\\", "\n", "\r", "\t")):
        return fallback
    if "://" in nxt or ".." in nxt:
        return fallback
    if nxt.startswith("/\\") or nxt.startswith("/%"):
        return fallback
    return nxt


def public_base_url(configured: str, request_host: str, request_url: str, extra_hosts: str = "") -> str:
    if configured:
        return configured.rstrip("/")
    host = (request_host or "").split(":")[0].lower()
    allowed = {
        "localhost",
        "127.0.0.1",
        "amiriinsuranceagency.com",
        "www.amiriinsuranceagency.com",
    }
    allowed.update(item.strip().lower() for item in (extra_hosts or "").split(",") if item.strip())
    if host not in allowed:
        return "https://amiriinsuranceagency.com"
    return (request_url or "").rstrip("/") or "https://amiriinsuranceagency.com"


def safe_blog_image(raw: str) -> str:
    value = (raw or "").strip()
    if ".." in value or value.startswith("//"):
        return ""
    if value.startswith("/static/uploads/blog/") or value.startswith("/static/img/"):
        return value
    return ""


def _safe_href(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.scheme == "mailto" and parsed.path:
        return parsed.geturl()
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return parsed.geturl()
    return ""


def _safe_src(value: str) -> str:
    image = safe_blog_image(value)
    if image:
        return image
    parsed = urlparse((value or "").strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return parsed.geturl()
    return ""


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip or tag not in ALLOWED_TAGS:
            return
        attrs_d = {str(key).lower(): (val or "") for key, val in attrs}
        kept: list[str] = []
        if tag == "a":
            href = _safe_href(attrs_d.get("href", ""))
            if href:
                kept.append(f'href="{escape(href, quote=True)}"')
            kept.append('rel="noopener noreferrer nofollow"')
        elif tag == "img":
            src = _safe_src(attrs_d.get("src", ""))
            if not src:
                return
            kept.append(f'src="{escape(src, quote=True)}"')
            kept.append(f'alt="{escape(attrs_d.get("alt", "")[:200], quote=True)}"')
        attr_html = (" " + " ".join(kept)) if kept else ""
        self.parts.append(f"<{tag}{attr_html}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip or tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(escape(data))


def sanitize_html(raw: str) -> str:
    if not raw:
        return ""
    parser = _Sanitizer()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return escape(raw)
    return "".join(parser.parts)


def plain_text(raw: str, limit: int = 400) -> str:
    text = re.sub(r"<[^>]+>", " ", sanitize_html(raw))
    return " ".join(unescape(text).split())[:limit]


def sanitize_public_post(post: dict) -> dict:
    item = dict(post)
    item["content"] = sanitize_html(str(item.get("content") or ""))
    item["excerpt"] = plain_text(str(item.get("excerpt") or item.get("content") or ""), 400)
    item["title"] = plain_text(str(item.get("title") or ""), 160)
    item["author"] = plain_text(str(item.get("author") or ""), 80)
    item["category"] = plain_text(str(item.get("category") or ""), 60)
    item["image"] = safe_blog_image(str(item.get("image") or ""))
    return item


def _secret_bytes() -> bytes:
    return (os.environ.get("SECRET_KEY") or "dev-only-not-for-production").encode("utf-8")


def sniff_upload(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data.startswith(b"%PDF"):
        return ".pdf"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _keystream(key: bytes, length: int) -> bytes:
    out = bytearray()
    index = 0
    while len(out) < length:
        out.extend(hashlib.sha256(key + index.to_bytes(8, "big")).digest())
        index += 1
    return bytes(out[:length])


def encrypt_bytes(data: bytes) -> bytes:
    key = hashlib.sha256(_secret_bytes()).digest()
    iv = os.urandom(16)
    cipher = bytes(a ^ b for a, b in zip(data, _keystream(key + iv, len(data))))
    mac = hmac.new(key, iv + cipher, hashlib.sha256).digest()
    return b"AM1" + iv + mac + cipher


def decrypt_bytes(blob: bytes) -> bytes:
    if not blob.startswith(b"AM1"):
        return blob
    iv, mac, cipher = blob[3:19], blob[19:51], blob[51:]
    key = hashlib.sha256(_secret_bytes()).digest()
    expected = hmac.new(key, iv + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        raise ValueError("Corrupt or foreign file")
    return bytes(a ^ b for a, b in zip(cipher, _keystream(key + iv, len(cipher))))


def encrypt_crm_files() -> None:
    PRIVATE_CRM_DIR.mkdir(parents=True, exist_ok=True)
    for item in PRIVATE_CRM_DIR.iterdir():
        if not item.is_file():
            continue
        raw = item.read_bytes()
        if raw.startswith(b"AM1"):
            continue
        item.write_bytes(encrypt_bytes(raw))


def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").replace("=", "")


def totp_code(secret: str, when: float | None = None) -> str:
    pad = secret + ("=" * ((8 - len(secret) % 8) % 8))
    key = base64.b32decode(pad, casefold=True)
    counter = int((when if when is not None else time.time()) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def totp_valid(secret: str, code: str) -> bool:
    offered = re.sub(r"\D", "", code or "")
    if len(offered) != 6 or not secret:
        return False
    now = time.time()
    for drift in (-1, 0, 1):
        if hmac.compare_digest(totp_code(secret, now + drift * 30), offered):
            return True
    return False


def otpauth_url(username: str, secret: str) -> str:
    label = quote(f"Amiri:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer=Amiri&digits=6&period=30"


def form_token() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(_secret_bytes(), ts.encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def form_token_valid(token: str, max_age: int = 3600) -> bool:
    ts, sep, sig = (token or "").partition(".")
    if not sep or not ts.isdigit():
        return False
    if abs(int(time.time()) - int(ts)) > max_age:
        return False
    expected = hmac.new(_secret_bytes(), ts.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def csrf_allowed(request, extra_hosts: str = "") -> bool:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True
    host = (request.host or "").split(":")[0].lower()
    allowed = {host, "localhost", "127.0.0.1", "amiriinsuranceagency.com", "www.amiriinsuranceagency.com"}
    allowed.update(item.strip().lower() for item in (extra_hosts or "").split(",") if item.strip())
    public = (os.environ.get("PUBLIC_URL") or "").strip()
    if public:
        allowed.add(urlparse(public).netloc.split(":")[0].lower())

    def host_ok(raw: str) -> bool:
        if not raw:
            return False
        netloc = urlparse(raw).netloc.split(":")[0].lower()
        return bool(netloc) and netloc in allowed

    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()
    if origin:
        return host_ok(origin)
    if referer:
        return host_ok(referer)
    return (request.remote_addr or "") in {"127.0.0.1", "::1"}


def paginate(rows: list, page: int, limit: int, cap: int = 200) -> list:
    size = min(cap, max(1, limit))
    start = max(0, (max(1, page) - 1) * size)
    return rows[start : start + size]


def can_see_owner(role: str, actor_id: str | None, owner_id: str | None) -> bool:
    if role == "admin":
        return True
    owner = owner_id or ""
    return not owner or owner == (actor_id or "")
