# Launch Runbook — H & H Investigation

Everything needed to take this app from the repo to a live, paid product at
`hhinvestigations.com`. Work top to bottom. Steps marked **(once)** are
one-time; the rest you'll repeat on every deploy as needed.

Nothing here puts a secret in the repo. Every key lives in the Render
dashboard (or your local `.streamlit/secrets.toml`, which is gitignored).

---

## 0. What you're deploying

- A Streamlit web app (`app.py`) — the self-service search tool, accounts,
  and Stripe-gated search depth.
- A Postgres database (Render provisions it from `render.yaml`).
- An hourly cron worker (`monitor.py`) that re-runs saved monitors.

`render.yaml` already declares all three. You connect the repo once and Render
reads that file ("Blueprint") to build everything.

---

## 1. Stripe — create the subscription products **(once)**

You sell two paid plans. Each needs a **recurring price** in Stripe; the app
references them by price ID.

1. Create a Stripe account and finish business verification (needed before you
   can accept live payments).
2. Start in **Test mode** (toggle, top-right of the Stripe dashboard) so you can
   rehearse without real charges.
3. **Products → Add product:**
   - Product **"H&H Pro"** → add a price → **Recurring**, monthly, set the
     amount (the app's Home page currently shows **$49/mo** as a placeholder —
     match it or tell me your real number).
   - Product **"H&H Deep"** → add a price → **Recurring**, monthly (Home shows
     **$149/mo** as a placeholder).
4. Open each price and copy its ID (looks like `price_1abc...`). You'll paste
   these into Render as `STRIPE_PRICE_PRO` and `STRIPE_PRICE_DEEP`.
5. **Developers → API keys** → copy the **Secret key** (`sk_test_...` now, swap
   to `sk_live_...` at go-live). This becomes `STRIPE_SECRET_KEY`.
6. **Settings → Billing → Customer portal** → enable it (lets subscribers
   cancel/update cards via the "Manage billing" button). Save.

> No webhook is required. The app confirms a checkout server-side on return and
> re-checks the subscription each time the Account page loads.

---

## 2. Render — deploy the app **(once to set up, then auto on push)**

1. Push your branch and merge it to the branch Render will track (e.g. `main`).
2. In Render: **New → Blueprint**, connect this GitHub repo, pick the branch.
   Render reads `render.yaml` and proposes: web service `hh-intake`, Postgres
   `hh-intake-db`, cron `hh-monitor`. Approve.
3. When prompted, fill the env vars marked `sync: false` (they're intentionally
   not in the repo). See the table in §3. At minimum set `ADMIN_PASSWORD` and
   the three Stripe values; the rest light up optional sources.
4. Click **Apply / Create**. First build runs `pip install -r
   requirements-prod.txt` and starts Streamlit. Watch the logs until it's live.
5. Render gives you a URL like `https://hh-intake.onrender.com`. Confirm the app
   loads there before wiring the domain.

On every later `git push` to the tracked branch, Render auto-redeploys.

---

## 3. Environment variables

Set these in the Render dashboard (web service **and** cron where noted).
`DATABASE_URL` and `PYTHON_VERSION` are filled automatically by `render.yaml`.

