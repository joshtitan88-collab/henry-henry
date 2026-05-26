import streamlit as st
import sqlite3
import datetime

st.set_page_config(
    page_title="H & H Investigation — Investigative Intelligence",
    page_icon="◆",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Brand constants
# ---------------------------------------------------------------------------
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

ADMIN_PASSWORD = "hhi-admin-2026"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
@st.cache_resource
def init_db():
    conn = sqlite3.connect("hhi_intake.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            client_name     TEXT NOT NULL,
            client_email    TEXT NOT NULL,
            client_firm     TEXT,
            service_tier    TEXT NOT NULL,
            rush            INTEGER NOT NULL DEFAULT 0,
            subject_name    TEXT NOT NULL,
            anchor_phone    TEXT,
            anchor_email    TEXT,
            anchor_address  TEXT,
            anchor_dob      TEXT,
            anchor_employer TEXT,
            anchor_other    TEXT,
            notes           TEXT,
            status          TEXT NOT NULL DEFAULT 'Submitted',
            admin_notes     TEXT
        )
    """)
    conn.commit()
    return conn


def insert_request(conn, data):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    year = datetime.datetime.now(datetime.timezone.utc).year
    cursor = conn.execute(
        """
        INSERT INTO requests (
            ref_number, created_at, updated_at,
            client_name, client_email, client_firm,
            service_tier, rush, subject_name,
            anchor_phone, anchor_email, anchor_address,
            anchor_dob, anchor_employer, anchor_other,
            notes, status
        ) VALUES (
            'TEMP', ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, 'Submitted'
        )
        """,
        (
            now, now,
            data["client_name"], data["client_email"], data.get("client_firm", ""),
            data["service_tier"], int(data.get("rush", False)), data["subject_name"],
            data.get("anchor_phone", ""), data.get("anchor_email", ""),
            data.get("anchor_address", ""), data.get("anchor_dob", ""),
            data.get("anchor_employer", ""), data.get("anchor_other", ""),
            data.get("notes", ""),
        ),
    )
    row_id = cursor.lastrowid
    ref = f"HHI-{year}-{row_id:04d}"
    conn.execute("UPDATE requests SET ref_number = ? WHERE id = ?", (ref, row_id))
    conn.commit()
    return ref


def get_requests(conn, client_email=None, status=None):
    query = "SELECT * FROM requests WHERE 1=1"
    params = []
    if client_email:
        query += " AND LOWER(client_email) = LOWER(?)"
        params.append(client_email)
    if status and status != "All":
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC"
    return conn.execute(query, params).fetchall()


def update_request(conn, ref_number, new_status, admin_notes):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.execute(
        "UPDATE requests SET status = ?, admin_notes = ?, updated_at = ? WHERE ref_number = ?",
        (new_status, admin_notes, now, ref_number),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400;1,600&family=IBM+Plex+Mono:wght@400;500&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&display=swap');

    :root {
        --gold: #c9a444;
        --gold-hi: #e8c060;
        --gold-dim: #7a5f1a;
        --bg: #07090d;
        --bg-2: #0d1117;
        --bg-3: #13181f;
        --text: #eaeef4;
        --text-2: #c2cdd9;
        --text-dim: #5a6878;
        --border: #1e2630;
        --border-2: #2a3444;
        --green: #2ea043;
        --mono: 'IBM Plex Mono', 'Courier New', monospace;
        --display: 'Cormorant Garamond', 'Georgia', serif;
        --body: 'Libre Baskerville', 'Georgia', serif;
    }

    .stApp {
        background-color: var(--bg);
        color: var(--text);
        font-family: var(--body);
    }

    [data-testid="stSidebar"] {
        background-color: var(--bg-2);
        border-right: 1px solid var(--border);
    }
    [data-testid="stSidebar"] * {
        color: var(--text-2) !important;
    }

    /* Brand bar */
    .brand-bar {
        display: flex; align-items: center; gap: 12px;
        padding: 18px 0; border-bottom: 1px solid var(--border);
        margin-bottom: 32px;
    }
    .brand-mark {
        width: 24px; height: 24px;
        border: 1px solid var(--gold-dim);
        display: flex; align-items: center; justify-content: center;
        font-size: 10px; color: var(--gold-dim);
    }
    .brand-name {
        font-family: var(--display);
        font-size: 20px; font-weight: 700;
        letter-spacing: 4px; color: var(--gold);
    }

    /* Section chrome */
    .section-title {
        font-family: var(--display);
        font-size: 36px; font-weight: 700;
        color: var(--text); line-height: 1.15;
        margin-bottom: 8px;
    }
    .section-title em { font-style: italic; color: var(--gold); }
    .section-label {
        font-family: var(--mono);
        font-size: 10px; letter-spacing: 4px;
        color: var(--gold-dim); text-transform: uppercase;
        margin-bottom: 12px;
    }

    /* Metric row */
    .metric-row {
        display: flex; gap: 1px;
        background: var(--border); border: 1px solid var(--border);
        margin: 32px 0;
    }
    .metric-card {
        flex: 1; background: var(--bg-2); padding: 24px 28px;
    }
    .metric-num {
        font-family: var(--display);
        font-size: 36px; font-weight: 700;
        color: var(--gold); line-height: 1; margin-bottom: 4px;
    }
    .metric-label {
        font-family: var(--mono);
        font-size: 10px; letter-spacing: 2px;
        color: var(--text-dim); text-transform: uppercase;
    }

    /* Tier grid */
    .tier-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 1px; background: var(--border); border: 1px solid var(--border);
        margin-top: 24px;
    }
    .tier-card {
        background: var(--bg-2); padding: 28px 24px;
        transition: background 0.15s;
    }
    .tier-card:hover { background: var(--bg-3); }
    .tier-card.featured { border-left: 2px solid var(--gold); }
    .tier-name {
        font-family: var(--display);
        font-size: 22px; font-weight: 700;
        color: var(--text); margin-bottom: 4px;
    }
    .tier-tag {
        font-family: var(--mono);
        font-size: 9px; letter-spacing: 1.5px;
        color: var(--text-dim); text-transform: uppercase;
        margin-bottom: 12px;
    }
    .tier-price {
        font-family: var(--display);
        font-size: 28px; font-weight: 700;
        color: var(--gold); margin-bottom: 8px;
    }
    .tier-scope {
        font-size: 14px; color: var(--text-2);
        font-style: italic; line-height: 1.6;
    }
    .tier-turn {
        font-family: var(--mono);
        font-size: 11px; color: var(--text-dim); margin-top: 10px;
    }

    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 3px 10px; border-radius: 3px;
        font-family: var(--mono);
        font-size: 10px; letter-spacing: 1.5px;
        text-transform: uppercase; color: #fff;
    }

    /* Confirmation card */
    .confirmation-card {
        background: var(--bg-2);
        border: 1px solid var(--gold-dim);
        border-left: 3px solid var(--gold);
        padding: 28px; margin: 24px 0;
    }
    .ref-number {
        font-family: var(--mono);
        font-size: 24px; color: var(--gold);
        letter-spacing: 3px; margin-bottom: 12px;
    }

    /* Request cards */
    .request-card {
        background: var(--bg-2);
        border: 1px solid var(--border-2);
        padding: 20px 24px; margin-bottom: 8px;
        transition: background 0.15s;
    }
    .request-card:hover { background: var(--bg-3); }
    .request-card .rc-header {
        display: flex; justify-content: space-between;
        align-items: center; margin-bottom: 8px;
    }
    .rc-ref {
        font-family: var(--mono);
        font-size: 14px; color: var(--gold);
        letter-spacing: 2px;
    }
    .rc-meta {
        font-family: var(--mono);
        font-size: 11px; color: var(--text-dim);
        line-height: 1.6;
    }

    /* Form overrides */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div {
        background-color: var(--bg-2) !important;
        color: var(--text) !important;
        border-color: var(--border) !important;
        font-family: var(--mono) !important;
    }

    /* Footer */
    .site-footer {
        border-top: 1px solid var(--border);
        padding: 28px 0; margin-top: 60px;
        display: flex; justify-content: space-between;
        align-items: center; flex-wrap: wrap; gap: 16px;
    }
    .footer-brand {
        font-family: var(--display);
        font-size: 15px; letter-spacing: 3px;
        color: var(--gold-dim); font-weight: 700;
    }
    .footer-legal {
        font-family: var(--mono);
        font-size: 10px; letter-spacing: 1px;
        color: var(--text-dim); text-align: right; line-height: 1.9;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------
def render_brand_bar():
    st.markdown(
        """
        <div class="brand-bar">
            <div class="brand-mark">◆</div>
            <div class="brand-name">H &amp; H INVESTIGATION</div>
        </div>
        """,
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
    return f'<span class="status-badge" style="background:{color};">{status}</span>'


def mask_name(name):
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return name


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

    html = '<div class="tier-grid">'
    for name, tag, price, turn, scope, featured in tiers:
        cls = "tier-card featured" if featured else "tier-card"
        html += f'<div class="{cls}"><div class="tier-name">{name}</div><div class="tier-tag">{tag}</div><div class="tier-price">{price}</div><div class="tier-scope">{scope}</div><div class="tier-turn">{turn}</div></div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

    st.markdown("")
    if st.button("Start a New Request", type="primary"):
        st.session_state.nav = "New Request"
        st.rerun()

    render_footer()


# ---------------------------------------------------------------------------
# Page: New Request
# ---------------------------------------------------------------------------
def page_new_request(conn):
    render_brand_bar()

    st.markdown('<div class="section-label">Client Intake</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Request <em>a Dossier</em></div>', unsafe_allow_html=True)

    if st.session_state.get("last_ref"):
        ref = st.session_state.last_ref
        st.markdown(
            f"""
            <div class="confirmation-card">
                <div class="ref-number">{ref}</div>
                <p style="color:#c2cdd9; font-size:14px; line-height:1.7; margin:0;">
                    Your request has been received. We will send an engagement letter
                    to the email address you provided. Work begins once the letter is signed.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
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

        submitted = st.form_submit_button("Submit Request", type="primary")

    if submitted:
        errors = []
        if not client_name.strip():
            errors.append("Your full name is required.")
        if not client_email.strip():
            errors.append("Your email is required.")
        if not subject_name.strip():
            errors.append("Subject full name is required.")
        anchors = [anchor_phone, anchor_email, anchor_address, anchor_dob, anchor_employer, anchor_other]
        if not any(a.strip() for a in anchors):
            errors.append("At least one anchor data point is required.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            ref = insert_request(conn, {
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
            })
            st.session_state.last_ref = ref
            st.rerun()

    render_footer()


