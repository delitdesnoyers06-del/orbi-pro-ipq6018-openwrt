# GOTCHAS - every trap that cost real time on this port

Symptoms first, so you can find the entry while you are staring at a broken box.

---

### 1. The stock firmware has no ssh, and the firewall blocks reverse connections
**Symptom:** `ssh: connect to port 22: Connection refused`; any `nc`/listener started on the target
never gets a connection.
**Fix:** start `telnetd -l /bin/sh -p 2323` from the **console** (`scripts/net-shell.sh`) and make
every transfer **host-initiated** (`pull_b64.py` / `push_b64.py`).  The shell dies on reboot - re-arm
it after every reboot.  Also: the workstation may be running `ufw`, so never design a workflow where
the device connects *to* you.

### 2. A DTB with a wrongly-named partitions node silently does nothing
**Symptom:** Linux boots but `/proc/mtd` shows only 16 partitions (`0:sbl1..0:art`), `ubi.mtd=...`
cannot attach, `VFS: Unable to mount root fs`, and the panic lists partitions only up to `mtdblock15`.
**Cause:** the kernel's `ofpart` parser matches a child node **named `partitions`**.  A generator bug
produced `papartitions` (two stale characters from an earlier text edit), so the node was ignored and
the kernel fell back to `qcom,smem-part` = the bootloader's SMEM table.
**Fix:** when rewriting a DTS programmatically, locate the block **after** all other text edits
(offsets taken earlier go stale).  Verify with
`dtc -I dtb -O dts <dtb> | grep -n 'partitions {'` and `grep 'label = "rootfs"' -A1`.

### 3. `mtdparts=` on the kernel command line does nothing
**Symptom:** `Unknown kernel command line parameters "mtdparts=..."`.
**Cause:** the OpenWrt `qualcommax` kernel has `CONFIG_MTD_CMDLINE_PARTS` **off**.
**Fix:** put the table in the DTB (`fixed-partitions`).  For reference, the NAND master name is
`qcom_nand.0` (`drivers/mtd/nand/raw/qcom_nandc.c`: `mtd->name = "qcom_nand.%d"`), which is what a
`mtdparts=` id would have to match.

### 4. U-Boot parses sizes as **hex**, and a stuck partition offset breaks `nand read`
**Symptom:** `nand read` fails with *"Size exceeds partition or device limit"*.
**Fix:** pass hex (`0xCC7204`, not `13398532`); and run `nand set_partition_offset 0` before reading -
the vendor boot path leaves a non-zero base behind.
Also: **Linux MTD offsets are not raw NAND offsets** (bad blocks are skipped differently); locate
staged data in U-Boot with `nand read 0x44000000 <off> 0x800; md.l 0x44000000 1`.

### 5. A mixed snapshot package set breaks WiFi/LuCI with cryptic errors

This is the single most common failure when packages are installed *after* the rootfs was built: the
snapshot feed moves, the image does not.  Three flavours, all with the same root cause and the same
rule - **install from the same snapshot, or keep the family consistent, but never upgrade blindly**:

**Symptom A - no 802.11k/v/r:** `hostapd: Line NN: unknown configuration item 'bss_transition'` ->
interface refused.  Cause: `wpad-basic-mbedtls` (the image default) has no k/v/r.  Fix:
`apk del wpad-basic-mbedtls; apk add wpad-mesh-mbedtls`.

**Symptom B - no VAPs at all:** `Error loading ucode: ... does not export 'macaddr_keep' ... from
"common"`, or `No MAC address from netifd ... Failed to invoke function 'macaddr_get'`.  Cause: newer
`wpad-mesh`/`wifi-scripts` ucode scripts expect a netifd method the image does not have.  Fix: keep the
newer wpad **binary** but restore the image's ucode scripts:
`for f in common.uc wdev.uc wifi-detect.uc hostapd.uc wpa_supplicant.uc; do cp -f /rom/usr/share/hostap/$f /usr/share/hostap/$f; done`
then `/etc/init.d/wpad restart`.

