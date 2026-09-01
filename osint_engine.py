"""Modular OSINT lookup engine for Henry & Henry.

Each source is an independent module that takes a query (name / username /
email / phone / domain) and returns a structured Result. Sources fail soft:
one source erroring never breaks the others. Sources that need an API key
report `no_key` until the key is provided via the app's secrets/env.

This module has no Streamlit dependency so it can be tested in isolation.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

TIMEOUT = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HH-Research/1.0; +https://hhinvestigations.com)"}


def _get(url, retries=2, backoff=0.6, **kwargs):
    """HTTP GET with self-healing: retry transient network errors and 5xx
    with exponential backoff. Raises the last error if all attempts fail."""
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("headers", HEADERS)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, **kwargs)
            if r.status_code >= 500:
                last_exc = requests.RequestException(f"server returned {r.status_code}")
            else:
                return r
        except requests.RequestException as e:
            last_exc = e
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))
    raise last_exc


@dataclass
class Result:
    source: str
    category: str
    status: str  # ok | not_found | error | no_key
    summary: str = ""
    items: list = field(default_factory=list)  # list[dict]
    detail: dict = field(default_factory=dict)
    error: str = ""
    latency_ms: int = 0


@dataclass
class Source:
    id: str
    label: str
    category: str
    inputs: tuple  # query fields this source can act on (any-of)
    key: Optional[str]  # config var required to enable, or None
    run: Callable  # (query: dict, cfg: dict) -> Result
    note: str = ""
    # If True, this source's findings (items) are stable enough that a change
    # should trip a monitor. False sources contribute only existence (status).
    track_items: bool = False


def _q(query, field_name):
    return (query.get(field_name) or "").strip()


# ---------------------------------------------------------------------------
# Source: username footprint (no key)
# ---------------------------------------------------------------------------
# Curated to sites whose 200/404 status is a reliable existence signal.
USERNAME_SITES = {
    "GitHub": "https://github.com/{u}",
    "GitLab": "https://gitlab.com/{u}",
    "Reddit": "https://www.reddit.com/user/{u}",
    "Keybase": "https://keybase.io/{u}",
    "Telegram": "https://t.me/{u}",
    "Steam": "https://steamcommunity.com/id/{u}",
    "Patreon": "https://www.patreon.com/{u}",
    "SoundCloud": "https://soundcloud.com/{u}",
    "Medium": "https://medium.com/@{u}",
    "Pastebin": "https://pastebin.com/u/{u}",
    "Replit": "https://replit.com/@{u}",
    "HackerNews": "https://news.ycombinator.com/user?id={u}",
}


def _check_site(name, url):
    try:
        r = _get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            return {"site": name, "url": url}
    except requests.RequestException:
        return None
    return None


def src_username(query, cfg):
    user = _q(query, "username")
    if not user:
        return Result("Username footprint", "Identity", "not_found", "No username provided.")
    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futures = [
            ex.submit(_check_site, name, tmpl.format(u=user))
            for name, tmpl in USERNAME_SITES.items()
        ]
        for f in concurrent.futures.as_completed(futures):
            hit = f.result()
            if hit:
                found.append(hit)
    found.sort(key=lambda x: x["site"])
    if not found:
        return Result("Username footprint", "Identity", "not_found",
                      f"No candidate profiles found for '{user}'.")
    return Result(
        "Username footprint", "Identity", "ok",
        f"{len(found)} candidate profile(s) for '{user}' — verify each manually.",
        items=found,
    )


# ---------------------------------------------------------------------------
# Source: GitHub profile (no key; optional GITHUB_TOKEN raises rate limit)
# ---------------------------------------------------------------------------
def src_github(query, cfg):
    user = _q(query, "username")
    if not user:
        return Result("GitHub profile", "Identity", "not_found", "No username provided.")
    headers = dict(HEADERS)
    if cfg.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {cfg['GITHUB_TOKEN']}"
    try:
        r = _get(f"https://api.github.com/users/{user}", headers=headers, timeout=TIMEOUT)
        if r.status_code == 404:
            return Result("GitHub profile", "Identity", "not_found", f"No GitHub user '{user}'.")
        if r.status_code == 403 and not cfg.get("GITHUB_TOKEN"):
            return Result("GitHub profile", "Identity", "no_key",
                          "GitHub rate-limits anonymous requests; set GITHUB_TOKEN to enable.")
        if r.status_code != 200:
            return Result("GitHub profile", "Identity", "error",
                          error=f"GitHub API returned {r.status_code}")
        d = r.json()
        detail = {
            "name": d.get("name"),
            "company": d.get("company"),
            "location": d.get("location"),
            "bio": d.get("bio"),
            "public_repos": d.get("public_repos"),
            "followers": d.get("followers"),
            "created_at": d.get("created_at"),
            "blog": d.get("blog"),
            "url": d.get("html_url"),
        }
        return Result("GitHub profile", "Identity", "ok",
                      f"GitHub user '{user}' — {d.get('public_repos', 0)} repos, "
                      f"{d.get('followers', 0)} followers.", detail=detail)
    except requests.RequestException as e:
        return Result("GitHub profile", "Identity", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: Gravatar (no key) — email -> public profile / avatar
# ---------------------------------------------------------------------------
def src_gravatar(query, cfg):
    email = _q(query, "email").lower()
    if not email:
        return Result("Gravatar", "Identity", "not_found", "No email provided.")
    h = hashlib.md5(email.encode()).hexdigest()
    try:
        r = _get(f"https://www.gravatar.com/{h}.json", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return Result("Gravatar", "Identity", "not_found",
                          f"No public Gravatar for {email}.")
        entry = (r.json().get("entry") or [{}])[0]
        accounts = [a.get("url") for a in entry.get("accounts", []) if a.get("url")]
        detail = {
            "display_name": entry.get("displayName"),
            "location": entry.get("currentLocation"),
            "about": entry.get("aboutMe"),
            "avatar": f"https://www.gravatar.com/avatar/{h}",
            "profile_url": entry.get("profileUrl"),
            "linked_accounts": accounts,
        }
        return Result("Gravatar", "Identity", "ok",
                      f"Public Gravatar profile found for {email}.", detail=detail)
    except (requests.RequestException, ValueError) as e:
        return Result("Gravatar", "Identity", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: domain RDAP / WHOIS (no key)
# ---------------------------------------------------------------------------
def src_domain(query, cfg):
    domain = _q(query, "domain").lower().replace("https://", "").replace("http://", "").strip("/")
    if not domain:
        return Result("Domain WHOIS/RDAP", "Infrastructure", "not_found", "No domain provided.")
    try:
        r = _get(f"https://rdap.org/domain/{domain}", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return Result("Domain WHOIS/RDAP", "Infrastructure", "not_found",
                          f"No RDAP record for {domain}.")
        d = r.json()
        events = {e.get("eventAction"): e.get("eventDate") for e in d.get("events", [])}
        registrar = None
        for ent in d.get("entities", []):
            if "registrar" in (ent.get("roles") or []):
                vcard = ent.get("vcardArray", [None, []])[1]
                for item in vcard:
                    if item[0] == "fn":
                        registrar = item[3]
        nameservers = [ns.get("ldhName") for ns in d.get("nameservers", [])]
        detail = {
            "domain": d.get("ldhName", domain),
            "registrar": registrar,
            "registered": events.get("registration"),
            "expires": events.get("expiration"),
            "last_changed": events.get("last changed"),
            "status": d.get("status"),
            "nameservers": nameservers,
        }
        return Result("Domain WHOIS/RDAP", "Infrastructure", "ok",
                      f"Registration record for {domain}"
                      + (f" via {registrar}." if registrar else "."), detail=detail)
    except (requests.RequestException, ValueError) as e:
        return Result("Domain WHOIS/RDAP", "Infrastructure", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: DNS records via Google DoH (no key)
# ---------------------------------------------------------------------------
def src_dns(query, cfg):
    domain = _q(query, "domain").lower().replace("https://", "").replace("http://", "").strip("/")
    if not domain:
        return Result("DNS records", "Infrastructure", "not_found", "No domain provided.")
    records = {}
    try:
        for rtype in ("A", "AAAA", "MX", "NS", "TXT"):
            r = _get("https://dns.google/resolve", params={"name": domain, "type": rtype})
            answers = r.json().get("Answer", []) if r.status_code == 200 else []
            vals = [a.get("data") for a in answers if a.get("data")]
            if vals:
                records[rtype] = vals
    except (requests.RequestException, ValueError) as e:
        return Result("DNS records", "Infrastructure", "error", error=str(e))
    if not records:
        return Result("DNS records", "Infrastructure", "not_found", f"No DNS records for {domain}.")
    detail = {k: ", ".join(v[:6]) for k, v in records.items()}
    return Result("DNS records", "Infrastructure", "ok",
                  f"{sum(len(v) for v in records.values())} DNS record(s) for {domain}.", detail=detail)


# ---------------------------------------------------------------------------
# Source: certificate-transparency subdomains via crt.sh (no key)
# ---------------------------------------------------------------------------
def src_crtsh(query, cfg):
    domain = _q(query, "domain").lower().replace("https://", "").replace("http://", "").strip("/")
    if not domain:
        return Result("Subdomains (crt.sh)", "Infrastructure", "not_found", "No domain provided.")
    try:
        r = _get("https://crt.sh/", params={"q": f"%.{domain}", "output": "json"})
        if r.status_code != 200:
            return Result("Subdomains (crt.sh)", "Infrastructure", "error",
                          error=f"crt.sh returned {r.status_code}")
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        return Result("Subdomains (crt.sh)", "Infrastructure", "error", error=str(e))
    subs = set()
    for entry in data:
        for n in (entry.get("name_value") or "").split("\n"):
            n = n.strip().lstrip("*.")
            if n.endswith(domain):
                subs.add(n)
    subs = sorted(subs)
    if not subs:
        return Result("Subdomains (crt.sh)", "Infrastructure", "not_found",
                      f"No certificate-transparency records for {domain}.")
    return Result("Subdomains (crt.sh)", "Infrastructure", "ok",
                  f"{len(subs)} subdomain(s) seen in CT logs for {domain}.",
                  items=[{"subdomain": s} for s in subs[:60]])


# ---------------------------------------------------------------------------
# Source: Reddit user (no key)
# ---------------------------------------------------------------------------
def src_reddit(query, cfg):
    user = _q(query, "username")
    if not user:
        return Result("Reddit profile", "Identity", "not_found", "No username provided.")
    try:
        r = _get(f"https://www.reddit.com/user/{user}/about.json")
        if r.status_code == 404:
            return Result("Reddit profile", "Identity", "not_found", f"No Reddit user '{user}'.")
        if r.status_code == 403:
            return Result("Reddit profile", "Identity", "error",
                          error="Reddit rate-limited this host.")
        if r.status_code != 200:
            return Result("Reddit profile", "Identity", "error",
                          error=f"Reddit returned {r.status_code}")
        d = r.json().get("data", {})
        import datetime as _dt
        created = d.get("created_utc")
        detail = {
            "link_karma": d.get("link_karma"),
            "comment_karma": d.get("comment_karma"),
            "created": _dt.datetime.utcfromtimestamp(created).date().isoformat() if created else None,
            "verified": d.get("verified"),
            "url": f"https://www.reddit.com/user/{user}",
        }
        return Result("Reddit profile", "Identity", "ok",
                      f"Reddit user '{user}' — {d.get('comment_karma', 0)} comment karma.", detail=detail)
    except (requests.RequestException, ValueError) as e:
        return Result("Reddit profile", "Identity", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: Hacker News user (no key)
# ---------------------------------------------------------------------------
def src_hackernews(query, cfg):
    user = _q(query, "username")
    if not user:
        return Result("Hacker News profile", "Identity", "not_found", "No username provided.")
    try:
        r = _get(f"https://hacker-news.firebaseio.com/v0/user/{user}.json")
        if r.status_code != 200 or r.json() is None:
            return Result("Hacker News profile", "Identity", "not_found", f"No HN user '{user}'.")
        d = r.json()
        import datetime as _dt
        created = d.get("created")
        detail = {
            "karma": d.get("karma"),
            "created": _dt.datetime.utcfromtimestamp(created).date().isoformat() if created else None,
            "submissions": len(d.get("submitted", [])),
            "about": d.get("about"),
            "url": f"https://news.ycombinator.com/user?id={user}",
        }
        return Result("Hacker News profile", "Identity", "ok",
                      f"HN user '{user}' — {d.get('karma', 0)} karma.", detail=detail)
    except (requests.RequestException, ValueError) as e:
        return Result("Hacker News profile", "Identity", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: CourtListener (no key required; COURTLISTENER_TOKEN raises limits)
# ---------------------------------------------------------------------------
def src_courtlistener(query, cfg):
    name = _q(query, "name")
    if not name:
        return Result("Court records (CourtListener)", "Legal", "not_found", "No name provided.")
    headers = dict(HEADERS)
    if cfg.get("COURTLISTENER_TOKEN"):
        headers["Authorization"] = f"Token {cfg['COURTLISTENER_TOKEN']}"
    try:
        r = _get(
            "https://www.courtlistener.com/api/rest/v4/search/",
            params={"q": name, "type": "o", "order_by": "dateFiled desc"},
            headers=headers, timeout=TIMEOUT,
        )
        if r.status_code in (401, 403):
            return Result("Court records (CourtListener)", "Legal", "no_key",
                          "CourtListener requires a free API token for this query.")
        if r.status_code != 200:
            return Result("Court records (CourtListener)", "Legal", "error",
                          error=f"CourtListener returned {r.status_code}")
        results = r.json().get("results", [])[:8]
        items = [{
            "case": it.get("caseName"),
            "court": it.get("court"),
            "date": it.get("dateFiled"),
            "url": "https://www.courtlistener.com" + (it.get("absolute_url") or ""),
        } for it in results]
        if not items:
            return Result("Court records (CourtListener)", "Legal", "not_found",
                          f"No court opinions matching '{name}'.")
        return Result("Court records (CourtListener)", "Legal", "ok",
                      f"{len(items)} court opinion(s) matching '{name}'.", items=items)
    except (requests.RequestException, ValueError) as e:
        return Result("Court records (CourtListener)", "Legal", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: HaveIBeenPwned breaches (needs HIBP_API_KEY)
# ---------------------------------------------------------------------------
def src_hibp(query, cfg):
    email = _q(query, "email")
    if not email:
        return Result("Breach exposure (HIBP)", "Exposure", "not_found", "No email provided.")
    key = cfg.get("HIBP_API_KEY")
    if not key:
        return Result("Breach exposure (HIBP)", "Exposure", "no_key",
                      "Set HIBP_API_KEY to enable breach lookups.")
    headers = dict(HEADERS)
    headers["hibp-api-key"] = key
    try:
        r = _get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
            params={"truncateResponse": "false"}, headers=headers, timeout=TIMEOUT,
        )
        if r.status_code == 404:
            return Result("Breach exposure (HIBP)", "Exposure", "not_found",
                          f"No known breaches for {email}.")
        if r.status_code != 200:
            return Result("Breach exposure (HIBP)", "Exposure", "error",
                          error=f"HIBP returned {r.status_code}")
        breaches = r.json()
        items = [{
            "name": b.get("Name"),
            "date": b.get("BreachDate"),
            "data": ", ".join(b.get("DataClasses", [])),
        } for b in breaches]
        return Result("Breach exposure (HIBP)", "Exposure", "ok",
                      f"{len(items)} breach(es) found for {email}.", items=items)
    except (requests.RequestException, ValueError) as e:
        return Result("Breach exposure (HIBP)", "Exposure", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: OpenCorporates (needs OPENCORPORATES_API_KEY)
# ---------------------------------------------------------------------------
def src_opencorporates(query, cfg):
    name = _q(query, "name")
    if not name:
        return Result("Company affiliations (OpenCorporates)", "Business", "not_found",
                      "No name provided.")
    key = cfg.get("OPENCORPORATES_API_KEY")
    if not key:
        return Result("Company affiliations (OpenCorporates)", "Business", "no_key",
                      "Set OPENCORPORATES_API_KEY to enable officer/company lookups.")
    try:
        r = _get(
            "https://api.opencorporates.com/v0.4/officers/search",
            params={"q": name, "api_token": key}, headers=HEADERS, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return Result("Company affiliations (OpenCorporates)", "Business", "error",
                          error=f"OpenCorporates returned {r.status_code}")
        officers = r.json().get("results", {}).get("officers", [])[:10]
        items = [{
            "name": o["officer"].get("name"),
            "position": o["officer"].get("position"),
            "company": (o["officer"].get("company") or {}).get("name"),
            "jurisdiction": o["officer"].get("jurisdiction_code"),
        } for o in officers if o.get("officer")]
        if not items:
            return Result("Company affiliations (OpenCorporates)", "Business", "not_found",
                          f"No officer records for '{name}'.")
        return Result("Company affiliations (OpenCorporates)", "Business", "ok",
                      f"{len(items)} officer record(s) for '{name}'.", items=items)
    except (requests.RequestException, ValueError) as e:
        return Result("Company affiliations (OpenCorporates)", "Business", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: phone validation (needs NUMVERIFY_API_KEY)
# ---------------------------------------------------------------------------
def src_phone(query, cfg):
    phone = re.sub(r"[^\d+]", "", _q(query, "phone"))
    if not phone:
        return Result("Phone intel (numverify)", "Contact", "not_found", "No phone provided.")
    key = cfg.get("NUMVERIFY_API_KEY")
    if not key:
        return Result("Phone intel (numverify)", "Contact", "no_key",
                      "Set NUMVERIFY_API_KEY to enable phone lookups.")
    try:
        r = _get(
            "https://apilayer.net/api/validate",
            params={"access_key": key, "number": phone}, headers=HEADERS, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return Result("Phone intel (numverify)", "Contact", "error",
                          error=f"numverify returned {r.status_code}")
        d = r.json()
        if not d.get("valid"):
            return Result("Phone intel (numverify)", "Contact", "not_found",
                          f"{phone} is not a valid number.")
        detail = {
            "international": d.get("international_format"),
            "country": d.get("country_name"),
            "location": d.get("location"),
            "carrier": d.get("carrier"),
            "line_type": d.get("line_type"),
        }
        return Result("Phone intel (numverify)", "Contact", "ok",
                      f"{d.get('international_format')} — {d.get('carrier') or 'unknown carrier'} "
                      f"({d.get('line_type') or 'unknown'}).", detail=detail)
    except (requests.RequestException, ValueError) as e:
        return Result("Phone intel (numverify)", "Contact", "error", error=str(e))


# ---------------------------------------------------------------------------
# Source: email deliverability / MX (no key)
# ---------------------------------------------------------------------------
def src_email_mx(query, cfg):
    email = _q(query, "email")
    if not email or "@" not in email:
        return Result("Email deliverability", "Contact", "not_found", "No valid email provided.")
    domain = email.rsplit("@", 1)[-1].lower()
    try:
        r = _get("https://dns.google/resolve", params={"name": domain, "type": "MX"})
        answers = r.json().get("Answer", []) if r.status_code == 200 else []
        mx = [a.get("data") for a in answers if a.get("data")]
    except (requests.RequestException, ValueError) as e:
        return Result("Email deliverability", "Contact", "error", error=str(e))
    if not mx:
        return Result("Email deliverability", "Contact", "not_found",
                      f"{domain} has no MX records — it cannot receive mail.")
    return Result("Email deliverability", "Contact", "ok",
                  f"{domain} accepts mail ({len(mx)} MX host(s)).",
                  detail={"domain": domain, "accepts_mail": True, "mx_hosts": [m.strip() for m in mx[:5]]})


# ---------------------------------------------------------------------------
# Source: Wayback Machine (no key)
# ---------------------------------------------------------------------------
def src_wayback(query, cfg):
    domain = _q(query, "domain").lower().replace("https://", "").replace("http://", "").strip("/")
    if not domain:
        return Result("Wayback Machine", "Infrastructure", "not_found", "No domain provided.")
    try:
        r = _get("https://archive.org/wayback/available", params={"url": domain})
        snap = (r.json().get("archived_snapshots") or {}).get("closest") if r.status_code == 200 else None
    except (requests.RequestException, ValueError) as e:
        return Result("Wayback Machine", "Infrastructure", "error", error=str(e))
    if not snap:
        return Result("Wayback Machine", "Infrastructure", "not_found",
                      f"No Wayback snapshots for {domain}.")
    ts = snap.get("timestamp", "")
    pretty = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else ts
    return Result("Wayback Machine", "Infrastructure", "ok",
                  f"{domain} archived — closest snapshot {pretty}.",
                  detail={"snapshot": pretty, "url": snap.get("url")})


# ---------------------------------------------------------------------------
# Source: Shodan host (needs SHODAN_API_KEY) — resolves domain -> IP -> host info
# ---------------------------------------------------------------------------
def src_shodan(query, cfg):
    domain = _q(query, "domain").lower().replace("https://", "").replace("http://", "").strip("/")
    if not domain:
        return Result("Shodan host", "Infrastructure", "not_found", "No domain provided.")
    key = cfg.get("SHODAN_API_KEY")
    if not key:
        return Result("Shodan host", "Infrastructure", "no_key",
                      "Set SHODAN_API_KEY to enable host/port intelligence.")
    try:
        rd = _get("https://dns.google/resolve", params={"name": domain, "type": "A"})
        ips = [a.get("data") for a in rd.json().get("Answer", []) if a.get("type") == 1]
        if not ips:
            return Result("Shodan host", "Infrastructure", "not_found", f"Could not resolve {domain}.")
        ip = ips[0]
        r = _get(f"https://api.shodan.io/shodan/host/{ip}", params={"key": key})
        if r.status_code == 404:
            return Result("Shodan host", "Infrastructure", "not_found", f"No Shodan data for {ip}.")
        if r.status_code == 401:
            return Result("Shodan host", "Infrastructure", "error", error="Invalid SHODAN_API_KEY.")
        if r.status_code != 200:
            return Result("Shodan host", "Infrastructure", "error", error=f"Shodan returned {r.status_code}")
        d = r.json()
        detail = {
            "ip": ip,
            "org": d.get("org"),
            "os": d.get("os"),
            "ports": d.get("ports"),
            "hostnames": d.get("hostnames"),
        }
        return Result("Shodan host", "Infrastructure", "ok",
                      f"{ip} — {len(d.get('ports', []))} open port(s)"
                      + (f", {d.get('org')}" if d.get("org") else "") + ".", detail=detail)
    except (requests.RequestException, ValueError) as e:
        return Result("Shodan host", "Infrastructure", "error", error=str(e))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
SOURCES = [
    Source("username", "Username footprint", "Identity", ("username",), None, src_username),
    Source("github", "GitHub profile", "Identity", ("username",), None, src_github),
    Source("reddit", "Reddit profile", "Identity", ("username",), None, src_reddit),
    Source("hackernews", "Hacker News profile", "Identity", ("username",), None, src_hackernews),
    Source("gravatar", "Gravatar", "Identity", ("email",), None, src_gravatar),
    Source("email_mx", "Email deliverability", "Contact", ("email",), None, src_email_mx),
    Source("domain", "Domain WHOIS/RDAP", "Infrastructure", ("domain",), None, src_domain),
    Source("dns", "DNS records", "Infrastructure", ("domain",), None, src_dns),
    Source("crtsh", "Subdomains (crt.sh)", "Infrastructure", ("domain",), None, src_crtsh, track_items=True),
    Source("wayback", "Wayback Machine", "Infrastructure", ("domain",), None, src_wayback),
    Source("shodan", "Shodan host", "Infrastructure", ("domain",), "SHODAN_API_KEY", src_shodan),
    Source("courtlistener", "Court records (CourtListener)", "Legal", ("name",), None, src_courtlistener, track_items=True),
    Source("hibp", "Breach exposure (HIBP)", "Exposure", ("email",), "HIBP_API_KEY", src_hibp, track_items=True),
    Source("opencorporates", "Company affiliations (OpenCorporates)", "Business", ("name",), "OPENCORPORATES_API_KEY", src_opencorporates, track_items=True),
    Source("phone", "Phone intel (numverify)", "Contact", ("phone",), "NUMVERIFY_API_KEY", src_phone),
]


def applicable_sources(query):
    """Sources that have at least one of their input fields present in the query."""
    out = []
    for s in SOURCES:
        if any(_q(query, f) for f in s.inputs):
            out.append(s)
    return out


def required_keys():
    """Config var names used by key-gated sources."""
    return sorted({s.key for s in SOURCES if s.key})


# Detail fields that legitimately change every run and must not trip a monitor.
_VOLATILE_DETAIL = {"snapshot", "url", "last_changed", "expires"}


def _norm_val(v):
    """Order-insensitive normalization so list/CSV ordering doesn't trip a monitor."""
    if isinstance(v, (list, tuple)):
        return sorted(str(x) for x in v)
    s = str(v)
    if "," in s:
        return sorted(p.strip() for p in s.split(","))
    return s


