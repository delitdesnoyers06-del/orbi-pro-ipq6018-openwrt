# Step-by-step porting guide

Target: Netgear Orbi Pro WiFi 6 Mini, router **SXR30** or satellite **SXS30** (Qualcomm IPQ6018,
fused secure boot).  Result: upstream OpenWrt running from NAND slot B, stock firmware untouched in
slot A, WiFi + all four GbE ports working, optionally as a wired dumb AP with roaming.

Read `HARDWARE.md` first (what the device is) and `GOTCHAS.md` (what will bite you).  Estimated time:
2-3 hours including the backup, most of it waiting.

---

## 0. Requirements

* The device, opened, with UART pads connected (3.3 V logic, **GND shared only**): a USB-TTL adapter
  or a Flipper Zero in "USB-UART Bridge" mode.  115200 8N1.
* A Linux workstation with `python3`, `dtc`/`fdtget` (device-tree-compiler), `ubinize` +
  `mkfs.ubifs`/`ubi-*` (mtd-utils), `curl`, `tar`.  `mkimage` is **not** needed.
* An Ethernet cable between the workstation and a LAN port of the Orbi (that is how the device is
  backed up and flashed - see gotcha 1).
* Be ready to lose the device's MAC/serial-specific settings.  Nothing here changes them, but an
  accident can.

```bash
export WORKDIR=$PWD        # holds work/ and dumps/
export ORBI_TARGET_IP=<the vendor system's LAN address>
```

## 1. Serial console + boot log

```bash
scripts/start-capture.sh 3600 /dev/ttyUSB0     # timestamped raw capture + .ts sidecar
# power-cycle the device; you should see SBL1 -> U-Boot -> kernel
```

Confirm in the log:

* `U-boot dni1 V0.4 ... NAND flash <256|512>MB; RAM 512MB` - note the NAND size, it decides which
  layout you build (see HARDWARE.md),
* `*** Warning - bad CRC, using default environment`,
* `secure boot fuse is enabled`,
* then the vendor kernel boots and you land on an autologin root shell.

If the port shows a `>` prompt, it is not a serial bridge; if nothing at all, swap TX/RX.

## 2. A network shell (and why not ssh)

The stock rootfs has **no ssh server**.  Start a passwordless one from the console and use it for all
transfers - it is the only channel that works when the workstation's firewall blocks inbound
connections:

```bash
scripts/net-shell.sh        # sends ^C over UART, then: telnetd -l /bin/sh -p 2323
export ORBI_TARGET_IP=<vendor-system-ip>
python3 scripts/tcmd.py 'uname -a; cat /proc/mtd'
```

This shell dies on every reboot: re-arm it from the console each time.  It is a root shell - lab only.

## 3. Full backup (do not skip)

```bash
python3 scripts/dump.py dumps 0-33      # 34 partitions, every one sha256-verified against the device
```

`dump.py` probes each partition with `dd | sha256sum` (which stops at a bad block), then pulls exactly
that many bytes as base64 through the telnet shell and compares hashes.  ~2 MiB/s; a 512 MiB chip takes
about 6 minutes.

Keep `dumps/mtd22-firmware.bin` (slot A) and `dumps/mtd25-firmware2.bin`/`mtd13..mtd16`
(`0:APPSBL*`, `0:ART`) somewhere safe: they are your only byte-exact rollback for those regions.

> UART-only recovery (device no longer boots, no shell): `uboot.py` + `flash_erase`/`nand write` from
> the bootloader prompt, or NMRP (`nmrp`) with the stock firmware image.

## 4. Prove the U-Boot environment persists

An unattended custom boot needs `saveenv` to survive a reset.  Verify it on *your* unit before you
rely on it (different NAND size = different U-Boot build):

```bash
python3 scripts/uboot.py --sep '@@' --cmds "setenv orbi_test 123@@saveenv"
# ... it resets at the end; catch the prompt again and read it back:
python3 scripts/uboot.py --sep '@@' --cmds "printenv orbi_test"
```

`orbi_test=123` after a reboot means you can set a persistent `bootcmd`.

