import streamlit as st
import os
import json
import html
import re
import secrets
import smtplib
import ssl
import datetime
from email.message import EmailMessage

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

STATUS_ORDER = ["Submitted", "Engagement Sent", "In Progress", "Delivered"]

STATUS_COLORS = {
    "Submitted": "#5a6878",
    "Engagement Sent": "#3a7bd5",
    "In Progress": "#c9a444",
    "Delivered": "#2ea043",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
# Page: Home
# ---------------------------------------------------------------------------
def page_home():
    render_brand_bar()
    st.markdown('<div class="section-label">Georgia-based · Nationwide remote delivery</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Investigative <em>Intelligence</em> on Demand</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <p style="max-width:640px; font-size:15px; color:#c2cdd9; line-height:1.8; margin-bottom:8px;">
        Give us a name and one anchor data point — phone, email, address, DOB, or employer.
        Within <strong style="color:#eaeef4;">48 hours</strong> you have a sealed PDF dossier
        cross-referenced across independent public-record sources.
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="metric-row">
            <div class="metric-card"><div class="metric-num">49+</div><div class="metric-label">Public-record sources</div></div>
            <div class="metric-card"><div class="metric-num">48h</div><div class="metric-label">Standard delivery</div></div>
            <div class="metric-card"><div class="metric-num">100%</div><div class="metric-label">Open-source · lawful</div></div>
            <div class="metric-card"><div class="metric-num">$295</div><div class="metric-label">Starting price</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-label">Pricing</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Intelligence <em>Tiers</em></div>', unsafe_allow_html=True)
    tiers = [
        ("Discovery", "Single subject · Identity", "$295", "48 hours", "Who is this person? Where are they now?", False),
        ("Asset & Affiliation", "Finances · Business ties", "$595", "72 hours", "What do they own? Where's the money?", False),
        ("Family Law Standard", "Court-ready documentation", "$895", "5 business days", "Can we use this in court?", True),
        ("Family Law Premium", "Two subjects · Comparative", "$1,495", "7 business days", "Two subjects — comparative analysis", False),
        ("Monthly Retainer", "4x FL Standard · Priority queue", "$1,495/mo", "24h priority", "4 FL Standard dossiers/month, 3-month minimum", False),
        ("Spec Audit", "Multi-subject · Expert-witness ready", "$3,500+", "10-14 days", "Complex multi-subject engagements, custom scope", False),
    ]
    html_out = '<div class="tier-grid">'
    for name, tag, price, turn, scope, featured in tiers:
        cls = "tier-card featured" if featured else "tier-card"
        html_out += (
            f'<div class="{cls}"><div class="tier-name">{esc(name)}</div>'
            f'<div class="tier-tag">{esc(tag)}</div><div class="tier-price">{esc(price)}</div>'
            f'<div class="tier-scope">{esc(scope)}</div><div class="tier-turn">{esc(turn)}</div></div>'
        )
    html_out += "</div>"
    st.markdown(html_out, unsafe_allow_html=True)

    st.markdown("")
    if st.button("Start a New Request", type="primary"):
        st.session_state.nav = "New Request"
        st.rerun()
    render_footer()


# ---------------------------------------------------------------------------
# Page: New Request
# ---------------------------------------------------------------------------
def page_new_request(engine):
    render_brand_bar()
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

    tab_req, tab_analytics = st.tabs(["Requests", "Search Analytics"])

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

    with tab_analytics:
        render_search_analytics(engine)

    render_footer()


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
# Page: OSINT Search
# ---------------------------------------------------------------------------
OSINT_KEYS = ["HIBP_API_KEY", "OPENCORPORATES_API_KEY", "NUMVERIFY_API_KEY",
              "GITHUB_TOKEN", "COURTLISTENER_TOKEN"]

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


def page_search():
    render_brand_bar()
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
        run = st.form_submit_button("Run Search", type="primary")

    if run:
        query = {"name": name, "email": email, "username": username, "phone": phone, "domain": domain}
        if not any((v or "").strip() for v in query.values()):
            st.error("Enter at least one identifier to search.")
        else:
            with st.spinner("Querying sources…"):
                results = osint_engine.run_search(query, osint_cfg)
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
        if st.button("Clear results"):
            for k in ("osint_results", "osint_query", "osint_summary", "osint_summary_err"):
                st.session_state.pop(k, None)
            st.rerun()

    render_footer()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
engine = get_engine()

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

pages = ["Home", "Search", "New Request", "My Requests", "Admin"]
default_idx = pages.index(st.session_state.get("nav", "Home"))
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
elif page == "Admin":
    page_admin(engine)
