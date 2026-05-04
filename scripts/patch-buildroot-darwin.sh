#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <buildroot-dir>" >&2
    exit 1
fi

buildroot_dir=$1

if [ "$(uname -s)" != "Darwin" ]; then
    exit 0
fi

pkg_autotools="$buildroot_dir/package/pkg-autotools.mk"
fakeroot_mk="$buildroot_dir/package/fakeroot/fakeroot.mk"
makedevs_c="$buildroot_dir/package/makedevs/makedevs.c"
toolchain_wrapper_c="$buildroot_dir/toolchain/toolchain-wrapper.c"
toolchain_wrapper_mk="$buildroot_dir/toolchain/toolchain-wrapper.mk"
python3_mk="$buildroot_dir/package/python3/python3.mk"
libzlib_mk="$buildroot_dir/package/libzlib/libzlib.mk"
rustc_mk="$buildroot_dir/package/rustc/rustc.mk"
rust_bin_hash="$buildroot_dir/package/rust-bin/rust-bin.hash"
check_hash_sh="$buildroot_dir/support/download/check-hash"
download_git_sh="$buildroot_dir/support/download/git"
mkusers_sh="$buildroot_dir/support/scripts/mkusers"
fs_common_mk="$buildroot_dir/fs/common.mk"

if [ ! -f "$pkg_autotools" ]; then
    echo "missing Buildroot file: $pkg_autotools" >&2
    exit 1
fi

if [ ! -f "$fakeroot_mk" ]; then
    echo "missing Buildroot file: $fakeroot_mk" >&2
    exit 1
fi

if [ ! -f "$makedevs_c" ]; then
    echo "missing Buildroot file: $makedevs_c" >&2
    exit 1
fi

if [ ! -f "$toolchain_wrapper_c" ]; then
    echo "missing Buildroot file: $toolchain_wrapper_c" >&2
    exit 1
fi

if [ ! -f "$toolchain_wrapper_mk" ]; then
    echo "missing Buildroot file: $toolchain_wrapper_mk" >&2
    exit 1
fi

if [ ! -f "$python3_mk" ]; then
    echo "missing Buildroot file: $python3_mk" >&2
    exit 1
fi

if [ ! -f "$libzlib_mk" ]; then
    echo "missing Buildroot file: $libzlib_mk" >&2
    exit 1
fi

if [ ! -f "$rustc_mk" ]; then
    echo "missing Buildroot file: $rustc_mk" >&2
    exit 1
fi

if [ ! -f "$rust_bin_hash" ]; then
    echo "missing Buildroot file: $rust_bin_hash" >&2
    exit 1
fi

if [ ! -f "$check_hash_sh" ]; then
    echo "missing Buildroot file: $check_hash_sh" >&2
    exit 1
fi

if [ ! -f "$download_git_sh" ]; then
    echo "missing Buildroot file: $download_git_sh" >&2
    exit 1
fi

if [ ! -f "$mkusers_sh" ]; then
    echo "missing Buildroot file: $mkusers_sh" >&2
    exit 1
fi

if [ ! -f "$fs_common_mk" ]; then
    echo "missing Buildroot file: $fs_common_mk" >&2
    exit 1
fi

patch_autopoint=0
if [ ! -x /bin/true ]; then
    if [ ! -x /usr/bin/true ]; then
        echo "missing /usr/bin/true on Darwin host" >&2
        exit 1
    fi
    patch_autopoint=1
fi

if [ "$patch_autopoint" -eq 1 ]; then
python3 - "$pkg_autotools" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '$(2)_AUTORECONF_ENV += AUTOPOINT=/bin/true'
new = '$(2)_AUTORECONF_ENV += AUTOPOINT=/usr/bin/true'

if new in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected pattern not found in {path}")

path.write_text(text.replace(old, new, 1))
PY
fi

python3 - "$fakeroot_mk" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = 'HOST_FAKEROOT_DEPENDENCIES = host-acl'
new = 'HOST_FAKEROOT_DEPENDENCIES ='

if 'HOST_FAKEROOT_DEPENDENCIES =\n' in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected pattern not found in {path}")

