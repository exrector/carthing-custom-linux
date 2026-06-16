0069f6f Zero-config transcode is project law; Line out removed from visible outputs
64bd280 docs: transcode-hub vision pinned, pipeline design, AAC-decode as the gate
27c9c88 Reference libsbc compiled freestanding for the device: encoder runs x70 realtime
531ad1e docs: line-out is live — chain map, discoveries, next steps
73ad409 Line-out chain LIVE end-to-end: iPhone SBC decoded to a RUNNING T9015 DAC
7ecb270 Chip work floor 3 COMPLETE: SBC decoder, bit-exact with ffmpeg, 1.7x realtime
5d723da connect_source auto-retry for sleeping iPhone; sink frame dumper for decoder dev
997f472 docs: final floor map — only the decoder remains; exact integration anchors for Codex
65a82f8 Chip work floors 2.5-5: sink process, socket protocol, bridge splice, gated endpoint
ea47009 docs: chip-work floor map for Codex — floors 1-2 done, decoder next
632b11f Chip work floor 2: AudioLocalSink — queue + player thread + decoder socket
6476671 T9015 local audio output: bare-ioctl ALSA engine, first stone of the chip work
552ba9d docs: task B+ refined — T9015 was proven 2026-05-24, live kernel already carries the path
739a2f9 docs: task B+ for Codex — probe the T9015 DAC playback path (owner-raised priority)
1754fce docs: overnight assignment for Codex — radio-tune test, audiodsp research, GUI-process design
ade2095 Adult audio path, stage 1: radio tuning per stream phase
492af14 Radio starvation fix: receiver loop honors backoff; standby pages no strangers mid-stream
