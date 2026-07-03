CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra
LDFLAGS ?= -lm

vxvm: vxvm.c
	$(CC) $(CFLAGS) -o vxvm vxvm.c $(LDFLAGS)

debug: vxvm.c
	$(CC) -g -O0 -fsanitize=address,undefined -Wall -Wextra -o vxvm vxvm.c $(LDFLAGS)

test: vxvm
	cd .. && python3 tests_vm.py

clean:
	rm -f vxvm

.PHONY: debug test clean
