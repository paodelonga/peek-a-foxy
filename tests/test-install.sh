#!/usr/bin/env bash
# Tests for install.sh against throwaway profiles and a fake Firefox directory.
# The loader is fetched from a local fixture repository, so no network access is needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL="$ROOT/install.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fails=0
check() {  # check DESCRIPTION CONDITION...
  local desc=$1; shift
  if "$@"; then echo "ok   - $desc"; else echo "FAIL - $desc"; fails=$((fails + 1)); fi
}
has_line()  { grep -qxF -- "$2" "$1"; }
no_line()   { ! grep -qxF -- "$2" "$1"; }
count_is()  { [[ $(grep -cF -- "$2" "$1") == "$3" ]]; }

new_profile() {
  rm -rf "$WORK/profile"; mkdir -p "$WORK/profile/chrome"
}

# --- fixture: a minimal fx-autoconfig repository ---
FIX="$WORK/fxac"
mkdir -p "$FIX/program/defaults/pref" "$FIX/profile/chrome/utils"
echo "// loader" > "$FIX/program/config.js"
echo 'pref("general.config.filename", "config.js");' > "$FIX/program/defaults/pref/config-prefs.js"
echo "boot" > "$FIX/profile/chrome/utils/boot.sys.mjs"
git -C "$FIX" init -q -b main
git -C "$FIX" -c user.name=t -c user.email=t@t add -A
git -C "$FIX" -c user.name=t -c user.email=t@t commit -q -m fixture
export FXAC_REPO="$FIX"
export FXAC_COMMIT="$(git -C "$FIX" rev-parse HEAD)"

FXDIR="$WORK/firefox"
mkdir -p "$FXDIR"; touch "$FXDIR/omni.ja"

# --- fresh install ---
new_profile
"$INSTALL" --profile "$WORK/profile" --firefox-dir "$FXDIR" >/dev/null
P="$WORK/profile"
check "installs the stylesheet"        test -f "$P/chrome/autohide.css"
check "installs the script"            test -f "$P/chrome/JS/autohide.uc.js"
check "installs chrome/utils"          test -f "$P/chrome/utils/boot.sys.mjs"
check "installs config.js"             test -f "$FXDIR/config.js"
check "installs config-prefs.js"       test -f "$FXDIR/defaults/pref/config-prefs.js"
check "creates userChrome.css import"  has_line "$P/chrome/userChrome.css" '@import url("autohide.css");'
check "enables stylesheet loading"     has_line "$P/user.js" 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);'

# --- idempotence ---
"$INSTALL" --profile "$WORK/profile" --firefox-dir "$FXDIR" >/dev/null
check "import is not duplicated"       count_is "$P/chrome/userChrome.css" '@import url("autohide.css");' 1
check "prefs are not duplicated"       count_is "$P/user.js" 'userchrome.tabs.autohide' 1

# --- existing user content and prefs are preserved ---
new_profile
printf 'body { color: red; }\n' > "$P/chrome/userChrome.css"
printf 'user_pref("userchrome.tabs.autohide", false);\n' > "$P/user.js"
"$INSTALL" --profile "$P" --skip-loader >/dev/null
check "keeps the user's own CSS"       has_line "$P/chrome/userChrome.css" 'body { color: red; }'
check "import comes first"             test "$(head -n 1 "$P/chrome/userChrome.css")" = '@import url("autohide.css");'
check "keeps a changed pref value"     has_line "$P/user.js" 'user_pref("userchrome.tabs.autohide", false);'

# --- migration from the old project name ---
new_profile
printf '@import url("tabs-autohide.css");\nbody{}\n' > "$P/chrome/userChrome.css"
mkdir -p "$P/chrome/JS"; touch "$P/chrome/tabs-autohide.css" "$P/chrome/JS/tabs_autohide.uc.js"
"$INSTALL" --profile "$P" --skip-loader >/dev/null
check "drops the legacy import"        no_line "$P/chrome/userChrome.css" '@import url("tabs-autohide.css");'
check "removes legacy stylesheet"      test ! -e "$P/chrome/tabs-autohide.css"
check "removes legacy script"          test ! -e "$P/chrome/JS/tabs_autohide.uc.js"

# --- an existing, different loader is not overwritten ---
new_profile
FX2="$WORK/firefox2"; mkdir -p "$FX2"; touch "$FX2/omni.ja"; echo "// someone else's" > "$FX2/config.js"
"$INSTALL" --profile "$P" --firefox-dir "$FX2" >/dev/null 2>&1
check "keeps a foreign config.js"      has_line "$FX2/config.js" "// someone else's"
check "still installs profile files"   test -f "$P/chrome/autohide.css"

# --- dry run changes nothing ---
new_profile
FX3="$WORK/firefox3"; mkdir -p "$FX3"; touch "$FX3/omni.ja"
"$INSTALL" --profile "$P" --firefox-dir "$FX3" --dry-run >/dev/null
check "dry run writes no files"        test -z "$(find "$P" "$FX3" -type f ! -name omni.ja)"

# --- uninstall ---
new_profile
printf 'body{}\n' > "$P/chrome/userChrome.css"
"$INSTALL" --profile "$P" --skip-loader >/dev/null
"$INSTALL" --profile "$P" --uninstall >/dev/null
check "uninstall removes the files"    test ! -e "$P/chrome/autohide.css" -a ! -e "$P/chrome/JS/autohide.uc.js"
check "uninstall removes the import"   no_line "$P/chrome/userChrome.css" '@import url("autohide.css");'
check "uninstall keeps the user's CSS" has_line "$P/chrome/userChrome.css" 'body{}'
check "uninstall removes the prefs"    test "$(grep -c 'userchrome\.' "$P/user.js")" = 0

# --- argument handling ---
check "rejects unknown options"        bash -c "! '$INSTALL' --bogus >/dev/null 2>&1"
check "rejects a missing value"        bash -c "! '$INSTALL' --profile >/dev/null 2>&1"

if ((fails)); then echo "$fails test(s) failed"; exit 1; fi
echo "all tests passed"
