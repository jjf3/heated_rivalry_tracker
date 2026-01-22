import csv
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

import requests

# -----------------------------
# Config
# -----------------------------
SUBREDDIT = os.environ.get("SUBREDDIT", "television").strip()
QUERY = os.environ.get("QUERY", "Heated Rivalry").strip()

LIMIT = int(os.environ.get("LIMIT", "100"))          # search results to pull
OTHER_POSTS_N = int(os.environ.get("OTHER_N", "5"))  # 3-5 recommended
SORT = os.environ.get("SORT", "new")                 # new | top | relevance
TIME_FILTER = os.environ.get("T", "all")             # all | year | month | week | day

USER_AGENT = os.environ.get(
    "USER_AGENT",
    "RewindOS-SubTracker/1.0 (personal project; respectful polling)"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(BASE_DIR, "out")
LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "tv_tracker.log")

ALL_POSTS_CSV = os.path.join(OUT_DIR, "television_heatedrivalry_all_posts.csv")
EPISODE_POSTS_CSV = os.path.join(OUT_DIR, "television_heatedrivalry_episode_posts.csv")
SELECTED_POSTS_CSV = os.path.join(OUT_DIR, "television_heatedrivalry_selected_posts.csv")
COMMENT_HISTORY_CSV = os.path.join(DATA_DIR, "television_heatedrivalry_comment_history.csv")

EPISODE_PLOT_PNG = os.path.join(OUT_DIR, "episode_comment_growth.png")
NON_EPISODE_PLOT_PNG = os.path.join(OUT_DIR, "non_episode_comment_growth.png")

DASHBOARD_HTML = os.path.join(OUT_DIR, "dashboard_tv_heatedrivalry.html")

SEARCH_URL = f"https://www.reddit.com/r/{SUBREDDIT}/search.json"

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

# -----------------------------
# Episode parsing
# -----------------------------
EP_PATTERNS = [
    # 1x01, 1X02, 10x3 (normalize)
    re.compile(r"\b(\d{1,2})\s*[xX]\s*(\d{1,2})\b"),
    # S01E01, s1e2
    re.compile(r"\b[Ss](\d{1,2})\s*[Ee](\d{1,2})\b"),
]

def extract_episode_code(title: str) -> Optional[str]:
    for pat in EP_PATTERNS:
        m = pat.search(title)
        if m:
            season = int(m.group(1))
            ep = int(m.group(2))
            return f"{season}x{ep:02d}"
    return None

def is_official_trailer(title: str) -> bool:
    t = title.lower()
    # keep it simple; you can tighten if needed
    return ("trailer" in t) and ("official" in t) and ("heated rivalry" in t)

# -----------------------------
# Data model
# -----------------------------
@dataclass
class Post:
    id: str
    name: str
    created_utc: int
    created_iso: str
    title: str
    permalink: str
    url: str
    author: str
    score: int
    num_comments: int
    episode_code: Optional[str]
    is_trailer: bool

# -----------------------------
# HTTP helpers
# -----------------------------
def request_json(session: requests.Session, url: str, params: dict, max_retries: int = 5) -> dict:
    # polite backoff for 429 / transient failures
    for attempt in range(1, max_retries + 1):
        r = session.get(url, params=params, timeout=30, allow_redirects=True)
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else min(60, 2 ** attempt)
            logging.warning(f"HTTP 429 rate-limited. Waiting {wait}s (attempt {attempt}/{max_retries})...")
            time.sleep(wait)
            continue

        if 500 <= r.status_code < 600:
            wait = min(60, 2 ** attempt)
            logging.warning(f"HTTP {r.status_code}. Waiting {wait}s (attempt {attempt}/{max_retries})...")
            time.sleep(wait)
            continue

        r.raise_for_status()

        ct = (r.headers.get("Content-Type") or "").lower()
        if "json" not in ct:
            raise ValueError(f"Expected JSON but got Content-Type={ct}. Final URL: {r.url}")

        return r.json()

    raise RuntimeError("Failed after retries (rate-limited or server errors).")

