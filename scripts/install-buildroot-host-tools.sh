#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
prefix="$repo_root/host-tools"
bin_dir="$prefix/bin"

mkdir -p "$bin_dir"

sh "$repo_root/scripts/install-gnu-patch.sh"
sh "$repo_root/scripts/install-gnu-findutils.sh"
sh "$repo_root/scripts/install-gnu-sed.sh"

ginstall_path=""
gcp_path=""
gchmod_path=""
coreutils_prefix=""
gdate_path=""
gstat_path=""
gmktemp_path=""
gsplit_path=""
if command -v ginstall >/dev/null 2>&1; then
    ginstall_path=$(command -v ginstall)
fi

if command -v gcp >/dev/null 2>&1; then
    gcp_path=$(command -v gcp)
fi

if command -v gchmod >/dev/null 2>&1; then
    gchmod_path=$(command -v gchmod)
fi

if command -v gdate >/dev/null 2>&1; then
    gdate_path=$(command -v gdate)
fi

if command -v gstat >/dev/null 2>&1; then
    gstat_path=$(command -v gstat)
fi

if command -v gmktemp >/dev/null 2>&1; then
    gmktemp_path=$(command -v gmktemp)
fi

if command -v gsplit >/dev/null 2>&1; then
    gsplit_path=$(command -v gsplit)
fi

if command -v brew >/dev/null 2>&1; then
    coreutils_prefix=$(brew --prefix coreutils 2>/dev/null || true)
    if [ -n "$coreutils_prefix" ] && [ -x "$coreutils_prefix/libexec/gnubin/install" ] && [ -z "$ginstall_path" ]; then
        ginstall_path="$coreutils_prefix/libexec/gnubin/install"
    fi
    if [ -n "$coreutils_prefix" ] && [ -x "$coreutils_prefix/libexec/gnubin/cp" ] && [ -z "$gcp_path" ]; then
        gcp_path="$coreutils_prefix/libexec/gnubin/cp"
    fi
    if [ -n "$coreutils_prefix" ] && [ -x "$coreutils_prefix/libexec/gnubin/chmod" ] && [ -z "$gchmod_path" ]; then
        gchmod_path="$coreutils_prefix/libexec/gnubin/chmod"
    fi
    if [ -n "$coreutils_prefix" ] && [ -x "$coreutils_prefix/libexec/gnubin/date" ] && [ -z "$gdate_path" ]; then
        gdate_path="$coreutils_prefix/libexec/gnubin/date"
    fi
    if [ -n "$coreutils_prefix" ] && [ -x "$coreutils_prefix/libexec/gnubin/stat" ] && [ -z "$gstat_path" ]; then
        gstat_path="$coreutils_prefix/libexec/gnubin/stat"
    fi
    if [ -n "$coreutils_prefix" ] && [ -x "$coreutils_prefix/libexec/gnubin/mktemp" ] && [ -z "$gmktemp_path" ]; then
        gmktemp_path="$coreutils_prefix/libexec/gnubin/mktemp"
    fi
    if [ -n "$coreutils_prefix" ] && [ -x "$coreutils_prefix/libexec/gnubin/split" ] && [ -z "$gsplit_path" ]; then
        gsplit_path="$coreutils_prefix/libexec/gnubin/split"
    fi
fi

if [ -n "$ginstall_path" ]; then
    ln -sf "$ginstall_path" "$bin_dir/install"
else
    echo "warning: GNU install was not found; Buildroot may fail on packages that use install -D" >&2
fi

if [ -n "$gcp_path" ]; then
    ln -sf "$gcp_path" "$bin_dir/cp"
else
    echo "warning: GNU cp was not found; Buildroot may fail on packages that use cp -d" >&2
fi

if [ -n "$gchmod_path" ]; then
    ln -sf "$gchmod_path" "$bin_dir/chmod"
else
    echo "warning: GNU chmod was not found; Buildroot may fail on packages that use chmod -c" >&2
fi

if [ -n "$gdate_path" ]; then
    ln -sf "$gdate_path" "$bin_dir/date"
fi

if [ -n "$gstat_path" ]; then
    ln -sf "$gstat_path" "$bin_dir/stat"
fi

if [ -n "$gmktemp_path" ]; then
    ln -sf "$gmktemp_path" "$bin_dir/mktemp"
fi

if [ -n "$gsplit_path" ]; then
    ln -sf "$gsplit_path" "$bin_dir/split"
else
    echo "warning: GNU split was not found; Buildroot may fail in fix-rpath finalization" >&2
fi

cat > "$bin_dir/flock" <<'EOF'
#!/usr/bin/env python3
import fcntl
import os
import subprocess
import sys
import time


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def parse(argv):
    shared = False
    nonblock = False
    timeout = None
    command = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-s":
            shared = True
        elif arg == "-x":
            shared = False
        elif arg == "-n":
            nonblock = True
        elif arg == "-w":
            i += 1
            if i >= len(argv):
                fail("flock: missing argument for -w")
            timeout = float(argv[i])
        elif arg == "-c":
            i += 1
            if i >= len(argv):
                fail("flock: missing argument for -c")
            command = ["/bin/sh", "-c", argv[i]]
        elif arg.startswith("-"):
            fail(f"flock: unsupported option {arg}")
        else:
            lockfile = arg
            rest = argv[i + 1 :]
            if command is None and rest:
                command = rest
            return shared, nonblock, timeout, lockfile, command
        i += 1
    fail("usage: flock [-snx] [-w sec] <lockfile> <command> [args...]")


