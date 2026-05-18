all:
	$(CC) $(CFLAGS) $(CPPFLAGS) -o carthing-iap2-agent iap2_agent.c $(LDFLAGS) $(LDLIBS) $(shell pkg-config --libs --cflags gio-2.0 gio-unix-2.0 glib-2.0) -lbluetooth -lpthread
