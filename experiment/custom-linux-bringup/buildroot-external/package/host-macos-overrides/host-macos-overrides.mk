ifeq ($(shell uname -s),Darwin)
HOST_DARWIN_CLANG := $(shell if [ -x /opt/homebrew/opt/llvm/bin/clang ]; then printf %s /opt/homebrew/opt/llvm/bin/clang; elif command -v clang >/dev/null 2>&1; then command -v clang; fi)
HOST_DARWIN_CLANGXX := $(shell if [ -x /opt/homebrew/opt/llvm/bin/clang++ ]; then printf %s /opt/homebrew/opt/llvm/bin/clang++; elif command -v clang++ >/dev/null 2>&1; then command -v clang++; fi)
HOST_DARWIN_APPLE_CLANG := $(shell if [ -x /usr/bin/clang ]; then printf %s /usr/bin/clang; fi)
HOST_DARWIN_APPLE_CLANGXX := $(shell if [ -x /usr/bin/clang++ ]; then printf %s /usr/bin/clang++; fi)

# Buildroot's host-tar Makefile.in does not link libiconv on macOS unless
# configure sees it in LIBS. Keep this override host-only so the target image
# stays free of any BlueZ or unrelated policy baggage.
HOST_TAR_CONF_ENV += LIBS="-liconv"

# host-e2fsprogs selects host-util-linux for libblkid/libuuid, but Darwin does
# not provide the Linux-specific headers required by libmount. Keep only the
# host libraries we actually need and drop the programs/libmount path.
HOST_UTIL_LINUX_CONF_OPTS := $(filter-out --enable-libmount,$(HOST_UTIL_LINUX_CONF_OPTS))
HOST_UTIL_LINUX_CONF_OPTS += --disable-libmount --disable-all-programs

# util-linux's warning probe treats -Wembedded-directive as supported on this
# host because the preprocessor accepts it, but gcc-15 then rejects it during
# compilation. Override the cache result to keep the host build deterministic.
HOST_UTIL_LINUX_CONF_ENV += ul_cv_warn__Wembedded_directive=no

# Homebrew gcc-15 ICEs on libuuid/src/uuid_time.c because util-linux uses a
# weak alias declaration there. Keep the workaround scoped to this host package
# so the rest of the build can still use the default Buildroot host settings.
ifneq ($(HOST_DARWIN_CLANG),)
HOST_UTIL_LINUX_CONF_ENV += \
	CC="$(HOST_DARWIN_CLANG)" \
	GCC="$(HOST_DARWIN_CLANG)" \
	CXX="$(HOST_DARWIN_CLANGXX)" \
	CPP="$(HOST_DARWIN_CLANG) -E"
endif

# Buildroot's host-e2fsprogs enables ELF shared libraries by default, but the
# Darwin linker does not understand the Linux-style -soname flow used there.
# Keep host-e2fsprogs in a plain static/no-ELF-shlibs mode on macOS.
HOST_E2FSPROGS_CONF_OPTS := $(filter-out --enable-elf-shlibs,$(HOST_E2FSPROGS_CONF_OPTS))
HOST_E2FSPROGS_CONF_OPTS += --disable-elf-shlibs

ifneq ($(HOST_DARWIN_CLANG),)
HOST_E2FSPROGS_CONF_ENV += \
	CC="$(HOST_DARWIN_CLANG)" \
	GCC="$(HOST_DARWIN_CLANG)" \
	CXX="$(HOST_DARWIN_CLANGXX)" \
	CPP="$(HOST_DARWIN_CLANG) -E"
endif

# host-gawk enables a macOS-only respawn path when configure finds
# _NSGetExecutablePath, but the upstream build then reaches an undeclared call
# in posix/gawkmisc.c on this host. Buildroot only needs a working host awk, so
# keep this optional Darwin path disabled rather than pulling more platform
# headers or patching the tarball contents.
HOST_GAWK_CONF_ENV += ac_cv_func__NSGetExecutablePath=no

# CPython's Darwin build uses os/log.h, which expects Apple's clang builtins.
# Keep the workaround scoped to the host interpreter only; target python still
# uses the cross toolchain from Buildroot.
ifneq ($(HOST_DARWIN_APPLE_CLANG),)
HOST_PYTHON3_CONF_ENV += \
	CC="$(HOST_DARWIN_APPLE_CLANG)" \
	GCC="$(HOST_DARWIN_APPLE_CLANG)" \
	CXX="$(HOST_DARWIN_APPLE_CLANGXX)" \
	CPP="$(HOST_DARWIN_APPLE_CLANG) -E"
endif

endif
