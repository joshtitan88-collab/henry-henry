#!/usr/bin/env python3
"""
OSINT Monitor CLI — re-runs saved monitors and emails on result changes.
"""

import json
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage

from sqlalchemy import create_engine, MetaData, Table, select, text

import osint_engine


def send_email(to_addr, subject, body):
    """Send an email. Return bool; never raise."""
    if not to_addr:
        return False

    smtp_host = os.environ.get("SMTP_HOST")
    if not smtp_host:
        return False

    try:
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_username = os.environ.get("SMTP_USERNAME")
        smtp_password = os.environ.get("SMTP_PASSWORD")
        smtp_from = os.environ.get("SMTP_FROM") or smtp_username or "no-reply@hhinvestigations.com"

        ctx = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(context=ctx)
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = to_addr
            msg.set_content(body)
            server.send_message(msg)

        return True
    except Exception:
        return False


def main():
    """Run all active monitors and email on changes."""
    db_url = os.environ.get("DATABASE_URL", "sqlite:///hhi_intake.db")

    # Normalize postgres:// to postgresql+psycopg2://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)

    # Configure engine based on driver
    engine_kwargs = {"pool_pre_ping": True}
    if "sqlite" in db_url:
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(db_url, **engine_kwargs)

    # Reflect the monitors table
    metadata = MetaData()
    try:
        monitors_table = Table("monitors", metadata, autoload_with=engine)
    except Exception:
        print("monitors table not found in database")
        return 0

    # Build config from env vars
    cfg = {k: os.environ.get(k) for k in osint_engine.required_keys()}

    print(f"[{datetime.now(timezone.utc).isoformat()}] Monitor run started")

    changed_count = 0
    baseline_count = 0
    no_change_count = 0
    error_count = 0

    # Read all active monitors
    with engine.connect() as conn:
        stmt = select(monitors_table).where(monitors_table.c.active == True)
        rows = conn.execute(stmt).mappings().fetchall()

    # Process each monitor
    for row in rows:
        try:
            label = row["label"]
            query_str = row["query"] or "{}"
            query = json.loads(query_str)
            notify_email = row["notify_email"]
            old_hash = row["last_hash"]

            # Run the search
            results = osint_engine.run_search(query, cfg, use_cache=False)
            fp = osint_engine.fingerprint(results)

            # Detect change
            is_baseline = not old_hash
            changed = bool(old_hash) and fp != old_hash

            # Build summary text
            summary_lines = [f"[{r.status}] {r.source}: {r.summary or r.error}" for r in results]
            summary_text = "\n".join(summary_lines)

            # Build compact summary for DB
            compact_summary = json.dumps([
                {"source": r.source, "status": r.status, "items": len(r.items or [])}
                for r in results
            ])

            # Update DB
            now_utc = datetime.now(timezone.utc)
            with engine.begin() as conn:
                conn.execute(
                    monitors_table.update()
                    .where(monitors_table.c.id == row["id"])
                    .values(
                        last_run=now_utc,
                        last_hash=fp,
                        last_summary=compact_summary
                    )
                )

            # Send email if changed
            if changed and notify_email:
                email_body = f"Query:\n{json.dumps(query, indent=2)}\n\nResults:\n{summary_text}"
                send_email(notify_email, f"[H&H Monitor] Change detected — {label}", email_body)

            # Log
            status = "CHANGED" if changed else ("baseline" if is_baseline else "no-change")
            print(f"[{now_utc.isoformat()}] {label}: {status}")

            if changed:
                changed_count += 1
            elif is_baseline:
                baseline_count += 1
            else:
                no_change_count += 1

        except Exception as e:
            print(f"[{datetime.now(timezone.utc).isoformat()}] {row['label']}: ERROR — {e}")
            error_count += 1

    total = changed_count + baseline_count + no_change_count + error_count
    print(f"[{datetime.now(timezone.utc).isoformat()}] Monitor run complete: "
          f"{total} total, {changed_count} changed, {baseline_count} baseline, "
          f"{no_change_count} no-change, {error_count} error")

    return 0


if __name__ == "__main__":
    exit(main())
