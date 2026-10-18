# Naukri QA / Automation Test Engineer Agent

Independent fork of the [auto-apply](../auto-apply) workflow, configured for **Automation / QA / SDET** roles and **2–8 years** experience. Does not modify the AI engineer project.

## What it does

Same pipeline as auto-apply:

1. Naukri login + optional daily profile resume upload  
2. **Profile-based jobs** (recommended / homepage)  
3. **Keyword search** (Automation Test Engineer, QA Automation, SDET, etc. × Pune, Hyderabad, Bangalore)  
4. **Freshness:** last **1 day** (`search.freshness_days: 1` → `?jobAge=1`)  
5. **Experience pre-filter** on cards (2–8 year band)  
6. **Match scoring** (role, skills, experience, salary, location)  
7. **Deduplication** + SQLite storage  
8. **Tailored PDF/DOCX** per qualified job (when Overleaf/resume is configured)  
9. **Reports:** `reports/YYYY-MM-DD/openings_latest.txt` with URLs and scores  

Default: **`apply_jobs: false`** — list and tailor only.

## Setup

```bash
cd /home/ss2303/Desktop/auto-apply-qa
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
./run.sh --login
```

Use a **separate** `.env` and `data/browser_profile/` from the AI project (already under this folder).

## Commands

```bash
./run.sh              # search, score, tailor, list openings
./run.sh --apply      # also submit applications (if enabled)
./run.sh --jobs       # stored jobs with URLs
./run.sh --dashboard
```

## QA-specific configuration

| Setting | Value |
|---------|--------|
| Experience band | **2–8 years** (`candidate_profile.yaml`) |
| Job freshness | **1 day** |
| Title gate | Automation / QA / SDET titles only |
| Primary searches | Automation Test Engineer, QA Automation Engineer, SDET, Software Test Engineer |

Edit `config/candidate_profile.yaml` for CTC, cities, and `target_roles`.

## Architecture (shared with auto-apply)

| Area | Path |
|------|------|
| Search + profile jobs | `src/browser/job_search.py`, `src/browser/naukri.py` |
| QA titles & JD signals | `src/jobs/relevance.py` |
| Experience 2–8 | `src/jobs/experience.py` |
| Scoring / qualify | `src/jobs/matcher.py` |
| Pipeline | `src/pipeline/runner.py` |
| Reports | `src/reporting/report.py` |

## Tests

```bash
pytest
```

## Relation to auto-apply

- **Path:** `/home/ss2303/Desktop/auto-apply-qa`  
- **Original:** `/home/ss2303/Desktop/auto-apply` (unchanged)  
- Separate `data/jobs.db`, reports, and browser profile recommended.