# -----------------------------
# Reddit fetch
# -----------------------------
def fetch_search_posts() -> List[Post]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })

    params = {
        "q": QUERY,
        "restrict_sr": 1,
        "sort": SORT,
        "t": TIME_FILTER,
        "limit": LIMIT,
        "raw_json": 1,
    }

    logging.info(f"Searching r/{SUBREDDIT} for '{QUERY}' (limit={LIMIT}, sort={SORT}, t={TIME_FILTER})")
    data = request_json(session, SEARCH_URL, params=params)

    children = (data.get("data") or {}).get("children") or []
    posts: List[Post] = []

    for ch in children:
        d = ch.get("data") or {}
        pid = d.get("id")
        if not pid:
            continue

        created_utc = safe_int(d.get("created_utc"), 0)
        created_iso = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat() if created_utc else ""

        title = d.get("title") or ""
        ep = extract_episode_code(title)
        trailer = is_official_trailer(title)

        posts.append(Post(
            id=pid,
            name=d.get("name") or f"t3_{pid}",
            created_utc=created_utc,
            created_iso=created_iso,
            title=title,
            permalink="https://www.reddit.com" + (d.get("permalink") or ""),
            url=d.get("url") or "",
            author=d.get("author") or "",
            score=safe_int(d.get("score"), 0),
            num_comments=safe_int(d.get("num_comments"), 0),
            episode_code=ep,
            is_trailer=trailer,
        ))

    logging.info(f"Found {len(posts)} posts")
    return posts

# -----------------------------
# CSV writers
# -----------------------------
def write_csv(path: str, rows: List[dict], fieldnames: List[str]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def ensure_history_header(path: str):
    if os.path.exists(path):
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "snapshot_utc", "post_id", "post_name", "episode_code", "is_episode",
            "is_trailer", "title", "permalink", "num_comments"
        ])
        w.writeheader()

def append_history(snapshot_utc: str, posts: List[Post]):
    ensure_history_header(COMMENT_HISTORY_CSV)
    with open(COMMENT_HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "snapshot_utc", "post_id", "post_name", "episode_code", "is_episode",
            "is_trailer", "title", "permalink", "num_comments"
        ])
        for p in posts:
            w.writerow({
                "snapshot_utc": snapshot_utc,
                "post_id": p.id,
                "post_name": p.name,
                "episode_code": p.episode_code or "",
                "is_episode": 1 if p.episode_code else 0,
                "is_trailer": 1 if p.is_trailer else 0,
                "title": p.title,
                "permalink": p.permalink,
                "num_comments": p.num_comments,
            })

# -----------------------------
# Selection logic
# -----------------------------
def pick_trailer(posts: List[Post]) -> Optional[Post]:
    trailers = [p for p in posts if p.is_trailer]
    if not trailers:
        return None
    # pick highest-comment trailer
    return sorted(trailers, key=lambda p: p.num_comments, reverse=True)[0]

def pick_other_posts(posts: List[Post], n: int) -> List[Post]:
    # exclude episode threads; exclude trailer
    candidates = [p for p in posts if not p.episode_code and not p.is_trailer]
    # pick by comment count, then score as tiebreaker
    candidates = sorted(candidates, key=lambda p: (p.num_comments, p.score), reverse=True)
    return candidates[:n]

def episode_posts(posts: List[Post]) -> List[Post]:
    eps = [p for p in posts if p.episode_code]
    # sort by episode then date
    eps.sort(key=lambda p: (p.episode_code, p.created_utc))
    return eps