path.write_text(text.replace(old, new, 1))
PY

python3 - "$makedevs_c" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
marker = '#define GROUP_PATH "etc/group"  /* MUST be relative */\n'

insertion = r'''
#ifdef __APPLE__
static struct passwd *carthing_fgetpwent(FILE *stream)
{
	static char *line;
	static size_t linecap;
	static struct passwd entry;
	char *fields[7];
	char *cursor;
	ssize_t linelen;
	int i;

	while ((linelen = getline(&line, &linecap, stream)) != -1) {
		if (linelen > 0 && line[linelen - 1] == '\n')
			line[--linelen] = '\0';
		if (linelen > 0 && line[linelen - 1] == '\r')
			line[--linelen] = '\0';
		if (line[0] == '\0' || line[0] == '#')
			continue;

		cursor = line;
		fields[0] = cursor;
		for (i = 1; i < 7; ++i) {
			cursor = strchr(cursor, ':');
			if (cursor == NULL)
				break;
			*cursor++ = '\0';
			fields[i] = cursor;
		}
		if (i != 7)
			continue;

		entry.pw_name = fields[0];
		entry.pw_passwd = fields[1];
		entry.pw_uid = (uid_t)strtoul(fields[2], NULL, 10);
		entry.pw_gid = (gid_t)strtoul(fields[3], NULL, 10);
		entry.pw_gecos = fields[4];
		entry.pw_dir = fields[5];
		entry.pw_shell = fields[6];
		return &entry;
	}

	return NULL;
}

static struct group *carthing_fgetgrent(FILE *stream)
{
	static char *line;
	static size_t linecap;
	static struct group entry;
	static char *empty_members[] = { NULL };
	char *fields[4];
	char *cursor;
	ssize_t linelen;
	int i;

	while ((linelen = getline(&line, &linecap, stream)) != -1) {
		if (linelen > 0 && line[linelen - 1] == '\n')
			line[--linelen] = '\0';
		if (linelen > 0 && line[linelen - 1] == '\r')
			line[--linelen] = '\0';
		if (line[0] == '\0' || line[0] == '#')
			continue;

		cursor = line;
		fields[0] = cursor;
		for (i = 1; i < 4; ++i) {
			cursor = strchr(cursor, ':');
			if (cursor == NULL)
				break;
			*cursor++ = '\0';
			fields[i] = cursor;
		}
		if (i != 4)
			continue;

		entry.gr_name = fields[0];
		entry.gr_passwd = fields[1];
		entry.gr_gid = (gid_t)strtoul(fields[2], NULL, 10);
		entry.gr_mem = empty_members;
		return &entry;
	}

	return NULL;
}

#define fgetpwent carthing_fgetpwent
#define fgetgrent carthing_fgetgrent
#endif
'''

if 'carthing_fgetpwent' in text:
    raise SystemExit(0)

if marker not in text:
    raise SystemExit(f"expected marker not found in {path}")

path.write_text(text.replace(marker, marker + insertion, 1))
PY

python3 - "$toolchain_wrapper_c" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
marker = '#include <stdbool.h>\n'
insertion = r'''
#ifdef __APPLE__
#include <mach-o/dyld.h>
#define program_invocation_short_name getprogname()
#endif
'''

if '#include <mach-o/dyld.h>' in text:
    raise SystemExit(0)

if marker not in text:
    raise SystemExit(f"expected marker not found in {path}")

path.write_text(text.replace(marker, marker + insertion, 1))
PY

