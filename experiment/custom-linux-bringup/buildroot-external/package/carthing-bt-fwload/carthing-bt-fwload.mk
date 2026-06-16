################################################################################
#
# carthing-bt-fwload
#
################################################################################

CARTHING_BT_FWLOAD_VERSION = 1.0
CARTHING_BT_FWLOAD_SITE = $(BR2_EXTERNAL_CARTHING_CUSTOM_LINUX_PATH)/package/carthing-bt-fwload/src
CARTHING_BT_FWLOAD_SITE_METHOD = local

define CARTHING_BT_FWLOAD_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(TARGET_CONFIGURE_OPTS) $(MAKE) -C $(@D) \
		CC="$(TARGET_CC)" \
		AR="$(TARGET_AR)" \
		LD="$(TARGET_LD)"
endef

define CARTHING_BT_FWLOAD_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/carthing-bt-fwload $(TARGET_DIR)/usr/bin/carthing-bt-fwload
endef

$(eval $(generic-package))
