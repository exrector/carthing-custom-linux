# macOS Now-Playing capture — research (2026-05-21)

Goal: feed the Car Thing **macOS desktop (D2)** with the Mac's Now Playing
(Apple Music **and** Podcasts) over BLE (CarThingLink). A headless Mac helper
must read system now-playing and push it to the device.

Host tested: **macOS 26.5** (build 25F5068a).

## Findings

### MediaRemote.framework — restricted
Apple restricted `MediaRemote.framework` starting **macOS 15.4**: regular
processes can no longer load it directly; only system apps with the right
entitlement / a `com.apple.` bundle prefix. On 26.5 this restriction is in
effect. MediaRemote is the only API that exposes **system-wide** now-playing
(whatever app is playing — Music, Podcasts, Safari, …) with title/artist/album/
position/duration/artwork **and the source bundle id** (`com.apple.Music` vs
`com.apple.podcasts`).

### AppleScript / osascript (built-in)
- **Apple Music**: fully scriptable (iTunes/Music Suite). Works natively, zero
  install. Verified live:
  ```sh
  osascript -e 'tell application "Music" to return (player state as text)'   # -> paused
  # name/artist/album of current track, player position, duration of current track
  ```
- **Podcasts**: **NOT scriptable.** No scripting dictionary. Music-suite terms
  fail to PARSE (not runtime errors):
  ```
  tell application "Podcasts" to return (player state as text)   # syntax error -2741
  tell application "Podcasts" to return name of current track    # syntax error -2740
  ```
  Only the base Standard Suite works (`name` -> "Podcasts").

### Are the Music commands universal? — NO
`player state` / `current track` are defined in **Music.app's `.sdef`**, not in
a shared macOS media API. Podcasts has no such dictionary, so the same words
don't exist for it (parse errors above). AppleScript media commands are
per-app, not universal → Podcasts is unreachable via AppleScript.

### Shortcuts (built-in)
`shortcuts run` is available; an existing shortcut "Получить текущую песню"
exists. Shortcuts media actions are Music-oriented (Music-only), not Podcasts.

### Cross-app option (third-party)
`media-control` (brew) or `ungive/mediaremote-adapter` use an entitled system
helper (e.g. system Perl) to reach the restricted MediaRemote indirectly. These
cover **both Music and Podcasts** (system-wide), expose a `stream`/`observe`
push mode, artwork, and the source bundle id. Requires installing third-party
software.

## Practical conclusion for the project

| Source | Native (osascript/Shortcuts) | Coverage |
|---|---|---|
| Apple Music | ✓ works now, zero install | full |
| Podcasts | ✗ no native path | only via system MediaRemote adapter (media-control) |

- **Native-only** path covers **Music** (osascript polling, or the
  `com.apple.Music.playerInfo` distributed notification for push). Zero install.
- **Podcasts** requires the MediaRemote adapter (third-party) — decision pending.
- Open idea (unverified): a tiny native listener for a possible
  `com.apple.podcasts…` distributed notification — undocumented, needs a small
  ObjC/Swift listener; not a one-liner.

## Sources
- https://github.com/ungive/mediaremote-adapter
- https://github.com/nohackjustnoobb/media-remote
- https://theapplewiki.com/wiki/Dev:MediaRemote.framework
