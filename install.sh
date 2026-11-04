#!/usr/bin/env bash
# firefox-autohide installer for Linux and macOS. See README.md.
set -euo pipefail

# fx-autoconfig is the loader that lets Firefox run the *.uc.js script. It is cloned at a pinned
# commit and the checkout is verified, so a moved branch or tag cannot change what gets installed.
# FXAC_REPO / FXAC_COMMIT can be overridden from the environment (used by tests/test-install.sh).
readonly FXAC_REPO="${FXAC_REPO:-https://github.com/MrOtherGuy/fx-autoconfig.git}"
readonly FXAC_COMMIT="${FXAC_COMMIT:-dfdab5684faffc112b76ccb1d8cab7f75da0102c}"

readonly CSS_IMPORT='@import url("autohide.css");'
readonly LEGACY_CSS_IMPORT='@import url("tabs-autohide.css");'   # name before the project was renamed
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SRC

profile="" fxdir="" skip_loader=0 uninstall=0 dry=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

  --profile DIR       Firefox profile to install into (default: auto-detected default profile)
  --firefox-dir DIR   Firefox install directory for the loader (default: auto-detected)
  --skip-loader       Only install the profile files; do not touch the Firefox install directory
  --uninstall         Remove this project's files and prefs from the profile
  --dry-run           Print what would be done without changing anything
  -h, --help          Show this help

The profile part needs no privileges. The fx-autoconfig loader (config.js and
defaults/pref/config-prefs.js) goes into the Firefox install directory, using sudo if needed.
EOF
}

die()  { echo "error: $*" >&2; exit 1; }
warn() { echo "warning: $*" >&2; }
run()  { if ((dry)); then echo "[dry-run] $*"; else "$@"; fi; }

# --- helpers (kept free of GNU-only flags so they work with BSD tools on macOS) --------------

# Rewrites FILE in place with the output of a command that reads it, preserving its mode and owner.
# usage: rewrite FILE cmd...   (the command gets FILE as its last argument)
rewrite() {
  local file=$1 tmp; shift
  tmp=$(mktemp)
  "$@" "$file" > "$tmp"
  cat "$tmp" > "$file"
  rm -f "$tmp"
}

# Removes every line of FILE that equals LINE exactly.
remove_line() {
  local file=$1 line=$2
  [[ -f $file ]] || return 0
  grep -qxF -- "$line" "$file" || return 0
  if ((dry)); then echo "[dry-run] remove '$line' from $file"; return 0; fi
  rewrite "$file" awk -v l="$line" '$0 != l'
}

# Removes every user_pref line for NAME from FILE.
remove_pref() {
  local file=$1 name=$2
  [[ -f $file ]] || return 0
  if ((dry)); then echo "[dry-run] remove pref $name from $file"; return 0; fi
  rewrite "$file" awk -v p="user_pref(\"$name\"" 'index($0, p) != 1'
}

# set_pref NAME VALUE [keep]: idempotent user.js entry. With "keep", an existing value is left alone.
set_pref() {
  local name=$1 value=$2 mode=${3:-} file="$profile/user.js"
  if ((dry)); then echo "[dry-run] user_pref(\"$name\", $value) in $file"; return 0; fi
  touch "$file"
  if grep -qF "user_pref(\"$name\"" "$file"; then
    [[ $mode == keep ]] && return 0
    remove_pref "$file" "$name"
  fi
  printf 'user_pref("%s", %s);\n' "$name" "$value" >> "$file"
}

# --- discovery ------------------------------------------------------------------------------

case "$(uname -s)" in
  Linux)  profiles_root="$HOME/.mozilla/firefox" ;;
  Darwin) profiles_root="$HOME/Library/Application Support/Firefox" ;;
  *)      die "unsupported OS: $(uname -s) (Linux and macOS only)" ;;
esac

