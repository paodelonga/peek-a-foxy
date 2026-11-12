# When each bar is visible

What this page says, and how it was checked (issue #57). It was written against `devel/devel` at `b629589` (the merge of pull request #81); all `file:line` references are to that commit. "Tab bar" means `#TabsToolbar` without `customtitlebar`, and only
`#TabsToolbar .toolbar-items` with it.

Builds: Release 157.0.1 (`/usr/lib/firefox`), ESR 153.6.0esr, Beta 160.0b4. Everything ran headless, on Linux.

How things were checked:

- **suite**: the existing browser tests, run unchanged on all three builds: `test_in_firefox.py test_pointer.py
  test_popups.py test_customtitlebar.py test_triggers.py test_settings.py` (148 tests). Release 147 passed and 1 skipped.
  Beta 147 passed and 1 skipped. ESR 146 passed, 1 skipped and 1 failed. The skip is
  `test_customtitlebar.py:184`, which runs on Windows only. The ESR failure is
  `test_pointer.py::test_the_bookmarks_bar_can_stay_visible_while_the_navigation_bar_hides`. It failed in the full
  run and again in 3 of 3 runs on its own, so it is not flaky. See gap G1.
- **probe**: a throwaway pytest file that was not kept in the repository. It reused the suite's conftest. Each probe opened a fresh window with both bars autohidden, turned the bookmarks bar on with one
  bookmark, and put the pointer on the page. Then it did one thing and printed the heights and root attributes.
  These are measurements, not assertions.
- **read**: the code was only read for these. Nothing ran.

In the verified column, R/E/B stands for Release/ESR/Beta. Default heights were: tabs 36 (44 on ESR), nav 37 (41
on ESR), bookmarks 23 (29 on ESR). The collapsed values are tabs ≤ 8 (0 for the holder with customtitlebar), nav 8,
bookmarks 0.

## 1. Situations

### A. Resting states

| # | situation | tab bar | navigation bar | bookmarks bar | what makes it so | automated test | verified R / E / B |
|---|---|---|---|---|---|---|---|
| 1 | Autohide off for a bar | normal | normal | normal | every rule is gated by `:root[autohide-tabs]` / `:root[autohide-urlbar]` (`chrome/autohide.css:59`, `:147`, `:188`) | `test_in_firefox.py::test_everything_starts_off` (:29); restore checked at the end of `::test_navbar_and_bookmarks_bar_hide_and_show_together` (:169) | suite pass / pass / pass |
| 2 | Tab autohide on, nothing going on, native title bar | collapsed to the 8 px strip, opacity 0 | (own state) | (own state) | collapsed rule `chrome/autohide.css:88-95` (`max-height: var(--autohide-tabs-strip)`) | `test_in_firefox.py::test_tab_bar_collapses_to_the_strip_and_opens_to_its_full_height` (:136); `test_customtitlebar.py::test_without_customtitlebar_the_whole_tab_bar_still_collapses_to_the_strip` (:149) | suite pass / pass / pass |
| 3 | Same with `customtitlebar` | only `.toolbar-items` collapses (height 0); the row and the window buttons stay | - | - | `chrome/autohide.css:73-75` (row min-height = strip), `:96-103` (holder `max-height: 0`) | `test_customtitlebar.py::test_collapsing_hides_only_the_tabs_and_keeps_the_window_buttons` (:87), `::test_a_window_without_caption_buttons_keeps_a_row_to_hover` (:211); `::test_on_windows_the_window_buttons_stay_whole_while_the_tabs_are_hidden` (:185) is Windows only | suite pass / pass / pass (the :185 test was skipped) |
| 4 | Navigation autohide on, `peekafoxy.bookmarks = follow` (default) | - | 8 px strip | height 0 (it has no strip of its own) | `chrome/autohide.css:156-158` (nav), `:197-205` (bookmarks `max-height: 0`) | `test_in_firefox.py::test_navbar_and_bookmarks_bar_hide_and_show_together` (:169) | suite pass / pass / pass. **On ESR the urlbar still paints over the page (see #61, G1)** |
| 5 | Navigation autohide on, `peekafoxy.bookmarks = visible` | - | 8 px strip | full height, always | `chrome/autohide.uc.js:140-141` sets `peekafoxy-bookmarks="visible"`; `chrome/autohide.css:159-160` (nav collapsed rule without the bookmarks-hover clause); `:188` and `:197` exclude `visible` | `test_pointer.py::test_the_bookmarks_bar_can_stay_visible_while_the_navigation_bar_hides` (:376) | suite pass / **FAIL** / pass |
| 6 | Bookmarks bar turned off by the user (Firefox `collapsed`) | - | - | stays off, even when the group opens | the CSS only sets `max-height`/`opacity` and never touches `collapsed` (`chrome/autohide.css:208-218`) | `test_in_firefox.py::test_a_bookmarks_bar_the_user_turned_off_stays_off` (:211) | suite pass / pass / pass |
| 7 | Popup window opened by a page (`window.open` with features, `window.toolbar.visible === false`) | (Firefox shows no tab strip there) | never hidden | - | `chrome/autohide.uc.js:78-86` (`isPopup`, `mayHide`, `applyState`) | `test_popups.py::test_a_popup_window_keeps_its_address_visible_even_when_new_windows_hide_the_navigation_bar` (:179) | suite pass / pass / pass |
| 8 | Bar toggled with the shortcut or the toolbar button (per window) | fully shown / autohidden | fully shown / autohidden | follows nav | `chrome/autohide.uc.js:404-412` (keydown), `:480-518` (widget callback), `:87-95` (`setEnabled`) | `test_in_firefox.py::test_shortcuts_toggle_only_their_own_window` (:103), `::test_the_toolbar_button_toggles_its_window` (:125) | suite pass / pass / pass |

### B. Pointer

| # | situation | tab bar | navigation bar | bookmarks bar | what makes it so | automated test | verified R / E / B |
|---|---|---|---|---|---|---|---|
| 9 | Pointer rests on the tab strip, then leaves | opens after the show delay (100 ms), closes after the hide delay (300 ms) plus 200 ms | stays | stays | `chrome/autohide.css:106` / `:115` (`:hover`), show delay `:220-224`, hide timing `:36-37` | `test_pointer.py::test_the_pointer_on_the_tab_strip_opens_the_tab_bar_and_leaving_closes_it` (:147, both variants) | suite pass / pass / pass |
| 10 | Pointer on the tab strip does not open the navigation bar | open | stays collapsed | stays | separate selectors per bar | `test_pointer.py::test_the_pointer_on_the_tab_strip_does_not_open_the_navigation_bar` (:166) | suite pass / pass / pass |
| 11 | Pointer rests on the navigation strip | stays | opens after the show delay | opens with it | `chrome/autohide.css:169` (nav `:hover`), `:208` (bookmarks follow `#nav-bar:hover`), delay `:225-228` | `test_pointer.py::test_the_pointer_on_the_navigation_strip_opens_the_navigation_bar_and_leaving_closes_it` (:179) | suite pass / pass / pass |
| 12 | Pointer on the navigation strip does not open the tab bar | stays collapsed | open | open | - | `test_pointer.py::test_the_pointer_on_the_navigation_strip_does_not_open_the_tab_bar` (:192) | suite pass / pass / pass |
| 13 | Pointer moves from the navigation bar down into the bookmarks bar (follow) | - | stays open | stays open | `chrome/autohide.css:157` (`:not(:has(#PersonalToolbar:is(:hover, :focus-within)))`), `:174`, `:212` | `test_pointer.py::test_moving_into_the_bookmarks_bar_keeps_the_navigation_group_open` (:207) | suite pass / pass / pass |
| 14 | Pointer on a `visible` bookmarks bar | - | must stay collapsed | visible | `chrome/autohide.css:159-160` has no bookmarks-hover clause; `:174` excludes `visible` | `test_pointer.py::...stay_visible_while_the_navigation_bar_hides` (:376) | suite pass / **FAIL** (the pointer lands on the ESR ghost urlbar and the nav bar opens to 41 px) / pass |
| 15 | Pointer drifts off a bar and comes back within the hide delay | stays open | stays open | - | `--autohide-hide` with delay, `chrome/autohide.css:37` | `test_pointer.py::test_drifting_off_a_bar_and_back_within_the_hide_delay_does_not_close_it` (:240, tabs and nav, both variants) | suite pass / pass / pass |
| 16 | Show delay applies only when the pointer alone opens the bar (not for focus, flash, popup, drag or peek) | - | - | - | `chrome/autohide.css:220-229` (`transition-delay` only under `:hover:not(:focus-within…)` and without the root markers) | delay itself: `test_pointer.py::test_the_pointer_must_rest_for_the_show_delay_before_a_bar_opens` (:273). That focus or flash skip the delay: **none** | suite pass / pass / pass (the delay part only) |
| 17 | `customtitlebar`: pointer over the window buttons (minimize/maximize/close) | the tabs open (the whole row is the hover target) | - | - | `chrome/autohide.css:97` / `:115` (`#TabsToolbar:hover .toolbar-items`) | `test_pointer.py` customtitlebar variants hover the row's centre, not the buttons. Buttons: **none** | read |
| 18 | Per-bar strip heights (0 = follow the shared one) | strip = `peekafoxy.tabs.strip.px` or `strip.px` | strip = `urlbar.strip.px` or `strip.px` | - | `chrome/autohide.uc.js:104-112`, `chrome/autohide.css:39-41` | `test_pointer.py::test_each_bar_can_have_a_strip_of_its_own_and_zero_follows_the_shared_one` (:298); `test_settings.py::test_the_strip_height_really_changes_how_far_a_bar_collapses` (:228) | suite pass / pass / pass |

### C. Focus and keyboard

| # | situation | tab bar | navigation bar | bookmarks bar | what makes it so | automated test | verified R / E / B |
|---|---|---|---|---|---|---|---|
| 19 | Urlbar focused with **Ctrl+L**, **Alt+D**, **F6**, **Ctrl+K** (real key events) | stays collapsed | open while focused | open with it | `chrome/autohide.css:170` (`#nav-bar:focus-within`), `:208` | `test_in_firefox.py::test_navbar_and_bookmarks_bar_hide_and_show_together` (:169) uses `gURLBar.focus()`, never real keys | probe (real keys through Marionette): all 4 keys focused `urlbar-input` and opened nav and bookmarks on R / E / B |
| 20 | Focus leaves the urlbar (page clicked, Escape and so on) | - | closes | closes | the `:focus-within` match goes away | same test (:169), via `gBrowser.selectedBrowser.focus()` | suite pass / pass / pass |
| 21 | Keyboard focus inside the tab strip | open | - | - | `chrome/autohide.css:107` / `:116` (`#TabsToolbar:focus-within`) | `test_customtitlebar.py::test_the_tabs_come_back_while_something_in_the_tab_bar_has_the_focus` (:133), customtitlebar only. Native variant: **none** | suite pass / pass / pass |
| 22 | Keyboard focus on a button of the navigation bar (toolbar keyboard navigation) | - | open | open | `chrome/autohide.css:170`, `:208` | **none** | read |
| 23 | New tab (**Ctrl+T**, `BrowserCommands.openTab()`) | flashes for `flash.ms` (1500 ms) | **stays open as long as the urlbar keeps the focus** (Firefox focuses it for a new tab) | open with it | flash: `chrome/autohide.uc.js:253-262`; nav: `chrome/autohide.css:170` | flash: `test_triggers.py::test_every_trigger_opens_the_bar_by_default[new tab, selected]` (:75), attribute only. Nav staying open: **none** | probe: at 0.4 s tabs 36, nav 37, bookmarks 23; at 2.4 s tabs 8, nav and bookmarks still open (urlbar focused) on R / E / B |
| 24 | New window (urlbar may take the focus) | - | open while the urlbar is focused | open | `chrome/autohide.css:170` | none. The suite deliberately blurs the urlbar of every new window (`tests/browser/conftest.py:160-171`, `settle_window`) | not run (see section 3) |
| 25 | Window becomes inactive (another window takes the focus) while its urlbar is focused | - | **closes**: `gURLBar.focused` stays true, but `#nav-bar:focus-within` is false | closes | `:focus-within` does not match in an inactive window, so `chrome/autohide.css:170` stops matching | **none** | probe (headless): nav 37 → 8, bookmarks 23 → 0 on R / E / B |
| 26 | Find bar open (**Ctrl+F**) | stays collapsed | stays collapsed | stays collapsed | the find bar is outside `#navigator-toolbox`; nothing reveals | none | probe: no change on R / E / B |

### D. Tab flashes (`tabs-flash` on the root)

| # | situation | tab bar | navigation bar | bookmarks bar | what makes it so | automated test | verified R / E / B |
|---|---|---|---|---|---|---|---|
| 27 | Tab switch (click, Ctrl+Tab, Ctrl+PgDn, Alt+1..9, "switch to tab") | open for `flash.ms` | - | - | `chrome/autohide.uc.js:250-252` (TabSelect, `revealSwitch`), `flashTabs` `:209-214`; CSS `chrome/autohide.css:108` / `:117` | `test_triggers.py::test_every_trigger_opens_the_bar_by_default[switch]` (:75), `[switch]` of :85 and :92; `test_customtitlebar.py::test_the_tabs_come_back_while_the_tab_bar_is_flashed` (:101); height on flash: `test_in_firefox.py:136` | suite pass / pass / pass |
| 28 | Tab you opened (new-tab page or home page, selected or in the background) | open for `flash.ms` if `reveal.new` | - | - | `chrome/autohide.uc.js:253-262`, `isNewTabPage` `:229-249` | `test_triggers.py` `[new tab, …]` of :75, :85, :92; `::test_the_new_tab_page_and_the_home_page_count_as_a_tab_you_opened` (:104), `::test_a_custom_home_page_is_still_a_tab_you_opened` (:120), :155, :172, :197; `test_in_firefox.py::test_opening_a_tab_reveals_the_tab_bar_briefly` (:154) | suite pass / pass / pass |
| 29 | Tab opened by a link, a bookmark or `window.open` | open if `reveal.link` | - | - | same, the other branch at `chrome/autohide.uc.js:260` | `test_triggers.py` `[link, …]` of :75, :85, :92; `::test_any_other_address_counts_as_a_link` (:112) | suite pass / pass / pass |
| 30 | Page of the current tab finishes loading (off by default) | open if `reveal.load` | - | - | `chrome/autohide.uc.js:268-284` | `test_settings.py::test_a_page_finishing_to_load_flashes_the_bar_only_when_asked` (:597), `::test_a_page_loading_in_the_background_does_not_flash_the_bar` (:611) | suite pass / pass / pass |
| 31 | Download finishes (off by default) | open if `reveal.download` | - | - | `chrome/autohide.uc.js:292-309` | `test_settings.py::test_a_finished_download_flashes_the_bar_only_when_asked` (:624) | suite pass / pass / pass |
| 32 | Background tab changes its title after loading (off by default) | open if `reveal.title` | - | - | `chrome/autohide.uc.js:286-290` | `test_settings.py::test_a_background_tab_changing_its_title_flashes_the_bar_only_when_asked` (:647) | suite pass / pass / pass |
| 33 | Every reveal pref off / `flash.ms = 0` | nothing opens | - | - | prefs read on every event (`chrome/autohide.uc.js:251`, `:260`) | `test_triggers.py::test_with_everything_off_nothing_opens_the_bar` (:98); `test_settings.py::test_the_flash_time_comes_from_the_pref` (:295) | suite pass / pass / pass |
| 34 | Closing the **selected** tab | flashes (through the TabSelect of the next tab) | - | - | `chrome/autohide.uc.js:250-252` | **none** | probe: flash, tabs open, on R / E / B |
| 35 | Closing a **background** tab | no flash | - | - | no TabClose listener | **none** | probe: no flash on R / E / B |
| 36 | Moving a tab with the keyboard (Ctrl+Shift+PgUp/PgDn, `gBrowser.moveTabBackward()`) | **no flash** | - | - | there is no TabMove listener: `grep TabMove chrome/` finds nothing. The brief lists "tab move" as a flash reason, but it does not exist in the code | **none** | probe: no flash on R / E / B |
| 37 | Pin / unpin a tab | no flash | - | - | no listener | none | probe: no flash on R / E / B |

### E. Popups (`peekafoxy-popup-open`, Firefox's `open` / `state` markers)

| # | situation | tab bar | navigation bar | bookmarks bar | what makes it so | automated test | verified R / E / B |
|---|---|---|---|---|---|---|---|
| 38 | Popup anchored in the tab bar (list all tabs, Firefox View, tab group editor…) | stays open while the pointer is in the popup | - | - | `chrome/autohide.uc.js:369-396` (popupshowing → `barOf(anchorNode ?? triggerNode ?? parentNode)`), CSS `chrome/autohide.css:110` / `:119` | `test_popups.py::test_the_tab_bar_stays_open_when_the_pointer_moves_into_its_popup` (:210, both variants, real all-tabs panel) | suite pass / pass / pass |
| 39 | Tab context menu | open | - | - | `chrome/autohide.css:88` / `:96` and `:112` / `:121` (`:has(#tabContextMenu:is([state="open"], [state="showing"]))`), plus the popup map, because the trigger node is the tab (`chrome/autohide.uc.js:382`) | `test_customtitlebar.py::test_the_tabs_come_back_while_the_tab_context_menu_is_open` (:141): customtitlebar only, and `state` is set by hand | suite pass / pass / pass. Probe with the real menu (native title bar, pointer moved to the page): tabs open, `popup-open="tabs"`, nav stays collapsed, on R / E / B |
| 40 | App menu (☰), extensions panel, downloads panel, doorhanger (`PopupNotifications`: permission and password prompts) | - | open while the popup is open | open | `chrome/autohide.uc.js:378-389` maps the anchor in `#nav-bar` to `navbar`; CSS `chrome/autohide.css:173`, `:211` | `test_popups.py::test_the_navigation_group_stays_open_for_a_popup_of_either_bar[navbar]` (:255): a synthetic panel, not Firefox's | probe with real panels: all 4 open nav and bookmarks with `popup-open="navbar"` and close afterwards, on R / E / B. Panels opened from a collapsed bar end up exactly where they do with the bar open (app menu gap 0 px, extensions -4 px, same as the control) |
| 41 | Identity popup / permissions popup (site information) | - | expected: open (anchor `#identity-icon-box` is inside `#nav-bar`) | expected: open | same as #40 | none | **not verified**: the probe could not open these panels by script (section 3) |
| 42 | Bookmarks folder menu / chevron of the bookmarks bar | - | open | open | popup map → `bookmarks`; CSS `chrome/autohide.css:173`, `:211` | `test_popups.py::...either_bar[bookmarks]` (:255), synthetic panel | suite pass / pass / pass. Probe with a real folder menu: `popup-open="bookmarks"`, both open, R / E / B |
| 43 | A button of the nav bar marked `open` (menu-type button) | - | open | open | `chrome/autohide.css:158`, `:171`, `:198`, `:209` (`toolbarbutton[open]`) | `test_popups.py::test_the_navigation_group_stays_open_while_firefox_marks_something_in_it_as_open[a button of the bar is open]` (:299) | suite pass / pass / pass |
| 44 | Urlbar results dropdown open (`#urlbar[open]`) | - | open | open | `chrome/autohide.css:156`, `:172`, `:197`, `:210` | same test `[the urlbar is open]` (:299): attribute set by hand | suite pass / pass / pass. Probe with real results: open, not clipped by `overflow: hidden` (hit-test on a result row lands in the view) on R / E / B |
| 45 | Two popups of one bar, popups of two bars, a popup removed without `popuphidden`, a cancelled `popupshowing` | as counted | as counted | as counted | `chrome/autohide.uc.js:369-396` | `test_popups.py` :340, :353, :363, :374 | suite pass / pass / pass |
| 46 | Popup not anchored in a bar (page context menu), tooltips | nothing opens | nothing opens | nothing opens | `chrome/autohide.uc.js:380` (tooltips skipped), `:383` (no bar → not recorded) | `test_popups.py::test_a_popup_that_belongs_to_no_bar_and_a_tooltip_do_not_open_one` (:384) | suite pass / pass / pass |
| 47 | Menu bar (Alt) and its menus, Ctrl+Tab preview panel | nothing opens | nothing opens | nothing opens | `#toolbar-menubar` is not in `BAR_NAMES` (`chrome/autohide.uc.js:340`) | none | read |

### F. Drag

| # | situation | tab bar | navigation bar | bookmarks bar | what makes it so | automated test | verified R / E / B |
|---|---|---|---|---|---|---|---|
| 48 | Dragging a tab (reorder or tear off) | open | stays collapsed | - | `chrome/autohide.uc.js:351-354` (`peekafoxy-dragging="tabs"`); CSS `chrome/autohide.css:89`, `:109`, `:114`, `:118`, `:122` (`movingtab`, `dragtarget`) | `test_in_firefox.py::test_dragging_a_tab_keeps_the_tab_bar_open_but_not_the_navigation_bar` (:362); `test_customtitlebar.py::test_the_tabs_come_back_while_a_tab_is_being_dragged_out_of_the_bar` (:120) | suite pass / pass / pass |
| 49 | Dragging a bookmark out of the bookmarks bar | - | open | open | `peekafoxy-dragging="bookmarks"`; CSS `chrome/autohide.css:173`, `:211` | `test_in_firefox.py::test_dragging_a_bookmark_keeps_the_bookmarks_bar_open` (:321) | suite pass / pass / pass |
| 50 | Dragging a button out of the navigation bar (outside Customize) | - | open | open | `peekafoxy-dragging="navbar"`, same selectors | none | read |
| 51 | A drag that never sends `dragend`/`drop` | marker cleared on the next mouse move | same | same | `chrome/autohide.uc.js:356-358` | `test_in_firefox.py::test_a_drag_that_never_reports_its_end_still_ends_on_the_next_mouse_move` (:349) | suite pass / pass / pass |
| 52 | Dragging **into** a hidden bar from the page, the desktop or another window (a link onto the tab strip, a link onto the urlbar, a tab into another window's strip) | open | open | open (together with the navigation bar: its own strip is 0 px) | `dragenter`/`dragleave` handlers in `chrome/JS/autohide.uc.js` set `peekafoxy-dragging` with a `draggedOver` flag; they leave a marker set by a `dragstart` in a bar alone | `test_in_firefox.py`: `test_a_link_dragged_over_the_hidden_tab_bar_opens_it_until_it_leaves`, `test_a_link_dragged_over_the_hidden_navigation_bar_opens_it_and_a_drop_closes_it`, `test_leaving_the_window_with_a_dragged_item_closes_the_bar`, `test_an_item_dragged_out_of_a_bar_keeps_its_bar_when_it_passes_over_the_page`. Synthetic events: a real drag from another program is not covered | suite pass / pass / pass |

### G. Modes and environment

| # | situation | tab bar | navigation bar | bookmarks bar | what makes it so | automated test | verified R / E / B |
|---|---|---|---|---|---|---|---|
| 53 | Full screen (F11, and DOM full screen) | left to Firefox | left to Firefox | left to Firefox | every rule has `:not([inFullscreen])` (`chrome/autohide.css:20-21`) | `test_in_firefox.py::test_full_screen_is_left_to_firefox` (:252): **only the nav bar is asserted** | suite pass / pass / pass |
| 54 | Customize Toolbar | full | full | full | `:not([customizing])` on every rule | `test_in_firefox.py::test_customize_toolbar_shows_the_bars_in_full` (:230): **only the nav bar is asserted** | suite pass / pass / pass |
| 55 | Easter egg "peek" (bars peek in rhythm, hide delay 0) | peeks | peeks | peeks with nav | `chrome/resources/peekafoxy.sys.mjs:1259-1286` (`peekBars`), CSS `chrome/autohide.css:111`, `:120`, `:173`, `:211`, `:232-234` | `test_easter_eggs.py::test_swswsad_makes_the_bars_peek_and_then_opens_the_player` (:440), `::test_the_bars_peek_even_when_they_are_showing` (:597), `::test_reduced_motion_means_no_fade_and_no_peeking` (:956) | not run (out of scope) |
| 56 | `prefers-reduced-motion: reduce` | no animation, hide delay kept | same | same | `chrome/autohide.css:236-242` | `test_settings.py::test_reduced_motion_still_wins_over_the_timing_settings` (:511) | suite pass / pass / pass |
| 57 | Vertical tabs (`sidebar.revamp` + `sidebar.verticalTabs`) | Firefox moves `#tabbrowser-tabs` into `#vertical-tabs` and collapses `#TabsToolbar` (height 0, `visibility: collapse`). **The tabs in the sidebar are always visible: autohide, flash, button and shortcut have no visible effect** | own state | own state | nothing in the code knows about vertical tabs | **none** | probe: same result on R / E / B (sidebar tab list height unchanged when `tabs-flash` is set) |
| 58 | Touch density (`browser.uidensity = 2`): taller bars vs the caps (64 / 52 / 40 px, `chrome/autohide.css:42-44`) | revealed = natural (49 on ESR, 53 on Beta) | revealed = natural (45) | revealed = natural (35) | the caps are not reached | none | probe: ESR and Beta equal. Release probe setup timed out (section 3) |
| 59 | Sidebar (Ctrl+B / Ctrl+H, no vertical tabs), docked devtools, print preview, reader view, notification bars | stay as they are | stay as they are | stay as they are | all outside `#navigator-toolbox`, nothing reveals | none | read (find bar, which works the same way, verified in #26) |
| 60 | Picture-in-picture window, undocked devtools, Library and other dialogs | script not loaded there | - | - | `// @include main` (`chrome/JS/autohide.uc.js:4`), and the script returns early without `gBrowser` (`:19-22`) | none | read |
| 61 | **ESR 153: nav bar collapsed, `follow` or `visible`** | - | `#nav-bar` is 8 px, **but `#urlbar` stays painted at its normal place over the top of the page** (y 12-44), catches the pointer and clicks, and hovering it opens the bar | (in `visible` mode the ghost urlbar covers the bookmarks bar) | on ESR 153.6 `#urlbar` has `popover="manual"` and is always `:popover-open` (top layer), so it escapes `overflow: hidden` and `opacity: 0` on `#nav-bar` (`chrome/autohide.css:147-149`, `:161-165`). Release 157 and Beta 160 have no `popover` attribute on `#urlbar` | **none** (all tests measure `#nav-bar`, never the urlbar box; only #14 trips over it) | probe: ESR screenshot shows the urlbar floating over the page while the bar is "hidden". `elementFromPoint` 2-26 px below the strip hits `nav-bar:urlbar-input`, and a real pointer there opens nav to 41 px. Release and Beta: the page is hit and nothing opens |

**Count:** 61 situations. 42 have an automated test that reaches them in some form (#1-15, 18-21, 23,
27-33, 38-40, 42-46, 48-49, 51, 53-56). Several of those reach the situation only partly: by hand-set attribute,
by synthetic panel, by `focus()` instead of keys, or by checking one bar only. 19 have no test (#16 partly, 17, 22,
24, 25, 26, 34-37, 41, 47, 50, 52, 57-61).

## 2. Gaps

**G1. ESR 153: the urlbar is never really hidden (high).** See #61. On ESR 153.6 `#urlbar` is a
`popover="manual"` that is always open in the top layer. `overflow: hidden` and `opacity: 0` on `#nav-bar` do not
reach it. The result: the urlbar paints over the top ~28 px of the page across its width, takes the clicks there,
and hovering it opens the navigation bar. That strip is several times taller than the 8 px one. In `visible` mode
it covers the bookmarks bar, which is why `test_pointer.py:376` failed on ESR in 4 of 4 runs. Fixed in #94 by a rule for `#urlbar` itself (transparent, no pointer events while the bar is collapsed), tested on all three builds.
- Reproduce: ESR 153.6, nav autohide on, pointer on the page → the urlbar is still drawn under the tab strip. Or run
  `PEEK_A_FOXY_FIREFOX=<esr> pytest -m browser "tests/browser/test_pointer.py::test_the_bookmarks_bar_can_stay_visible_while_the_navigation_bar_hides"`.
- Proposed test: with nav collapsed and the pointer away, assert that
  `document.elementFromPoint(urlbarCenterX, navBar.bottom + 10)` is not inside `#nav-bar`. Also assert that the
  urlbar's rect does not extend below `#nav-bar`'s rect, or that it is not rendered
  (`checkVisibility({visibilityProperty: true})` is false). Run on all three builds.
- Fix idea (untested): add `visibility: hidden` to the collapsed nav rule, with a delayed `visibility` transition so
  that it flips after the hide animation. `visibility` is inherited through the DOM, so it also reaches a top-layer
  descendant, and hidden elements are not hit-tested.

**G2. Dragging something into a hidden bar did not open it (closed, #85).** A `dragenter` over a hidden bar now opens it, and it closes when the item goes on to the page, leaves the window, or is dropped. The tests send synthetic drag events carrying a `DataTransfer`; a real drag from another program was not tried on this machine.

**G3. Vertical tabs are not handled (medium).** See #57. With Firefox's vertical tabs the tab-bar autohide, its
Tracked in #86.

button, its shortcut and every flash do nothing visible, and the probe found no diagnostic about it.
- Reproduce: set `sidebar.revamp` and `sidebar.verticalTabs` to true and toggle the tab-bar shortcut.
- Proposed test: with those prefs set, assert one of two things. Either a `Diag` notice or a disabled/hidden tab
  button (the project chooses not to support it), or the sidebar tab list collapsing (the project chooses to
  support it).

**G4. Tab changes that produce no flash (low/medium).** #35-37. A keyboard tab move (Ctrl+Shift+PgUp/PgDn) moves
Tracked in #87.

a tab you cannot see. Closing a background tab, pinning, muting, and a tab asking for attention also give no
feedback. The brief names "tab move" as a flash reason, but there is no `TabMove` listener anywhere in `chrome/`.
- Proposed test: `gBrowser.moveTabBackward()` → expect `tabs-flash` when a new pref (for example
  `peekafoxy.tabs.reveal.move`) is on, and no flash while `#tabbrowser-tabs[movingtab]` is set (a drag already keeps
  the bar open).

**G5. An inactive window drops its navigation bar even with the urlbar focused (decide).** #25. Switching to
Tracked in #88.

another window collapses the nav bar of the window where you were typing, and it opens again when you come back.
That may be what people want. It is untested either way.
- Proposed test (whichever behaviour is chosen): focus the urlbar in window A, open window B, and read A's nav
  height without focusing A (`switch_to_window(a, focus=False)`).

**G6. A new tab, and probably a new window, leave the navigation bar open until the focus moves (decide).** #23,
Tracked in #89.

#24. That is correct while you type, but the bar stays open for as long as you don't. The suite neutralises this on
purpose (`tests/browser/conftest.py:160-171`), so no test pins the real behaviour.
- Proposed test: `BrowserCommands.openTab()` → nav at natural height while `gURLBar.focused`, collapsed after
  `gBrowser.selectedBrowser.focus()`.

**G7. The show delay is skipped for every bar while any popup is open on any bar (low).**
Tracked in #90.

`chrome/autohide.css:221`, `:223`, `:225` exclude a bare `[peekafoxy-popup-open]`, `[peekafoxy-dragging]` or
`[peekafoxy-peek]`, whatever value they hold. For example, with the tab context menu open, the nav strip opens with
no delay.
- Proposed test: open a panel anchored in the tab bar, then move the pointer to the nav strip with
  `show.delay.ms = 1200` and expect the nav bar still collapsed after 0.5 s.

**G8. `visible` bookmarks still get the reveal cap (low).** The reveal rules at `chrome/autohide.css:208-213` do not
Tracked in #91.

exclude `[peekafoxy-bookmarks="visible"]`, so while the nav group is revealed a `visible` bookmarks bar gets
`max-height: 40px` with no `overflow: hidden` (the base rule at `:188` excludes `visible`). Not triggered at default
or touch density (35 px). It only matters for a bookmarks bar taller than 40 px.

**G9. Weaker spots in existing tests (coverage, not behaviour).**
Tracked in #92.

- `test_in_firefox.py:230` (Customize) and `:252` (full screen) assert only the navigation bar. Also assert the tab
  bar and the bookmarks bar.
- The tab context menu (`test_customtitlebar.py:141`) and tab-strip focus (`:133`) are tested only with
  `customtitlebar`, and the context menu only by setting `state` by hand. Add a native-title-bar variant that opens
  the real menu (`openPopupAtScreen(x, y, true, event)` with an event dispatched on the tab, as the probe did).
- The `open` markers (`test_popups.py:299`) and the nav popups (`:255`) use hand-set attributes or synthetic panels.
  The probe showed that the real app menu, extensions panel, downloads panel, `PopupNotifications` and urlbar
  results all work. A test with `PanelUI.show()` and `PopupNotifications.show(...)` would catch a Firefox change in
  how those are anchored.
- No test uses the real focus keys (Ctrl+L, F6, Alt+D, Ctrl+K). The suite already has `Browser.real_keys`
  (`tests/browser/conftest.py:292-307`), and the probe used it successfully on all three builds.
- Nothing checks that focus, flash or popup reveals skip the show delay (#16).

## 3. Not verified, and why

- **Identity and permissions popups (#41).** Firefox creates `#identity-popup` lazily. The probe's calls
  (`gIdentityHandler.handleIdentityButtonEvent`, `_openPopup`, and a synthetic click with autohide **off** as a
  control) never opened it, and `gPermissionPanel._openPopup` threw a TypeError. The expected behaviour comes only
  from the code: its anchor is inside `#nav-bar`, the same path as the panels verified in #40.
- **Real hover during an OS drag session (#52).** Marionette cannot run a native drag session headless. Only the
  root markers were checked, with synthetic drag events. The claim that hover does not update during a drag is
  taken from the code comment at `chrome/autohide.uc.js:334` and was not re-measured.
- **Window activation under a real window manager (#25).** Headless Firefox emulates focus. The result
  (`:focus-within` false in the inactive window) is what Gecko did there; a real compositor may behave the same,
  but this was not checked.
- **A new window focusing its urlbar (#24).** `test_in_firefox.py:82` says Firefox does this only "sometimes", and
  It was not probed.
- **Windows and macOS `customtitlebar` with real caption buttons.** `test_customtitlebar.py:185` is Windows only
  and was skipped. All `customtitlebar` results here come from Linux with the attribute forced and a stand-in
  button box.
- **Large chrome fonts.** `ui.textScaleFactor = 180` set at runtime did not change the bar heights (it seems to
  apply only at startup), so the caps were checked only with touch density. On Release the touch-density probe
  failed in its setup (the bookmark item never appeared within 10 s), so only ESR and Beta numbers exist for #58.
- **Tab hover preview panel, tab group editor, PiP, devtools, print, reader view (#38, #59, #60).** Read only.
  The preview panel is a `panel` anchored to a tab, so by `chrome/autohide.uc.js:378-389` it would keep the tab bar
  open while it is shown. It was not checked whether it can outlive the hover.
- **Easter egg peek (#55).** Its tests exist but were not run (out of scope for this task).
- **Whether the ESR ghost urlbar (G1) appears with a real (non-headless) ESR.** The probe was headless. The cause
  (`#urlbar[popover="manual"]` open in the top layer) is in Firefox's own markup and does not depend on headless
  mode, so the same is expected in a normal window.
- **Touch or pen input on the strips.** Not tested at all.