## 5. Build the OpenWrt image set

```bash
scripts/fetch-openwrt-artifacts.sh          # sysupgrade kernel+rootfs, and the rbr350 initramfs (DTB)
DEV=sxr30 scripts/openwrt-build-image.sh    # or DEV=sxs30
```

The build produces, in `work/openwrt/build/`:

| file | what it is |
|---|---|
| `<dev>.dtb` | upstream DTB with a **fixed-partitions** NAND table (the 16 QTI partitions, `boarddata`, a `vendor_hdr` window, and a `rootfs` partition over slot B) and all four GE ports enabled |
| `openwrt-<dev>.itb` | FIT (kernel + that DTB), with crc32/sha1 digests, booted by the vendor U-Boot with a plain `bootm` |
| `openwrt-<dev>.ubi` | UBI image: volumes `kernel`, `rootfs` (squashfs), `rootfs_data` (autoresize -> the overlay grows to fill slot B at first boot) |

Sanity check before writing anything:

```bash
UBI=work/openwrt/build/openwrt-sxr30.ubi
python3 scripts/openwrt-ubi-parse.py $UBI            # volumes + PEB count
dtc -I dtb -O dts work/openwrt/build/sxr30.dtb | grep -E 'label = "rootfs"' -A1
fdtget -t s work/openwrt/build/openwrt-sxr30.itb /configurations/config@1 kernel   # -> kernel-1
```

Size check: the UBI is ~13 MiB and must be smaller than the slot-B partition (75 MiB on the satellite,
109 MiB on the router).

## 6. Install into slot B (slot A stays intact)

```bash
scripts/openwrt-install-telnet.sh sxr30 $ORBI_TARGET_IP
```

Steps it performs (all of them verified):

1. push `openwrt-<dev>.ubi` to `/tmp` over the telnet shell (base64 through the pty, ~1.2 MiB/s),
2. `sha256sum` on the target == local hash,
3. `flash_erase /dev/mtd25 0 0` (the whole slot-B partition - leftovers break UBI attach),
4. `nandwrite -p /dev/mtd25 /tmp/openwrt-<dev>.ubi`,
5. read the first N blocks back and compare sha256.

Then point U-Boot at it:

```bash
DEV=sxr30 scripts/openwrt-set-bootcmd.sh
```

which saves this environment (it reboots the box and drives the `IPQ6018#` prompt):

```
stockboot    = mii write 0x01 0x0 0x800; sleep 2; nmrp; bootdni; boot_DNI_secureboot
mtdids       = nand0=nand0
mtdparts     = mtdparts=nand0:0x6d00000@0x8800000(rootfs)      # sxs30: 0x4b00000@0x6600000
openwrt_boot = nand set_partition_offset 0; ubi part rootfs; ubi read 0x44000000 kernel; bootm 0x44000000
bootargs     = console=ttyMSM0,115200n8
bootcmd      = run openwrt_boot; run stockboot
```

`run stockboot` is kept as the fallback; the rollback is
`setenv bootcmd 'run stockboot'; saveenv; reset` (or at the prompt before the env was ever written).

The first boot ends with `Please press Enter to activate this console.` on the UART - **the default
rootfs has no WiFi and a static 192.168.1.1 on `br-lan` with only the CPU port in the bridge**.

## 7. WiFi: per-unit calibration + MACs (the two things that are not automatic)

### 7.1 The calibration file

`ath11k` needs `/lib/firmware/ath11k/IPQ6018/hw1.0/cal-ahb-c000000.wifi.bin` (64 KiB, per unit; the
`board-2.bin` from the `ipq-wifi-netgear_rbk350` package is model-wide and already in the image).
Without it: `qmi failed to load CAL data file` / `failed to load board data file: -12` and **no
wiphy**, so no wifi at all.

It is produced by the **vendor** firmware from `0:ART` at boot.  Get it exactly once, from your own
unit:

