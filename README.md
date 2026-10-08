# job-radar

Personal job radar for remote / India full-stack and AI-automation roles.

Wave 1 harvests public ATS directories. Wave 2 **polls every board** through Geonode + Scrapling (`AsyncFetcher`, 5000 concurrency) and keeps only jobs the local profile can realistically win.

## What Wave 1 pulls

| Source | What we take |
| --- | --- |
| [LastRound ATS directory](https://github.com/fyrosofttech/lastroundai-hiring-data) (CC BY 4.0) | Confirmed `ats` + `board_slug` for ~10k companies |
| [ats-jobs-mcp](https://github.com/groundtruthtools/ats-jobs-mcp) | Recent job-count snapshot, merged onto the same slugs |
| [YC India](https://yc-oss.github.io/api/tags/india.json) + [YC hiring](https://yc-oss.github.io/api/companies/hiring.json) | India / remote / Chennai **hints**, plus YC-only rows when there is no ATS slug yet |

Service companies stay in. Wipro, HCLTech, Capgemini, and Accenture are also seeded as **Workday / SuccessFactors** boards in `data/enterprise_boards.json`.

## Run

```bash
cd job-radar
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python3 -m job_radar harvest
python3 -m job_radar harvest --refresh
python3 -m job_radar probe            # live first page of Workday + SuccessFactors
GEONODE_PROXY=host:port:user:pass python3 -m job_radar poll
python3 -m job_radar poll --resume
python3 -m job_radar poll --ats greenhouse --limit 20 --concurrency 50
python3 -m job_radar rank
python3 -m job_radar inbox
python3 -m job_radar inbox --limit 20
python3 -m job_radar enrich            # Wave 4: brief all pending survivors
python3 -m job_radar enrich --limit 40 # first-pass cap (used once for smoke)
python3 -m job_radar export --fit strong
python3 -m unittest discover -s tests -v
```

Wave 4 needs `OPENROUTER_API_KEY` in `job-radar/.env`. Default model is `openrouter/free`. One call per **new kept survivor** (target families, plus generic SDE only if score ≥ 40) — not per board, not the 3k+ low-score generic SDEs. Already-briefed rows are skipped.

Wave 2 aborts if `GEONODE_PROXY` / `SCRAPE_PROXY` is missing (no laptop-IP fallback). 404 boards become `dead`. Matching jobs land in `data/radar.sqlite`.

## Outputs

| File | Meaning |
| --- | --- |
| `data/candidates.jsonl` | Full unproven registry (almost every public GH/Lever/Ashby board) |
| `data/priority.jsonl` / `data/priority.csv` | Subset with a **YC or location India hint** — the interesting Wave 2 queue |
| `data/harvest_summary.json` | Counts |
| `data/probe_enterprise.json` | Live totals from Workday CXS and SuccessFactors CSB/RMK |
| `data/profile.json` | Local only (gitignored). Copy `data/profile.example.json` and fill in targets, stack, and salary floors |
| `data/radar.sqlite` | Company status + matching jobs after `poll` |
| `data/matches.jsonl` | Open matches from the latest poll |
| `data/poll_summary.json` | Active / watch / empty / dead / match counts |
| `data/inbox.jsonl` / `data/inbox.csv` | Wave 3 ranked matches (acceptance-weighted) |
| `data/rank_summary.json` | Family / geo mix after `rank` |
| `data/briefs.jsonl` | Wave 4 OpenRouter briefs on inbox survivors |

Workday: `POST {host}/wday/cxs/{tenant}/{site}/jobs` (page size 20).  
SuccessFactors: CSB JSON on Wipro/HCL, RMK HTML tiles on Capgemini.

`india_hint` on YC rows is profile text. Enterprise seed rows are marked India because those firms hire there; `probe` confirms live jobs.