**Symptom C - LuCI answers `502 Bad Gateway`** (*"The process did not produce any response"*) and
`logread` shows:
```
Runtime error: Unable to dlopen file '/usr/lib/ucode/html.so':
  Error relocating /usr/lib/ucode/html.so: ucv_metamethod_lookup: symbol not found
In module(), file /usr/share/ucode/luci/dispatcher.uc, line 1, byte 1
  called from anonymous function (/www/cgi-bin/luci:7:22)
```
Cause: the current feed's `ucode-mod-html` / `-log` / `lucihttp` are built against the **new**
`libucode.so.2026xxxx`, while `/usr/bin/ucode` is still the image's older build linked to the older
SONAME -> the interpreter cannot load its own plugin, the LUCI CGI dies, uhttpd reports 502.
Diagnose with `ucode -e 'require("html"); print("ok\n")'`.
Fix: upgrade the **whole ucode family together** (core *and* every `ucode-mod-*`), then restart uhttpd:
```bash
apk upgrade ucode ucode-mod-digest ucode-mod-fs ucode-mod-html ucode-mod-log \
            ucode-mod-nl80211 ucode-mod-rtnl ucode-mod-ubus ucode-mod-uci \
            ucode-mod-uclient ucode-mod-uloop    # add libucode2026* if the feed names it
/etc/init.d/uhttpd restart
```
Verify every plugin loads:
`ucode -e 'require("fs"); require("ubus"); require("uci"); require("html"); require("log"); require("rtnl"); require("nl80211"); require("uloop"); print("ok\n")'`
Keep a copy of the working set (`tar czf /root/ucode-backup.tgz /usr/bin/ucode /usr/lib/libucode.so.* /usr/lib/ucode`)
before upgrading - `/rom` also holds the image's original build, so a restore is always possible.

### 6. `rssi_*` options belong on the radio, not the interface
**Symptom:** min-RSSI steering does nothing; `/var/run/hostapd-phy*.conf` shows `rssi_reject_assoc_rssi=0`.
**Cause:** netifd reads them from the `wifi-device` (radio) section.
**Fix:** put them there and verify in the generated hostapd config.

### 7. The calibration file is mandatory, per unit, and validated
**Symptom:** `ath11k ... qmi failed to load CAL data file:cal-ahb-c000000.wifi.bin`,
`failed to load board data file: -12`, `ls /sys/class/ieee80211/` empty, `iw dev` shows nothing.
**Fix:** install the **vendor-generated** `/lib/firmware/IPQ6018/caldata.bin` as
`/lib/firmware/ath11k/IPQ6018/hw1.0/cal-ahb-c000000.wifi.bin` (64 KiB, from `0:ART` at vendor boot -
see GUIDE step 7.1).  Never copy it between units, and do not edit its header: the 16-bit field at
offset `0x0a` is a per-unit checksum of the body - changing it (even by one) makes the firmware reject
the blob with `failed to wait board file download request: -110`.

