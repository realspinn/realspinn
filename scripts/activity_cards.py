#!/usr/bin/env python3
"""Build the animated GitHub activity cards for the profile README.

Writes assets/activity-stats.svg and assets/activity-streak.svg from the
GitHub GraphQL API. Stars, commits, reviews, pull requests and issues count
public activity only; the streak card follows the public contribution
calendar. Needs a GITHUB_TOKEN environment variable (the Actions token is
enough). Standard library only.

    GITHUB_TOKEN=... python scripts/activity_cards.py realspinn
"""

import datetime as dt
import json
import math
import os
import sys
import urllib.request
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")

# Card geometry: a 420x200 card inside an 8px transparent margin, so the
# neon halo can spill past the card edge onto the page.
W, H, M, R = 420, 200, 8, 14
PERIM = 2 * (W - 2 * R) + 2 * (H - 2 * R) + 2 * math.pi * R
SANS = "'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "Consolas, 'SFMono-Regular', Menlo, monospace"


def gql(query, **variables):
    request = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": "bearer " + os.environ["GITHUB_TOKEN"],
            "User-Agent": "profile-activity-cards",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    if body.get("errors"):
        raise SystemExit("GitHub API error: " + str(body["errors"][0].get("message")))
    return body["data"]


STATS_QUERY = """
query($login: String!, $prs: String!, $merged: String!, $issues: String!) {
  user(login: $login) {
    createdAt
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      nodes { stargazerCount }
    }
    contributionsCollection {
      commitContributionsByRepository(maxRepositories: 100) {
        repository { isPrivate } contributions { totalCount }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: 100) {
        repository { isPrivate } contributions { totalCount }
      }
    }
  }
  prs: search(query: $prs, type: ISSUE) { issueCount }
  merged: search(query: $merged, type: ISSUE) { issueCount }
  issues: search(query: $issues, type: ISSUE) { issueCount }
}
"""

CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""


def public_total(by_repo):
    return sum(r["contributions"]["totalCount"] for r in by_repo if not r["repository"]["isPrivate"])


