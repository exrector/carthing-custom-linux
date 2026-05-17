################################################################################
#
# carthing-btattach-mini
#
################################################################################

CARTHING_BTATTACH_MINI_VERSION = 1.0
CARTHING_BTATTACH_MINI_SITE = $(BR2_EXTERNAL_CARTHING_CUSTOM_LINUX_PATH)/package/carthing-btattach-mini/src
CARTHING_BTATTACH_MINI_SITE_METHOD = local

define CARTHING_BTATTACH_MINI_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(TARGET_CONFIGURE_OPTS) $(MAKE) -C $(@D) \
		CC="$(TARGET_CC)" \
		AR="$(TARGET_AR)" \
		LD="$(TARGET_LD)"
endef

define CARTHING_BTATTACH_MINI_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/carthing-btattach-mini $(TARGET_DIR)/usr/bin/carthing-btattach-mini
endef

$(eval $(generic-package))
