import streamlit as st
import os
import json
import html
import re
import hashlib
import secrets
import smtplib
import ssl
import datetime
from email.message import EmailMessage

import requests

from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    Integer, String, Text, DateTime, Boolean, select, func,
)

import osint_engine
import llm

st.set_page_config(
    page_title="H & H Investigation — Investigative Intelligence",
    page_icon="◆",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Config (env vars first, then st.secrets, then default)
# ---------------------------------------------------------------------------
def get_config(key, default=None):
    if key in os.environ:
        return os.environ[key]
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


TIERS = [
    "Discovery — $295",
    "Asset & Affiliation — $595",
    "Family Law Standard — $895",
    "Family Law Premium — $1,495",
    "Monthly Retainer — $1,495/mo",
    "Spec Audit — $3,500+",
]

# Search-depth ladder — the self-service subscription model. Each tier is a
# superset of the previous one; the deepest tier reaches breach / dark-web
# exposure data. Source ids map to osint_engine.SOURCES. To change which
# sources a plan includes, edit the lists here.
DEPTH_RECON = ["username", "github", "reddit", "hackernews", "gravatar",
               "email_mx", "domain", "dns", "wayback"]
DEPTH_PRO = DEPTH_RECON + ["crtsh", "courtlistener", "opencorporates", "phone", "shodan"]
DEPTH_DEEP = DEPTH_PRO + ["hibp"]

DEPTHS = {
    "Recon — surface web": DEPTH_RECON,
    "Pro — public records & infrastructure": DEPTH_PRO,
    "Deep — adds breach & dark-web exposure": DEPTH_DEEP,
}

# Which plan unlocks which depth tiers. A plan can select any depth at or below
# its rank. Plans map 1:1 to the first N depth tiers.
PLAN_RANK = {"Recon": 0, "Pro": 1, "Deep": 2}


def allowed_depths(plan):
    """Depth-tier labels a plan may select (its rank and everything below)."""
    keys = list(DEPTHS.keys())
    return keys[: PLAN_RANK.get(plan, 0) + 1]

# Public-facing plan cards (Home). Tuple: name, tag, price, benefit headline,
# feature lines, featured?, badge. The middle tier carries the badge — buyers
# gravitate toward the recommended middle option (compromise effect), and the
# benefit line leads with the outcome, not the feature list.
PLANS = [
    ("Recon", "Surface web", "Free",
     "See anyone's public footprint in seconds — no card required.", [
        "Social-handle footprint across 12 sites",
        "GitHub · Reddit · Hacker News · Gravatar",
        "Email deliverability + domain WHOIS / DNS / Wayback",
    ], False, None),
    ("Pro", "Public records & infrastructure", "$34.99 / mo",
     "Go past the surface: court records, business ties, and live infrastructure.", [
        "Everything in Recon, plus:",
        "Court records (CourtListener) · company officers",
        "Subdomains (crt.sh) · phone intel · host & port intel (Shodan)",
    ], True, "Recommended"),
    ("Deep", "Breach & dark-web exposure", "$59.99 / mo",
     "Know what's already leaked — full breach & dark-web exposure.", [
        "Everything in Pro, plus:",
        "Breach / dark-web exposure lookup (HaveIBeenPwned)",
        "Scheduled monitoring with change alerts",
    ], False, None),
]

STATUS_ORDER = ["Submitted", "Engagement Sent", "In Progress", "Delivered"]

STATUS_COLORS = {
    "Submitted": "#5a6878",
    "Engagement Sent": "#3a7bd5",
    "In Progress": "#c9a444",
    "Delivered": "#2ea043",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Residents of these states are blocked from the self-service tool. California's
# investigative-services and consumer-data rules are the strictest in the U.S.,
# so CA residents are excluded pending counsel review. Edit this set to adjust.
RESTRICTED_STATES = {"California"}

US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
    "Outside the United States",
]

ACCEPTABLE_USE_SUMMARY = """
**You run the searches — you own how the results are used.** H&H provides the
tools; it does not conduct investigations for you and is not a consumer
reporting agency.

**Permitted:** lawful research you are authorized to perform — locating your own
information, due diligence, journalism, fraud prevention, reconnecting with
people, and similar legitimate purposes.

**Never permitted:**
- Employment, credit, insurance, housing/tenant, or any other **FCRA-covered**
  eligibility decision. Results are **not** a consumer report.
- Stalking, harassment, intimidation, threats, or causing harm to any person.
- Unlawful discrimination, or any use that violates federal, state, or local law.
- Re-selling the data or misrepresenting it as a background or credit report.
"""

TERMS_MD = """
# Terms of Use & Acceptable Use Policy

_Last updated: 2026-05-28_

These Terms govern your use of the H&H Investigation self-service search tool
(the "Tool"). By accessing or using the Tool you agree to these Terms. If you do
not agree, do not use the Tool.

## 1. Self-service nature of the Tool

The Tool provides **self-service** access to publicly available, open-source,
and public-record information. **You** decide what to search and **you** run each
search. H&H Investigation ("H&H") supplies software that automates lookups you
could perform yourself. H&H does **not** perform investigations on your behalf,
does **not** act as a licensed private investigator for you, and forms **no**
investigator-client or attorney-client relationship with you.

## 2. Not a consumer reporting agency

H&H is **not** a consumer reporting agency, and the information returned by the
Tool is **not** a "consumer report" or "investigative consumer report" as those
terms are defined in the federal Fair Credit Reporting Act (FCRA), 15 U.S.C.
§ 1681 et seq. **You may not use the Tool or its results, in whole or in part:**

- to make decisions about **employment** (hiring, retention, promotion, reassignment);
- to evaluate eligibility for **credit** or insurance;
- to evaluate **housing or tenancy** applications;
- to determine eligibility for a government **license or benefit**; or
- for any other purpose covered by the FCRA or any comparable state law.

If you need information for any of these purposes, obtain a compliant consumer
report from a licensed consumer reporting agency.

## 3. Prohibited uses

You agree that you will **not** use the Tool to:

- stalk, harass, intimidate, threaten, dox, or otherwise harm any person;
- violate the Driver's Privacy Protection Act (DPPA), the Gramm-Leach-Bliley Act
  (GLBA), or any other privacy, anti-stalking, computer-fraud, or data-protection law;
- engage in unlawful discrimination;
- impersonate any person or misrepresent the source or nature of the data; or
- resell, sublicense, or redistribute the data or present it as a background,
  credit, or consumer report.

## 4. Lawful purpose and your responsibility

You represent that for **every** search you run you have a lawful, legitimate
purpose and are authorized to seek the information. **You are solely responsible**
for your searches and for how you use the results. You agree to indemnify and
hold harmless H&H and its operators from any claim arising out of your use of the
Tool or your violation of these Terms or any law.

## 5. Geographic eligibility

The Tool is offered only to individuals located in, and resident of, eligible
U.S. jurisdictions. It is **not** available to residents of California or to
users outside the United States. You must accurately state your state of
residence; misrepresenting it is a breach of these Terms.

## 6. Data accuracy; no warranty

Information is aggregated from third-party public and open sources. H&H does not
originate, verify, or guarantee the accuracy, completeness, or timeliness of any
result. The Tool is provided **"as is"** and **"as available,"** without
warranties of any kind, express or implied. Results may be incomplete, outdated,
or incorrect, and must be independently verified before you rely on them.

## 7. Limitation of liability

To the maximum extent permitted by law, H&H and its operators will not be liable
for any indirect, incidental, special, consequential, or punitive damages, or for
any loss arising from your use of, or inability to use, the Tool or its results.

## 8. Eligibility and changes

You must be at least 18 years old to use the Tool. H&H may modify these Terms or
suspend the Tool at any time. Continued use after a change constitutes acceptance.

## 9. Contact

Questions about these Terms: joshua@hhinvestigations.com

---

_This document is a starting template and has not been reviewed by an attorney.
Have qualified counsel review and adapt it before relying on it in production._
"""


def esc(value):
    """HTML-escape any value before it enters an unsafe_allow_html block."""
    return html.escape("" if value is None else str(value))


# ---------------------------------------------------------------------------
# Database (SQLite locally, Postgres in production via DATABASE_URL)
# ---------------------------------------------------------------------------
metadata = MetaData()

requests_t = Table(
    "requests", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ref_number", String(32), unique=True),
    Column("access_token", String(64)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("client_name", String(255)),
    Column("client_email", String(255)),
    Column("client_firm", String(255)),
    Column("service_tier", String(100)),
    Column("rush", Boolean),
    Column("subject_name", String(255)),
    Column("anchor_phone", String(100)),
    Column("anchor_email", String(255)),
    Column("anchor_address", Text),
    Column("anchor_dob", String(50)),
    Column("anchor_employer", String(255)),
    Column("anchor_other", Text),
    Column("notes", Text),
    Column("status", String(50)),
    Column("admin_notes", Text),
)

# Persistence + learning substrate: every OSINT search is logged here so the
# system accumulates a dataset of what was searched, which sources answered,
# how fast, and where coverage gaps are — the basis for measuring and improving
# source performance over time.
searches_t = Table(
    "searches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True)),
    Column("query", Text),      # JSON: the non-empty query fields
    Column("summary", Text),    # JSON: [{source, status, items, latency_ms, error}]
    Column("n_sources", Integer),
    Column("n_ok", Integer),
)

# User accounts. A plan ("Recon" free / "Pro" / "Deep") controls how deep a
# user's searches can go. Stripe fields stay empty until a subscription is made.
users_t = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(255), unique=True),
    Column("pw_salt", String(64)),
    Column("pw_hash", String(128)),
    Column("created_at", DateTime(timezone=True)),
    Column("plan", String(20), default="Recon"),
    Column("plan_status", String(30), default="free"),
    Column("stripe_customer_id", String(64)),
    Column("stripe_subscription_id", String(64)),
    Column("current_period_end", DateTime(timezone=True)),
)

# Single-use, time-limited password-reset tokens. Stored hashed so a database
# leak never exposes a usable token. A separate table (not extra columns on
# users) so metadata.create_all adds it cleanly to existing databases.
password_resets_t = Table(
    "password_resets", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer),
    Column("token_hash", String(64)),
    Column("created_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
    Column("used", Boolean, default=False),
)

# Saved searches that monitor.py re-runs on a schedule, alerting on change.
monitors_t = Table(
    "monitors", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True)),
    Column("label", String(200)),
    Column("query", Text),          # JSON
    Column("notify_email", String(255)),
    Column("active", Boolean, default=True),
    Column("last_run", DateTime(timezone=True)),
    Column("last_hash", String(64)),
    Column("last_summary", Text),   # JSON
)