python3 - "$toolchain_wrapper_c" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """\t} else {\n\t\tbasename = progpath;\n\t\tabsbasedir = malloc(PATH_MAX + 1);\n\t\tret = readlink(\"/proc/self/exe\", absbasedir, PATH_MAX);\n\t\tif (ret < 0) {\n\t\t\tperror(__FILE__ \": readlink\");\n\t\t\treturn 2;\n\t\t}\n\t\tabsbasedir[ret] = '\\0';\n\t\tfor (i = ret; i > 0; i--) {\n\t\t\tif (absbasedir[i] == '/') {\n\t\t\t\tabsbasedir[i] = '\\0';\n\t\t\t\tif (++count == 2)\n\t\t\t\t\tbreak;\n\t\t\t}\n\t\t}\n\t}\n"""
new = """\t} else {\n\t\tbasename = progpath;\n\t\tabsbasedir = malloc(PATH_MAX + 1);\n#ifdef __APPLE__\n\t\tuint32_t executable_path_size = PATH_MAX;\n\t\tif (_NSGetExecutablePath(absbasedir, &executable_path_size) != 0) {\n\t\t\terrno = ENAMETOOLONG;\n\t\t\tperror(__FILE__ \": _NSGetExecutablePath\");\n\t\t\treturn 2;\n\t\t}\n\t\tchar *resolved_path = realpath(absbasedir, NULL);\n\t\tif (resolved_path == NULL) {\n\t\t\tperror(__FILE__ \": realpath\");\n\t\t\treturn 2;\n\t\t}\n\t\tfree(absbasedir);\n\t\tabsbasedir = resolved_path;\n\t\tret = strlen(absbasedir);\n#else\n\t\tret = readlink(\"/proc/self/exe\", absbasedir, PATH_MAX);\n\t\tif (ret < 0) {\n\t\t\tperror(__FILE__ \": readlink\");\n\t\t\treturn 2;\n\t\t}\n\t\tabsbasedir[ret] = '\\0';\n#endif\n\t\tfor (i = ret; i > 0; i--) {\n\t\t\tif (absbasedir[i] == '/') {\n\t\t\t\tabsbasedir[i] = '\\0';\n\t\t\t\tif (++count == 2)\n\t\t\t\t\tbreak;\n\t\t\t}\n\t\t}\n\t}\n"""

if '_NSGetExecutablePath(absbasedir, &executable_path_size)' in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected block not found in {path}")

path.write_text(text.replace(old, new, 1))
PY

python3 - "$toolchain_wrapper_mk" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """define TOOLCHAIN_WRAPPER_BUILD
\t$(HOSTCC) $(HOST_CFLAGS) $(TOOLCHAIN_WRAPPER_ARGS) \\
\t\t-s -Wl,--hash-style=$(TOOLCHAIN_WRAPPER_HASH_STYLE) \\
\t\ttoolchain/toolchain-wrapper.c \\
\t\t-o $(@D)/toolchain-wrapper
endef
"""
new = """ifeq ($(shell uname -s),Darwin)
TOOLCHAIN_WRAPPER_HOST_LDFLAGS = -s
else
TOOLCHAIN_WRAPPER_HOST_LDFLAGS = -s -Wl,--hash-style=$(TOOLCHAIN_WRAPPER_HASH_STYLE)
endif

define TOOLCHAIN_WRAPPER_BUILD
\t$(HOSTCC) $(HOST_CFLAGS) $(TOOLCHAIN_WRAPPER_ARGS) \\
\t\t$(TOOLCHAIN_WRAPPER_HOST_LDFLAGS) \\
\t\ttoolchain/toolchain-wrapper.c \\
\t\t-o $(@D)/toolchain-wrapper
endef
"""

if 'TOOLCHAIN_WRAPPER_HOST_LDFLAGS = -s -Wl,--hash-style=$(TOOLCHAIN_WRAPPER_HASH_STYLE)' in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected block not found in {path}")

path.write_text(text.replace(old, new, 1))
PY

python3 - "$python3_mk" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '\tLDFLAGS="$(HOST_LDFLAGS) -Wl,--enable-new-dtags" \\\n'
new = '\tLDFLAGS="$(HOST_LDFLAGS)" \\\n'

if new in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected pattern not found in {path}")

path.write_text(text.replace(old, new, 1))
PY

