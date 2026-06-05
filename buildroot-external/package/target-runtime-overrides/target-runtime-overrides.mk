################################################################################
#
# Car Thing target runtime overrides
#
################################################################################

# The target uses a modern Buildroot libc on the stock Linux 4.9 kernel.
# libc exposes posix_spawn(), but the call returns ENOSYS on this kernel and
# makes Python's subprocess module fail instead of falling back to fork/exec.
# Do not expose the unusable API in the target interpreter.
PYTHON3_CONF_ENV += \
	ac_cv_func_posix_spawn=no \
	ac_cv_func_posix_spawnp=no \
	ac_cv_func_posix_spawn_file_actions_addclosefrom_np=no
