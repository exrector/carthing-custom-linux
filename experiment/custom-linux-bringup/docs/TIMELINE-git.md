7298424 Document microphone capture test
1599974 Separate iAP2 app fields
a45da84 Narrow iAP2 shim surface
0450d24 Map iAP2 message-set boundary
092cf64 Prove sent-only EA02 launch
bec8daf Probe iAP2 message-set rejection
578c098 Isolate iAP2 ACK boundary
2e029d5 Enable classic iAP2 pairing
03e117b Document classic pairing failure
82e3802 Document raw HCI socket breakthrough
73ba280 Refine classic probe ownership handling
889c8de Add classic profile probe scaffold
62db5cd Document classic SDP service proof
9654003 Document external Clock alert evidence
f7b1371 Document BLE alert profile probe
a5ed383 Document negative Live Activity timer test
931e47a Document Live Activities boundary
aef1804 Document ANCS removal and queue proofs
078b37b Document live ANCS notification proof
4350358 Add ANCS notification mirror layer
a9db13b Checkpoint isolate iAP2 test identity and SDP trace
a068060 Checkpoint unify classic test identity with CarThing
c6db8bd Checkpoint add clean-room classic link key cache
7890379 Checkpoint reach classic auth in integrated iAP2 mode
fabe067 Checkpoint trace iPhone-side ACL drop after iAP2 attach
14da1b1 Checkpoint prove classic ACL bring-up for iAP2 mini
98fb0c3 Checkpoint preserve reconnect session artifacts and 10-minute proof
3f35243 Checkpoint record 2-minute BLE reconnect proof
0313c26 Checkpoint add bonded-only BLE reconnect path
5957d3a Checkpoint record clean re-pair reset and classic inquiry proof
18013c4 Checkpoint add clean-room CAFE active connect path
0bdc997 Checkpoint split HID pairing boundary from iAP2 transport
295b60b Checkpoint set classic iAP2 identity and scan policy
b2824fd Checkpoint enable classic transport daemon for iAP2 mini
58ae2c5 Checkpoint prove minimal clean-room SDP responder
e256276 Checkpoint prove local SDP socket path for iAP2 mini
c7fe058 Checkpoint add RFCOMM transport wrapper for iAP2 mini
493ecf0 Checkpoint prove minimal iAP2 link-layer daemon
9331b09 Checkpoint add raw iAP2 framing to mini session daemon
3229ca1 Checkpoint add minimal clean-room iAP2 session daemon
fc09f21 Checkpoint add live AA01 and auth responder backend
16ca256 Checkpoint add iAP2 AA03 auth payload builder
fed4779 Checkpoint prove live ACP3 signature path
d4c4839 Checkpoint align raw mfi probe with ACP3 sign path
eea6214 Checkpoint correct ACP3 sign register map
33b2d34 Checkpoint record apple_mfi sign-path poll mismatch
605e91f Checkpoint record raw I2C PKCS7 certificate extraction
12ef585 Checkpoint add raw I2C apple_mfi fallback probe
db8829e Checkpoint record live apple_mfi kernel blocker
51f3194 Checkpoint add low-level apple_mfi probe
26fb9ae Checkpoint lock MFi archive as reference only
0adf5bc Revert "Checkpoint start isolated MFi iAP2 revival track"
a736174 Checkpoint start isolated MFi iAP2 revival track
ae30700 Checkpoint add bonded reconnect advertising path
135c00b Checkpoint freeze v1 working baseline and reliability pass
0bfec2a Checkpoint prove cold boot and fix stale USB host route
eb649e8 Checkpoint persist HID pairing path and bond storage
5021eb3 Checkpoint move bt runtime autostart into init-wrapper
0103346 Checkpoint prepare attach autostart rootfs
fa94ae9 Checkpoint record live hci-socket runtime proof
8d6c279 Checkpoint pivot Bluetooth runtime to kernel attach path
bfae699 Checkpoint record post-launch HCI probe frontier
aec1e51 Checkpoint narrow fwload post-launch controls
2128b5a Checkpoint lock host-side bring-up rule and fwload frontier
72bf8e0 Checkpoint record fwload toolchain rebuild path
565eea9 Checkpoint track fwload source and Launch RAM fix
65363c7 Checkpoint fix firmware staging for read-only rootfs
6243bb3 Checkpoint record manual Bluetooth runtime frontier
3c47ee4 Checkpoint preserve session state and resume notes
d8b690c Checkpoint clarify staged custom Linux goal
6a31bd2 Checkpoint clean fallback image install path
3bf8c79 Checkpoint simplify local-open service path
95fe9d0 Checkpoint clean access docs and reverse-control hygiene
fd92489 Checkpoint add local-open access profile
bb9458a Checkpoint restore SSH and reverse-agent control path
3778d8f Checkpoint early-userspace diagnostics and host tooling
aa8a1a7 Checkpoint revert early init-wrapper regression
447a68a Checkpoint harden early USB and telnet bootstrap
a8f8893 Archive legacy MFi iAP2 references
ab44128 Checkpoint document storage map and cleanup policy
58cf3de Checkpoint record control rootfs USB gadget flap
0b6e27b Checkpoint support alternate flash bundle path
24cc4e7 Checkpoint restore first-handle burn write path
9fa8efa Checkpoint stabilize burn reconnect settle and release
b82de5d Checkpoint align rootfs flasher with stable mmc path
d37be2a Checkpoint harden rootfs-only burn flasher
9aed0ae Checkpoint match fallback rootfs fs features
3584d0d Checkpoint add reverse control agent path
d67a024 Checkpoint add service IP markers and fallback rootfs build
55cad92 Checkpoint add stage2 network fingerprint
c47896e Checkpoint add busybox emergency ingress
6de3494 Checkpoint add late USB beacon path
e9c0596 Checkpoint add host beacon path for early boot debug
aece82b Checkpoint add HTTP rescue path for boot debug
ddf7d83 Checkpoint bake dropbear host keys into rootfs
1427b17 Checkpoint harden early stage2 network bring-up
b5df041 Checkpoint add init fallback entrypoint
43bfbbe Checkpoint add early init wrapper
0aa239c Checkpoint clean init contract for device1
f621336 Checkpoint widen USB gadget interface matching
18dfa01 Checkpoint custom linux bring-up baseline