def acquire(fd, shared, nonblock, timeout):
    operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    start = time.monotonic()
    while True:
        try:
            mode = operation | (fcntl.LOCK_NB if nonblock or timeout is not None else 0)
            fcntl.flock(fd, mode)
            return
        except BlockingIOError:
            if nonblock:
                sys.exit(1)
            if timeout is not None and time.monotonic() - start >= timeout:
                sys.exit(1)
            time.sleep(0.1)


def main():
    shared, nonblock, timeout, lockfile, command = parse(sys.argv[1:])
    fd = os.open(lockfile, os.O_RDWR | os.O_CREAT, 0o666)
    acquire(fd, shared, nonblock, timeout)
    if command is None:
        return 0
    result = subprocess.run(command)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
EOF

chmod 0755 "$bin_dir/flock"
"$bin_dir/flock" -c "true" "$prefix/.flock-test"
rm -f "$prefix/.flock-test"

if [ ! -e "$bin_dir/date" ]; then
cat > "$bin_dir/date" <<'EOF'
#!/usr/bin/env python3
import datetime as dt
import os
import subprocess
import sys


def passthrough() -> "None":
    os.execv("/bin/date", ["date", *sys.argv[1:]])


def parse_expr(expr: str) -> dt.datetime:
    if expr.startswith("@"):
        return dt.datetime.fromtimestamp(float(expr[1:]), tz=dt.timezone.utc)

    candidates = [
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ]
    normalized = expr.replace("Z", "+00:00")

    for fmt in candidates:
        try:
            parsed = dt.datetime.strptime(normalized, fmt)
            if parsed.tzinfo is None:
                return parsed.astimezone()
            return parsed
        except ValueError:
            continue

    try:
        parsed = dt.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.astimezone()
        return parsed
    except ValueError:
        passthrough()
        raise AssertionError("unreachable")


def main() -> int:
    argv = sys.argv[1:]
    expr = None
    use_utc = False
    fmt = None
    passthrough_args = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-u":
            use_utc = True
        elif arg == "-d":
            i += 1
            if i >= len(argv):
                return 1
            expr = argv[i]
        elif arg.startswith("+"):
            fmt = arg[1:]
        else:
            passthrough_args.append(arg)
        i += 1

    if expr is None or passthrough_args:
        passthrough()

    parsed = parse_expr(expr)
    if use_utc:
        parsed = parsed.astimezone(dt.timezone.utc)
    elif parsed.tzinfo is not None:
        parsed = parsed.astimezone()

    if fmt is None:
        passthrough()

    sys.stdout.write(parsed.strftime(fmt))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF
fi

if [ ! -e "$bin_dir/stat" ]; then
cat > "$bin_dir/stat" <<'EOF'
#!/usr/bin/env python3
import os
import subprocess
import sys


def passthrough() -> "None":
    os.execv("/usr/bin/stat", ["stat", *sys.argv[1:]])


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) == 3 and argv[0] == "-c" and argv[1] == "%Y":
        try:
            st = os.stat(argv[2])
        except OSError as exc:
            print(f"stat: {exc}", file=sys.stderr)
            return 1
        print(int(st.st_mtime))
        return 0

    passthrough()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF
fi

if [ ! -e "$bin_dir/mktemp" ]; then
cat > "$bin_dir/mktemp" <<'EOF'
#!/usr/bin/env python3
import os
import sys
import tempfile


def passthrough() -> "None":
    os.execv("/usr/bin/mktemp", ["mktemp", *sys.argv[1:]])


def main() -> int:
    argv = sys.argv[1:]
    directory = None
    create_dir = False
    template = None
    passthrough_args = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-d":
            create_dir = True
        elif arg == "--tmpdir":
            i += 1
            if i >= len(argv):
                return 1
            directory = argv[i]
        elif arg.startswith("--tmpdir="):
            directory = arg.split("=", 1)[1]
        elif arg.startswith("-"):
            passthrough_args.append(arg)
        else:
            template = arg
        i += 1

    if passthrough_args:
        passthrough()

    if template is None:
        prefix = "tmp."
        suffix = ""
    else:
        if "X" not in template:
            passthrough()
        x_count = len(template) - len(template.rstrip("X"))
        if x_count == 0:
            passthrough()
        prefix = template[:-x_count]
        suffix = ""

    if create_dir:
        path = tempfile.mkdtemp(prefix=prefix, suffix=suffix, dir=directory)
    else:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
        os.close(fd)

    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF
fi

chmod 0755 "$bin_dir/date" "$bin_dir/stat" "$bin_dir/mktemp"
"$bin_dir/date" -u -d "1970-01-01 00:00:00 +0000" "+%Y-%m-%dT%H:%M:%S+00:00" >/dev/null
"$bin_dir/stat" -c "%Y" "$0" >/dev/null
tmp_test=$("$bin_dir/mktemp" --tmpdir="$prefix")
rm -f "$tmp_test"
"$bin_dir/sed" --version | head -n 1 >/dev/null
"$bin_dir/cp" --version | head -n 1 >/dev/null
if [ -x "$bin_dir/chmod" ]; then
    "$bin_dir/chmod" --version | head -n 1 >/dev/null
fi
if [ -x "$bin_dir/split" ]; then
    "$bin_dir/split" --version | head -n 1 >/dev/null
fi

echo "Installed Buildroot host tools into $prefix"