# ---------------------------------------------------------------------------
# Page: My Requests
# ---------------------------------------------------------------------------
def page_my_requests(conn):
    render_brand_bar()

    st.markdown('<div class="section-label">Track</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">My <em>Requests</em></div>', unsafe_allow_html=True)

    email = st.text_input("Enter the email you used when submitting your request")

    if not email.strip():
        st.info("Enter your email above to look up your requests.")
        render_footer()
        return

    status_filter = st.selectbox("Filter by status", ["All"] + STATUS_ORDER)
    rows = get_requests(conn, client_email=email.strip(), status=status_filter)

    if not rows:
        st.warning("No requests found for that email address and filter.")
        render_footer()
        return

    for r in rows:
        badge = status_badge(r["status"])
        masked = mask_name(r["subject_name"])
        created = r["created_at"][:10]
        updated = r["updated_at"][:10]
        st.markdown(
            f"""
            <div class="request-card">
                <div class="rc-header">
                    <span class="rc-ref">{r["ref_number"]}</span>
                    {badge}
                </div>
                <div class="rc-meta">
                    Tier: {r["service_tier"]}<br>
                    Subject: {masked}<br>
                    Submitted: {created} · Updated: {updated}
                    {"  ·  RUSH" if r["rush"] else ""}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    render_footer()


# ---------------------------------------------------------------------------
# Page: Admin
# ---------------------------------------------------------------------------
def page_admin(conn):
    render_brand_bar()

    if not st.session_state.get("admin_auth"):
        st.markdown('<div class="section-label">Restricted</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Admin <em>Access</em></div>', unsafe_allow_html=True)
        pw = st.text_input("Password", type="password")
        if st.button("Log in"):
            if pw == ADMIN_PASSWORD:
                st.session_state.admin_auth = True
                st.rerun()
            else:
                st.error("Invalid password.")
        render_footer()
        return

    st.markdown('<div class="section-label">Admin</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Request <em>Dashboard</em></div>', unsafe_allow_html=True)

    if st.button("Log out", key="admin_logout"):
        st.session_state.admin_auth = False
        st.rerun()

    all_rows = get_requests(conn)
    counts = {s: 0 for s in STATUS_ORDER}
    for r in all_rows:
        if r["status"] in counts:
            counts[r["status"]] += 1

    metric_html = '<div class="metric-row">'
    for s in STATUS_ORDER:
        metric_html += f'<div class="metric-card"><div class="metric-num">{counts[s]}</div><div class="metric-label">{s}</div></div>'
    metric_html += "</div>"
    st.markdown(metric_html, unsafe_allow_html=True)

    status_filter = st.selectbox("Filter by status", ["All"] + STATUS_ORDER, key="admin_status_filter")
    if status_filter != "All":
        rows = [r for r in all_rows if r["status"] == status_filter]
    else:
        rows = all_rows

    if not rows:
        st.info("No requests match the current filter.")
        render_footer()
        return

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
                if r["anchor_phone"]:
                    anchors.append(f"Phone: {r['anchor_phone']}")
                if r["anchor_email"]:
                    anchors.append(f"Email: {r['anchor_email']}")
                if r["anchor_address"]:
                    anchors.append(f"Address: {r['anchor_address']}")
                if r["anchor_dob"]:
                    anchors.append(f"DOB: {r['anchor_dob']}")
                if r["anchor_employer"]:
                    anchors.append(f"Employer: {r['anchor_employer']}")
                if r["anchor_other"]:
                    anchors.append(f"Other: {r['anchor_other']}")
                st.markdown("**Anchors:**  \n" + "  \n".join(anchors) if anchors else "**Anchors:** —")
                if r["notes"]:
                    st.markdown(f"**Notes:** {r['notes']}")
                st.markdown(f"**Created:** {r['created_at'][:19]}")
                st.markdown(f"**Updated:** {r['updated_at'][:19]}")

            st.divider()
            cur_idx = STATUS_ORDER.index(r["status"]) if r["status"] in STATUS_ORDER else 0
            new_status = st.selectbox(
                "Status",
                STATUS_ORDER,
                index=cur_idx,
                key=f"status_{r['ref_number']}",
            )
            admin_notes = st.text_area(
                "Admin notes",
                value=r["admin_notes"] or "",
                key=f"notes_{r['ref_number']}",
            )
            if st.button("Save", key=f"save_{r['ref_number']}"):
                update_request(conn, r["ref_number"], new_status, admin_notes)
                st.success(f"Updated {r['ref_number']}.")
                st.rerun()

    render_footer()


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------
conn = init_db()

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

pages = ["Home", "New Request", "My Requests", "Admin"]
default_idx = pages.index(st.session_state.get("nav", "Home"))

page = st.sidebar.radio("Navigation", pages, index=default_idx, label_visibility="collapsed")

if st.session_state.get("nav") and st.session_state.nav != page:
    st.session_state.nav = page

if page == "Home":
    page_home()
elif page == "New Request":
    page_new_request(conn)
elif page == "My Requests":
    page_my_requests(conn)
elif page == "Admin":
    page_admin(conn)