# -----------------------------
# Plotting (matplotlib)
# -----------------------------
def make_plots():
    import matplotlib.pyplot as plt

    if not os.path.exists(COMMENT_HISTORY_CSV):
        logging.warning("No comment history yet; skipping plots. Run script multiple times over days to build history.")
        return

    # Load history
    history_rows = []
    with open(COMMENT_HISTORY_CSV, "r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            history_rows.append(row)

    def parse_dt(s: str):
        # isoformat with timezone
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    # group by post_name
    by_post: Dict[str, List[Tuple[datetime, int, dict]]] = {}
    for row in history_rows:
        dt = parse_dt(row["snapshot_utc"])
        if not dt:
            continue
        post_name = row["post_name"]
        num_comments = safe_int(row["num_comments"], 0)
        by_post.setdefault(post_name, []).append((dt, num_comments, row))

    # sort each series by time
    for k in list(by_post.keys()):
        by_post[k].sort(key=lambda x: x[0])

    # Episode plot: one line per episode post (post_name)
    plt.figure()
    plotted_any = False
    for post_name, series in by_post.items():
        # determine if episode
        is_episode = series[0][2].get("is_episode") == "1"
        if not is_episode:
            continue
        x = [t for (t, _, __) in series]
        y = [c for (_, c, __) in series]
        label = series[0][2].get("episode_code") or post_name
        plt.plot(x, y, label=label)
        plotted_any = True

    if plotted_any:
        plt.title("Episode discussion comment counts over time")
        plt.xlabel("Snapshot time (UTC)")
        plt.ylabel("Comments")
        plt.xticks(rotation=30, ha="right")
        plt.tight_layout()
        plt.legend(loc="best", fontsize=8)
        plt.savefig(EPISODE_PLOT_PNG, dpi=150)
        plt.close()
        logging.info(f"Wrote plot: {EPISODE_PLOT_PNG}")
    else:
        plt.close()

    # Non-episode plot: exclude episode discussions
    plt.figure()
    plotted_any = False
    for post_name, series in by_post.items():
        is_episode = series[0][2].get("is_episode") == "1"
        if is_episode:
            continue
        x = [t for (t, _, __) in series]
        y = [c for (_, c, __) in series]
        # shorter label
        title = (series[0][2].get("title") or "")[:40].strip()
        label = title + ("…" if len(series[0][2].get("title") or "") > 40 else "")
        plt.plot(x, y, label=label)
        plotted_any = True

    if plotted_any:
        plt.title("Non-episode Heated Rivalry posts: comment counts over time")
        plt.xlabel("Snapshot time (UTC)")
        plt.ylabel("Comments")
        plt.xticks(rotation=30, ha="right")
        plt.tight_layout()
        # legend can get messy; keep it small
        plt.legend(loc="best", fontsize=7)
        plt.savefig(NON_EPISODE_PLOT_PNG, dpi=150)
        plt.close()
        logging.info(f"Wrote plot: {NON_EPISODE_PLOT_PNG}")
    else:
        plt.close()

# -----------------------------
# HTML dashboard
# -----------------------------
def write_dashboard_html(all_posts: List[Post], eps: List[Post], trailer: Optional[Post], others: List[Post]):
    def row_for(p: Post) -> str:
        ep = p.episode_code or ""
        kind = "Episode" if p.episode_code else ("Trailer" if p.is_trailer else "Other")
        return f"""
        <tr>
          <td>{kind}</td>
          <td>{ep}</td>
          <td><a href="{p.permalink}" target="_blank" rel="noopener">{p.title}</a></td>
          <td style="text-align:right">{p.num_comments}</td>
          <td style="text-align:right">{p.score}</td>
          <td>{p.created_iso}</td>
        </tr>
        """

    trailer_html = ""
    if trailer:
        trailer_html = f"""
        <h2>Official Trailer (best match)</h2>
        <table>
          <thead><tr><th>Title</th><th>Comments</th><th>Score</th><th>Created (UTC)</th></tr></thead>
          <tbody>
            <tr>
              <td><a href="{trailer.permalink}" target="_blank" rel="noopener">{trailer.title}</a></td>
              <td style="text-align:right">{trailer.num_comments}</td>
              <td style="text-align:right">{trailer.score}</td>
              <td>{trailer.created_iso}</td>
            </tr>
          </tbody>
        </table>
        """

    others_rows = "\n".join(row_for(p) for p in others)

    eps_rows = "\n".join(row_for(p) for p in eps)

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>RewindOS: r/television Heated Rivalry tracker</title>
  <style>
    body {{ font-family: system-ui, Arial, sans-serif; margin: 24px; }}
    .muted {{ color: #666; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f6f6f6; text-align: left; }}
    img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 10px; padding: 6px; }}
    code {{ background: #f6f6f6; padding: 2px 6px; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>r/{SUBREDDIT}: Heated Rivalry tracking</h1>
  <p class="muted">
    Query: <code>{QUERY}</code> · Generated: <code>{utc_now_iso()}</code><br/>
    Data source: Reddit public JSON search endpoint (no OAuth key).
  </p>

  {trailer_html}

  <h2>Episode discussion threads detected</h2>
  <table>
    <thead>
      <tr><th>Type</th><th>Episode</th><th>Title</th><th>Comments</th><th>Score</th><th>Created (UTC)</th></tr>
    </thead>
    <tbody>
      {eps_rows if eps_rows else "<tr><td colspan='6' class='muted'>No episode threads detected by title pattern.</td></tr>"}
    </tbody>
  </table>

  <h2>Other notable posts (top by comments)</h2>
  <table>
    <thead>
      <tr><th>Type</th><th>Episode</th><th>Title</th><th>Comments</th><th>Score</th><th>Created (UTC)</th></tr>
    </thead>
    <tbody>
      {others_rows if others_rows else "<tr><td colspan='6' class='muted'>No additional posts selected.</td></tr>"}
    </tbody>
  </table>

  <h2>Comment growth over time</h2>
  <p class="muted">
    These plots require multiple snapshots. Re-run the script daily/hourly (Task Scheduler) to build <code>comment_history.csv</code>.
  </p>

  <h3>Episode discussions</h3>
  <img src="episode_comment_growth.png" alt="Episode discussion growth plot" onerror="this.style.display='none'"/>

  <h3>Non-episode posts</h3>
  <img src="non_episode_comment_growth.png" alt="Non-episode growth plot" onerror="this.style.display='none'"/>

  <h2>Outputs</h2>
  <ul>
    <li><code>{os.path.basename(ALL_POSTS_CSV)}</code></li>
    <li><code>{os.path.basename(EPISODE_POSTS_CSV)}</code></li>
    <li><code>{os.path.basename(SELECTED_POSTS_CSV)}</code></li>
    <li><code>comment_history.csv</code> (in /data; appended each run)</li>
  </ul>
</body>
</html>
"""
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    logging.info(f"Wrote dashboard HTML: {DASHBOARD_HTML}")

# -----------------------------
# Main
# -----------------------------
def main():
    snapshot = utc_now_iso()
    try:
        posts = fetch_search_posts()

        # Write all posts CSV
        all_rows = [{
            "id": p.id,
            "created_utc": p.created_utc,
            "created_iso": p.created_iso,
            "title": p.title,
            "episode_code": p.episode_code or "",
            "is_trailer": 1 if p.is_trailer else 0,
            "num_comments": p.num_comments,
            "score": p.score,
            "author": p.author,
            "permalink": p.permalink,
            "url": p.url,
        } for p in posts]

        write_csv(ALL_POSTS_CSV, all_rows, list(all_rows[0].keys()) if all_rows else
                  ["id","created_utc","created_iso","title","episode_code","is_trailer","num_comments","score","author","permalink","url"])

        eps = episode_posts(posts)
        eps_rows = [{
            "episode_code": p.episode_code,
            "id": p.id,
            "created_iso": p.created_iso,
            "title": p.title,
            "num_comments": p.num_comments,
            "score": p.score,
            "permalink": p.permalink,
        } for p in eps]
        write_csv(EPISODE_POSTS_CSV, eps_rows, ["episode_code","id","created_iso","title","num_comments","score","permalink"])

        trailer = pick_trailer(posts)
        others = pick_other_posts(posts, OTHER_POSTS_N)

        selected = []
        if trailer:
            selected.append(trailer)
        selected.extend(others)

        sel_rows = [{
            "type": ("Trailer" if p.is_trailer else ("Episode" if p.episode_code else "Other")),
            "episode_code": p.episode_code or "",
            "id": p.id,
            "created_iso": p.created_iso,
            "title": p.title,
            "num_comments": p.num_comments,
            "score": p.score,
            "permalink": p.permalink,
        } for p in selected]
        write_csv(SELECTED_POSTS_CSV, sel_rows, ["type","episode_code","id","created_iso","title","num_comments","score","permalink"])

        # Append history snapshot for time series plots
        append_history(snapshot, posts)

        # Build plots from history
        make_plots()

        # Write HTML dashboard
        write_dashboard_html(posts, eps, trailer, others)

        logging.info("Done.")

    except Exception as e:
        logging.exception("FAILED run")
        # Fail non-zero so schedulers know it failed
        raise

if __name__ == "__main__":
    main()
