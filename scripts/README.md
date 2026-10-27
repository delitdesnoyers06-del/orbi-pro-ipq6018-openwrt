# Toolkit

All scripts are generic (no site-specific addresses, keys or credentials) and were used on real
hardware for the port described in `../GUIDE.md`.  `WORKDIR` (default: the current directory) is where
`work/`, `dumps/` and `logs/` live.

## Serial console (UART 115200 8N1)

| script | purpose |
|---|---|
| `start-capture.sh [secs] [port]` | background, timestamped raw capture (`logs/<port>-<ts>.log` + `.ts`), writes `logs/.current` |
| `console_cmd.py '<cmd>' [port]` | sends **Ctrl-C** (to break out of the vendor `hyd` shell-grab), then one command, prints the new output |
| `uboot.py` | reboots the box, spams a key during `bootdelay=2`, runs `--cmds` at the `IPQ6018#` prompt, then resumes with `reset`.  `--sep '@@'` lets values contain `;`, `--assume-prompt` skips detection |

## Network shell and transfers (host-initiated; survives a blocking firewall)

| script | purpose |
|---|---|
| `net-shell.sh` | over the UART, starts `telnetd -l /bin/sh -p 2323` on the stock firmware (no ssh there) |
| `status.sh` | ping + ssh/telnet port check |
| `tcmd.py '<cmd>' [timeout] [host] [port]` | run one command in the telnet shell and strip echo/markers |
| `orbi_tcp.py` | the telnet client used by the other tools (`ORBI_TARGET_IP` env, default 192.168.1.1) |
| `pull_b64.py <device> <out> <bytes>` | pull a device file (base64, decoded per line - busybox wraps at 76 chars) |
| `push_b64.py <local> <target-path>` | push a file to the device over the pty (verifies size + sha256) |
| `cmd.sh` | convenience wrapper for `tcmd.py` |

## Backup / inspection

| script | purpose |
|---|---|
| `dump.py [outdir] [filter]` | **verified** backup of `mtd0..mtd33` (probe readable length + sha256 on the device, pull exactly that many bytes, compare; writes `.meta` + `SHA256SUMS-verified.txt`) |
| `parse_dni_image.py <firmware-dump>` | parse a Netgear/DNI slot image: ELF container, certificate segment, FIT, rootfs uImage header, squashfs |
| `openwrt-ubi-parse.py <ubi-image>` | raw UBI inspector (EC/VID headers, volume table, PEB counts) |

## Build (no `mkimage` needed)

| script | purpose |
|---|---|
| `fetch-openwrt-artifacts.sh [url]` | download the upstream snapshot artifacts (rbs350 sysupgrade kernel+rootfs, rbr350 initramfs for the router DTB) |
| `openwrt-make-dtb.py <stock.dts> <out.dts> [--layout sxs30\|sxr30] [--rootfs-off ... --rootfs-size ...] [--model ...] [--compatible ...]` | rewrite the NAND `partitions` node into a `fixed-partitions` table (QTI partitions + `boarddata` nvmem + `vendor_hdr` window + slot-B `rootfs`), enable all four GE ports, optional model rename |
| `openwrt-make-fit.py --kernel ... --dtb ... --out ...` | build the U-Boot FIT with `dtc` + python-computed crc32/sha1 digests (mkimage-free, reproducible) |
| `openwrt-build-image.sh` | `DEV=sxs30\|sxr30` -> `work/openwrt/build/{<dev>.dtb, openwrt-<dev>.itb, openwrt-<dev>.ubi, SHA256SUMS-<dev>}` |

Requirements: `dtc`, `fdtget`, `ubinize` (mtd-utils), `python3`, `curl`, `tar`.  Optional:
`uboot-tools` for `mkimage` (not used).

## Install / boot configuration

| script | purpose |
|---|---|
| `openwrt-install-telnet.sh [dev] [target-ip]` | push the UBI, `flash_erase`+`nandwrite` **slot B only**, read back and verify |
| `openwrt-set-bootcmd.sh` | set `stockboot`/`openwrt_boot`/`mtdparts`/`bootcmd` and `saveenv` (reboots the target over ssh or telnet, or uses an already-open prompt) |

## Device-side helpers used by the guide

```bash
# kernel-only update once installed
ubiupdatevol /dev/ubi0_0 <new.itb>

# stability test for the wifi phy MAC
for p in /sys/class/ieee80211/phy*/macaddress; do echo "$p $(cat $p)"; done

# what netifd gave hostapd
grep -E 'rrm_|bss_transition|mobility_domain|ft_|rssi_' /var/run/hostapd-phy*.conf
```