python3 - "$libzlib_mk" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """define LIBZLIB_CONFIGURE_CMDS
\t(cd $(@D); rm -rf config.cache; \\
\t\t$(TARGET_CONFIGURE_ARGS) \\
\t\t$(TARGET_CONFIGURE_OPTS) \\
\t\tCFLAGS=\"$(TARGET_CFLAGS) $(LIBZLIB_PIC)\" \\
\t\t./configure \\
\t\t$(LIBZLIB_SHARED) \\
\t\t--prefix=/usr \\
\t)
endef
"""
new = """define LIBZLIB_CONFIGURE_CMDS
\t(cd $(@D); rm -rf config.cache; \\
\t\t$(TARGET_CONFIGURE_ARGS) \\
\t\t$(TARGET_CONFIGURE_OPTS) \\
\t\tCFLAGS=\"$(TARGET_CFLAGS) $(LIBZLIB_PIC)\" \\
\t\t./configure \\
\t\t$(LIBZLIB_SHARED) \\
\t\t--uname=Linux \\
\t\t--prefix=/usr \\
\t)
endef
"""

if '--uname=Linux \\' in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected block not found in {path}")

path.write_text(text.replace(old, new, 1))
PY

python3 - "$rustc_mk" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = 'RUSTC_HOST_NAME = $(RUSTC_HOST_ARCH)-unknown-linux-gnu\n'
new = """ifeq ($(shell uname -s),Darwin)
RUSTC_HOST_NAME = $(RUSTC_HOST_ARCH)-apple-darwin
else
RUSTC_HOST_NAME = $(RUSTC_HOST_ARCH)-unknown-linux-gnu
endif
"""

if 'RUSTC_HOST_NAME = $(RUSTC_HOST_ARCH)-apple-darwin' in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected pattern not found in {path}")

path.write_text(text.replace(old, new, 1))
PY

python3 - "$rust_bin_hash" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
marker = '# From https://static.rust-lang.org/dist/rust-1.88.0-aarch64-unknown-linux-gnu.tar.xz.sha256\n'
insertion = """# From https://static.rust-lang.org/dist/rust-1.88.0-aarch64-apple-darwin.tar.xz.sha256
sha256  9d64ea19e4051422428991b2c66bf108699f1ff11cc090466474902efad4db96  rust-1.88.0-aarch64-apple-darwin.tar.xz
# From https://static.rust-lang.org/dist/rust-1.88.0-x86_64-apple-darwin.tar.xz.sha256
sha256  421d34e45b9a17a51cf32351332f5c2a9dc944aad36d23bedc526912fcbd2fec  rust-1.88.0-x86_64-apple-darwin.tar.xz
"""

if 'rust-1.88.0-aarch64-apple-darwin.tar.xz' in text:
    raise SystemExit(0)

if marker not in text:
    raise SystemExit(f"expected marker not found in {path}")

path.write_text(text.replace(marker, insertion + marker, 1))
PY

python3 - "$check_hash_sh" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """    # mapfile reads all lines, even the last one if it is missing a \\n\n    mapfile -t hash_lines <\"${h_file}\"\n    for hash_line in \"${hash_lines[@]}\"; do\n"""
new = """    while IFS= read -r hash_line || [ -n \"${hash_line}\" ]; do\n"""
broken = """    while IFS= read -r hash_line || [ -n \"${hash_line}\" ]; do\n        read -r t h f <<<\"${hash_line}\"\n        case \"${t}\" in\n            ''|'#'*)\n                # Skip comments and empty lines\n                continue\n                ;;\n            *)\n                if [ \"${f}\" = \"${base}\" ]; then\n                    check_one_hash \"${t}\" \"${h}\" \"${file}\" \"${h_file}\"\n                    : $((nb_checks++))\n                fi\n                ;;\n        esac\n    done\n"""
fixed = """    while IFS= read -r hash_line || [ -n \"${hash_line}\" ]; do\n        read -r t h f <<<\"${hash_line}\"\n        case \"${t}\" in\n            ''|'#'*)\n                # Skip comments and empty lines\n                continue\n                ;;\n            *)\n                if [ \"${f}\" = \"${base}\" ]; then\n                    check_one_hash \"${t}\" \"${h}\" \"${file}\" \"${h_file}\"\n                    : $((nb_checks++))\n                fi\n                ;;\n        esac\n    done <\"${h_file}\"\n"""

if 'done <"${h_file}"' in text:
    raise SystemExit(0)

