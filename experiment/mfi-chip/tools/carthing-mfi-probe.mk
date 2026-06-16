################################################################################
#
# carthing-mfi-probe
#
################################################################################

CARTHING_MFI_PROBE_VERSION = 1.0
CARTHING_MFI_PROBE_SITE = $(BR2_EXTERNAL_CARTHING_CUSTOM_LINUX_PATH)/package/carthing-mfi-probe/src
CARTHING_MFI_PROBE_SITE_METHOD = local

define CARTHING_MFI_PROBE_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(TARGET_CONFIGURE_OPTS) $(MAKE) -C $(@D) \
		CC="$(TARGET_CC)" \
		AR="$(TARGET_AR)" \
		LD="$(TARGET_LD)"
endef

define CARTHING_MFI_PROBE_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/carthing-mfi-probe $(TARGET_DIR)/usr/bin/carthing-mfi-probe
endef

$(eval $(generic-package))