find_profile() {
  local ini="$profiles_root/profiles.ini" path
  [[ -f $ini ]] || die "no profiles.ini in '$profiles_root'; pass --profile DIR"
  # Prefer the profile marked as default for this install, then the one flagged Default=1.
  path=$(awk -F= '/^\[Install/{i=1; next} /^\[/{i=0} i && $1=="Default"{print $2; exit}' "$ini")
  if [[ -z $path ]]; then
    path=$(awk -F= '/^\[Profile/{p=""} $1=="Path"{p=$2} $1=="Default" && $2==1{print p; exit}' "$ini")
  fi
  [[ -n $path ]] || die "could not detect the default profile; pass --profile DIR"
  case $path in /*) echo "$path" ;; *) echo "$profiles_root/$path" ;; esac
}

find_fxdir() {
  local candidate bin
  case "$(uname -s)" in
    Darwin)
      for candidate in "/Applications/Firefox.app" "/Applications/Firefox Developer Edition.app" \
                       "/Applications/Firefox Nightly.app"; do
        [[ -f $candidate/Contents/Resources/omni.ja ]] && { echo "$candidate/Contents/Resources"; return; }
      done ;;
    *)
      for bin in firefox firefox-developer-edition firefox-esr; do
        if candidate=$(command -v "$bin" 2>/dev/null); then
          candidate=$(dirname "$(readlink -f "$candidate")")
          [[ -f $candidate/omni.ja ]] && { echo "$candidate"; return; }
        fi
      done
      for candidate in /usr/lib/firefox /usr/lib/firefox-developer-edition /usr/lib/firefox-esr /opt/firefox; do
        [[ -f $candidate/omni.ja ]] && { echo "$candidate"; return; }
      done ;;
  esac
  die "could not find the Firefox install directory; pass --firefox-dir DIR"
}

# --- arguments ------------------------------------------------------------------------------

need_value() { (($# >= 2)) || die "$1 needs a value"; }

while (($#)); do
  case "$1" in
    --profile)     need_value "$@"; profile=$2; shift 2 ;;
    --firefox-dir) need_value "$@"; fxdir=$2; shift 2 ;;
    --skip-loader) skip_loader=1; shift ;;
    --uninstall)   uninstall=1; shift ;;
    --dry-run)     dry=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *)             usage >&2; die "unknown option: $1" ;;
  esac
done

[[ -n $profile ]] || profile=$(find_profile)
[[ -d $profile ]] || die "profile directory does not exist: $profile"
chrome="$profile/chrome"

# --- uninstall ------------------------------------------------------------------------------

if ((uninstall)); then
  echo "Removing from $profile"
  run rm -f "$chrome/autohide.css" "$chrome/JS/autohide.uc.js" \
            "$chrome/tabs-autohide.css" "$chrome/JS/tabs_autohide.uc.js"
  remove_line "$chrome/userChrome.css" "$CSS_IMPORT"
  remove_line "$chrome/userChrome.css" "$LEGACY_CSS_IMPORT"
  remove_pref "$profile/user.js" "userchrome.tabs.autohide"
  remove_pref "$profile/user.js" "userchrome.urlbar.autohide"
  echo "Left in place: chrome/utils (fx-autoconfig) and the loader in the Firefox directory;"
  echo "other scripts may be using them."
  exit 0
fi

# --- profile files --------------------------------------------------------------------------

echo "Profile: $profile"
run mkdir -p "$chrome/JS"
run install -m 644 "$SRC/chrome/autohide.css" "$chrome/autohide.css"
run install -m 644 "$SRC/chrome/JS/autohide.uc.js" "$chrome/JS/autohide.uc.js"

# Leftovers from before the project was renamed.
run rm -f "$chrome/tabs-autohide.css" "$chrome/JS/tabs_autohide.uc.js"
remove_line "$chrome/userChrome.css" "$LEGACY_CSS_IMPORT"

# Hook the CSS into userChrome.css without touching the user's own rules.
if ((dry)); then
  echo "[dry-run] ensure '$CSS_IMPORT' is the first line of $chrome/userChrome.css"
elif [[ ! -f $chrome/userChrome.css ]]; then
  printf '%s\n' "$CSS_IMPORT" > "$chrome/userChrome.css"
elif ! grep -qxF "$CSS_IMPORT" "$chrome/userChrome.css"; then
  # An @import rule is only valid before any other rule.
  { printf '%s\n' "$CSS_IMPORT"; cat "$chrome/userChrome.css"; } > "$chrome/userChrome.css.new"
  cat "$chrome/userChrome.css.new" > "$chrome/userChrome.css"
  rm -f "$chrome/userChrome.css.new"
fi

set_pref toolkit.legacyUserProfileCustomizations.stylesheets true
# Defaults for windows that have no saved state; "keep" preserves a value the user has changed.
set_pref userchrome.tabs.autohide true keep
set_pref userchrome.urlbar.autohide false keep

# --- loader (fx-autoconfig) -----------------------------------------------------------------

loader_installed=1
if ((skip_loader)); then
  loader_installed=0
  echo "Skipping the fx-autoconfig loader (--skip-loader)."
else
  command -v git >/dev/null || die "git is required to fetch fx-autoconfig (or use --skip-loader)"
  [[ -n $fxdir ]] || fxdir=$(find_fxdir)
  case $fxdir in
    */snap/*|*/flatpak/*|/var/lib/flatpak/*)
      die "Snap and Flatpak builds of Firefox are read-only and not supported ($fxdir)" ;;
  esac
  [[ -d $fxdir ]] || die "Firefox directory does not exist: $fxdir"
  echo "Firefox directory: $fxdir"

  if ((dry)); then
    echo "[dry-run] clone $FXAC_REPO at $FXAC_COMMIT and install the loader into $fxdir"
  else
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    git clone --quiet "$FXAC_REPO" "$tmp/fxac"
    git -C "$tmp/fxac" checkout --quiet "$FXAC_COMMIT"
    [[ $(git -C "$tmp/fxac" rev-parse HEAD) == "$FXAC_COMMIT" ]] || die "fx-autoconfig commit mismatch"

    # chrome/utils belongs to this profile and is safe to refresh.
    mkdir -p "$chrome/utils"
    cp -R "$tmp/fxac/profile/chrome/utils/." "$chrome/utils/"

    loader_files=("config.js" "defaults/pref/config-prefs.js")
    conflict=0
    for f in "${loader_files[@]}"; do
      if [[ -f $fxdir/$f ]] && ! cmp -s "$tmp/fxac/program/$f" "$fxdir/$f"; then
        warn "$fxdir/$f already exists and differs from the one this installer provides."
        conflict=1
      fi
    done
    if ((conflict)); then
      warn "Not overwriting an existing autoconfig setup. If it is an older fx-autoconfig, update it by hand."
      loader_installed=0
    else
      sudo_cmd=()
      [[ -w $fxdir ]] || sudo_cmd=(sudo)
      echo "Installing the loader${sudo_cmd[0]:+ (using sudo)}"
      for f in "${loader_files[@]}"; do
        # ${arr[@]+...} keeps an empty array valid under `set -u` in bash 3.2 (macOS).
        ${sudo_cmd[@]+"${sudo_cmd[@]}"} mkdir -p "$(dirname "$fxdir/$f")"
        ${sudo_cmd[@]+"${sudo_cmd[@]}"} install -m 644 "$tmp/fxac/program/$f" "$fxdir/$f"
      done
    fi
  fi
fi

cat <<EOF

Done. Close ALL Firefox windows and start it again.
If the toolbar buttons or shortcuts are missing, open about:support and click "Clear startup cache...".
Then add "Tabs autohide" / "Urlbar autohide" from Customize Toolbar.
Ctrl+Alt+T (tabs) and Ctrl+Alt+U (urlbar) toggle the current window.
EOF
if ((loader_installed)); then
  echo "A Firefox update can remove the loader from its install directory; re-run ./install.sh if that happens."
fi
