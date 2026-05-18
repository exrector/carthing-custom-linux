################################################################################
#
# carthing-iap2-mini
#
################################################################################

CARTHING_IAP2_MINI_VERSION = 1.0
CARTHING_IAP2_MINI_SITE = $(BR2_EXTERNAL_CARTHING_CUSTOM_LINUX_PATH)/package/carthing-iap2-mini/src
CARTHING_IAP2_MINI_SITE_METHOD = local

define CARTHING_IAP2_MINI_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(TARGET_CONFIGURE_OPTS) $(MAKE) -C $(@D) \
		CC="$(TARGET_CC)" \
		AR="$(TARGET_AR)" \
		LD="$(TARGET_LD)"
endef

define CARTHING_IAP2_MINI_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/carthing-iap2-mini $(TARGET_DIR)/usr/bin/carthing-iap2-mini
endef

$(eval $(generic-package))