# Customer reviews. Submitted by signed-in users (one per user; resubmitting
# replaces the prior one and re-enters moderation). Hidden until an admin
# approves — the public site shows only real, vetted testimonials and stays
# empty until they exist. Nothing is ever seeded or fabricated. Separate table
# so metadata.create_all adds it cleanly to existing databases.
reviews_t = Table(
    "reviews", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer),
    Column("display_name", String(80)),
    Column("role", String(120)),
    Column("rating", Integer),
    Column("body", Text),
    Column("approved", Boolean, default=False),
    Column("featured", Boolean, default=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)


@st.cache_resource
def get_engine():
    url = get_config("DATABASE_URL", "sqlite:///hhi_intake.db")
    # Render/Heroku hand out postgres:// ; SQLAlchemy wants postgresql+psycopg2://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    metadata.create_all(engine)
    return engine


def insert_request(engine, data):
    now = datetime.datetime.now(datetime.timezone.utc)
    token = secrets.token_urlsafe(9)
    with engine.begin() as conn:
        res = conn.execute(
            requests_t.insert().values(
                ref_number="PENDING", access_token=token,
                created_at=now, updated_at=now,
                client_name=data["client_name"], client_email=data["client_email"],
                client_firm=data.get("client_firm", ""), service_tier=data["service_tier"],
                rush=bool(data.get("rush", False)), subject_name=data["subject_name"],
                anchor_phone=data.get("anchor_phone", ""), anchor_email=data.get("anchor_email", ""),
                anchor_address=data.get("anchor_address", ""), anchor_dob=data.get("anchor_dob", ""),
                anchor_employer=data.get("anchor_employer", ""), anchor_other=data.get("anchor_other", ""),
                notes=data.get("notes", ""), status="Submitted", admin_notes="",
            )
        )
        row_id = res.inserted_primary_key[0]
        ref = f"HHI-{now.year}-{row_id:04d}"
        conn.execute(
            requests_t.update().where(requests_t.c.id == row_id).values(ref_number=ref)
        )
    return ref, token


def get_request_by_token(engine, ref_number, token):
    with engine.connect() as conn:
        row = conn.execute(
            select(requests_t).where(
                requests_t.c.ref_number == ref_number,
                requests_t.c.access_token == token,
            )
        ).mappings().first()
    return row


def get_all_requests(engine, status=None):
    stmt = select(requests_t)
    if status and status != "All":
        stmt = stmt.where(requests_t.c.status == status)
    stmt = stmt.order_by(requests_t.c.id.desc())
    with engine.connect() as conn:
        return conn.execute(stmt).mappings().all()


def status_counts(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            select(requests_t.c.status, func.count()).group_by(requests_t.c.status)
        ).all()
    counts = {s: 0 for s in STATUS_ORDER}
    for status, n in rows:
        if status in counts:
            counts[status] = n
    return counts


def update_request(engine, ref_number, new_status, admin_notes):
    now = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            requests_t.update()
            .where(requests_t.c.ref_number == ref_number)
            .values(status=new_status, admin_notes=admin_notes, updated_at=now)
        )


# ---------------------------------------------------------------------------
# Search persistence + learning data
# ---------------------------------------------------------------------------
def log_search(engine, query, results):
    """Persist one search and its per-source outcome. Best-effort: a logging
    failure must never break the search itself."""
    now = datetime.datetime.now(datetime.timezone.utc)
    summary = [{
        "source": r.source, "status": r.status, "items": len(r.items),
        "latency_ms": getattr(r, "latency_ms", 0), "error": (r.error or "")[:200],
    } for r in results]
    q = {k: v for k, v in query.items() if (v or "").strip()}
    try:
        with engine.begin() as conn:
            conn.execute(searches_t.insert().values(
                created_at=now,
                query=json.dumps(q),
                summary=json.dumps(summary),
                n_sources=len(results),
                n_ok=sum(1 for r in results if r.status == "ok"),
            ))
    except Exception:  # noqa: BLE001 — never let logging break the search
        pass


def recent_searches(engine, limit=50):
    with engine.connect() as conn:
        return conn.execute(
            select(searches_t).order_by(searches_t.c.id.desc()).limit(limit)
        ).mappings().all()


def source_stats(engine, limit=1000):
    """Aggregate per-source reliability from the search log — the metric the
    system uses to track how well each source is doing its job."""
    rows = recent_searches(engine, limit=limit)
    stats = {}
    for row in rows:
        try:
            summary = json.loads(row["summary"] or "[]")
        except (ValueError, TypeError):
            continue
        for entry in summary:
            s = stats.setdefault(entry["source"], {
                "ok": 0, "not_found": 0, "no_key": 0, "error": 0,
                "total": 0, "latency_sum": 0, "latency_n": 0,
            })
            s["total"] += 1
            s[entry.get("status", "error")] = s.get(entry.get("status", "error"), 0) + 1
            lat = entry.get("latency_ms") or 0
            if lat:
                s["latency_sum"] += lat
                s["latency_n"] += 1
    for s in stats.values():
        answered = s["ok"] + s["not_found"]
        s["success_rate"] = round(100 * s["ok"] / s["total"]) if s["total"] else 0
        s["answer_rate"] = round(100 * answered / s["total"]) if s["total"] else 0
        s["avg_latency_ms"] = round(s["latency_sum"] / s["latency_n"]) if s["latency_n"] else 0
    return stats


# ---------------------------------------------------------------------------
# Monitors — saved searches re-run on a schedule, alerting on change
# ---------------------------------------------------------------------------
def add_monitor(engine, label, query, notify_email):
    q = {k: v for k, v in query.items() if (v or "").strip()}
    with engine.begin() as conn:
        conn.execute(monitors_t.insert().values(
            created_at=datetime.datetime.now(datetime.timezone.utc),
            label=label, query=json.dumps(q), notify_email=notify_email or "",
            active=True, last_run=None, last_hash="", last_summary="",
        ))


def list_monitors(engine):
    with engine.connect() as conn:
        return conn.execute(select(monitors_t).order_by(monitors_t.c.id.desc())).mappings().all()


def delete_monitor(engine, monitor_id):
    with engine.begin() as conn:
        conn.execute(monitors_t.delete().where(monitors_t.c.id == monitor_id))


def set_monitor_active(engine, monitor_id, active):
    with engine.begin() as conn:
        conn.execute(monitors_t.update().where(monitors_t.c.id == monitor_id).values(active=active))


def run_monitor(engine, monitor, cfg):
    """Re-run one monitor's search (fresh), detect change vs. last fingerprint,
    email on change, and persist the new state. Returns (changed, results)."""
    query = json.loads(monitor["query"] or "{}")
    results = osint_engine.run_search(query, cfg, use_cache=False)
    fp = osint_engine.fingerprint(results)
    changed = bool(monitor["last_hash"]) and fp != monitor["last_hash"]
    now = datetime.datetime.now(datetime.timezone.utc)
    summary = [{"source": r.source, "status": r.status, "items": len(r.items)} for r in results]
    with engine.begin() as conn:
        conn.execute(monitors_t.update().where(monitors_t.c.id == monitor["id"]).values(
            last_run=now, last_hash=fp, last_summary=json.dumps(summary),
        ))
    if changed and monitor["notify_email"]:
        q = ", ".join(f"{k}={v}" for k, v in query.items())
        send_email(monitor["notify_email"],
                   f"[H&H Monitor] Change detected — {monitor['label']}",
                   f"The monitored search '{monitor['label']}' ({q}) changed.\n\n"
                   + build_report_md(query, results))
    return changed, results


# ---------------------------------------------------------------------------
# Reviews — real, opt-in customer testimonials (admin-moderated)
# ---------------------------------------------------------------------------
def get_user_review(engine, user_id):
    with engine.connect() as conn:
        return conn.execute(
            select(reviews_t).where(reviews_t.c.user_id == user_id)
        ).mappings().first()


def upsert_review(engine, user_id, display_name, role, rating, body):
    """One review per user. Submitting or editing always sets approved=False so
    every change is re-moderated before it can appear publicly."""
    now = datetime.datetime.now(datetime.timezone.utc)
    existing = get_user_review(engine, user_id)
    with engine.begin() as conn:
        if existing:
            conn.execute(reviews_t.update().where(reviews_t.c.id == existing["id"]).values(
                display_name=display_name, role=role, rating=rating, body=body,
                approved=False, updated_at=now,
            ))
        else:
            conn.execute(reviews_t.insert().values(
                user_id=user_id, display_name=display_name, role=role, rating=rating,
                body=body, approved=False, featured=False, created_at=now, updated_at=now,
            ))


def list_reviews(engine):
    """All reviews, pending first then newest — for the admin moderation queue."""
    with engine.connect() as conn:
        return conn.execute(
            select(reviews_t).order_by(reviews_t.c.approved.asc(), reviews_t.c.id.desc())
        ).mappings().all()


def public_reviews(engine, limit=6):
    """Approved reviews only, featured first. Returns [] when none are approved —
    callers MUST render nothing in that case (no placeholder, no fabrication)."""
    with engine.connect() as conn:
        return conn.execute(
            select(reviews_t).where(reviews_t.c.approved.is_(True))
            .order_by(reviews_t.c.featured.desc(), reviews_t.c.id.desc()).limit(limit)
        ).mappings().all()


