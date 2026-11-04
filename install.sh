#!/usr/bin/env bash
# Installs firefox-tabs-autohide into a Firefox profile (Linux).
#
#   ./install.sh [--profile DIR] [--firefox-dir DIR] [--skip-loader] [--uninstall] [--dry-run]
#
# The profile part needs no privileges. The fx-autoconfig loader (config.js and
# defaults/pref/config-prefs.js) goes into the Firefox install dir and needs sudo.
set -euo pipefail

FXAC_REPO="https://github.com/MrOtherGuy/fx-autoconfig.git"
FXAC_COMMIT="dfdab5684faffc112b76ccb1d8cab7f75da0102c"   # pinned; verified after clone
CSS_IMPORT='@import url("tabs-autohide.css");'
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

profile="" ; fxdir="" ; skip_loader=0 ; uninstall=0 ; dry=0

die() { echo "error: $*" >&2; exit 1; }
run() { if ((dry)); then echo "[dry-run] $*"; else "$@"; fi; }

while (($#)); do
  case "$1" in
    --profile)     profile="${2:?}"; shift 2 ;;
    --firefox-dir) fxdir="${2:?}"; shift 2 ;;
    --skip-loader) skip_loader=1; shift ;;
    --uninstall)   uninstall=1; shift ;;
    --dry-run)     dry=1; shift ;;
    -h|--help)     sed -n '2,8p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

find_profile() {
  local ini="$HOME/.mozilla/firefox/profiles.ini" p
  [[ -f $ini ]] || die "no profiles.ini found; pass --profile DIR"
  # Prefer the profile marked Default=1 inside an [Install...] section, then [Profile...] Default=1.
  p=$(awk -F= '/^\[Install/{i=1;next} /^\[/{i=0} i&&$1=="Default"{print $2; exit}' "$ini")
  if [[ -z $p ]]; then
    p=$(awk -F= '/^\[Profile/{s=1;path="";rel=1} s&&$1=="Path"{path=$2} s&&$1=="IsRelative"{rel=$2} s&&$1=="Default"&&$2==1{print path; exit}' "$ini")
  fi
  [[ -n $p ]] || die "could not detect the default profile; pass --profile DIR"
  [[ $p = /* ]] && echo "$p" || echo "$HOME/.mozilla/firefox/$p"
}

find_fxdir() {
  local bin c
  for bin in firefox firefox-developer-edition firefox-esr; do
    if c=$(command -v "$bin" 2>/dev/null); then
      c=$(dirname "$(readlink -f "$c")")
      [[ -f $c/omni.ja || -f $c/browser/omni.ja ]] && { echo "$c"; return; }
    fi
  done
  for c in /usr/lib/firefox /usr/lib/firefox-developer-edition /usr/lib/firefox-esr /opt/firefox; do
    [[ -f $c/omni.ja ]] && { echo "$c"; return; }
  done
  die "could not find the Firefox install dir; pass --firefox-dir DIR"
}

[[ -n $profile ]] || profile=$(find_profile)
[[ -d $profile ]] || die "profile dir does not exist: $profile"
chrome="$profile/chrome"

if ((uninstall)); then
  echo "Removing from $profile"
  run rm -f "$chrome/tabs-autohide.css" "$chrome/JS/tabs_autohide.uc.js"
  if [[ -f $chrome/userChrome.css ]]; then
    run sed -i '\|^@import url("tabs-autohide.css");$|d' "$chrome/userChrome.css"
  fi
  run sed -i '/^user_pref("userchrome.tabs.autohide"/d' "$profile/user.js" 2>/dev/null || true
  echo "Left in place: chrome/utils (fx-autoconfig) and the loader in the Firefox dir; they may be used by other scripts."
  exit 0
fi

# --- profile files -----------------------------------------------------------
echo "Profile: $profile"
run mkdir -p "$chrome/JS"
run install -m644 "$SRC/chrome/tabs-autohide.css" "$chrome/tabs-autohide.css"
run install -m644 "$SRC/chrome/JS/tabs_autohide.uc.js" "$chrome/JS/tabs_autohide.uc.js"

# Hook the CSS into userChrome.css without overwriting the user's own rules.
if ((dry)); then
  echo "[dry-run] ensure '$CSS_IMPORT' is first line of $chrome/userChrome.css"
elif [[ ! -f $chrome/userChrome.css ]]; then
  printf '%s\n' "$CSS_IMPORT" > "$chrome/userChrome.css"
elif ! grep -qxF "$CSS_IMPORT" "$chrome/userChrome.css"; then
  # @import rules must come before any other rule.
  { printf '%s\n' "$CSS_IMPORT"; cat "$chrome/userChrome.css"; } > "$chrome/userChrome.css.new"
  mv "$chrome/userChrome.css.new" "$chrome/userChrome.css"
fi

set_pref() {  # set_pref NAME VALUE  (idempotent, in user.js)
  local f="$profile/user.js"
  if ((dry)); then echo "[dry-run] user_pref(\"$1\", $2) in $f"; return; fi
  touch "$f"
  grep -q "^user_pref(\"$1\"" "$f" && sed -i "\|^user_pref(\"$1\"|d" "$f"
  printf 'user_pref("%s", %s);\n' "$1" "$2" >> "$f"
}
set_pref toolkit.legacyUserProfileCustomizations.stylesheets true
set_pref userchrome.tabs.autohide true

# --- fx-autoconfig -----------------------------------------------------------
if ((skip_loader)); then
  echo "Skipping the fx-autoconfig loader (--skip-loader)."
else
  command -v git >/dev/null || die "git is required to fetch fx-autoconfig"
  [[ -n $fxdir ]] || fxdir=$(find_fxdir)
  echo "Firefox dir: $fxdir"
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  git clone --quiet "$FXAC_REPO" "$tmp/fxac"
  git -C "$tmp/fxac" checkout --quiet "$FXAC_COMMIT"
  [[ $(git -C "$tmp/fxac" rev-parse HEAD) == "$FXAC_COMMIT" ]] || die "fx-autoconfig commit mismatch"

  # chrome/utils is per profile and safe to overwrite.
  run mkdir -p "$chrome/utils"
  run cp -r "$tmp/fxac/profile/chrome/utils/." "$chrome/utils/"

  # Loader into the Firefox dir (privileged).
  sudo_cmd=(); [[ -w $fxdir ]] || sudo_cmd=(sudo)
  echo "Installing the loader into $fxdir ${sudo_cmd:+(sudo)}"
  run "${sudo_cmd[@]}" install -Dm644 "$tmp/fxac/program/config.js" "$fxdir/config.js"
  run "${sudo_cmd[@]}" install -Dm644 "$tmp/fxac/program/defaults/pref/config-prefs.js" "$fxdir/defaults/pref/config-prefs.js"
fi

cat <<EOF

Done. Close ALL Firefox windows and start it again.
If the button or shortcut is missing, open about:support and click "Clear startup cache...".
Then add "Tabs autohide" from Customize Toolbar. Ctrl+Alt+T toggles the current window.
Package updates may remove the loader from the Firefox dir; just re-run ./install.sh.
EOF