### 8. The phy MAC can be randomised on every boot
**Symptom:** with a valid calibration the radios work, but `/sys/class/ieee80211/phy*/macaddress` is
a different `…:xx:xx` every boot (and the AP BSSID changes with it), even if you patch the calibration
header's MAC slots to your own addresses.
**Fix:** set the MAC per AP interface in UCI: `option macaddr '<unit base MAC +1/+2>'`.  Verified: the
interface comes up with exactly that address and it is stable across reboots.
(Do **not** use `option bssid`; on modern OpenWrt that path goes through netifd's `macaddr_get`.)

### 9. `flash_erase` takes **byte offsets**, not block indices
**Symptom:** after `flash_erase <mtddev> <index> <blocks>` the partition is garbage and the box
panics.
**Fix:** `flash_erase /dev/mtd25 0 0` (whole partition) or `flash_erase /dev/mtd25 0x4c0000 1`
(start offset in bytes, then count of 128 KiB blocks).

### 10. Rebooting to the U-Boot prompt: the watchdog eats commands
**Symptom:** a long batch of prompt commands causes a reset mid-sequence, and after each reset the
**first character of the next line is lost** (`mw.b` arrives as `w.b`, `nand erase` as `and erase`).
**Fix:** keep prompt sessions short and batched; do bulk work from a running OS.  `uboot.py` supports
`--sep` so values may contain `;`, and `--assume-prompt` when the box is already sitting at the prompt.

### 11. `HIT ANY KEY` is only a 2 second window, and NMRP is in the boot path
**Symptom:** failed `bootm` drops the box into Netgear NMRP/TFTP "Upgrade Mode" which times out after
2-4 minutes (`ERROR: can't get kernel image!`) and returns to the prompt.  Budget ~3 minutes per
failure, and remember the prompt has **no `boot`/`reboot`** - use `reset` or `run bootcmd`.

### 12. The vendor console is periodically stolen by `hyd`/`led-control`
**Symptom:** typed characters echo but never execute.
**Fix:** send **Ctrl-C** first (that is what `console_cmd.py` does).  Also `echo 1 > /proc/sys/kernel/printk`
when kernel wlan spam floods the UART.

### 13. `saveenv` is only proven after *your* unit proves it
**Symptom:** you set `bootcmd`, it works, and after a power cycle the box boots the vendor firmware.
**Fix:** test it first: `setenv orbi_test 123; saveenv` -> `reset` -> `printenv orbi_test`.  The env
is invalid on arrival (`bad CRC, using default environment`), and `delenv` (which is
`nand erase 0xd80000 0x80000`) restores the compiled defaults.

### 14. `apk` fails with TLS errors when the clock is wrong
**Symptom:** `wgetSSL verify error: unknown error` / `ERROR: wget: exited with error 5` on every feed;
`https://downloads.openwrt.org` fails to open; only a few packages listed.
**Cause:** no RTC - the clock starts at the rootfs build date.
**Fix:** `date -u -s "<host date and time>"`, then `apk update`.

### 15. Never touch the fused/board data regions
`0:SBL1`, `0:MIBIB`, `0:QSEE*`, `0:APPSBL*`, `0:ART*`, `boarddata1/2` are either verified by fused
secure boot or hold the unit's identity/calibration.  Editing them bricks the device (no USB recovery).
**Never run the U-Boot `fuseipq` command** - it burns QFPROM bits permanently.
Only ever write the **inactive** slot (`mtd25` = `firmware2`).

### 16. The stock vendor boot still works - and it must stay working
Occupying slot B removes the vendor's A/B second slot, so verify `run stockboot` **after** the install
(`setenv bootcmd 'run stockboot'; saveenv; reset`).  On some units the vendor rootfs uImage header
CRC (`hcrc`) is stale and the vendor boot path flips the boot partition on error; if `run stockboot`
starts failing after you wrote slot B, restore the slot-A header block from your backup
(`nand write` of the 128 KiB block that holds it, exposed to OpenWrt as the `vendor_hdr` partition).

### 17. HTTPS is silently disabled (and plain HTTP may then be unreachable)
**Symptom:** `http://<ap>/` works, `https://<ap>/` refuses the connection, `netstat -ltn` shows only
`:80`.  Or the reverse: a browser is redirected to a dead https URL (LuCI unreachable) while `curl`
still shows :80 answering.
**Cause:** `uhttpd.main.listen_https` is configured by default, but the TLS listener is only started if
`/etc/uhttpd.crt` + `.key` exist - and the cert is generated by `px5g`, which **is not installed in a
plain snapshot image**.  With `uci get uhttpd.main.redirect_https` = `1` the box then redirects to a
port nothing listens on.
**Fix:**
```bash
apk add px5g-mbedtls              # provides /usr/sbin/px5g
uci set uhttpd.main.redirect_https='0'   # keep plain http working too
uci commit uhttpd
/etc/init.d/uhttpd restart        # init script generates an EC self-signed cert (CN=OpenWrt, 397 days)
netstat -ltn | grep -E ':80 |:443 '
curl -sk -o /dev/null -w '%{http_code}\n' https://<ap>/          # expect 200
curl -s  -o /dev/null -w '%{http_code}\n' https://<ap>/cgi-bin/luci/  # 403/200, never 502
```
The cert is self-signed (browsers warn) - import it or live with the warning; it is a LAN appliance.

### 18. After any package install, check LuCI and WiFi - the feed drifts
A quick post-install smoke test catches every ABI drift described in gotcha 5 *before* you walk away:
```bash
for p in /sys/class/ieee80211/phy*/macaddress; do echo "$p $(cat $p)"; done   # stable MACs, 2 phys
ls /sys/class/ieee80211/                                                     # 2 wiphys, not 0
wifi reload && sleep 20 && iwinfo | grep -E 'ESSID|Access Point|Channel'      # both APs back up
ps | grep -c '[u]steerd'; logread | grep -iE 'hostapd.*(fail|error)' | tail
df -h /overlay | tail -1                                                     # overlay not full
logread | grep -iE 'dlopen|symbol not found' | tail -3                         # ucode ABI ok
```
A `phyrf_bdf`/`cal` error instead means the calibration file is missing (gotcha 7); a missing wiphy
with no error at all is usually a *rejected* cal blob (wrong unit's file, or byte 0x0a edited).