def review_summary(engine):
    """Aggregate of approved reviews for the social-proof bar. Returns
    {"count", "avg", "stars"} or None when none are approved — so any caller
    inherits the same hidden-until-real guarantee as public_reviews."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(reviews_t.c.rating).where(reviews_t.c.approved.is_(True))
        ).all()
    if not rows:
        return None
    ratings = [int(r[0] or 0) for r in rows]
    avg = sum(ratings) / len(ratings)
    return {"count": len(ratings), "avg": round(avg, 1), "stars": "★" * int(round(avg))}


def set_review_approved(engine, review_id, approved):
    with engine.begin() as conn:
        conn.execute(reviews_t.update().where(reviews_t.c.id == review_id).values(approved=approved))


def set_review_featured(engine, review_id, featured):
    with engine.begin() as conn:
        conn.execute(reviews_t.update().where(reviews_t.c.id == review_id).values(featured=featured))


def delete_review(engine, review_id):
    with engine.begin() as conn:
        conn.execute(reviews_t.delete().where(reviews_t.c.id == review_id))


# ---------------------------------------------------------------------------
# Email (no-op if SMTP is not configured)
# ---------------------------------------------------------------------------
def send_email(to_addr, subject, body):
    host = get_config("SMTP_HOST")
    if not host or not to_addr:
        return False
    port = int(get_config("SMTP_PORT", "587"))
    user = get_config("SMTP_USERNAME")
    password = get_config("SMTP_PASSWORD")
    sender = get_config("SMTP_FROM", user or "no-reply@hhinvestigations.com")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return True
    except Exception:
        return False


def notify_new_request(ref, token, data):
    client_msg = (
        f"Thank you for contacting H & H Investigation.\n\n"
        f"Your request reference: {ref}\n"
        f"Your access code: {token}\n\n"
        f"Keep these to check your request status at "
        f"https://intake.hhinvestigations.com (My Requests).\n\n"
        f"Service tier: {data['service_tier']}\n\n"
        f"We will follow up with an engagement letter. Work begins once it is signed.\n\n"
        f"— H & H Investigation"
    )
    client_sent = send_email(data["client_email"], f"H&H Investigation — Request {ref}", client_msg)

    admin_to = get_config("NOTIFY_EMAIL")
    if admin_to:
        admin_msg = (
            f"New intake request {ref}\n\n"
            f"Client: {data['client_name']} <{data['client_email']}> {data.get('client_firm','')}\n"
            f"Tier: {data['service_tier']}  Rush: {data.get('rush')}\n"
            f"Subject: {data['subject_name']}\n"
            f"Anchors: phone={data.get('anchor_phone','')} email={data.get('anchor_email','')} "
            f"addr={data.get('anchor_address','')} dob={data.get('anchor_dob','')} "
            f"employer={data.get('anchor_employer','')} other={data.get('anchor_other','')}\n"
            f"Notes: {data.get('notes','')}\n"
        )
        send_email(admin_to, f"[Intake] {ref} — {data['subject_name']}", admin_msg)

    return client_sent


def notify_subscription_active(user, plan):
    """One-time welcome + honest review invite, sent right after a confirmed
    upgrade. No-op if SMTP is unconfigured (send_email returns False)."""
    base = app_base_url()
    body = (
        f"You're on H&H {plan} — thank you.\n\n"
        f"Your account now unlocks the {plan} tier of search depth. Sign in and run "
        f"a search any time at {base}/.\n\n"
        f"If the tool earns it, we'd value an honest review. From your Account page you "
        f"can leave one in a minute. It only appears publicly after we review it, and "
        f"you can edit or remove it whenever you like.\n\n"
        f"Questions or feedback? Just reply to this email.\n\n"
        f"— H&H Investigation"
    )
    return send_email(user.get("email"), f"Welcome to H&H {plan}", body)


# ---------------------------------------------------------------------------
# Accounts + auth (email + password; PBKDF2 hashing, no extra deps)
# ---------------------------------------------------------------------------
def _hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return salt, dk.hex()


def create_user(engine, email, password):
    """Create a free-plan account. Returns (user_row, error_str)."""
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        return None, "Enter a valid email address."
    if len(password) < 8:
        return None, "Password must be at least 8 characters."
    salt, pw_hash = _hash_password(password)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        with engine.begin() as conn:
            conn.execute(users_t.insert().values(
                email=email, pw_salt=salt, pw_hash=pw_hash, created_at=now,
                plan="Recon", plan_status="free",
            ))
    except Exception:  # unique-constraint or DB error
        return None, "An account with that email already exists."
    return get_user_by_email(engine, email), None


def get_user_by_email(engine, email):
    with engine.connect() as conn:
        return conn.execute(
            select(users_t).where(users_t.c.email == email.strip().lower())
        ).mappings().first()


def get_user_by_id(engine, user_id):
    with engine.connect() as conn:
        return conn.execute(
            select(users_t).where(users_t.c.id == user_id)
        ).mappings().first()


def verify_login(engine, email, password):
    row = get_user_by_email(engine, email)
    if not row:
        return None
    _, attempt = _hash_password(password, row["pw_salt"])
    if secrets.compare_digest(attempt, row["pw_hash"] or ""):
        return row
    return None


def set_user_subscription(engine, user_id, customer_id, sub_id, plan, status, period_end):
    with engine.begin() as conn:
        conn.execute(users_t.update().where(users_t.c.id == user_id).values(
            stripe_customer_id=customer_id, stripe_subscription_id=sub_id,
            plan=plan, plan_status=status, current_period_end=period_end,
        ))


def downgrade_user(engine, user_id):
    with engine.begin() as conn:
        conn.execute(users_t.update().where(users_t.c.id == user_id).values(
            plan="Recon", plan_status="canceled",
        ))


# ---------------------------------------------------------------------------
# Password reset (single-use, time-limited tokens; needs SMTP to deliver)
# ---------------------------------------------------------------------------
RESET_TTL_MIN = 60


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _as_utc(dt):
    """SQLite hands back naive datetimes; treat them as UTC for comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def create_password_reset(engine, email):
    """Issue a single-use reset token for the user, invalidating any prior
    outstanding tokens. Returns the raw token, or None if no such user. The
    caller MUST NOT reveal which case occurred (avoids account enumeration)."""
    user = get_user_by_email(engine, email)
    if not user:
        return None
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as conn:
        conn.execute(password_resets_t.update().where(
            password_resets_t.c.user_id == user["id"],
            password_resets_t.c.used == False,  # noqa: E712
        ).values(used=True))
        conn.execute(password_resets_t.insert().values(
            user_id=user["id"], token_hash=_token_hash(token), created_at=now,
            expires_at=now + datetime.timedelta(minutes=RESET_TTL_MIN), used=False,
        ))
    return token


def consume_password_reset(engine, token, new_password):
    """Validate a reset token and set the new password. Returns (ok, error)."""
    if len(new_password) < 8:
        return False, "Password must be at least 8 characters."
    now = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as conn:
        row = conn.execute(select(password_resets_t).where(
            password_resets_t.c.token_hash == _token_hash(token)
        )).mappings().first()
        if not row or row["used"]:
            return False, "This reset link is invalid or has already been used."
        if _as_utc(row["expires_at"]) and now > _as_utc(row["expires_at"]):
            return False, "This reset link has expired. Request a new one."
        salt, pw_hash = _hash_password(new_password)
        conn.execute(users_t.update().where(users_t.c.id == row["user_id"]).values(
            pw_salt=salt, pw_hash=pw_hash))
        conn.execute(password_resets_t.update().where(
            password_resets_t.c.id == row["id"]).values(used=True))
    return True, None


def request_password_reset(engine, email):
    """Create a reset token and email the link. Returns True only if an email
    was actually sent; the UI shows the same neutral message regardless."""
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return False
    token = create_password_reset(engine, email)
    if not token:
        return False
    link = app_base_url() + "/?reset=" + token
    body = (
        "We received a request to reset your H&H Investigation password.\n\n"
        f"Reset it here (this link expires in {RESET_TTL_MIN} minutes):\n{link}\n\n"
        "If you didn't request this, ignore this email — your password will not "
        "change.\n\n— H&H Investigation"
    )
    return send_email(email, "H&H Investigation — password reset", body)


# ---------------------------------------------------------------------------
# Stripe (raw REST via requests; dormant unless STRIPE_SECRET_KEY is set)
# ---------------------------------------------------------------------------
STRIPE_API = "https://api.stripe.com/v1"


def stripe_enabled():
    return bool(get_config("STRIPE_SECRET_KEY"))


def _stripe_post(path, data):
    r = requests.post(f"{STRIPE_API}{path}", data=data,
                      auth=(get_config("STRIPE_SECRET_KEY"), ""), timeout=20)
    r.raise_for_status()
    return r.json()


def _stripe_get(path):
    r = requests.get(f"{STRIPE_API}{path}",
                     auth=(get_config("STRIPE_SECRET_KEY"), ""), timeout=20)
    r.raise_for_status()
    return r.json()


def plan_price_id(plan):
    return get_config(f"STRIPE_PRICE_{plan.upper()}")


def price_to_plan(price_id):
    for plan in ("Pro", "Deep"):
        if price_id and plan_price_id(plan) == price_id:
            return plan
    return None


def app_base_url():
    return (get_config("APP_BASE_URL", "http://localhost:8501") or "").rstrip("/")


def create_checkout_url(user, plan):
    """Create a Stripe Checkout subscription session; return its URL."""
    price = plan_price_id(plan)
    if not price:
        raise RuntimeError(f"No Stripe price configured for {plan} (set STRIPE_PRICE_{plan.upper()}).")
    base = app_base_url()
    data = {
        "mode": "subscription",
        "line_items[0][price]": price,
        "line_items[0][quantity]": 1,
        "client_reference_id": str(user["id"]),
        "metadata[plan]": plan,
        "subscription_data[metadata][plan]": plan,
        "success_url": base + "/?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": base + "/?checkout=cancel",
    }
    if user.get("stripe_customer_id"):
        data["customer"] = user["stripe_customer_id"]
    else:
        data["customer_email"] = user["email"]
    return _stripe_post("/checkout/sessions", data)["url"]


def create_billing_portal_url(customer_id):
    return _stripe_post("/billing_portal/sessions",
                        {"customer": customer_id, "return_url": app_base_url() + "/"})["url"]


def _ts_to_dt(ts):
    try:
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def confirm_checkout(engine, session_id):
    """Verify a returned Checkout session with Stripe and, if paid, attach the
    subscription to the user named by client_reference_id. Returns the user id
    that was updated, or None."""
    sess = _stripe_get(f"/checkout/sessions/{session_id}")
    if sess.get("payment_status") != "paid" and sess.get("status") != "complete":
        return None
    user_id = sess.get("client_reference_id")
    sub_id = sess.get("subscription")
    cust_id = sess.get("customer")
    plan = (sess.get("metadata") or {}).get("plan") or "Pro"
    if not user_id:
        return None
    period_end = None
    if sub_id:
        sub = _stripe_get(f"/subscriptions/{sub_id}")
        period_end = _ts_to_dt(sub.get("current_period_end"))
        mapped = price_to_plan((sub.get("items", {}).get("data", [{}])[0].get("price") or {}).get("id"))
        plan = mapped or plan
    set_user_subscription(engine, int(user_id), cust_id, sub_id, plan, "active", period_end)
    return int(user_id)


