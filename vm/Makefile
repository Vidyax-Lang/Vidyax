CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra
LDFLAGS ?= -lm

# libcurl backs ai.ask() and get(). Auto-detected via pkg-config; force off
# with `make CURL=0` to build the stub (both raise a catchable error).
CURL ?= $(shell pkg-config --exists libcurl 2>/dev/null && echo 1 || echo 0)
ifeq ($(CURL),1)
  CURL_CFLAGS := -DVX_HAVE_CURL $(shell pkg-config --cflags libcurl)
  CURL_LIBS   := $(shell pkg-config --libs libcurl)
endif

vxvm: vxvm.c
	$(CC) $(CFLAGS) $(CURL_CFLAGS) -o vxvm vxvm.c $(LDFLAGS) $(CURL_LIBS)

debug: vxvm.c
	$(CC) -g -O0 -fsanitize=address,undefined -Wall -Wextra $(CURL_CFLAGS) -o vxvm vxvm.c $(LDFLAGS) $(CURL_LIBS)

test: vxvm
	cd .. && python3 tests_vm.py

clean:
	rm -f vxvm

.PHONY: debug test clean
