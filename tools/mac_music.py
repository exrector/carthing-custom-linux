"""Native Apple Music now-playing capture + control via osascript (dev-Mac).

Zero third-party software (built-in osascript). This is the basis for the future
on-Mac helper that will push Music now-playing to the Car Thing over BLE; for now
the simulator uses it directly to make the macOS desktop (D2) live.

read()    -> dict {connected, playing, title, artist, album, position, duration}
control() -> play / pause / play_pause / next / prev on Apple Music
"""
import subprocess

SEP = "\x1f"

_READ = """
set sep to (ASCII character 31)
if application "Music" is running then
  tell application "Music"
    set ps to (player state as text)
    if ps is "playing" or ps is "paused" then
      set t to name of current track
      set a to artist of current track
      try
        set al to album of current track
      on error
        set al to ""
      end try
      set p to (player position as integer)
      set d to (duration of current track as integer)
      return "RUN" & sep & ps & sep & t & sep & a & sep & al & sep & p & sep & d
    else
      return "RUN" & sep & ps & sep & "" & sep & "" & sep & "" & sep & "0" & sep & "0"
    end if
  end tell
else
  return "OFF"
end if
"""

_VERB = {"play": "play", "pause": "pause", "play_pause": "playpause",
         "next": "next track", "prev": "previous track"}


def read(timeout=3.0):
    try:
        out = subprocess.run(["osascript", "-e", _READ], capture_output=True,
                             text=True, timeout=timeout).stdout.strip()
    except Exception:
        return {"connected": False}
    if not out or out == "OFF":
        return {"connected": False}
    parts = out.split(SEP)
    if len(parts) < 7 or parts[0] != "RUN":
        return {"connected": True, "playing": False, "title": "", "artist": "",
                "album": "", "position": 0, "duration": 0}
    _, ps, t, a, al, p, d = parts[:7]
    return {"connected": True, "playing": ps == "playing", "title": t, "artist": a,
            "album": al, "position": int(p or 0), "duration": int(d or 0)}


def control(command):
    verb = _VERB.get(command)
    if not verb:
        return
    try:
        subprocess.run(["osascript", "-e", f'tell application "Music" to {verb}'],
                       capture_output=True, timeout=3.0)
    except Exception:
        pass