def refresh_subscription(engine, user):
    """Poll Stripe for the user's current subscription state and sync the plan.
    No-op if Stripe is off or the user has no subscription."""
    if not stripe_enabled() or not user or not user.get("stripe_subscription_id"):
        return user
    try:
        sub = _stripe_get(f"/subscriptions/{user['stripe_subscription_id']}")
    except Exception:
        return user
    status = sub.get("status")
    if status in ("active", "trialing"):
        price_id = (sub.get("items", {}).get("data", [{}])[0].get("price") or {}).get("id")
        plan = price_to_plan(price_id) or user["plan"]
        set_user_subscription(engine, user["id"], user.get("stripe_customer_id"),
                              user["stripe_subscription_id"], plan, status,
                              _ts_to_dt(sub.get("current_period_end")))
    else:
        downgrade_user(engine, user["id"])
    return get_user_by_id(engine, user["id"])


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400;1,600&family=IBM+Plex+Mono:wght@400;500&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&display=swap');

    :root {
        --gold: #c9a444; --gold-hi: #e8c060; --gold-dim: #7a5f1a;
        --bg: #07090d; --bg-2: #0d1117; --bg-3: #13181f;
        --text: #eaeef4; --text-2: #c2cdd9; --text-dim: #5a6878;
        --border: #1e2630; --border-2: #2a3444; --green: #2ea043;
        --mono: 'IBM Plex Mono', 'Courier New', monospace;
        --display: 'Cormorant Garamond', 'Georgia', serif;
        --body: 'Libre Baskerville', 'Georgia', serif;
    }
    .stApp { background-color: var(--bg); color: var(--text); font-family: var(--body); }
    [data-testid="stSidebar"] { background-color: var(--bg-2); border-right: 1px solid var(--border); }
    [data-testid="stSidebar"] * { color: var(--text-2) !important; }

    .brand-bar { display: flex; align-items: center; gap: 12px; padding: 18px 0;
        border-bottom: 1px solid var(--border); margin-bottom: 32px; }
    .brand-mark { width: 24px; height: 24px; border: 1px solid var(--gold-dim);
        display: flex; align-items: center; justify-content: center; font-size: 10px; color: var(--gold-dim); }
    .brand-name { font-family: var(--display); font-size: 20px; font-weight: 700; letter-spacing: 4px; color: var(--gold); }

    .section-title { font-family: var(--display); font-size: 36px; font-weight: 700; color: var(--text); line-height: 1.15; margin-bottom: 8px; }
    .section-title em { font-style: italic; color: var(--gold); }
    .section-label { font-family: var(--mono); font-size: 10px; letter-spacing: 4px; color: var(--gold-dim); text-transform: uppercase; margin-bottom: 12px; }

    .metric-row { display: flex; gap: 1px; background: var(--border); border: 1px solid var(--border); margin: 32px 0; }
    .metric-card { flex: 1; background: var(--bg-2); padding: 24px 28px; }
    .metric-num { font-family: var(--display); font-size: 36px; font-weight: 700; color: var(--gold); line-height: 1; margin-bottom: 4px; }
    .metric-label { font-family: var(--mono); font-size: 10px; letter-spacing: 2px; color: var(--text-dim); text-transform: uppercase; }

    .tier-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1px; background: var(--border); border: 1px solid var(--border); margin-top: 24px; }
    .tier-card { background: var(--bg-2); padding: 28px 24px; transition: background 0.15s; }
    .tier-card:hover { background: var(--bg-3); }
    .tier-card.featured { border-left: 2px solid var(--gold); }
    .tier-name { font-family: var(--display); font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
    .tier-tag { font-family: var(--mono); font-size: 9px; letter-spacing: 1.5px; color: var(--text-dim); text-transform: uppercase; margin-bottom: 12px; }
    .tier-price { font-family: var(--display); font-size: 28px; font-weight: 700; color: var(--gold); margin-bottom: 8px; }
    .tier-scope { font-size: 14px; color: var(--text-2); font-style: italic; line-height: 1.6; }
    .tier-turn { font-family: var(--mono); font-size: 11px; color: var(--text-dim); margin-top: 10px; }
    .tier-badge { display: inline-block; font-family: var(--mono); font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--bg); background: var(--gold); padding: 2px 9px; border-radius: 2px; margin-bottom: 12px; font-weight: 500; }
    .tier-benefit { font-family: var(--body); font-size: 13px; color: var(--text); line-height: 1.55; margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }

    .upgrade-card { background: var(--bg-2); border: 1px solid var(--border-2); border-left: 3px solid var(--gold); padding: 18px 22px; margin: 22px 0 12px; }
    .uc-label { font-family: var(--mono); font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: var(--gold-dim); margin-bottom: 7px; }
    .uc-title { font-family: var(--display); font-size: 19px; font-weight: 700; color: var(--text); line-height: 1.3; margin-bottom: 6px; }
    .uc-meta { font-family: var(--mono); font-size: 11px; color: var(--text-dim); letter-spacing: 0.5px; }
    .rv-stars { color: var(--gold); font-size: 14px; letter-spacing: 2px; margin-bottom: 12px; }
    .rv-body { font-family: var(--body); font-size: 14px; color: var(--text-2); line-height: 1.7; font-style: italic; margin-bottom: 14px; }
    .rv-who { font-family: var(--display); font-size: 16px; font-weight: 700; color: var(--text); }
    .rv-role { font-family: var(--mono); font-size: 10px; letter-spacing: 1px; color: var(--text-dim); text-transform: uppercase; margin-top: 3px; }
    .rv-summary { display: flex; align-items: baseline; gap: 12px; margin-top: 20px; padding: 14px 18px; background: var(--bg-2); border: 1px solid var(--border); border-left: 2px solid var(--gold); }
    .rv-summary-stars { color: var(--gold); font-size: 16px; letter-spacing: 2px; }
    .rv-summary-avg { font-family: var(--display); font-size: 22px; font-weight: 700; color: var(--gold); line-height: 1; }
    .rv-summary-meta { font-family: var(--mono); font-size: 10px; letter-spacing: 2px; color: var(--text-dim); text-transform: uppercase; }

    .status-badge { display: inline-block; padding: 3px 10px; border-radius: 3px; font-family: var(--mono); font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: #fff; }

    .confirmation-card { background: var(--bg-2); border: 1px solid var(--gold-dim); border-left: 3px solid var(--gold); padding: 28px; margin: 24px 0; }
    .ref-number { font-family: var(--mono); font-size: 24px; color: var(--gold); letter-spacing: 3px; margin-bottom: 6px; }
    .access-code { font-family: var(--mono); font-size: 14px; color: var(--text-2); letter-spacing: 2px; margin-bottom: 12px; }

    .request-card { background: var(--bg-2); border: 1px solid var(--border-2); padding: 20px 24px; margin-bottom: 8px; }
    .request-card .rc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .rc-ref { font-family: var(--mono); font-size: 14px; color: var(--gold); letter-spacing: 2px; }
    .rc-meta { font-family: var(--mono); font-size: 11px; color: var(--text-dim); line-height: 1.6; }

    .stTextInput > div > div > input, .stTextArea > div > div > textarea, .stSelectbox > div > div {
        background-color: var(--bg-2) !important; color: var(--text) !important;
        border-color: var(--border) !important; font-family: var(--mono) !important; }

    .site-footer { border-top: 1px solid var(--border); padding: 28px 0; margin-top: 60px;
        display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }
    .footer-brand { font-family: var(--display); font-size: 15px; letter-spacing: 3px; color: var(--gold-dim); font-weight: 700; }
    .footer-legal { font-family: var(--mono); font-size: 10px; letter-spacing: 1px; color: var(--text-dim); text-align: right; line-height: 1.9; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------
def render_brand_bar():
    st.markdown(
        '<div class="brand-bar"><div class="brand-mark">◆</div>'
        '<div class="brand-name">H &amp; H INVESTIGATION</div></div>',
        unsafe_allow_html=True,
    )


def render_footer():
    st.markdown(
        """
        <div class="site-footer">
            <div class="footer-brand">H &amp; H Investigation</div>
            <div class="footer-legal">
                joshua@hhinvestigations.com<br>
                All findings derived from lawful open-source intelligence and public records.<br>
                Subjects of investigations remain confidential.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(status):
    color = STATUS_COLORS.get(status, "#5a6878")
    return f'<span class="status-badge" style="background:{color};">{esc(status)}</span>'


def mask_name(name):
    parts = (name or "").strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return name or ""


# ---------------------------------------------------------------------------
# Pre-entry consent gate (CA-resident block + acceptable-use attestations)
# ---------------------------------------------------------------------------
def require_consent():
    """Gate the self-service tools. Returns True only after the user has, this
    session, selected an eligible state of residence and accepted every
    acceptable-use attestation. Otherwise renders the gate and returns False."""
    if st.session_state.get("consent_ok"):
        return True

    st.markdown('<div class="section-label">Before you begin</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Terms of <em>Use</em></div>', unsafe_allow_html=True)
    st.markdown(
        '<p style="max-width:680px;font-size:14px;color:#c2cdd9;line-height:1.8;">'
        'H&amp;H provides <strong style="color:#eaeef4;">self-service</strong> access to '
        'public-record and open-source search tools. <strong style="color:#eaeef4;">You</strong> '
        'run the searches and are solely responsible for how you use the results. '
        'H&amp;H is not a consumer reporting agency and does not run investigations on your behalf.</p>',
        unsafe_allow_html=True,
    )

    state = st.selectbox("Your state of residence", ["— Select —"] + US_STATES,
                         key="consent_state_sel")

    if state in RESTRICTED_STATES or state == "Outside the United States":
        where = "your location" if state == "Outside the United States" else state
        st.error(
            f"This self-service tool is not available to residents of {where}. "
            "Access is blocked based on the location you selected."
        )
        st.caption("If you believe this is in error, contact joshua@hhinvestigations.com.")
        return False

    st.markdown("**You must confirm all of the following to proceed:**")
    c_age = st.checkbox("I am at least 18 years old.", key="consent_age")
    c_lawful = st.checkbox(
        "I have a lawful, legitimate purpose for every search I run, and I am "
        "authorized to seek this information.", key="consent_lawful")
    c_fcra = st.checkbox(
        "I understand the results are NOT a consumer report, and I will not use "
        "them for employment, credit, insurance, housing/tenant screening, or "
        "any other FCRA-covered eligibility decision.", key="consent_fcra")
    c_noharm = st.checkbox(
        "I will not use this tool to stalk, harass, intimidate, or harm any "
        "person, or for any purpose prohibited by law.", key="consent_noharm")
    c_terms = st.checkbox(
        'I have read and agree to the Terms of Use & Acceptable Use Policy '
        '(see "Terms" in the sidebar).', key="consent_terms")

    if st.button("Enter the tool", type="primary", key="consent_enter"):
        if state == "— Select —":
            st.error("Please select your state of residence.")
        elif not all([c_age, c_lawful, c_fcra, c_noharm, c_terms]):
            st.error("You must check every box above to use the tool.")
        else:
            st.session_state.consent_ok = True
            st.session_state.consent_state = state
            st.rerun()

    with st.expander("Acceptable Use — summary"):
        st.markdown(ACCEPTABLE_USE_SUMMARY)

    return False


# ---------------------------------------------------------------------------
# Login gate (email + password). Returns the user row or None.
# ---------------------------------------------------------------------------
def require_login(engine):
    user = st.session_state.get("user")
    if user:
        return user

    st.markdown('<div class="section-label">Account required</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Sign <em>In</em></div>', unsafe_allow_html=True)
    st.caption("Free Recon-tier account. Upgrade anytime for deeper searches.")
    tab_login, tab_signup = st.tabs(["Log in", "Create account"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            pw = st.text_input("Password", type="password", key="login_pw")
            if st.form_submit_button("Log in", type="primary"):
                row = verify_login(engine, email, pw)
                if row:
                    st.session_state.user = dict(row)
                    st.rerun()
                else:
                    st.error("Invalid email or password.")

        with st.expander("Forgot your password?"):
            if not get_config("SMTP_HOST"):
                st.caption("Password reset by email isn't enabled yet. Email "
                           "joshua@hhinvestigations.com to reset your password.")
            else:
                with st.form("reset_request_form"):
                    r_email = st.text_input("Account email", key="reset_req_email")
                    if st.form_submit_button("Email me a reset link"):
                        request_password_reset(engine, r_email)
                        st.success("If an account exists for that email, a reset "
                                   "link is on its way. Check your inbox and spam.")

    with tab_signup:
        with st.form("signup_form"):
            email2 = st.text_input("Email", key="signup_email")
            pw2 = st.text_input("Password (8+ characters)", type="password", key="signup_pw")
            if st.form_submit_button("Create free account", type="primary"):
                row, err = create_user(engine, email2, pw2)
                if err:
                    st.error(err)
                else:
                    st.session_state.user = dict(row)
                    st.rerun()
    return None


def handle_stripe_return(engine):
    """Process a Stripe Checkout redirect (?session_id=...) exactly once."""
    sid = st.query_params.get("session_id")
    if not sid or st.session_state.get("_checkout_done"):
        return
    st.session_state["_checkout_done"] = True
    msg = "Checkout could not be confirmed. If you were charged, contact support."
    if stripe_enabled():
        try:
            uid = confirm_checkout(engine, sid)
            if uid:
                row = get_user_by_id(engine, uid)
                if row:
                    urow = dict(row)
                    st.session_state.user = urow
                    notify_subscription_active(urow, urow.get("plan", "Pro"))
                msg = "Subscription active — your plan has been updated."
        except Exception:
            pass
    st.session_state["_checkout_msg"] = msg
    st.session_state.nav = "Account"
    st.query_params.clear()


def page_reset_password(engine, token):
    """Set-a-new-password screen reached via an emailed ?reset=<token> link."""
    st.markdown('<div class="section-label">Account</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Reset <em>Password</em></div>', unsafe_allow_html=True)

    if st.session_state.get("_reset_done"):
        st.success("Your password has been reset. You can now log in.")
        if st.button("Go to login", type="primary"):
            st.session_state.pop("_reset_done", None)
            st.session_state.nav = "Account"
            st.query_params.clear()
            st.rerun()
        return

    with st.form("reset_set_form"):
        pw1 = st.text_input("New password (8+ characters)", type="password")
        pw2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Set new password", type="primary"):
            if pw1 != pw2:
                st.error("Passwords don't match.")
            else:
                ok, err = consume_password_reset(engine, token, pw1)
                if ok:
                    st.session_state["_reset_done"] = True
                    st.rerun()
                else:
                    st.error(err)


# ---------------------------------------------------------------------------
# Page: Terms of Use
# ---------------------------------------------------------------------------
def page_terms():
    render_brand_bar()
    st.markdown(TERMS_MD)
    render_footer()


# ---------------------------------------------------------------------------
# Page: Home
# ---------------------------------------------------------------------------
def page_home():
    render_brand_bar()
    n_sources = len(osint_engine.SOURCES)
    st.markdown('<div class="section-label">Self-service · Open-source intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Run Your Own <em>Intelligence</em> Search</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <p style="max-width:640px; font-size:15px; color:#c2cdd9; line-height:1.8; margin-bottom:8px;">
        Enter a name, email, username, phone, or domain. The tool fans out across dozens of
        public-record and open-source signals in parallel and hands you a cross-referenced
        report in <strong style="color:#eaeef4;">seconds</strong> — you run the search, the
        results are yours. This is a self-service research tool, not a background-check service.
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="metric-row">
            <div class="metric-card"><div class="metric-num">{n_sources}</div><div class="metric-label">Live data sources</div></div>
            <div class="metric-card"><div class="metric-num">Seconds</div><div class="metric-label">Parallel lookups</div></div>
            <div class="metric-card"><div class="metric-num">100%</div><div class="metric-label">Open-source · lawful</div></div>
            <div class="metric-card"><div class="metric-num">You</div><div class="metric-label">Run the search</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-label">Plans</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">The Deeper You Go, <em>The More You See</em></div>', unsafe_allow_html=True)
    html_out = '<div class="tier-grid">'
    for name, tag, price, benefit, features, featured, badge in PLANS:
        cls = "tier-card featured" if featured else "tier-card"
        badge_html = f'<div class="tier-badge">{esc(badge)}</div>' if badge else ''
        feats = "".join(f'<div class="tier-scope">• {esc(f)}</div>' for f in features)
        html_out += (
            f'<div class="{cls}">{badge_html}<div class="tier-name">{esc(name)}</div>'
            f'<div class="tier-tag">{esc(tag)}</div><div class="tier-price">{esc(price)}</div>'
            f'<div class="tier-benefit">{esc(benefit)}</div>'
            f'{feats}</div>'
        )
    html_out += "</div>"
    st.markdown(html_out, unsafe_allow_html=True)
    st.caption("Card checkout is being finalized — pricing shown is current. Cancel anytime. "
               "Results are not a consumer report and may not be used for FCRA-covered decisions.")

    render_testimonials(engine)

    st.markdown("")
    if st.button("Start Searching", type="primary"):
        st.session_state.nav = "Search"
        st.rerun()
    render_footer()


# ---------------------------------------------------------------------------
# Page: New Request
# ---------------------------------------------------------------------------
def page_new_request(engine):
    render_brand_bar()
    if not require_consent():
        render_footer()
        return
    st.markdown('<div class="section-label">Client Intake</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Request <em>a Dossier</em></div>', unsafe_allow_html=True)

    if st.session_state.get("last_ref"):
        info = st.session_state.last_ref
        followup = (
            "A confirmation email is on its way."
            if info.get("email_sent")
            else "Save the reference and access code below — keep them to track your request."
        )
        st.markdown(
            f"""
            <div class="confirmation-card">
                <div class="ref-number">{esc(info['ref'])}</div>
                <div class="access-code">Access code: {esc(info['token'])}</div>
                <p style="color:#c2cdd9; font-size:14px; line-height:1.7; margin:0;">
                    Your request has been received. {esc(followup)}
                    We will send an engagement letter; work begins once it is signed.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.info("Save your reference number and access code. You'll need both to view status under 'My Requests'.")
        if st.button("Submit Another Request"):
            del st.session_state.last_ref
            st.rerun()
        render_footer()
        return

    with st.form("intake_form"):
        st.markdown("**Your Information**")
        c1, c2 = st.columns(2)
        with c1:
            client_name = st.text_input("Full name *")
            client_email = st.text_input("Email *")
            client_firm = st.text_input("Firm / company")
        with c2:
            tier = st.selectbox("Service tier *", TIERS)
            rush = st.checkbox("Rush delivery (+$200 / +$500)")

        st.divider()
        st.markdown("**Subject Information**")
        subject_name = st.text_input("Subject full name *")
        st.markdown("Provide at least one anchor data point:")
        a1, a2, a3 = st.columns(3)
        with a1:
            anchor_phone = st.text_input("Phone")
            anchor_dob = st.text_input("Date of birth")
        with a2:
            anchor_email = st.text_input("Email address")
            anchor_employer = st.text_input("Employer")
        with a3:
            anchor_address = st.text_input("Address")
            anchor_other = st.text_area("Other anchors", height=80)

        st.divider()
        notes = st.text_area("Additional notes", height=80)
        agree = st.checkbox(
            "I confirm I have a lawful, legitimate purpose for this request and am authorized to make it."
        )
        submitted = st.form_submit_button("Submit Request", type="primary")

    if submitted:
        errors = []
        if not client_name.strip():
            errors.append("Your full name is required.")
        if not client_email.strip():
            errors.append("Your email is required.")
        elif not EMAIL_RE.match(client_email.strip()):
            errors.append("Please enter a valid email address.")
        if not subject_name.strip():
            errors.append("Subject full name is required.")
        anchors = [anchor_phone, anchor_email, anchor_address, anchor_dob, anchor_employer, anchor_other]
        if not any(a.strip() for a in anchors):
            errors.append("At least one anchor data point is required.")
        if not agree:
            errors.append("You must confirm a lawful, legitimate purpose to proceed.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            data = {
                "client_name": client_name.strip(),
                "client_email": client_email.strip(),
                "client_firm": client_firm.strip(),
                "service_tier": tier,
                "rush": rush,
                "subject_name": subject_name.strip(),
                "anchor_phone": anchor_phone.strip(),
                "anchor_email": anchor_email.strip(),
                "anchor_address": anchor_address.strip(),
                "anchor_dob": anchor_dob.strip(),
                "anchor_employer": anchor_employer.strip(),
                "anchor_other": anchor_other.strip(),
                "notes": notes.strip(),
            }
            ref, token = insert_request(engine, data)
            email_sent = notify_new_request(ref, token, data)
            st.session_state.last_ref = {"ref": ref, "token": token, "email_sent": email_sent}
            st.rerun()

    render_footer()


# ---------------------------------------------------------------------------
# Page: My Requests (ref + access code, no email enumeration)
# ---------------------------------------------------------------------------
def page_my_requests(engine):
    render_brand_bar()
    st.markdown('<div class="section-label">Track</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">My <em>Request</em></div>', unsafe_allow_html=True)
    st.caption("Enter the reference number and access code you received when you submitted.")

    c1, c2 = st.columns(2)
    with c1:
        ref = st.text_input("Reference number", placeholder="HHI-2026-0001")
    with c2:
        token = st.text_input("Access code")

    if not ref.strip() or not token.strip():
        st.info("Enter both your reference number and access code to view your request.")
        render_footer()
        return

    row = get_request_by_token(engine, ref.strip(), token.strip())
    if not row:
        st.warning("No request found for that reference number and access code.")
        render_footer()
        return

    badge = status_badge(row["status"])
    created = str(row["created_at"])[:10]
    updated = str(row["updated_at"])[:10]
    st.markdown(
        f"""
        <div class="request-card">
            <div class="rc-header">
                <span class="rc-ref">{esc(row["ref_number"])}</span>
                {badge}
            </div>
            <div class="rc-meta">
                Tier: {esc(row["service_tier"])}<br>
                Subject: {esc(mask_name(row["subject_name"]))}<br>
                Submitted: {esc(created)} · Updated: {esc(updated)}
                {"  ·  RUSH" if row["rush"] else ""}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_footer()


# ---------------------------------------------------------------------------
# Page: Account (plan + subscription management)
# ---------------------------------------------------------------------------
def page_account(engine):
    render_brand_bar()
    user = require_login(engine)
    if not user:
        render_footer()
        return

    # Sync plan with Stripe (no-op if Stripe off or no subscription).
    fresh = refresh_subscription(engine, user)
    if fresh:
        st.session_state.user = dict(fresh)
        user = st.session_state.user

    _msg = st.session_state.pop("_checkout_msg", None)
    if _msg:
        st.success(_msg)

    st.markdown('<div class="section-label">Account</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Your <em>Plan</em></div>', unsafe_allow_html=True)
    plan = user.get("plan", "Recon")
    status = user.get("plan_status", "free")
    st.markdown(
        f'<div class="request-card"><div class="rc-meta">'
        f'Signed in as <strong style="color:#eaeef4;">{esc(user["email"])}</strong><br>'
        f'Current plan: <strong style="color:#c9a444;">{esc(plan)}</strong> · {esc(status)}<br>'
        f'Search depth unlocked: {esc(", ".join(allowed_depths(plan)))}'
        + (f'<br>Renews / expires: {esc(str(user["current_period_end"])[:10])}'
           if user.get("current_period_end") else "")
        + '</div></div>',
        unsafe_allow_html=True,
    )

    rank = PLAN_RANK.get(plan, 0)
    if rank < 2:
        nxt_name, nxt_adds = {
            0: ("Pro", "court records, company officers, subdomains, and phone & infrastructure intel"),
            1: ("Deep", "breach & dark-web exposure plus scheduled monitoring with change alerts"),
        }[rank]
        st.caption(f"Your plan doesn't yet include {nxt_adds}. {nxt_name} unlocks it.")

    if not stripe_enabled():
        st.info("Paid upgrades aren't live yet — set STRIPE_SECRET_KEY and the "
                "STRIPE_PRICE_PRO / STRIPE_PRICE_DEEP price IDs to enable checkout.")
    else:
        st.markdown("#### Change plan")
        cols = st.columns(2)
        for i, target in enumerate(("Pro", "Deep")):
            with cols[i]:
                if PLAN_RANK[plan] >= PLAN_RANK[target]:
                    st.button(f"{target} — active or included", disabled=True, key=f"up_{target}")
                elif not plan_price_id(target):
                    st.button(f"{target} — price not set", disabled=True, key=f"up_{target}")
                elif st.button(f"Upgrade to {target}", type="primary", key=f"up_{target}"):
                    try:
                        url = create_checkout_url(user, target)
                        st.link_button(f"Continue to secure checkout →", url)
                    except Exception as e:
                        st.error(f"Could not start checkout: {e}")
        if user.get("stripe_customer_id") and st.button("Manage billing / cancel"):
            try:
                st.link_button("Open billing portal →", create_billing_portal_url(user["stripe_customer_id"]))
            except Exception as e:
                st.error(f"Could not open billing portal: {e}")

    st.divider()
    render_review_form(engine, user)

    st.divider()
    if st.button("Log out", key="user_logout"):
        st.session_state.pop("user", None)
        st.rerun()
    render_footer()


# ---------------------------------------------------------------------------
# Page: Admin
# ---------------------------------------------------------------------------
def page_admin(engine):
    render_brand_bar()
    admin_pw = get_config("ADMIN_PASSWORD")

    if not admin_pw:
        st.markdown('<div class="section-label">Admin</div>', unsafe_allow_html=True)
        st.error(
            "Admin access is not configured. Set the ADMIN_PASSWORD environment variable "
            "(or add it to .streamlit/secrets.toml) to enable the dashboard."
        )
        render_footer()
        return

    if not st.session_state.get("admin_auth"):
        st.markdown('<div class="section-label">Restricted</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Admin <em>Access</em></div>', unsafe_allow_html=True)
        pw = st.text_input("Password", type="password")
        if st.button("Log in"):
            if secrets.compare_digest(pw, admin_pw):
                st.session_state.admin_auth = True
                st.rerun()
            else:
                st.error("Invalid password.")
        render_footer()
        return

    st.markdown('<div class="section-label">Admin</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Admin <em>Dashboard</em></div>', unsafe_allow_html=True)
    if st.button("Log out", key="admin_logout"):
        st.session_state.admin_auth = False
        st.rerun()

    tab_req, tab_reviews, tab_monitors, tab_analytics, tab_assistant = st.tabs(
        ["Requests", "Reviews", "Monitors", "Search Analytics", "Assistant"])

    with tab_req:
        counts = status_counts(engine)
        metric_html = '<div class="metric-row">'
        for s in STATUS_ORDER:
            metric_html += f'<div class="metric-card"><div class="metric-num">{counts[s]}</div><div class="metric-label">{esc(s)}</div></div>'
        metric_html += "</div>"
        st.markdown(metric_html, unsafe_allow_html=True)

        status_filter = st.selectbox("Filter by status", ["All"] + STATUS_ORDER, key="admin_status_filter")
        rows = get_all_requests(engine, status=status_filter)
        if not rows:
            st.info("No requests match the current filter.")
        for r in rows:
            with st.expander(f"{r['ref_number']} — {r['subject_name']} ({r['status']})"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Client:** {r['client_name']}")
                    st.markdown(f"**Email:** {r['client_email']}")
                    st.markdown(f"**Firm:** {r['client_firm'] or '—'}")
                    st.markdown(f"**Tier:** {r['service_tier']}")
                    st.markdown(f"**Rush:** {'Yes' if r['rush'] else 'No'}")
                with c2:
                    st.markdown(f"**Subject:** {r['subject_name']}")
                    anchors = []
                    for label, key in [
                        ("Phone", "anchor_phone"), ("Email", "anchor_email"),
                        ("Address", "anchor_address"), ("DOB", "anchor_dob"),
                        ("Employer", "anchor_employer"), ("Other", "anchor_other"),
                    ]:
                        if r[key]:
                            anchors.append(f"{label}: {r[key]}")
                    st.markdown("**Anchors:**  \n" + ("  \n".join(anchors) if anchors else "—"))
                    if r["notes"]:
                        st.markdown(f"**Notes:** {r['notes']}")
                    st.markdown(f"**Created:** {str(r['created_at'])[:19]}")
                    st.markdown(f"**Updated:** {str(r['updated_at'])[:19]}")

                st.divider()
                cur_idx = STATUS_ORDER.index(r["status"]) if r["status"] in STATUS_ORDER else 0
                new_status = st.selectbox("Status", STATUS_ORDER, index=cur_idx, key=f"status_{r['ref_number']}")
                admin_notes = st.text_area("Admin notes", value=r["admin_notes"] or "", key=f"notes_{r['ref_number']}")
                if st.button("Save", key=f"save_{r['ref_number']}"):
                    update_request(engine, r["ref_number"], new_status, admin_notes)
                    st.success(f"Updated {r['ref_number']}.")
                    st.rerun()

    with tab_reviews:
        render_admin_reviews(engine)

    with tab_monitors:
        render_admin_monitors(engine)

    with tab_analytics:
        render_search_analytics(engine)

    with tab_assistant:
        render_admin_assistant(engine)

    render_footer()


# ---------------------------------------------------------------------------
# Admin: monitors (saved searches, re-run on a schedule)
# ---------------------------------------------------------------------------
def render_admin_monitors(engine):
    st.caption("Saved searches re-run on a schedule by monitor.py (cron). "
               "You get an email when the findings change.")
    with st.form("add_monitor_form", clear_on_submit=True):
        label = st.text_input("Monitor label", placeholder="e.g. Watch acme.com")
        c1, c2 = st.columns(2)
        with c1:
            m_name = st.text_input("Full name", key="mon_name")
            m_email = st.text_input("Email", key="mon_email")
            m_username = st.text_input("Username", key="mon_username")
        with c2:
            m_phone = st.text_input("Phone", key="mon_phone")
            m_domain = st.text_input("Domain", key="mon_domain")
        notify = st.text_input("Notify email (on change)")
        if st.form_submit_button("Add monitor", type="primary"):
            query = {"name": m_name, "email": m_email, "username": m_username,
                     "phone": m_phone, "domain": m_domain}
            if not label.strip() or not any((v or "").strip() for v in query.values()):
                st.error("A label and at least one search field are required.")
            else:
                add_monitor(engine, label.strip(), query, notify.strip())
                st.success(f"Monitor '{label.strip()}' added.")
                st.rerun()

    monitors = list_monitors(engine)
    if not monitors:
        st.info("No monitors yet.")
        return
    for m in monitors:
        q = json.loads(m["query"] or "{}")
        qstr = ", ".join(f"{esc(k)}={esc(v)}" for k, v in q.items())
        state = "active" if m["active"] else "paused"
        last = str(m["last_run"])[:19] if m["last_run"] else "never run"
        with st.expander(f"{m['label']} — {state} · last: {last}"):
            st.markdown(f"**Query:** {qstr}")
            st.markdown(f"**Notify:** {esc(m['notify_email'] or '—')}")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Run now", key=f"runmon_{m['id']}"):
                    changed, _ = run_monitor(engine, m, build_osint_cfg())
                    st.success("Change detected — alert sent." if changed
                               else "Ran. No change since last run." if m["last_hash"]
                               else "Baseline captured.")
                    st.rerun()
            with c2:
                if st.button("Pause" if m["active"] else "Resume", key=f"togmon_{m['id']}"):
                    set_monitor_active(engine, m["id"], not m["active"])
                    st.rerun()
            with c3:
                if st.button("Delete", key=f"delmon_{m['id']}"):
                    delete_monitor(engine, m["id"])
                    st.rerun()


# ---------------------------------------------------------------------------
# Reviews UI — capture (Account), public display (Home), moderation (Admin)
# ---------------------------------------------------------------------------
def render_review_form(engine, user):
    """Opt-in review capture for a signed-in customer. Submissions are hidden
    until an admin approves them, and every edit re-enters moderation."""
    existing = get_user_review(engine, user["id"])
    st.markdown("#### Share your experience")
    if existing:
        state = "published" if existing["approved"] else "pending review — not yet public"
        st.caption(f"You have a review on file ({state}). Editing it sends it back for approval.")
    else:
        st.caption("Used H&H for real work? An honest review helps others decide. "
                   "It only appears publicly after we review and approve it.")
    with st.form("review_form"):
        display_name = st.text_input(
            "Name to display", value=(existing["display_name"] if existing else ""),
            max_chars=80, placeholder="e.g. Jordan M. or J. Marsh, Paralegal")
        role = st.text_input(
            "Role / context (optional)", value=(existing["role"] if existing else ""),
            max_chars=120, placeholder="e.g. Investigator · Journalist · Small-business owner")
        rating = st.slider("Rating", 1, 5, value=int(existing["rating"]) if existing else 5)
        body = st.text_area(
            "Your review", value=(existing["body"] if existing else ""),
            max_chars=600, placeholder="What did the tool help you do? Be specific and honest.")
        agree = st.checkbox(
            "I agree H&H may publicly display this review with the name and role I entered, "
            "and confirm it reflects my genuine experience.")
        if st.form_submit_button("Submit review", type="primary"):
            if not display_name.strip() or not body.strip():
                st.error("A display name and a review are required.")
            elif not agree:
                st.error("Please confirm you agree to public display.")
            else:
                upsert_review(engine, user["id"], display_name.strip(), role.strip(),
                              int(rating), body.strip())
                st.success("Thank you — your review was submitted and is pending approval "
                           "before it appears publicly.")
                st.rerun()


def render_testimonials(engine):
    """Render approved customer reviews. If none are approved, render NOTHING —
    the section simply does not exist until real, vetted reviews do."""
    rows = public_reviews(engine, limit=6)
    if not rows:
        return
    st.markdown('<div class="section-label">What customers say</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">In Their <em>Words</em></div>', unsafe_allow_html=True)
    summary = review_summary(engine)
    if summary:
        noun = "review" if summary["count"] == 1 else "reviews"
        st.markdown(
            f'<div class="rv-summary"><span class="rv-summary-stars">{summary["stars"]}</span>'
            f'<span class="rv-summary-avg">{summary["avg"]:.1f}</span>'
            f'<span class="rv-summary-meta">average from {summary["count"]} '
            f'verified customer {noun}</span></div>',
            unsafe_allow_html=True,
        )
    cards = '<div class="tier-grid">'
    for r in rows:
        stars = "★" * int(r["rating"] or 0)
        role = f'<div class="rv-role">{esc(r["role"])}</div>' if r["role"] else ''
        cards += (
            f'<div class="tier-card"><div class="rv-stars">{stars}</div>'
            f'<div class="rv-body">“{esc(r["body"])}”</div>'
            f'<div class="rv-who">{esc(r["display_name"])}</div>{role}</div>'
        )
    cards += "</div>"
    st.markdown(cards, unsafe_allow_html=True)


def render_admin_reviews(engine):
    st.caption("Real, opt-in customer reviews. Nothing appears on the public site "
               "until you approve it here — there are no seeded or fabricated entries.")
    rows = list_reviews(engine)
    if not rows:
        st.info("No reviews submitted yet. They'll appear here for approval once "
                "signed-in customers leave them from their Account page.")
        return
    pending = sum(1 for r in rows if not r["approved"])
    if pending:
        st.markdown(f"**{pending}** awaiting approval.")
    for r in rows:
        n = int(r["rating"] or 0)
        stars = "★" * n + "☆" * (5 - n)
        state = "approved" if r["approved"] else "pending"
        feat = " · featured" if r["featured"] else ""
        with st.expander(f"{stars} — {r['display_name']} ({state}{feat})"):
            if r["role"]:
                st.markdown(f"*{esc(r['role'])}*")
            st.markdown(esc(r["body"]))
            st.caption(f"Submitted {str(r['created_at'])[:19]} · user #{r['user_id']}")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Unapprove" if r["approved"] else "Approve",
                             key=f"aprv_{r['id']}",
                             type="secondary" if r["approved"] else "primary"):
                    set_review_approved(engine, r["id"], not r["approved"])
                    st.rerun()
            with c2:
                if st.button("Unfeature" if r["featured"] else "Feature", key=f"feat_{r['id']}"):
                    set_review_featured(engine, r["id"], not r["featured"])
                    st.rerun()
            with c3:
                if st.button("Delete", key=f"delrev_{r['id']}"):
                    delete_review(engine, r["id"])
                    st.rerun()


# ---------------------------------------------------------------------------
# Admin: search analytics (the "learning" surface)
# ---------------------------------------------------------------------------
def render_search_analytics(engine):
    searches = recent_searches(engine, limit=1000)
    if not searches:
        st.info("No searches logged yet. Run searches and source-performance data will accumulate here.")
        return

    total = len(searches)
    avg_ok = round(sum(s["n_ok"] for s in searches) / total, 1)
    st.markdown(
        f'<div class="metric-row">'
        f'<div class="metric-card"><div class="metric-num">{total}</div><div class="metric-label">Searches logged</div></div>'
        f'<div class="metric-card"><div class="metric-num">{avg_ok}</div><div class="metric-label">Avg sources hit</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("**Source reliability** — how each source is performing across logged searches.")
    stats = source_stats(engine)
    rows = []
    for source, s in sorted(stats.items(), key=lambda kv: kv[1]["total"], reverse=True):
        rows.append({
            "Source": source,
            "Runs": s["total"],
            "Answer rate": f"{s['answer_rate']}%",
            "Hit rate": f"{s['success_rate']}%",
            "Errors": s["error"],
            "Needs key": s["no_key"],
            "Avg ms": s["avg_latency_ms"],
        })
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
        degraded = [r["Source"] for r in rows
                    if int(r["Errors"]) and int(r["Errors"]) >= max(1, int(0.5 * stats[r["Source"]]["total"]))]
        if degraded:
            st.warning("Degraded sources (high error rate) — investigate or heal: " + ", ".join(degraded))

    st.markdown("**Recent searches**")
    for s in searches[:25]:
        try:
            q = json.loads(s["query"] or "{}")
        except (ValueError, TypeError):
            q = {}
        qstr = ", ".join(f"{esc(k)}={esc(v)}" for k, v in q.items()) or "—"
        st.markdown(
            f'<div class="rc-meta" style="padding:4px 0;border-bottom:1px solid var(--border);">'
            f'{str(s["created_at"])[:19]} · {esc(s["n_ok"])}/{esc(s["n_sources"])} hit · {qstr}</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Admin: AI assistant (runs on the cheap LLM layer — Ollama/Gemini/Claude)
# ---------------------------------------------------------------------------
def admin_assistant_context(engine):
    parts = [
        "You are the in-app admin assistant for the Henry & Henry OSINT tool, a "
        "Streamlit application. Help the admin understand and debug the app. Be "
        "concise and practical. You can explain behavior and propose fixes, but you "
        "cannot modify the running code yourself — code changes go through the "
        "developer and a redeploy.",
        "App pages: Home, Search (OSINT lookup), New Request (client intake), "
        "My Requests (status lookup), Admin.",
        "OSINT sources: " + ", ".join(s.label for s in osint_engine.SOURCES) + ".",
    ]
    try:
        counts = status_counts(engine)
        parts.append("Intake request counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()) + ".")
    except Exception:
        pass
    try:
        stats = source_stats(engine)
        if stats:
            parts.append("Recent source reliability (hit% / errors): " + "; ".join(
                f"{k} {v['success_rate']}%/{v['error']}" for k, v in stats.items()) + ".")
    except Exception:
        pass
    return "\n".join(parts)


def render_admin_assistant(engine):
    cfg = build_llm_cfg()
    provider = llm.provider_label(cfg)
    if not provider:
        st.info("AI assistant is off. Start Ollama locally (free) or set GEMINI_API_KEY "
                "(cheap) to enable a debug chat here.")
        return
    st.caption(f"Assistant engine: {provider} · admin-only")
    st.session_state.setdefault("admin_chat", [])

    for m in st.session_state.admin_chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # If the last message is from the user, generate a reply.
    if st.session_state.admin_chat and st.session_state.admin_chat[-1]["role"] == "user":
        convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in st.session_state.admin_chat)
        prompt = admin_assistant_context(engine) + "\n\nConversation:\n" + convo + "\nASSISTANT:"
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                text, used = llm.generate(prompt, cfg)
            if not text:
                text = f"(assistant unavailable: {used})"
            st.markdown(text)
        st.session_state.admin_chat.append({"role": "assistant", "content": text})
        st.rerun()

    with st.form("admin_assistant_form", clear_on_submit=True):
        msg = st.text_area("Ask the assistant", placeholder="e.g. why is the Reddit source erroring?")
        if st.form_submit_button("Send") and msg.strip():
            st.session_state.admin_chat.append({"role": "user", "content": msg.strip()})
            st.rerun()

    if st.session_state.admin_chat and st.button("Clear chat", key="clear_admin_chat"):
        st.session_state.admin_chat = []
        st.rerun()


# ---------------------------------------------------------------------------
# Page: OSINT Search
# ---------------------------------------------------------------------------
OSINT_KEYS = ["HIBP_API_KEY", "OPENCORPORATES_API_KEY", "NUMVERIFY_API_KEY",
              "GITHUB_TOKEN", "COURTLISTENER_TOKEN", "SHODAN_API_KEY"]

OSINT_STATUS = {"ok": "#2ea043", "not_found": "#5a6878", "no_key": "#c9a444", "error": "#c23b22"}
OSINT_LABEL = {"ok": "FOUND", "not_found": "NONE", "no_key": "NEEDS KEY", "error": "ERROR"}


LLM_KEYS = ["OLLAMA_HOST", "OLLAMA_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL",
            "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"]


def build_osint_cfg():
    return {k: get_config(k) for k in OSINT_KEYS}


def build_llm_cfg():
    return {k: get_config(k) for k in LLM_KEYS}


def render_source_status(cfg):
    """Compact 'which sources are live vs need a key' panel."""
    chips = []
    for s in osint_engine.SOURCES:
        if s.key is None or cfg.get(s.key):
            color, txt = "#2ea043", "live"
        else:
            color, txt = "#7a5f1a", f"needs {s.key}"
        chips.append(
            f'<span style="display:inline-block;margin:3px 8px 3px 0;font-family:var(--mono);'
            f'font-size:11px;color:var(--text-2);">'
            f'<span style="color:{color};">●</span> {esc(s.label)} '
            f'<span style="color:var(--text-dim);">({esc(txt)})</span></span>'
        )
    st.markdown("".join(chips), unsafe_allow_html=True)


def build_summary_prompt(query, results):
    lines = ["You are an OSINT analyst. Write a concise, factual intelligence "
             "summary of the findings below. Use neutral language, do not "
             "speculate beyond the data, note where coverage is thin, and end "
             "with a one-line confidence note. Findings:\n"]
    q = ", ".join(f"{k}={v}" for k, v in query.items() if (v or "").strip())
    lines.append(f"Search subject: {q}\n")
    for r in results:
        if r.status not in ("ok",):
            continue
        lines.append(f"\n## {r.source} ({r.category})")
        if r.summary:
            lines.append(r.summary)
        for k, v in (r.detail or {}).items():
            if v:
                lines.append(f"- {k}: {v}")
        for it in (r.items or [])[:8]:
            lines.append("- " + "; ".join(f"{k}: {v}" for k, v in it.items() if v))
    return "\n".join(lines)


def build_report_md(query, results, summary=None):
    lines = ["# OSINT Report — H & H Investigation", ""]
    lines.append(f"_Generated {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    q = ", ".join(f"{k}={v}" for k, v in query.items() if (v or "").strip())
    lines.append(f"\n**Search subject:** {q}\n")
    if summary:
        lines += ["## Summary", "", summary, ""]
    lines.append("## Findings")
    for r in results:
        lines.append(f"\n### {r.source}  ·  {r.status.upper()}  ·  {r.category}")
        if r.summary:
            lines.append(r.summary)
        if r.error:
            lines.append(f"_error: {r.error}_")
        for k, v in (r.detail or {}).items():
            if v:
                if isinstance(v, list):
                    v = ", ".join(str(x) for x in v)
                lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        for it in (r.items or []):
            lines.append("- " + "; ".join(f"{k}: {v}" for k, v in it.items() if v))
    lines += ["", "---",
              "_Derived from lawful open-source intelligence and public records. "
              "Not a consumer report; not for FCRA-covered decisions._"]
    return "\n".join(lines)


def render_osint_result(r):
    color = OSINT_STATUS.get(r.status, "#5a6878")
    label = OSINT_LABEL.get(r.status, r.status.upper())
    title = r.summary or r.error or label
    with st.expander(f"{r.source} — {title}", expanded=(r.status == "ok")):
        st.markdown(
            f'<span class="status-badge" style="background:{color};">{label}</span> '
            f'<span style="color:#5a6878;font-family:var(--mono);font-size:11px;letter-spacing:1px;">'
            f'{esc(r.category)}</span>',
            unsafe_allow_html=True,
        )
        if r.status == "error" and r.error:
            st.caption(esc(r.error))
        if r.status == "no_key":
            st.caption(esc(r.summary))
        for k, v in (r.detail or {}).items():
            if v:
                if isinstance(v, list):
                    v = ", ".join(str(x) for x in v)
                st.markdown(f"**{esc(k.replace('_', ' ').title())}:** {esc(v)}")
        for it in (r.items or []):
            url = it.get("url")
            line = " · ".join(f"{esc(k)}: {esc(v)}" for k, v in it.items() if v and k != "url")
            if url:
                st.markdown(f"- [{esc(line or url)}]({url})")
            else:
                st.markdown(f"- {line}")


def render_upgrade_nudge(plan):
    """Success-moment upgrade card. Shown only to users below the deepest plan,
    right after they've seen everything their tier returned — tied to a real
    limitation (the sources their plan didn't run), not manufactured friction.
    States plainly what the next tier additionally checks. No fake urgency."""
    rank = PLAN_RANK.get(plan, 0)
    if rank >= 2:
        return
    target, price, what = {
        0: ("Pro", "$34.99 / mo",
            "court records, company officers, subdomains, phone intel, and host & port intel"),
        1: ("Deep", "$59.99 / mo",
            "breach & dark-web exposure (HaveIBeenPwned) and scheduled monitoring with change alerts"),
    }[rank]
    st.markdown(
        f'<div class="upgrade-card"><div class="uc-label">Beyond this search</div>'
        f'<div class="uc-title">{esc(target)} also checks {esc(what)}.</div>'
        f'<div class="uc-meta">{esc(price)} · cancel anytime</div></div>',
        unsafe_allow_html=True,
    )
    if st.button(f"Unlock {target} →", key="nudge_up"):
        st.session_state.nav = "Account"
        st.rerun()


def page_search():
    render_brand_bar()
    user = require_login(engine)
    if not user:
        render_footer()
        return
    if not require_consent():
        render_footer()
        return
    st.markdown('<div class="section-label">OSINT Search</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Public-Record <em>Lookup</em></div>', unsafe_allow_html=True)
    st.caption(
        "Aggregates publicly available open-source and public-record signals. For lawful "
        "research only. This is not a consumer report and may not be used for employment, "
        "credit, tenant, or insurance decisions, or to harass or stalk any person."
    )

    osint_cfg = build_osint_cfg()
    with st.expander("Source status — which lookups are live vs. need a key"):
        render_source_status(osint_cfg)

    with st.form("osint_form"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Full name", placeholder="court records, company officers")
            email = st.text_input("Email", placeholder="breach exposure, Gravatar")
            username = st.text_input("Username / handle", placeholder="social footprint, GitHub")
        with c2:
            phone = st.text_input("Phone")
            domain = st.text_input("Domain", placeholder="example.com")
        depth_names = allowed_depths(user.get("plan", "Recon"))
        depth = st.selectbox("Search depth", depth_names, index=len(depth_names) - 1,
                             help="Higher tiers run more (and deeper) sources. "
                                  "The deepest tier reaches breach / dark-web exposure data.")
        run = st.form_submit_button("Run Search", type="primary")

    if run:
        query = {"name": name, "email": email, "username": username, "phone": phone, "domain": domain}
        if not any((v or "").strip() for v in query.values()):
            st.error("Enter at least one identifier to search.")
        else:
            with st.spinner("Querying sources…"):
                results = osint_engine.run_search(query, osint_cfg, source_ids=DEPTHS[depth])
                log_search(engine, query, results)
                st.session_state.osint_results = results
                st.session_state.osint_query = query
                st.session_state.pop("osint_summary", None)

    results = st.session_state.get("osint_results")
    if results:
        q = st.session_state.get("osint_query", {})
        shown = ", ".join(f"{esc(k)}={esc(v)}" for k, v in q.items() if (v or "").strip())
        found = sum(1 for r in results if r.status == "ok")
        st.markdown(f"**Query:** {shown}")
        st.caption(f"{found} of {len(results)} sources returned data.")

        # AI summary — runs on the cheapest available provider (local Ollama
        # first, then Gemini, then optional Claude).
        llm_cfg = build_llm_cfg()
        provider = llm.provider_label(llm_cfg)
        cols = st.columns([1, 2])
        with cols[0]:
            if provider and found:
                if st.button("Generate AI summary"):
                    with st.spinner(f"Summarizing via {provider}…"):
                        text, used = llm.generate(build_summary_prompt(q, results), llm_cfg)
                    if text:
                        st.session_state.osint_summary = text
                    else:
                        st.session_state.osint_summary = None
                        st.session_state.osint_summary_err = used
        with cols[1]:
            if provider:
                st.caption(f"AI summary engine: {provider}")
            else:
                st.caption("AI summary off — start Ollama locally or set GEMINI_API_KEY to enable.")

        if st.session_state.get("osint_summary"):
            st.markdown("#### AI summary")
            st.markdown(esc(st.session_state.osint_summary).replace("\n", "  \n"))
        elif st.session_state.get("osint_summary_err"):
            st.warning(f"Summary failed: {esc(st.session_state.osint_summary_err)}")

        st.markdown("#### Sources")
        for r in results:
            render_osint_result(r)

        render_upgrade_nudge(user.get("plan", "Recon"))

        report = build_report_md(q, results, st.session_state.get("osint_summary"))
        subject_slug = re.sub(r"[^a-z0-9]+", "-", (shown or "report").lower())[:40].strip("-")
        dl, clr = st.columns([1, 1])
        with dl:
            st.download_button("Download report (.md)", report,
                               file_name=f"osint-{subject_slug or 'report'}.md",
                               mime="text/markdown")
        with clr:
            if st.button("Clear results"):
                for k in ("osint_results", "osint_query", "osint_summary", "osint_summary_err"):
                    st.session_state.pop(k, None)
                st.rerun()

    render_footer()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
engine = get_engine()
handle_stripe_return(engine)

_reset_token = st.query_params.get("reset")
if _reset_token:
    render_brand_bar()
    page_reset_password(engine, _reset_token)
    render_footer()
    st.stop()

st.sidebar.markdown(
    """
    <div style="text-align:center; padding:16px 0 24px;">
        <span style="font-family:'Cormorant Garamond',Georgia,serif; font-size:16px; font-weight:700; letter-spacing:3px; color:#c9a444;">
            H &amp; H
        </span>
    </div>
    """,
    unsafe_allow_html=True,
)

_u = st.session_state.get("user")
if _u:
    st.sidebar.markdown(
        f"<div style='text-align:center;font-family:IBM Plex Mono,monospace;font-size:11px;"
        f"color:#5a6878;padding-bottom:10px;'>{esc(_u['email'])}<br>"
        f"plan: <span style='color:#c9a444;'>{esc(_u.get('plan','Recon'))}</span></div>",
        unsafe_allow_html=True,
    )

pages = ["Home", "Search", "New Request", "My Requests", "Account", "Terms", "Admin"]
nav = st.session_state.get("nav", "Home")
default_idx = pages.index(nav) if nav in pages else 0
page = st.sidebar.radio("Navigation", pages, index=default_idx, label_visibility="collapsed")
if st.session_state.get("nav") and st.session_state.nav != page:
    st.session_state.nav = page

if page == "Home":
    page_home()
elif page == "Search":
    page_search()
elif page == "New Request":
    page_new_request(engine)
elif page == "My Requests":
    page_my_requests(engine)
elif page == "Account":
    page_account(engine)
elif page == "Terms":
    page_terms()
elif page == "Admin":
    page_admin(engine)
