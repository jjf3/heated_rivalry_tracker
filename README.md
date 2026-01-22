# Heated Rivalry Fandom Tracker

A lightweight Python project for measuring **active fandom engagement** on Reddit by tracking discussion behavior rather than subscriber counts.

This tool was built in response to recent changes in how Reddit exposes community metrics, which make traditional subscriber- and viewer-based tracking inconsistent or misleading for longitudinal analysis. Instead of focusing on membership totals, the tracker measures **comment growth over time** across episode discussion threads, trailers, and related posts.

---

## What This Project Does

- Searches **r/television** for posts related to *Heated Rivalry*
- Identifies and classifies posts into:
  - episode discussion threads (e.g. `1x01`, `S01E02`)
  - the official trailer thread
  - other high-engagement, non-episode posts
- Captures post-level metadata:
  - comment count
  - score (net upvotes)
  - creation timestamp
- Appends comment counts to a time-series dataset on each run
- Generates:
  - CSV exports for analysis
  - line graphs showing comment growth over time
  - a local HTML dashboard for review

The result is a reproducible way to observe how discussion evolves as episodes air—without relying on opaque or UI-derived audience metrics.

---

## Why Comments Instead of Subscribers

Reddit’s visible membership and “active user” numbers now vary by interface, context, and aggregation layer, making them unreliable for tracking growth over time.

Comments, by contrast:
- represent active participation
- accumulate gradually rather than instantaneously
- reflect both positive and negative engagement
- remain accessible via public endpoints

For fandom analysis, comment growth provides a clearer signal of **sustained interest and response** than subscriber totals alone.

---

## Project Structure

```
heated_rivalry_tracker/
├─ src/
│  ├─ heated_rivalry_tracker.py
│  └─ server_out.py
│
├─ data/
├─ out/
├─ logs/
├
│
├─ README.md
├─ requirements.txt
└─ .gitignore
```

---

## Requirements

- Python 3.11 or newer

Install dependencies with:

```
pip install -r requirements.txt
```

---

## How to Run

```
python src/heated_rivalry_tracker.py
```

To view the dashboard:

```
python src/server_out.py
```

Then open:

```
http://localhost:8010/dashboard_tv_heatedrivalry.html
```

---

## Notes on Data Use

- Uses only Reddit’s public JSON endpoints
- No API keys or authentication required
- Designed for infrequent polling (6–12 hours recommended)
- Comment trends emerge over repeated runs

---

Part of the **RewindOS** project — tracking cultural signals where traditional metrics fall short.
