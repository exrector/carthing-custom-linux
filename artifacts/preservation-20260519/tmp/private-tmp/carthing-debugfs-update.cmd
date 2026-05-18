rm /etc/default/carthing
write overlay/etc/default/carthing /etc/default/carthing
rm /etc/init.d/rcS
write overlay/etc/init.d/rcS /etc/init.d/rcS
write overlay/etc/init.d/S11-runtime-state /etc/init.d/S11-runtime-state
rm /usr/lib/carthing/ble_transport.py
write overlay/usr/lib/carthing/ble_transport.py /usr/lib/carthing/ble_transport.py
rm /usr/lib/carthing/media_remote.py
write overlay/usr/lib/carthing/media_remote.py /usr/lib/carthing/media_remote.py
rm /usr/libexec/carthing/contract-selftest
write overlay/usr/libexec/carthing/contract-selftest /usr/libexec/carthing/contract-selftest
rm /usr/libexec/carthing/init-wrapper
write overlay/usr/libexec/carthing/init-wrapper /usr/libexec/carthing/init-wrapper
stat /etc/init.d/S11-runtime-state
stat /usr/lib/carthing/media_remote.py
stat /usr/lib/carthing/ble_transport.py
close
