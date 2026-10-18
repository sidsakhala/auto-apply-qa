#!/usr/bin/env bash
# Start the Naukri job agent.
#   ./run.sh              search, tailor PDFs per JD, list openings (apply_jobs in config)
#   ./run.sh --apply      also tailor and apply for this run
#   ./run.sh --login      sign in once
#   ./run.sh --search     same as default when apply_jobs is false
#   ./run.sh --jobs       list stored jobs with URLs

set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/playwright install chromium
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [[ $# -eq 0 ]]; then
  set -- --run-now
fi

exec python main.py "$@"
