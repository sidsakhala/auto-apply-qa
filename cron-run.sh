#!/usr/bin/env bash
# Hourly entry point. Attaches to the logged-in desktop so Chromium can open.
# A missing login skips this hour. A later login does not replay it.

set -euo pipefail

cd "$(dirname "$0")"

uid="$(id -u)"
export XDG_RUNTIME_DIR="/run/user/${uid}"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"

if [[ ! -S "${XDG_RUNTIME_DIR}/bus" ]]; then
  echo "Desktop session is not running. Skipping this hour."
  exit 0
fi

display=""
xauthority=""
wayland=""
while read -r pid; do
  [[ -r "/proc/${pid}/environ" ]] || continue
  while IFS= read -r line; do
    case "$line" in
      DISPLAY=*) display="${line#DISPLAY=}" ;;
      XAUTHORITY=*) xauthority="${line#XAUTHORITY=}" ;;
      WAYLAND_DISPLAY=*) wayland="${line#WAYLAND_DISPLAY=}" ;;
    esac
  done < <(tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null || true)
  if [[ -n "$display" && -n "$xauthority" && -f "$xauthority" ]]; then
    break
  fi
  display=""
  xauthority=""
  wayland=""
done < <(pgrep -u "$uid" || true)

if [[ -z "$display" || -z "$xauthority" ]]; then
  echo "No graphical login found. Sign in to the desktop before the next hour."
  exit 0
fi

export DISPLAY="$display"
export XAUTHORITY="$xauthority"
unset WAYLAND_DISPLAY
export NAUKRI_FORCE_X11=1

echo "Starting on display ${DISPLAY}"
exec ./run.sh "$@"
