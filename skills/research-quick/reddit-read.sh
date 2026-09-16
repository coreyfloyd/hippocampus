#!/usr/bin/env bash
# reddit-read.sh <reddit-thread-url>
#
# Read a Reddit thread's full rendered text (post + comments) WITHOUT the
# programmatic-scrape blocks that hit Defuddle/curl/WebFetch, and WITHOUT
# stealing window focus.
#
# How it works: Reddit serves the real page to a normal human-loaded browser
# tab but blocks bots/automation. `open -g` loads the URL in the user's already-
# logged-in Safari *in the background* (-g = do not foreground the app), then
# Safari's native AppleScript `text of document` property extracts the rendered
# text. The tab we opened is closed afterward, so it reads invisibly and leaves
# no tab litter. Requires: macOS, Safari, user signed into Reddit in Safari.
#
# Prints cleaned thread text to stdout. Canonical home: research-quick skill;
# also used by research-feedback.
set -uo pipefail

url="${1:?usage: reddit-read.sh <reddit-thread-url>}"

# Load in the background — does NOT bring Safari to the foreground.
open -g -a Safari "$url"

# Poll until the page has rendered meaningful content (length stabilizes), or
# time out (~16s). Reddit is an SPA + lazy-loads comments, so a fixed sleep is
# unreliable; we wait for the extracted-text length to stop growing.
text=""; prev=-1; stable=0
for _ in $(seq 1 20); do
  sleep 0.8
  text=$(osascript -e 'tell application "Safari" to get text of front document' 2>/dev/null || true)
  len=${#text}
  if [ "$len" -gt 1200 ] && [ "$len" -eq "$prev" ]; then
    stable=$((stable + 1))
    [ "$stable" -ge 2 ] && break   # stable across two polls => loaded
  else
    stable=0
  fi
  prev=$len
done

# Emit cleaned text: drop promoted/ad blocks, price lines, and blank lines.
printf '%s\n' "$text" \
  | grep -ivE 'promoted|advertise on reddit|reddit ads|ads\.reddit\.com|redditforbusiness|target subreddits|learn more|taylormade|quisitive|orthofeet|^\$[0-9]' \
  | sed '/^[[:space:]]*$/d' \
  || true

# Close ONLY the tab we opened — match by the Reddit thread id so we never
# touch the user's other tabs. No-op if not found.
tid=$(printf '%s' "$url" | sed -nE 's#.*/comments/([a-z0-9]+)/.*#\1#p')
if [ -n "$tid" ]; then
  osascript - "$tid" <<'APPLESCRIPT' 2>/dev/null || true
on run argv
  set tid to item 1 of argv
  tell application "Safari"
    repeat with w in windows
      repeat with t in (tabs of w)
        if (URL of t) contains ("/comments/" & tid & "/") then
          close t
          return
        end if
      end repeat
    end repeat
  end tell
end run
APPLESCRIPT
fi
