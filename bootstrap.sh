#!/usr/bin/env bash
set -euo pipefail

make -C vm >/dev/null
python3 vxc.py vxc.vx -o /tmp/vxc_s0.vxc
./vm/vxvm --allow-fs /tmp/vxc_s0.vxc vxc.vx /tmp/vxc_s1.vxc
./vm/vxvm --allow-fs /tmp/vxc_s1.vxc vxc.vx /tmp/vxc_s2.vxc
cmp /tmp/vxc_s1.vxc /tmp/vxc_s2.vxc
echo "Fixed-point bootstrap verified ($(stat -c%s /tmp/vxc_s2.vxc) bytes)"
