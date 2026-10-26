#!/usr/bin/env python3
"""
Watch a Patreon creator's membership tiers and report when a limited tier has free slots.

Usage:
    python3 patreon_tier_watch.py                      # list all tiers once
    python3 patreon_tier_watch.py --match merchant     # exit 0 if a matching tier has slots, 3 if not, 1 on error
    python3 patreon_tier_watch.py --match merchant --loop 900 --ntfy https://ntfy.sh/your-topic

Patreon exposes each tier ("reward") through its public JSON:API. For limited tiers,
`user_limit` is the cap and `remaining` is the number of open slots (0 = sold out).
Unlimited tiers have `user_limit` = null.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

VANITY = "highlands_miniatures"
DEBUG = False
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def campaign_id(vanity):
    # 1) Try the API vanity filter.
    try:
        q = urllib.parse.urlencode({"filter[vanity]": vanity, "json-api-version": "1.0"})
        data = json.loads(get(f"https://www.patreon.com/api/campaigns?{q}"))
        if data.get("data"):
            return data["data"][0]["id"]
    except Exception:
        pass
    # 2) Fall back to scraping the creator page for the campaign id.
    html = get(f"https://www.patreon.com/{vanity}", accept="text/html")
    for pat in (r'"campaign"\s*:\s*\{\s*"data"\s*:\s*\{\s*"id"\s*:\s*"(\d+)"',
                r'/api/campaigns/(\d+)',
                r'patreon-media/p/campaign/(\d+)'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    raise SystemExit("Could not find campaign id; open the page, DevTools > Network, "
                     "filter on 'campaigns/' and pass it with --campaign-id.")


def tiers(cid):
    # No sparse fieldset: request every public reward attribute.
    q = urllib.parse.urlencode({"include": "rewards", "json-api-version": "1.0"})
    data = json.loads(get(f"https://www.patreon.com/api/campaigns/{cid}?{q}"))
    out = []
    for inc in data.get("included", []):
        if inc.get("type") != "reward":
            continue
        a = dict(inc["attributes"], id=inc.get("id"))
        if not a.get("title") or a.get("published") is False:
            continue
        out.append(a)
    return out


def describe(a):
    price = (a.get("amount_cents") or 0) / 100
    limit, rem = a.get("user_limit"), a.get("remaining")
    if "user_limit" not in a and "remaining" not in a:
        status = "limit fields not returned"
    else:
        status = "unlimited" if limit is None else (
            "SOLD OUT" if rem == 0 else f"{rem} of {limit} available")
    return f"{a['title']:<40} {price:>8.2f} {a.get('currency') or ''}  {status}"


def check(cid, match):
    ts = tiers(cid)
    hits = []
    for a in ts:
        line = describe(a)
        print(line)
        if DEBUG and match and match.lower() in a["title"].lower():
            raw = {k: v for k, v in a.items() if k not in ("description",)}
            print("  raw:", json.dumps(raw, sort_keys=True))
        if match and match.lower() in a["title"].lower() and a.get("remaining"):
            hits.append(line)
    return hits


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vanity", default=VANITY)
    p.add_argument("--campaign-id", default="4091047")  # Highlands Miniatures
    p.add_argument("--match", help="substring of tier title to watch, e.g. 'merchant'")
    p.add_argument("--loop", type=int, help="poll every N seconds")
    p.add_argument("--ntfy", help="ntfy.sh topic URL to push a notification to")
    p.add_argument("--debug", action="store_true", help="print raw attributes of matched tiers")
    args = p.parse_args()
    global DEBUG
    DEBUG = args.debug

    cid = args.campaign_id or campaign_id(args.vanity)
    print(f"campaign id: {cid}\n")

    while True:
        hits = check(cid, args.match)
        if hits:
            msg = "Tier available:\n" + "\n".join(hits)
            print("\n" + msg)
            if args.ntfy:
                urllib.request.urlopen(urllib.request.Request(
                    args.ntfy, data=msg.encode(), headers={"Title": "Patreon tier open"}))
            if not args.loop:
                sys.exit(0)
            return
        if not args.loop:
            sys.exit(3 if args.match else 0)  # 3 = nothing open; 1 = error (uncaught exception)
        print(f"\n{time.strftime('%H:%M:%S')} nothing open, sleeping {args.loop}s\n")
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
