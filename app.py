import streamlit as st

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="H & H Investigation — Investigative Intelligence",
    page_icon="◆",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Brand palette & custom CSS
# ---------------------------------------------------------------------------
INK = "#07090d"
GOLD = "#c9a444"
GOLD_HI = "#e8c060"
GOLD_DIM = "#7a5f1a"
PAPER = "#0d1117"
TEXT = "#eaeef4"
TEXT_2 = "#c2cdd9"
TEXT_DIM = "#5a6878"
BORDER = "#1e2630"

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400;1,600&family=IBM+Plex+Mono:wght@400;500&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&display=swap');

    :root {{
        --gold: {GOLD};
        --gold-hi: {GOLD_HI};
        --gold-dim: {GOLD_DIM};
        --bg: {INK};
        --bg-2: {PAPER};
        --text: {TEXT};
        --text-2: {TEXT_2};
        --text-dim: {TEXT_DIM};
        --border: {BORDER};
        --mono: 'IBM Plex Mono', 'Courier New', monospace;
        --display: 'Cormorant Garamond', 'Georgia', serif;
        --body: 'Libre Baskerville', 'Georgia', serif;
    }}

    .stApp {{
        background-color: var(--bg);
        color: var(--text);
        font-family: var(--body);
    }}

    /* Header / brand bar */
    .brand-bar {{
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 18px 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 32px;
    }}
    .brand-mark {{
        width: 24px; height: 24px;
        border: 1px solid var(--gold-dim);
        display: flex; align-items: center; justify-content: center;
        font-size: 10px; color: var(--gold-dim);
    }}
    .brand-name {{
        font-family: var(--display);
        font-size: 20px; font-weight: 700;
        letter-spacing: 4px; color: var(--gold);
    }}

    /* Section titles */
    .section-title {{
        font-family: var(--display);
        font-size: 36px; font-weight: 700;
        color: var(--text); line-height: 1.15;
        margin-bottom: 8px;
    }}
    .section-title em {{
        font-style: italic; color: var(--gold);
    }}
    .section-label {{
        font-family: var(--mono);
        font-size: 10px; letter-spacing: 4px;
        color: var(--gold-dim); text-transform: uppercase;
        margin-bottom: 12px;
    }}

    /* Metric cards */
    .metric-row {{
        display: flex; gap: 1px;
        background: var(--border);
        border: 1px solid var(--border);
        margin: 32px 0;
    }}
    .metric-card {{
        flex: 1;
        background: var(--bg-2);
        padding: 24px 28px;
    }}
    .metric-num {{
        font-family: var(--display);
        font-size: 36px; font-weight: 700;
        color: var(--gold); line-height: 1;
        margin-bottom: 4px;
    }}
    .metric-label {{
        font-family: var(--mono);
        font-size: 10px; letter-spacing: 2px;
        color: var(--text-dim); text-transform: uppercase;
    }}

    /* Tier cards */
    .tier-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 1px;
        background: var(--border);
        border: 1px solid var(--border);
        margin-top: 24px;
    }}
    .tier-card {{
        background: var(--bg-2);
        padding: 28px 24px;
        transition: background 0.15s;
    }}
    .tier-card:hover {{ background: #13181f; }}
    .tier-card.featured {{
        border-left: 2px solid var(--gold);
    }}
    .tier-name {{
        font-family: var(--display);
        font-size: 22px; font-weight: 700;
        color: var(--text); margin-bottom: 4px;
    }}
    .tier-tag {{
        font-family: var(--mono);
        font-size: 9px; letter-spacing: 1.5px;
        color: var(--text-dim); text-transform: uppercase;
        margin-bottom: 12px;
    }}
    .tier-price {{
        font-family: var(--display);
        font-size: 28px; font-weight: 700;
        color: var(--gold); margin-bottom: 8px;
    }}
    .tier-scope {{
        font-size: 14px; color: var(--text-2);
        font-style: italic; line-height: 1.6;
    }}
    .tier-turn {{
        font-family: var(--mono);
        font-size: 11px; color: var(--text-dim);
        margin-top: 10px;
    }}

    /* Deliverable list */
    .del-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 1px;
        background: var(--border);
        border: 1px solid var(--border);
        margin-top: 24px;
    }}
    .del-card {{
        background: var(--bg-2);
        padding: 28px 24px;
    }}
    .del-num {{
        font-family: var(--mono);
        font-size: 10px; letter-spacing: 2px;
        color: var(--text-dim); margin-bottom: 10px;
    }}
    .del-card h4 {{
        font-family: var(--display);
        font-size: 18px; font-weight: 700;
        color: var(--gold); margin-bottom: 8px;
    }}
    .del-card p {{
        font-size: 13px; color: var(--text-2); line-height: 1.7;
    }}

    /* Process steps */
    .step-row {{
        display: flex; gap: 32px;
        margin-top: 24px;
    }}
    .step {{
        flex: 1;
    }}
    .step-num {{
        width: 48px; height: 48px;
        border: 1px solid var(--border);
        background: var(--bg-2);
        display: flex; align-items: center; justify-content: center;
        font-family: var(--mono); font-size: 12px;
        color: var(--gold); margin-bottom: 16px;
    }}
    .step h4 {{
        font-family: var(--display);
        font-size: 17px; font-weight: 700;
        color: var(--text); margin-bottom: 8px;
    }}
    .step p {{
        font-size: 13px; color: var(--text-2); line-height: 1.7;
    }}

    /* Compliance block */
    .compliance {{
        background: var(--bg-2);
        border: 1px solid var(--border);
        padding: 36px 40px;
        margin-top: 24px;
    }}
    .compliance p {{
        font-size: 14px; color: var(--text-2); line-height: 1.8;
        max-width: 720px; margin-bottom: 20px;
    }}
    .comp-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px 40px;
    }}
    .comp-item {{
        font-family: var(--mono);
        font-size: 11px; color: var(--text-2);
        line-height: 1.6;
    }}
    .comp-item.no {{ color: var(--text-dim); }}

    /* Intake form */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div {{
        background-color: var(--bg-2) !important;
        color: var(--text) !important;
        border-color: var(--border) !important;
        font-family: var(--mono) !important;
    }}

    /* Footer */
    .site-footer {{
        border-top: 1px solid var(--border);
        padding: 28px 0;
        margin-top: 60px;
        display: flex; justify-content: space-between; align-items: center;
        flex-wrap: wrap; gap: 16px;
    }}
    .footer-brand {{
        font-family: var(--display);
        font-size: 15px; letter-spacing: 3px;
        color: var(--gold-dim); font-weight: 700;
    }}
    .footer-legal {{
        font-family: var(--mono);
        font-size: 10px; letter-spacing: 1px;
        color: var(--text-dim); text-align: right;
        line-height: 1.9;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Brand bar
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="brand-bar">
        <div class="brand-mark">◆</div>
        <div class="brand-name">H &amp; H INVESTIGATION</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------
st.markdown('<div class="section-label">Georgia-based · Nationwide remote delivery</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Investigative <em>Intelligence</em> on Demand</div>', unsafe_allow_html=True)
st.markdown(
    """
    <p style="max-width:640px; font-size:15px; color:#c2cdd9; line-height:1.8; margin-bottom:8px;">
    Give us a name and one anchor data point — phone, email, address, DOB, or employer.
    Within <strong style="color:#eaeef4;">48 hours</strong> you have a sealed PDF dossier:
    phones, addresses, court records, asset signals, custody-relevant findings —
    every material claim <strong style="color:#eaeef4;">cross-referenced across independent
    public-record sources</strong>, with a per-finding confidence rating and a complete
    sources appendix.
    </p>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="metric-row">
        <div class="metric-card">
            <div class="metric-num">49+</div>
            <div class="metric-label">Public-record sources</div>
        </div>
        <div class="metric-card">
            <div class="metric-num">48h</div>
            <div class="metric-label">Standard delivery</div>
        </div>
        <div class="metric-card">
            <div class="metric-num">100%</div>
            <div class="metric-label">Open-source · lawful</div>
        </div>
        <div class="metric-card">
            <div class="metric-num">$295</div>
            <div class="metric-label">Starting price</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
st.markdown('<div class="section-label">01 · Services</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">What Every Dossier <em>Contains</em></div>', unsafe_allow_html=True)

deliverables = [
    ("01", "Executive Summary", "Two-paragraph plain-English findings. Read it to a client on the phone — no interpretation required."),
    ("02", "Contact Data", "Current phones and emails from public and breach-exposed records. Current address with prior-address history where public records support it."),
    ("03", "Court & Legal Records", "Civil and criminal records pulled by hand. Judgments, restraining orders, and relevant docket entries flagged for counsel."),
    ("04", "Asset Signals", "Real property, business officer roles, vehicles where public filings allow, professional licenses, and UCC filings."),
    ("05", "Identity Graph", "Visual map connecting the subject to known associates, prior addresses, phone clusters, and business entities."),
    ("06", "Verdict & Sources", "Corroboration verdict (ACCEPT / INSUFFICIENT), per-finding confidence rating, and complete sources appendix."),
]

del_html = '<div class="del-grid">'
for num, title, desc in deliverables:
    del_html += f'<div class="del-card"><div class="del-num">{num}</div><h4>{title}</h4><p>{desc}</p></div>'
del_html += "</div>"
st.markdown(del_html, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
st.markdown("")
st.markdown('<div class="section-label">02 · Pricing</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Intelligence <em>Tiers</em></div>', unsafe_allow_html=True)

tiers = [
    ("Discovery", "Single subject · Identity", "$295", "48 hours", "Who is this person? Where are they now?", False),
    ("Asset & Affiliation", "Finances · Business ties", "$595", "72 hours", "What do they own? Where's the money?", False),
    ("Family Law Standard", "Court-ready documentation", "$895", "5 business days", "Can we use this in court?", True),
    ("Family Law Premium", "Two subjects · Comparative", "$1,495", "7 business days", "Two subjects — comparative analysis", False),
    ("Monthly Retainer", "4× FL Standard · Priority queue", "$1,495/mo", "24h priority", "4 FL Standard dossiers/month, 3-month minimum", False),
    ("Spec Audit", "Multi-subject · Expert-witness ready", "$3,500+", "10–14 days", "Complex multi-subject engagements, custom scope", False),
]

tier_html = '<div class="tier-grid">'
for name, tag, price, turn, scope, featured in tiers:
    cls = "tier-card featured" if featured else "tier-card"
    tier_html += f"""
    <div class="{cls}">
        <div class="tier-name">{name}</div>
        <div class="tier-tag">{tag}</div>
        <div class="tier-price">{price}</div>
        <div class="tier-scope">{scope}</div>
        <div class="tier-turn">⏱ {turn}</div>
    </div>
    """
tier_html += "</div>"
st.markdown(tier_html, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------
st.markdown("")
st.markdown('<div class="section-label">03 · Process</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Four Steps. <em>No Portal</em> to Learn.</div>', unsafe_allow_html=True)

steps = [
    ("01", "Email a Subject", "Full name plus one anchor — phone, email, address, DOB, or employer. More anchors yield sharper results."),
    ("02", "Sign Engagement", "One-page engagement letter documents your legitimate purpose. 30 seconds. Required before work begins."),
    ("03", "We Investigate", "Our pipeline queries 49+ public-record sources. Every material claim corroborated before it enters the dossier."),
    ("04", "Sealed PDF Delivered", "Dossier lands in your inbox within the SLA window. Invoice follows on delivery."),
]

step_html = '<div class="step-row">'
for num, title, desc in steps:
    step_html += f"""
    <div class="step">
        <div class="step-num">{num}</div>
        <h4>{title}</h4>
        <p>{desc}</p>
    </div>
    """
step_html += "</div>"
st.markdown(step_html, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------
st.markdown("")
st.markdown('<div class="section-label">04 · Compliance</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Trust & <em>Legal Scope</em></div>', unsafe_allow_html=True)

st.markdown(
    """
    <div class="compliance">
        <p>
            H &amp; H Investigation uses lawful open-source records exclusively — public court records,
            county recorder filings, public-facing social media, and public commercial databases. Every
            dossier includes a documented sources appendix and a repeatable methodology.
        </p>
        <div class="comp-grid">
            <div class="comp-item">✓ Public court &amp; docket records</div>
            <div class="comp-item">✓ County recorder &amp; property filings</div>
            <div class="comp-item">✓ Public commercial databases</div>
            <div class="comp-item">✓ Public-facing social media</div>
            <div class="comp-item">✓ Breach-exposed public contact data</div>
            <div class="comp-item">✓ Business &amp; license registrations</div>
            <div class="comp-item">✓ UCC filings (public record)</div>
            <div class="comp-item">✓ Federal bankruptcy records (PACER)</div>
            <div class="comp-item no">✗ No protected health or education records</div>
            <div class="comp-item no">✗ No DPPA-restricted DMV data</div>
            <div class="comp-item no">✗ No sealed criminal records</div>
            <div class="comp-item no">✗ No consumer credit data · No pretext</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Intake form
# ---------------------------------------------------------------------------
st.markdown("")
st.markdown('<div class="section-label">05 · Start a Case</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Request <em>a Dossier</em></div>', unsafe_allow_html=True)
st.caption("Fill out the form below and we will follow up via email to complete the engagement.")

with st.form("intake_form"):
    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Your name")
        client_email = st.text_input("Your email")
        client_firm = st.text_input("Firm / company (optional)")
    with col2:
        tier = st.selectbox(
            "Service tier",
            [
                "Discovery — $295",
                "Asset & Affiliation — $595",
                "Family Law Standard — $895",
                "Family Law Premium — $1,495",
                "Monthly Retainer — $1,495/mo",
                "Spec Audit — $3,500+",
            ],
        )
        rush = st.checkbox("Rush delivery (+$200 / +$500)")
        subject_name = st.text_input("Subject full name")

    anchor = st.text_area(
        "Anchor data point(s)",
        placeholder="Phone, email, address, DOB, employer — at least one required",
        height=80,
    )
    notes = st.text_area("Additional notes (optional)", height=80)

    submitted = st.form_submit_button("Submit Request")
    if submitted:
        if not client_name or not client_email or not subject_name or not anchor:
            st.error("Please fill in all required fields (your name, email, subject name, and at least one anchor).")
        else:
            st.success(
                f"Request received for **{tier}** on subject **{subject_name}**. "
                f"We will send an engagement letter to **{client_email}** shortly."
            )

# ---------------------------------------------------------------------------
# Contact
# ---------------------------------------------------------------------------
st.markdown("")
st.markdown(
    """
    <div style="text-align:center; padding:48px 0;">
        <p style="font-family:var(--mono); font-size:10px; letter-spacing:4px; color:var(--gold-dim); text-transform:uppercase; margin-bottom:12px;">
            Contact
        </p>
        <p style="font-family:var(--mono); font-size:16px; letter-spacing:2px; color:var(--gold); margin-bottom:16px;">
            joshua@hhinvestigations.com
        </p>
        <p style="font-family:var(--mono); font-size:10px; letter-spacing:2.5px; color:var(--text-dim); text-transform:uppercase;">
            Joshua Henry, Principal · Greater Atlanta, GA · Nationwide Remote Delivery
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
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