| Variable | Needed for | Notes |
|---|---|---|
| `ADMIN_PASSWORD` | Admin dashboard | Long random string. Without it the Admin page is locked. |
| `APP_BASE_URL` | Stripe redirects | Already set to `https://hhinvestigations.com` in `render.yaml`. Change if your domain differs. |
| `STRIPE_SECRET_KEY` | Paid upgrades | `sk_test_...` to rehearse, `sk_live_...` to go live. Until set, upgrades stay dormant. |
| `STRIPE_PRICE_PRO` | Pro checkout | `price_...` from §1. |
| `STRIPE_PRICE_DEEP` | Deep checkout | `price_...` from §1. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` | Intake emails **and password reset** | Without SMTP, password reset falls back to "contact support". Set on web **and** cron. |
| `NOTIFY_EMAIL` | Admin intake alerts | Where new "New Request" submissions are emailed. |
| `HIBP_API_KEY` | Deep tier (breach exposure) | Paid key from haveibeenpwned.com. The Deep plan's headline feature. Set on web **and** cron. |
| `OPENCORPORATES_API_KEY`, `NUMVERIFY_API_KEY`, `GITHUB_TOKEN`, `COURTLISTENER_TOKEN`, `SHODAN_API_KEY` | Pro-tier sources | Optional; each strengthens its source. Set on web **and** cron. |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | AI summaries | Optional, cheap. Ollama (local) is tried first and is free. |

---

## 4. Domain — point hhinvestigations.com at Render **(once)**

1. Render → the `hh-intake` web service → **Settings → Custom Domains → Add**.
   Add both `hhinvestigations.com` and `www.hhinvestigations.com`.
2. Render shows the DNS records to create. At your registrar:
   - Apex `hhinvestigations.com` → the `A` record (or `ALIAS`/`ANAME`) Render
     specifies.
   - `www` → `CNAME` to the Render hostname.
3. Wait for DNS to propagate; Render auto-issues the TLS certificate. The
   `CNAME` file in the repo is for GitHub Pages and does not affect Render.
4. Confirm `https://hhinvestigations.com` loads the app and the padlock is green.
5. Make sure `APP_BASE_URL` matches the final domain (no trailing slash) so the
   Stripe redirect lands back on your site.

---

## 5. Smoke test (test mode)

With `STRIPE_SECRET_KEY` = `sk_test_...`:

1. Visit the live URL → **Create account** → log in.
2. Open the consent gate on **Search**, accept, run a search with just a
   username (works with no API keys). Confirm results render.
3. **Account → Upgrade to Pro** → checkout with Stripe's test card
   `4242 4242 4242 4242`, any future expiry, any CVC. Complete payment.
4. You should land back on **Account** with plan = **Pro** and the Pro/Deep
   search depths unlocked.
5. **Manage billing** → cancel in the portal → reload Account → plan returns to
   **Recon**.
6. **Forgot password** (needs SMTP set) → request a link → follow the emailed
   link → set a new password → log in with it.

---

## 6. Go live

1. Stripe dashboard → flip to **Live mode**. Re-create the two products/prices
   (test and live objects are separate) and copy the **live** price IDs.
2. In Render, replace `STRIPE_SECRET_KEY` with `sk_live_...` and update
   `STRIPE_PRICE_PRO` / `STRIPE_PRICE_DEEP` with the live IDs.
3. Redeploy (Render does this automatically on env-var change).
4. Run one real low-value transaction end-to-end, then refund it from Stripe to
   confirm the live path works.

---

## 7. Before you take real money — owner checklist

- [ ] Have an attorney review `TERMS_MD` in `app.py` (it's a template; §9 says so).
- [ ] Confirm the placeholder prices on the Home page match your real Stripe prices.
- [ ] Set a real `NOTIFY_EMAIL` so you see intake submissions.
- [ ] Decide whether to keep the California / non-US block (`RESTRICTED_STATES`
      in `app.py`) — it's currently on, pending counsel review.
- [ ] Back up the Postgres database (Render → database → backups).

---

## Troubleshooting

- **"Paid upgrades aren't live yet"** on Account → `STRIPE_SECRET_KEY` isn't set
  on the web service.
- **"price not set"** on an upgrade button → that plan's `STRIPE_PRICE_*` is
  missing or doesn't match a price in the current Stripe mode (test vs live).
- **Checkout returns but plan didn't change** → `APP_BASE_URL` doesn't match the
  domain the user is on, so the `?session_id=` return hit the wrong host.
- **Password reset email never arrives** → SMTP isn't configured, or it's set on
  the web service but the link domain (`APP_BASE_URL`) is wrong.
- **Monitors never email** → SMTP and the source keys must be set on the **cron**
  service too, not only the web service.
