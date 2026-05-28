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
# Registry
# ---------------------------------------------------------------------------
SOURCES = [
    Source("username", "Username footprint", "Identity", ("username",), None, src_username),
    Source("github", "GitHub profile", "Identity", ("username",), None, src_github),
    Source("gravatar", "Gravatar", "Identity", ("email",), None, src_gravatar),
    Source("domain", "Domain WHOIS/RDAP", "Infrastructure", ("domain",), None, src_domain),
    Source("courtlistener", "Court records (CourtListener)", "Legal", ("name",), None, src_courtlistener),
    Source("hibp", "Breach exposure (HIBP)", "Exposure", ("email",), "HIBP_API_KEY", src_hibp),
    Source("opencorporates", "Company affiliations (OpenCorporates)", "Business", ("name",), "OPENCORPORATES_API_KEY", src_opencorporates),
    Source("phone", "Phone intel (numverify)", "Contact", ("phone",), "NUMVERIFY_API_KEY", src_phone),
]


def applicable_sources(query):
    """Sources that have at least one of their input fields present in the query."""
    out = []
    for s in SOURCES:
        if any(_q(query, f) for f in s.inputs):
            out.append(s)
    return out


def run_search(query, cfg, source_ids=None):
    """Run all applicable sources in parallel and return a list[Result]."""
    cfg = cfg or {}
    sources = applicable_sources(query)
    if source_ids is not None:
        sources = [s for s in sources if s.id in source_ids]
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
    return results