def fingerprint(results):
    """Stable hash of the *meaningful findings* in a result set, for monitors.

    Rules that keep alerts signal-not-noise:
    - Only `ok`/`not_found` sources count, so a flaky source or missing key
      (`error`/`no_key`) never fires a false alert.
    - Every counted source contributes its existence (status).
    - Only `track_items` sources (subdomains, court records, breaches, company
      officers) contribute their findings (items) — volatile sources like DNS
      A-records and username presence-checks contribute existence only."""
    track = {s.label: s.track_items for s in SOURCES}
    norm = []
    for r in sorted(results, key=lambda r: r.source):
        if r.status not in ("ok", "not_found"):
            continue
        entry = {"source": r.source, "status": r.status}
        if track.get(r.source):
            entry["items"] = sorted(
                json.dumps({k: _norm_val(v) for k, v in sorted(it.items())}, sort_keys=True)
                for it in (r.items or [])
            )
        norm.append(entry)
    return hashlib.sha256(json.dumps(norm, sort_keys=True).encode()).hexdigest()


CACHE_TTL = 600  # seconds
_CACHE = {}  # key -> (timestamp, results)


def _cache_key(query, sources, cfg):
    # Key on the normalized query plus which sources ran and whether each had
    # its key — so adding a key (or a different query) misses the stale entry.
    q = "|".join(f"{k}={_q(query, k)}" for k in sorted(query))
    s = ",".join(f"{src.id}:{int(bool(cfg.get(src.key)))}" for src in sources)
    return q + "||" + s


def run_search(query, cfg, source_ids=None, use_cache=True):
    """Run all applicable sources in parallel and return a list[Result].

    Results are cached in-process for CACHE_TTL seconds to cut cost/latency on
    repeat queries; pass use_cache=False for always-fresh runs (e.g. monitors).
    """
    cfg = cfg or {}
    sources = applicable_sources(query)
    if source_ids is not None:
        sources = [s for s in sources if s.id in source_ids]

    key = _cache_key(query, sources, cfg)
    if use_cache:
        hit = _CACHE.get(key)
        if hit and (time.monotonic() - hit[0]) < CACHE_TTL:
            return hit[1]

    def _timed(s):
        t0 = time.monotonic()
        try:
            r = s.run(query, cfg)
        except Exception as e:  # noqa: BLE001 — fail soft per source
            r = Result(s.label, s.category, "error", error=str(e))
        r.latency_ms = int((time.monotonic() - t0) * 1000)
        return r

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(_timed, sources):
            results.append(r)
    order = {s.label: i for i, s in enumerate(SOURCES)}
    results.sort(key=lambda r: order.get(r.source, 99))

    if use_cache:
        _CACHE[key] = (time.monotonic(), results)
    return results
