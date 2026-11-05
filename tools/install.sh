#!/usr/bin/env bash
# Install the process automation of this repository into a Hermes profile.
#
# The scripts in tools/ are the source of truth; the cron jobs of the Lead run a *copy* in
# profiles/<profile>/scripts/ (Hermes refuses symlinks there, see tools/README.md). This script
# makes that copy: it reads from the directory it lives in and writes into the profile.
#
# Idempotent: a file that is already identical is left alone, so a second run changes nothing and
# prints the same target directory.
#
# Usage:
#   tools/install.sh [--profile <name>] [--profiles-root <dir>] [--dry-run]
#   tools/install.sh <name>                # shorthand for --profile <name>
#
# Defaults: profile sw-lead; profiles root $HERMES_PROFILES_ROOT, else $HERMES_HOME/profiles, else
# ~/.hermes/profiles. A HERMES_HOME that points at a profile directory (…/profiles/<name>) is
# refused: inside the agent runtime HERMES_HOME is the profile, so the derived path would be nested
# and nothing would install where the cron jobs read. Pass --profiles-root or unset HERMES_HOME.
# Exit codes: 0 ok, 1 source or target problem, 2 usage.
set -euo pipefail

FILES=(
  github-watch.sh
  dev-dispatch.sh
  assignee_sync.py
  review-pack.py
  gen-prozess-diagramm.py
  gen-beitrag-diagramm.py
  swimlane_svg.py
)

profile="sw-lead"
profiles_root="${HERMES_PROFILES_ROOT:-}"
profiles_root_set=0
dry_run=0
profile_set=0

usage() {
  awk 'NR > 1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      [[ $# -ge 2 ]] || { echo "install.sh: --profile needs a value" >&2; exit 2; }
      profile="$2"
      profile_set=1
      shift 2
      ;;
    --profiles-root)
      [[ $# -ge 2 ]] || { echo "install.sh: --profiles-root needs a value" >&2; exit 2; }
      profiles_root="$2"
      profiles_root_set=1
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      echo "install.sh: unknown option $1" >&2
      exit 2
      ;;
    *)
      if [[ "$profile_set" -eq 1 ]]; then
        echo "install.sh: unexpected argument $1" >&2
        exit 2
      fi
      profile="$1"
      profile_set=1
      shift
      ;;
  esac
done

if [[ -z "$profile" || "$profile" == */* ]]; then
  echo "install.sh: invalid profile name '${profile}'" >&2
  exit 2
fi

# Resolve the profiles root only when neither --profiles-root nor HERMES_PROFILES_ROOT said it.
if [[ "$profiles_root_set" -eq 0 && -z "${HERMES_PROFILES_ROOT:-}" ]]; then
  hermes_home="${HERMES_HOME:-}"
  while [[ "$hermes_home" == */ ]]; do
    hermes_home="${hermes_home%/}"
  done
  if [[ -n "$hermes_home" && "$(basename "$(dirname "$hermes_home")")" == "profiles" ]]; then
    echo "HERMES_HOME looks like a profile (${hermes_home}); pass --profiles-root or unset HERMES_HOME" >&2
    exit 2
  fi
  profiles_root="${hermes_home:-$HOME/.hermes}/profiles"
fi

src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="$profiles_root/$profile/scripts"

missing=0
for file in "${FILES[@]}"; do
  if [[ ! -f "$src_dir/$file" ]]; then
    echo "install.sh: missing source file $src_dir/$file" >&2
    missing=1
  fi
done
if [[ "$missing" -ne 0 ]]; then
  exit 1
fi

if [[ "$dry_run" -eq 0 ]]; then
  mkdir -p "$target"
  if [[ ! -w "$target" ]]; then
    echo "install.sh: target directory not writable: $target" >&2
    exit 1
  fi
fi

for file in "${FILES[@]}"; do
  src="$src_dir/$file"
  dest="$target/$file"
  if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
    echo "unchanged  $dest"
    continue
  fi
  if [[ "$dry_run" -eq 1 ]]; then
    echo "would copy $src -> $dest"
    continue
  fi
  mode="$(stat -c '%a' "$src")"
  install -m "$mode" "$src" "$dest"
  echo "copied     $dest"
done

if [[ "$dry_run" -eq 0 ]]; then
  for file in "${FILES[@]}"; do
    if ! cmp -s "$src_dir/$file" "$target/$file"; then
      echo "install.sh: verification failed for $target/$file" >&2
      exit 1
    fi
  done
fi

echo "target: $target"