```bash
# 1. (U-Boot prompt) temporarily boot the stock system again
setenv bootcmd 'run stockboot'; saveenv; reset
# 2. after it boots, re-arm the shell and copy the vendor-generated blob out
scripts/net-shell.sh
python3 scripts/pull_b64.py /lib/firmware/IPQ6018/caldata.bin caldata.bin 65536
# 3. back to OpenWrt
#    (U-Boot prompt) setenv bootcmd 'run openwrt_boot; run stockboot'; saveenv; reset
# 4. install it (persists: /lib/firmware is on the overlay)
ssh root@<openwrt-ip> 'mkdir -p /lib/firmware/ath11k/IPQ6018/hw1.0'
ssh root@<openwrt-ip> 'cat > /lib/firmware/ath11k/IPQ6018/hw1.0/cal-ahb-c000000.wifi.bin' < caldata.bin
# 5. reboot (or `rmmod ath11k_ahb; modprobe ath11k_ahb`) and check
ssh root@<openwrt-ip> 'ls /sys/class/ieee80211/; dmesg | grep -i ath11k | tail'
```

Never copy another unit's calibration (it is RF calibration data, not a config file), and never edit
byte 0x0a of that file - the firmware validates it against the body (see GOTCHAS).

### 7.2 MAC addresses

On units whose `0:ART` still holds the factory placeholder MACs (`00:03:7f:12:34:5x`), the firmware
randomises the phy MAC on **every boot**.  Fix it at the interface level in UCI (stable, survives
reboots, no firmware tricks):

```bash
uci set wireless.default_radio0.macaddr='<base+2>'   # 5 GHz AP
uci set wireless.default_radio1.macaddr='<base+1>'   # 2.4 GHz AP
uci commit wireless
```

`<base>` is the unit's Ethernet MAC (`ubus call network.interface.lan status | grep macaddress`,
or the vendor label).  Take **unused** addresses from that block - do not reuse the LAN ports' MACs.

## 8. Turn it into a wired dumb AP (and merge several APs)

Two things matter: the box must not be a router/DHCP server, and the radios must be on the right
channels with a shared roaming domain.

```bash
# all four Ethernet jacks in one bridge, static address, gateway/DNS = your real router
uci set network.@device[0].ports='lan1 lan2 lan3 lan4'
uci set network.lan.ipaddr='192.168.1.10/24'
uci set network.lan.netmask='255.255.255.0'
uci set network.lan.gateway='192.168.1.1'
uci set network.lan.dns='192.168.1.1'
uci commit network

# no DHCP/DNS on the box - the main router leases
uci set dhcp.lan.ignore='1'; uci set dhcp.lan.dhcpv4='disabled'
uci set dhcp.lan.dhcpv6='disabled'; uci set dhcp.lan.ra='disabled'; uci commit dhcp

# hostname
uci set system.@system[0].hostname='OrbiAP'; uci commit system
```

Wireless (`/etc/config/wireless`), identical on **every** AP you want to merge:

```
config wifi-device 'radio0'          # 5 GHz
	option type 'mac80211'
	option path 'platform/soc@0/c000000.wifi'
	option band '5g'
	option channel '36'          # pick a different 80 MHz block per AP, or a DFS ch (52/100)
	option htmode 'HE80'
	option country 'XX'          # your regulatory domain, e.g. FR / DE / US
	option txpower '20'
	option rssi_reject_assoc_rssi '-72'      # <- on the *device*, not the iface (gotcha 6)
	option rssi_ignore_probe_request '-80'

config wifi-iface 'default_radio0'
	option device 'radio0'
	option network 'lan'
	option mode 'ap'
	option ssid 'CHANGEME'
	option encryption 'psk2'
	option key 'CHANGEME'
	option ieee80211k '1'          # 802.11k: neighbour reports
	option ieee80211v '1'          # 802.11v: BSS transition management
	option ieee80211r '1'          # 802.11r: fast transition
	option mobility_domain 'a1b2' # SAME value on every AP of the group
	option ft_psk_generate_local '1'
	option ft_over_ds '1'
	option reassociation_deadline '1000'
	option macaddr '<stable MAC from 7.2>'
```

