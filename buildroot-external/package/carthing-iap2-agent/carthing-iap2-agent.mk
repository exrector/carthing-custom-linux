################################################################################
#
# carthing-iap2-agent
#
################################################################################

CARTHING_IAP2_AGENT_VERSION = 1.0
CARTHING_IAP2_AGENT_SITE = $(BR2_EXTERNAL_CARTHING_CUSTOM_LINUX_PATH)/package/carthing-iap2-agent/src
CARTHING_IAP2_AGENT_SITE_METHOD = local
CARTHING_IAP2_AGENT_DEPENDENCIES = bluez5_utils dbus glib2

define CARTHING_IAP2_AGENT_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(TARGET_CONFIGURE_OPTS) $(MAKE) -C $(@D) \
		CC="$(TARGET_CC)" \
		AR="$(TARGET_AR)" \
		LD="$(TARGET_LD)"
endef

define CARTHING_IAP2_AGENT_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/carthing-iap2-agent $(TARGET_DIR)/usr/bin/carthing-iap2-agent
endef

$(eval $(generic-package))
