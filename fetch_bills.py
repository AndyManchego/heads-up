"""
Heads Up: daily federal bill updater.

1. Asks Congress.gov for bills with activity in the last few days.
2. Keeps only bills that are actually moving (passed a chamber, sent to the
   President, or became law).
3. Summarizes each new or changed bill with Claude.
4. Saves everything to Supabase so the website can show it.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html import unescape

import anthropic
import requests

CONGRESS_API_KEY = os.environ["CONGRESS_API_KEY"].strip()
SUPABASE_URL = os.environ["SUPABASE_URL"].strip().rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"].strip()
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "2"))
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
MAX_SUMMARIES = int(os.environ.get("MAX_SUMMARIES", "40"))   # cost safety cap per run
MAX_TEXT_CHARS = 120_000                                     # very long bills get trimmed

API = "https://api.congress.gov/v3"
BILL_TYPES = {"HR", "S", "HJRES", "SJRES"}   # real bills; skips simple/concurrent resolutions

# Order matters: the first match wins, most advanced stage first.
STAGES = [
    ("Became law",          r"became public law|signed by president"),
    ("Sent to President",   r"presented to president"),
    ("Vetoed",              r"vetoed"),
    ("Passed Senate",       r"passed senate|passed/agreed to in senate|received in the house"),
    ("Passed House",        r"passed house|passed/agreed to in house|received in the senate"),
    ("Scheduled for vote",  r"placed on the union calendar|placed on the house calendar|placed on senate legislative calendar"),
]

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
sb_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


# ---------- Congress.gov ----------

def congress_get(path, **params):
    params.update(api_key=CONGRESS_API_KEY, format="json")
    for attempt in range(4):
        r = requests.get(f"{API}{path}", params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def recent_bills():
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=LOOKBACK_DAYS)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    bills, offset = [], 0
    while True:
        data = congress_get("/bill", fromDateTime=start.strftime(fmt), toDateTime=now.strftime(fmt),
                            sort="updateDate desc", limit=250, offset=offset)
        page = data.get("bills", [])
        bills.extend(page)
        if len(page) < 250:
            return bills
        offset += 250


def stage_for(action_text):
    t = (action_text or "").lower()
    for name, pattern in STAGES:
        if re.search(pattern, t):
            return name
    return None


def latest_text(congress, btype, number):
    """Returns (version_name, plain_text) for the newest text version, or (None, None)."""
    data = congress_get(f"/bill/{congress}/{btype.lower()}/{number}/text")
    versions = data.get("textVersions", [])
    if not versions:
        return None, None
    versions.sort(key=lambda v: v.get("date") or "", reverse=True)
    v = versions[0]
    url = next((f["url"] for f in v.get("formats", []) if f.get("type") == "Formatted Text"), None)
    if not url:
        return v.get("type"), None
    html = requests.get(url, timeout=60).text
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return f"{v.get('type')} ({v.get('date', '')[:10]})", text


# ---------- Supabase ----------

def existing_row(bill_id):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/bills", headers=sb_headers,
                     params={"id": f"eq.{bill_id}", "select": "text_version,summary"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def save(row):
    h = dict(sb_headers, Prefer="resolution=merge-duplicates")
    r = requests.post(f"{SUPABASE_URL}/rest/v1/bills", headers=h, data=json.dumps(row), timeout=30)
    if r.status_code >= 300:
        print("  Supabase error:", r.status_code, r.text[:300])


# ---------- Claude ----------

PROMPT = """You summarize U.S. federal legislation for ordinary voters. Be strictly neutral and accurate.
Use only the bill text below; never invent facts. If something isn't in the text, say "Not stated in the bill."

Bill: {label}
Official title: {title}
Latest action: {action}

Return ONLY a JSON object (no markdown, no backticks) with these keys:
- "plain_title": short plain-English title, under 12 words, describing what it does
- "one_line": one sentence a busy person can understand
- "what_changes": array of 2-5 short plain-English bullets
- "who_affected": array of 1-4 short bullets
- "money": one or two sentences on costs, fees, or funding, or "Not stated in the bill."
- "timing": when it takes effect, in plain words
- "supporters_say": array of 1-3 arguments supporters would plausibly make, written fairly
- "opponents_say": array of 1-3 arguments opponents would plausibly make, written fairly
- "receipts": array of 2-3 objects {{"section": "Sec. 2(a)", "quote": exact excerpt under 25 words}}
- "topics": array of 1-3 from: Taxes, Cars & transportation, Small business, Housing, Health care, Guns, Education, Energy & environment, Immigration, Defense & veterans, Tech & privacy, Agriculture, Labor & jobs, Criminal justice, Government operations, Foreign affairs, Other
- "caveats": one sentence on anything unclear or that depends on other laws

BILL TEXT:
{text}"""


def summarize(label, title, action, text):
    msg = claude.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": PROMPT.format(
            label=label, title=title, action=action, text=text[:MAX_TEXT_CHARS])}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
    return json.loads(raw)


# ---------- Main ----------

def main():
    bills = recent_bills()
    print(f"{len(bills)} bills had activity in the last {LOOKBACK_DAYS} day(s).")
    summarized = 0

    for b in bills:
        btype = (b.get("type") or "").upper()
        if btype not in BILL_TYPES:
            continue
        action = (b.get("latestAction") or {}).get("text", "")
        stage = stage_for(action)
        if not stage:
            continue   # not moving yet

        congress, number = b["congress"], b["number"]
        bill_id = f"{congress}-{btype.lower()}-{number}"
        label = f"{btype} {number}"
        print(f"{label}: {stage}")

        row = {
            "id": bill_id,
            "congress": congress,
            "bill_type": btype,
            "number": str(number),
            "title": b.get("title"),
            "stage": stage,
            "latest_action": action,
            "latest_action_date": (b.get("latestAction") or {}).get("actionDate"),
            "congress_url": f"https://www.congress.gov/bill/{congress}th-congress/"
                            f"{'house' if btype.startswith('H') else 'senate'}-"
                            f"{'bill' if btype in ('HR', 'S') else 'joint-resolution'}/{number}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            version, text = latest_text(congress, btype, number)
            prev = existing_row(bill_id)
            needs_summary = text and (not prev or prev.get("text_version") != version or not prev.get("summary"))

            if needs_summary and summarized < MAX_SUMMARIES:
                row["summary"] = summarize(label, b.get("title"), action, text)
                row["text_version"] = version
                summarized += 1
                print("  summarized")
            elif not text:
                print("  no text published yet; saving status only")
        except Exception as e:   # one bad bill shouldn't stop the run
            print(f"  skipped summary: {e}")

        save(row)

    print(f"Done. Wrote {summarized} new summaries.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Run failed:", e)
        sys.exit(1)