(the 2.4 GHz `radio1` section is the same with `.../c000000.wifi+1`, `band '2g'`, `htmode 'HE20'`
and its own channel).

Notes:

* `wpad-basic-mbedtls` (the image default) **cannot do k/v/r** - install `wpad-mesh-mbedtls` (or
  `wpad-mbedtls`) first, otherwise hostapd refuses the interface with
  `unknown configuration item 'bss_transition'`.
* Different channels per AP: an 80 MHz block overlaps its neighbours.  With two APs, put them in
  different blocks (e.g. 36 and 52, or 36 and 100) and use different 2.4 GHz channels (1/6/11).
* Band steering: `apk add usteer luci-app-usteer` and
  `/etc/config/usteer`: `local_mode 1`, `band_steering_min_snr '-75'`,
  `band_steering_interval 20000`, `assoc_steering 1`, `probe_steering 1`.  With several APs each runs
  its own local instance; coordinated cross-AP steering would need `dawn` (or all APs as usteer nodes)
  - optional.
* Clients roam between the APs by themselves once SSID/key/`mobility_domain` match and both APs send
  802.11k/v.  Min-RSSI rejects make them leave early; they cannot be *pulled* to the better AP
  without coordinated steering.

Verify:

```bash
iwinfo                     # both APs: right channel, HE mode, "WPA2-PSK / FT-PSK (CCMP)"
grep -E 'rrm_|bss_transition|mobility_domain|ft_' /var/run/hostapd-phy*.conf
iw dev | grep -E 'ssid|channel'
# from a laptop:
nmcli -f BSSID,SSID,CHAN,SIGNAL dev wifi list | grep <ssid>
```

## 9. Persistence, updates and rollback

* Everything you changed lives on the overlay (`rootfs_data` in slot B): packages, `/etc/config`,
  `/lib/firmware/cal-...`.  It grows to fill the partition on first boot (49 MiB on a satellite slot,
  74 MiB on a router slot).
* Kernel/rootfs update without touching anything else:
  `ubiupdatevol /dev/ubi0_0 <new.itb>` (kernel) or rebuild the UBI and rewrite slot B
  (`openwrt-install-telnet.sh` again).
* **Do not blanket `apk upgrade`** on these boxes: the snapshot feed moves, and a newer
  wpad/wifi-scripts can require a netifd method your image does not have (gotcha 5).  Install the
  specific packages you need, and keep `wpad`/`hostapd-common`/`wifi-scripts` consistent with each
  other.
* Rollback at the `IPQ6018#` prompt: `setenv bootcmd 'run stockboot'; saveenv; reset`.
  Rollback of slot B bytes: `flash_erase /dev/mtd25 0 0` + `nandwrite -p /dev/mtd25 dumps/mtd25-*.bin`
  from the vendor system.
* `sysupgrade` is not usable (no vendor U-Boot replacement, custom FIT+UBI layout).

## 10. If it does not boot

| symptom | likely cause |
|---|---|
| `bootm` returns, then `nmrp`/TFTP mode, then the prompt | FIT not found / bad size argument (U-Boot parses sizes as hex) - check `mtdparts`, run `ubi part rootfs; ubi info l` |
| `Kernel panic - not syncing: VFS: Unable to mount root fs`, `available partitions` ends at `mtdblock15` | the DTB's `partitions` node was not applied (wrong node name, gotcha 2) - the kernel fell back to the SMEM table |
| kernel boots, `ubi0: attached`, then panic | wrong slot-B offset/size, or the UBI was written into the wrong mtd (check `mtdparts` and `nand read`) |
| boots, no wifi, `failed to load board data file` | calibration file missing/invalid (step 7.1) |
| wifi up, but BSSID changes every boot | phy MAC randomised; set `option macaddr` (step 7.2) |
| hostapd: `unknown configuration item 'bss_transition'` | `wpad-basic-*` installed - install `wpad-mesh-mbedtls` |
| `bootcmd` changes do not stick | `saveenv` did not work on your unit - test it (step 4) |