def fetch(login):
    data = gql(
        STATS_QUERY,
        login=login,
        prs=f"author:{login} is:pr is:public",
        merged=f"author:{login} is:pr is:merged is:public",
        issues=f"author:{login} is:issue is:public",
    )
    user = data["user"]
    cc = user["contributionsCollection"]
    stats = {
        "stars": sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        "commits": public_total(cc["commitContributionsByRepository"]),
        "prs": data["prs"]["issueCount"],
        "merged": data["merged"]["issueCount"],
        "reviews": public_total(cc["pullRequestReviewContributionsByRepository"]),
        "issues": data["issues"]["issueCount"],
    }

    # The calendar API returns at most one year per query.
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    created = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    days = {}
    for year in range(created.year, now.year + 1):
        start = max(created, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
        end = min(now, dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
        cal = gql(CALENDAR_QUERY, login=login, **{"from": start.isoformat(), "to": end.isoformat()})
        for week in cal["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                date = dt.date.fromisoformat(day["date"])
                if date <= now.date():
                    days[date] = day["contributionCount"]
    return stats, days, now.date()


def streaks(days, today):
    one = dt.timedelta(days=1)
    # Today does not break the streak until it is over.
    end = today if days.get(today, 0) else today - one
    cur_start = end
    while days.get(cur_start, 0):
        cur_start -= one
    cur_start += one
    current = (end - cur_start).days + 1 if days.get(end, 0) else 0

    best, best_range, run, run_start = 0, None, 0, None
    for date in sorted(days):
        if days[date]:
            run_start = date if run == 0 else run_start
            run += 1
            if run > best:
                best, best_range = run, (run_start, date)
        else:
            run = 0
    active = [d for d in sorted(days) if days[d]]
    return {
        "total": sum(days.values()),
        "first": active[0] if active else None,
        "current": current,
        "current_range": (cur_start, end) if current else None,
        "longest": best,
        "longest_range": best_range,
    }


def day_label(date, today):
    text = f"{date:%b} {date.day}"
    return text if date.year == today.year else f"{text}, {date.year}"


def range_label(span, today, empty):
    if not span:
        return empty
    a, b = span
    return day_label(a, today) if a == b else f"{day_label(a, today)} – {day_label(b, today)}"


STYLE = """
@keyframes orbit { from { stroke-dashoffset: PERIM } to { stroke-dashoffset: 0 } }
@keyframes breathe { 0%, 100% { opacity: .45 } 50% { opacity: 1 } }
@keyframes sweep { 0% { transform: translateX(-180px) } 40%, 100% { transform: translateX(640px) } }
@keyframes rise { from { opacity: 0; transform: translateY(8px) } }
@keyframes ping { from { transform: scale(1); opacity: .9 } to { transform: scale(2.8); opacity: 0 } }
@keyframes flicker { 0%, 100% { transform: scale(1, 1) } 30% { transform: scale(.94, 1.08) }
  55% { transform: scale(1.04, .96) } 80% { transform: scale(.97, 1.05) } }
@keyframes draw { from { stroke-dasharray: 0 RING } }
@keyframes pulse { 0%, 100% { opacity: .55 } 50% { opacity: 1 } }
.comet { animation: orbit 7s linear infinite }
.comet.late { animation-delay: -3.5s }
.breathe { animation: breathe 4.5s ease-in-out infinite }
.sweep { animation: sweep 7s ease-in-out 1.2s infinite both }
.rise { animation: rise .8s cubic-bezier(.2, .7, .2, 1) both }
.ping { transform-box: fill-box; transform-origin: center; animation: ping 1.8s ease-out infinite }
.flame { transform-box: fill-box; transform-origin: 50% 100%; animation: flicker 1.4s ease-in-out infinite }
.draw { animation: draw 1.6s cubic-bezier(.3, .7, .2, 1) .4s both }
.pulse { animation: pulse 3s ease-in-out infinite }
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important }
  .comet, .sweep, .ping { display: none }
}
"""


def card(title, desc, body, ring=0.0):
    x, y = M, M
    edge = (
        f"M{x + R} {y}H{x + W - R}A{R} {R} 0 0 1 {x + W} {y + R}V{y + H - R}"
        f"A{R} {R} 0 0 1 {x + W - R} {y + H}H{x + R}A{R} {R} 0 0 1 {x} {y + H - R}"
        f"V{y + R}A{R} {R} 0 0 1 {x + R} {y}Z"
    )
    dash = f"{PERIM * 0.08:.1f} {PERIM * 0.92:.1f}"
    style = STYLE.replace("PERIM", f"{PERIM:.1f}").replace("RING", f"{ring:.1f}")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W + 2 * M}" height="{H + 2 * M}" viewBox="0 0 {W + 2 * M} {H + 2 * M}" role="img" aria-labelledby="title desc">
  <title id="title">{escape(title)}</title>
  <desc id="desc">{escape(desc)}</desc>
  <style>{style}</style>
  <defs>
    <filter id="neon" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="2.6" result="blur"/>
      <feFlood flood-color="#ff3b5c" flood-opacity=".95"/>
      <feComposite in2="blur" operator="in" result="glow"/>
      <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="halo" x="-10%" y="-20%" width="120%" height="140%">
      <feGaussianBlur stdDeviation="4.5"/>
    </filter>
    <filter id="spark" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="2.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#1d0b12"/>
      <stop offset=".45" stop-color="#131316"/>
      <stop offset="1" stop-color="#141417"/>
    </linearGradient>
    <radialGradient id="bloom" cx="88%" cy="0%" r="80%">
      <stop offset="0" stop-color="#ff3b5c" stop-opacity=".38"/>
      <stop offset=".5" stop-color="#7a0d24" stop-opacity=".14"/>
      <stop offset="1" stop-color="#7a0d24" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="shine" x1="0" x2="1">
      <stop offset="0" stop-color="#fff" stop-opacity="0"/>
      <stop offset=".5" stop-color="#fff" stop-opacity=".08"/>
      <stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="fire" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0" stop-color="#ff3b5c"/>
      <stop offset=".55" stop-color="#ff7a45"/>
      <stop offset="1" stop-color="#ffd166"/>
    </linearGradient>
    <clipPath id="clip"><rect x="{x}" y="{y}" width="{W}" height="{H}" rx="{R}"/></clipPath>
  </defs>

  <path class="breathe" d="{edge}" fill="none" stroke="#ff3b5c" stroke-width="4" opacity=".7" filter="url(#halo)"/>
  <rect x="{x}" y="{y}" width="{W}" height="{H}" rx="{R}" fill="url(#bg)"/>
  <g clip-path="url(#clip)">
    <rect class="breathe" x="{x}" y="{y}" width="{W}" height="{H}" fill="url(#bloom)"/>
    <g transform="skewX(-20)"><rect class="sweep" x="0" y="{y}" width="120" height="{H}" fill="url(#shine)"/></g>
    <g transform="translate({x} {y})">
{body}
    </g>
  </g>
  <path d="{edge}" fill="none" stroke="#ff3b5c" stroke-opacity=".5" stroke-width="1"/>
  <g fill="none" stroke-linecap="round" stroke-dasharray="{dash}">
    <path class="comet" d="{edge}" stroke="#ff3b5c" stroke-width="4" filter="url(#spark)"/>
    <path class="comet" d="{edge}" stroke="#ffe1e7" stroke-width="1.4"/>
    <path class="comet late" d="{edge}" stroke="#ff3b5c" stroke-width="3" opacity=".6" filter="url(#spark)"/>
  </g>
</svg>
"""


def stats_card(s):
    tiles = [
        ("STARS EARNED", s["stars"]),
        ("COMMITS · 1Y", s["commits"]),
        ("PRS OPENED", s["prs"]),
        ("PRS MERGED", s["merged"]),
        ("REVIEWS · 1Y", s["reviews"]),
        ("ISSUES OPENED", s["issues"]),
    ]
    parts = [
        f'      <text x="22" y="38" font-family="{SANS}" font-size="17" font-weight="700" fill="#ff5c77" filter="url(#neon)">Public GitHub activity</text>',
        '      <circle cx="396" cy="32" r="4" fill="#ff3b5c" filter="url(#spark)"/>',
        '      <circle class="ping" cx="396" cy="32" r="4" fill="none" stroke="#ff3b5c" stroke-width="1.5"/>',
    ]
    for i, (label, value) in enumerate(tiles):
        tx, ty = 22 + (i % 3) * 128, 56 + (i // 3) * 68
        parts.append(
            f'      <g transform="translate({tx} {ty})"><g class="rise" style="animation-delay:{0.15 + i * 0.12:.2f}s">'
            f'<rect width="120" height="60" rx="9" fill="#fff" fill-opacity=".035" stroke="#ff3b5c" stroke-opacity=".25"/>'
            f'<text x="12" y="22" font-family="{MONO}" font-size="10" letter-spacing=".4" fill="#b5aeaa">{escape(label)}</text>'
            f'<text x="12" y="48" font-family="{SANS}" font-size="23" font-weight="700" fill="#fff" filter="url(#neon)">{value:,}</text>'
            f"</g></g>"
        )
    desc = (
        f"Public GitHub activity: {s['stars']:,} stars earned, {s['commits']:,} commits in the last year, "
        f"{s['prs']:,} pull requests opened, {s['merged']:,} merged, {s['reviews']:,} pull requests reviewed "
        f"in the last year, {s['issues']:,} issues opened."
    )
    return card("Public GitHub activity", desc, "\n".join(parts))


def streak_card(k, today):
    ring_r, cx, cy, gap = 38, 210, 82, 30
    circ = 2 * math.pi * ring_r
    arc = circ - gap
    # Rotate so the gap in the ring sits at the top, under the flame.
    rot = -90 + math.degrees(gap / ring_r) / 2
    since = f"Since {day_label(k['first'], dt.date(1, 1, 1))}" if k["first"] else "No contributions yet"
    current_range = range_label(k["current_range"], today, "No current streak")
    longest_range = range_label(k["longest_range"], today, "No streak yet")

    def side(x, value, label, sub, delay):
        return (
            f'      <g class="rise" style="animation-delay:{delay}s">'
            f'<text x="{x}" y="92" text-anchor="middle" font-family="{SANS}" font-size="27" font-weight="700" fill="#fff" filter="url(#neon)">{value:,}</text>'
            f'<text x="{x}" y="122" text-anchor="middle" font-family="{SANS}" font-size="13" font-weight="600" fill="#ff8a9e">{escape(label)}</text>'
            f'<text x="{x}" y="143" text-anchor="middle" font-family="{MONO}" font-size="10" fill="#a8a29e">{escape(sub)}</text></g>'
        )

    body = "\n".join([
        '      <g stroke="#ff3b5c" stroke-opacity=".22"><path d="M140 40V160M280 40V160"/></g>',
        side(70, k["total"], "Total contributions", since, 0.2),
        side(350, k["longest"], "Longest streak", longest_range, 0.45),
        f'      <circle cx="{cx}" cy="{cy}" r="{ring_r}" fill="none" stroke="#ff3b5c" stroke-opacity=".14" stroke-width="5"/>',
        f'      <circle class="draw" cx="{cx}" cy="{cy}" r="{ring_r}" fill="none" stroke="#ff3b5c" stroke-width="5" stroke-linecap="round" '
        f'stroke-dasharray="{arc:.1f} {circ:.1f}" transform="rotate({rot:.1f} {cx} {cy})" filter="url(#neon)"/>',
        f'      <circle class="pulse" cx="{cx}" cy="{cy}" r="{ring_r}" fill="none" stroke="#ff3b5c" stroke-width="9" stroke-opacity=".35" '
        f'stroke-dasharray="{arc:.1f} {circ:.1f}" transform="rotate({rot:.1f} {cx} {cy})" filter="url(#halo)"/>',
        f'      <g transform="translate({cx} {cy - ring_r - 1})"><g class="flame" filter="url(#spark)">'
        '<path d="M0-14C5-8 10-3 10 3C10 10 5 14 0 14C-5 14-10 10-10 3C-10-2-6-5-4-10C-3-5-1-4 1-6C2-8 1-11 0-14Z" fill="url(#fire)"/>'
        '<path d="M0-1C3 2 5 5 5 8C5 11 3 13 0 13C-3 13-5 11-5 8C-5 5-2 3 0-1Z" fill="#ffe08a"/></g></g>',
        f'      <g class="rise" style="animation-delay:.3s">'
        f'<text x="{cx}" y="{cy + 10}" text-anchor="middle" font-family="{SANS}" font-size="29" font-weight="700" fill="#fff" filter="url(#neon)">{k["current"]:,}</text>'
        f'<text x="{cx}" y="148" text-anchor="middle" font-family="{SANS}" font-size="14" font-weight="700" fill="#ff5c77" filter="url(#neon)">Current streak</text>'
        f'<text x="{cx}" y="168" text-anchor="middle" font-family="{MONO}" font-size="10" fill="#a8a29e">{escape(current_range)}</text></g>',
    ])
    desc = (
        f"Contribution streak: {k['total']:,} total contributions ({since[0].lower() + since[1:]}), "
        f"current streak {k['current']:,} days ({current_range}), longest streak {k['longest']:,} days ({longest_range})."
    )
    return card("Contribution streak", desc, body, ring=circ)


def main():
    login = sys.argv[1] if len(sys.argv) > 1 else "realspinn"
    stats, days, today = fetch(login)
    files = {
        "activity-stats.svg": stats_card(stats),
        "activity-streak.svg": streak_card(streaks(days, today), today),
    }
    for name, svg in files.items():
        with open(os.path.join(ASSETS, name), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(svg)
        print("wrote assets/" + name)


if __name__ == "__main__":
    main()
