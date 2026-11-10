#!/usr/bin/env python3
"""Refresh the self-hosted stat cards and the Pinned table.

Stdlib only. Reads GH_TOKEN (optional but recommended) and OWNER from the
environment. Writes assets/stats/*.svg and rewrites the block between the
PINNED markers in README.md. Idempotent: unchanged output means no git diff.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
OWNER = os.environ.get("OWNER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "moneytosms"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

THEMES = {
    "dark": dict(bg="#18181b", bar="#27272a", line="#3f3f46", text="#e4e4e7",
                 dim="#a1a1aa", green="#22c55e", cyan="#0891b2", track="#27272a"),
    "light": dict(bg="#fafafa", bar="#e4e4e7", line="#d4d4d8", text="#18181b",
                  dim="#52525b", green="#16a34a", cyan="#0e7490", track="#e4e4e7"),
}
MONO = "SFMono-Regular,Consolas,Menlo,monospace"
LANG_COLORS = ["#22c55e", "#0891b2", "#a78bfa", "#f59e0b", "#f472b6", "#94a3b8"]


def api(path, accept="application/vnd.github+json"):
    req = urllib.request.Request("https://api.github.com" + path)
    req.add_header("Accept", accept)
    req.add_header("User-Agent", "profile-readme-updater")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def safe(fn, default):
    try:
        return fn()
    except (urllib.error.URLError, KeyError, ValueError) as e:
        print(f"warn: {e}", file=sys.stderr)
        return default


def all_repos():
    out, page = [], 1
    while True:
        chunk = api(f"/users/{OWNER}/repos?per_page=100&type=owner&page={page}")
        out += chunk
        if len(chunk) < 100:
            return out
        page += 1


def collect():
    repos = [r for r in all_repos() if not r["fork"]]
    user = api(f"/users/{OWNER}")
    langs = {}
    for r in repos:
        data = safe(lambda: api(f"/repos/{OWNER}/{r['name']}/languages"), {})
        for k, v in data.items():
            langs[k] = langs.get(k, 0) + v
    prs = safe(lambda: api(f"/search/issues?q=author:{OWNER}+type:pr&per_page=1")["total_count"], None)
    commits = safe(lambda: api(f"/search/commits?q=author:{OWNER}&per_page=1")["total_count"], None)
    return dict(
        stars=sum(r["stargazers_count"] for r in repos),
        repos=user["public_repos"],
        followers=user["followers"],
        prs=prs,
        commits=commits,
        langs=sorted(langs.items(), key=lambda kv: -kv[1]),
    )


def frame(t, title, body, h):
    return (
        f'<svg width="495" height="{h}" viewBox="0 0 495 {h}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{escape(title)}">'
        f'<defs><clipPath id="r"><rect width="495" height="{h}" rx="10"/></clipPath></defs>'
        f'<g clip-path="url(#r)"><rect width="495" height="{h}" fill="{t["bg"]}"/>'
        f'<rect width="495" height="30" fill="{t["bar"]}"/>'
        '<circle cx="16" cy="15" r="5" fill="#f87171"/><circle cx="34" cy="15" r="5" fill="#fbbf24"/>'
        '<circle cx="52" cy="15" r="5" fill="#34d399"/>'
        f'<text x="247" y="19" text-anchor="middle" font-family="{MONO}" font-size="12" fill="{t["dim"]}">{escape(title)}</text>'
        f'<g font-family="{MONO}" font-size="14">{body}</g></g>'
        f'<rect x="0.5" y="0.5" width="494" height="{h-1}" rx="10" fill="none" stroke="{t["line"]}"/></svg>\n'
    )


def stats_svg(t, s):
    rows = [("stars earned", s["stars"]), ("public repos", s["repos"]),
            ("followers", s["followers"]), ("pull requests", s["prs"]),
            ("commits (public)", s["commits"])]
    body = f'<text x="24" y="58" fill="{t["cyan"]}" font-weight="bold">$ stats --user {escape(OWNER)}</text>'
    for i, (k, v) in enumerate(rows):
        y = 88 + i * 26
        val = "n/a" if v is None else f"{v:,}"
        body += (f'<text x="24" y="{y}" fill="{t["green"]}">{k}</text>'
                 f'<text x="471" y="{y}" text-anchor="end" fill="{t["text"]}">{val}</text>')
    return frame(t, f"{OWNER}@github: stats", body, 230)


def langs_svg(t, s):
    top = s["langs"][:6]
    total = sum(v for _, v in s["langs"]) or 1
    body = f'<text x="24" y="58" fill="{t["cyan"]}" font-weight="bold">$ langs --top {len(top)}</text>'
    for i, (name, v) in enumerate(top):
        y = 88 + i * 22
        pct = 100 * v / total
        width = max(2, 190 * v / top[0][1])
        c = LANG_COLORS[i % len(LANG_COLORS)]
        body += (f'<text x="24" y="{y}" fill="{t["text"]}">{escape(name)}</text>'
                 f'<rect x="170" y="{y-10}" width="190" height="10" rx="3" fill="{t["track"]}"/>'
                 f'<rect x="170" y="{y-10}" width="{width:.0f}" height="10" rx="3" fill="{c}"/>'
                 f'<text x="471" y="{y}" text-anchor="end" fill="{t["dim"]}">{pct:.1f}%</text>')
    return frame(t, f"{OWNER}@github: languages", body, 230)


def write_if_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")


def pinned_html(cfg):
    cols = cfg.get("columns", 3)
    width = f"{100 // cols}%"
    cells = []
    for item in cfg["repos"]:
        stars = safe(lambda: api(f"/repos/{OWNER}/{item['name']}")["stargazers_count"], 0)
        star = f" ★{stars}" if stars else ""
        extra = ""
        if item.get("link"):
            extra = f" [{item['link']['label']}]({item['link']['url']})."
        cells.append(
            f'<td width="{width}" valign="top">\n\n'
            f'**[{item["title"]}](https://github.com/{OWNER}/{item["name"]})**{star}\n'
            f'{item["pitch"]}{extra}\n\n</td>'
        )
    rows = ["<tr>\n" + "\n".join(cells[i:i + cols]) + "\n</tr>" for i in range(0, len(cells), cols)]
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def update_readme(cfg):
    p = ROOT / "README.md"
    text = p.read_text()
    block = f"<!-- PINNED:START -->\n{pinned_html(cfg)}\n<!-- PINNED:END -->"
    new, n = re.subn(r"<!-- PINNED:START -->.*?<!-- PINNED:END -->", lambda _: block, text, flags=re.S)
    if n != 1:
        sys.exit("README.md is missing the PINNED markers")
    write_if_changed(p, new)


def main():
    cfg = json.loads((ROOT / ".github" / "pinned.json").read_text())
    stats = collect()
    out = ROOT / "assets" / "stats"
    out.mkdir(parents=True, exist_ok=True)
    for name, t in THEMES.items():
        write_if_changed(out / f"stats-{name}.svg", stats_svg(t, stats))
        write_if_changed(out / f"langs-{name}.svg", langs_svg(t, stats))
    update_readme(cfg)


if __name__ == "__main__":
    main()
