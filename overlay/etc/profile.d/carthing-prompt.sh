# Show the unique device name in the shell prompt so an SSH session immediately
# makes clear which Car Thing you're on. hostname is set from the real
# controller MAC by the runtime (see ble_transport.init_ble).
if [ "$PS1" ]; then
	_ct_host=$(hostname)
	if [ "$(id -u)" -eq 0 ]; then
		export PS1="${_ct_host}:\w# "
	else
		export PS1="${_ct_host}:\w\$ "
	fi
	unset _ct_host
fi