if broken in text:
    path.write_text(text.replace(broken, fixed, 1))
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected pattern not found in {path}")

text = text.replace(old, new, 1)
text = text.replace('    done\n', '    done <"${h_file}"\n', 1)
path.write_text(text)
PY

python3 - "$download_git_sh" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """mapfile -d \"\" files < <(\n    set -o pipefail  # Constrained to this sub-shell\n    find . -print0 \\\n    |_plain_git check-attr --stdin -z export-subst \\\n    |(i=0\n      while read -r -d \"\" val; do\n        case \"$((i++%3))\" in\n          (0)   path=\"${val}\";;\n          (1)   ;; # Attribute name, always \"export-subst\", as requested\n          (2)\n            if [ \"${val}\" = \"set\" ]; then\n                printf \"%s\\0\" \"${path}\"\n            fi;;\n        esac\n      done\n     )\n)\n"""
new = """files=()\nwhile IFS= read -r -d \"\" file; do\n    files+=(\"${file}\")\ndone < <(\n    set -o pipefail  # Constrained to this sub-shell\n    find . -print0 \\\n    |_plain_git check-attr --stdin -z export-subst \\\n    |(i=0\n      while read -r -d \"\" val; do\n        case \"$((i++%3))\" in\n          (0)   path=\"${val}\";;\n          (1)   ;; # Attribute name, always \"export-subst\", as requested\n          (2)\n            if [ \"${val}\" = \"set\" ]; then\n                printf \"%s\\0\" \"${path}\"\n            fi;;\n        esac\n      done\n     )\n)\n"""

if new in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected pattern not found in {path}")

path.write_text(text.replace(old, new, 1))
PY

python3 - "$mkusers_sh" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """    # Read in all the file in memory, exclude empty lines and comments\n    # mapfile reads all lines, even the last one if it is missing a \\n\n    mapfile -t ENTRIES < <( sed -r -e 's/#.*//; /^[[:space:]]*$/d;' \"${USERS_TABLE}\" )\n"""
new = """    # Read in all the file in memory, exclude empty lines and comments\n    while IFS= read -r line || [ -n \"${line}\" ]; do\n        ENTRIES+=(\"${line}\")\n    done < <( sed -r -e 's/#.*//; /^[[:space:]]*$/d;' \"${USERS_TABLE}\" )\n"""

if new in text:
    raise SystemExit(0)

if old not in text:
    raise SystemExit(f"expected pattern not found in {path}")

path.write_text(text.replace(old, new, 1))
PY

python3 - "$fs_common_mk" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old_runner = '\tPATH=$$(BR_PATH) FAKEROOTDONTTRYCHOWN=1 $$(HOST_DIR)/bin/fakeroot -- $$(FAKEROOT_SCRIPT)\n'
new_runner = """ifeq ($(shell uname -s),Darwin)
\tPATH=$$(BR_PATH) sudo -n $$(FAKEROOT_SCRIPT)
else
\tPATH=$$(BR_PATH) FAKEROOTDONTTRYCHOWN=1 $$(HOST_DIR)/bin/fakeroot -- $$(FAKEROOT_SCRIPT)
endif
"""
old_cleanup = '\t$(Q)rm -rf $$(TARGET_DIR)\n'
new_cleanup = """ifeq ($(shell uname -s),Darwin)
\tPATH=$$(BR_PATH) sudo -n rm -rf $$(TARGET_DIR)
else
\t$(Q)rm -rf $$(TARGET_DIR)
endif
"""

if 'PATH=$$(BR_PATH) sudo -n $$(FAKEROOT_SCRIPT)' not in text:
    if old_runner not in text:
        raise SystemExit(f"expected fakeroot runner not found in {path}")
    text = text.replace(old_runner, new_runner, 1)

if 'PATH=$$(BR_PATH) sudo -n rm -rf $$(TARGET_DIR)' not in text:
    if old_cleanup not in text:
        raise SystemExit(f"expected fakeroot cleanup not found in {path}")
    text = text.replace(old_cleanup, new_cleanup, 1)

path.write_text(text)
PY
