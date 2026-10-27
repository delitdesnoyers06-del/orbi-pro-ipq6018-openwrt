# Measured hardware and boot facts (Netgear Orbi Pro WiFi 6 Mini, IPQ6018 "starling")

Everything below was measured on real units (one router `SXR30`, one satellite `SXS30`) - not taken
from datasheets.  Values are per-variant where they differ.  Do not publish unit-unique data (serials,
MACs, calibration) when re-sharing this file.

## SoC / board

| item | value |
|---|---|
| SoC | Qualcomm **IPQ6018**, DT compatible `qcom,ipq6018`, board `AP-CP03-C1` (`qcom,ipq6018-cp03`) |
| cores / clock | 4x Cortex-A53, 800 MHz CPU, 466 MHz DDR (NSS core 0 active) |
| RAM | 512 MiB DDR3 (Linux reports ~425 MiB available) |
| switch/PHY | QCA8075 5-port GbE PHY package, PSGMII; `qca-ppe` (NSS) + `qca-edma`; netdevs `lan1..lan4` (DSA) |
| radios | 2x ath11k (5 GHz `c000000.wifi`, 2.4 GHz `c000000.wifi+1`), dual-band WiFi 6 |
| serial | 115200 8N1 on `ttyMSM0`, autologin root shell in the vendor firmware |
| recovery | Netgear **NMRP** server in U-Boot (`nmrp`), TFTP (`tftpboot`/`tftpsrv`), no USB |

## NAND - two hardware variants

| | SXS30 (satellite) | SXR30 (router) |
|---|---|---|
| chip | Winbond **W29N02GZ, 256 MiB**, ONFI ID `1590aaef` | Winbond **W29N04GZ, 512 MiB**, ONFI ID `1590acef` |
| geometry | 128 KiB erase / 2048 B page / 64 B OOB, SLC | same |
| U-Boot banner | `dni1 V0.4 ... NAND flash 256MB; RAM 512MB` | `... NAND flash 512MB; RAM 512MB` |
| slot A `firmware` | `0x01b0000` + `0x4b00000` (75 MiB) | `0x01b0000` + `0x6d00000` (109 MiB) |
| slot B `firmware2` | `0x6600000` + `0x4b00000` | `0x8800000` + `0x6d00000` |
| `rootfs2` | `0x6ae0000` | `0x8ce0000` |
| `reserved` (free) | ~6.5 MiB | ~190 MiB |

Everything up to `mtd22` (`firmware`) has the **same offset and size** on both, which is why a single
set of scripts covers both: only the slot-B window changes.  Both variants share the same SoC, RAM,
switch, PHY and radios, and the vendor ships one kernel + one DTB for both models (router vs satellite
is decided at runtime from `boarddata1`).

## Partition map (offsets from the boot log; identical for mtd0..mtd21)

```
0x0000000 0x0180000 0:SLB1        0x1100000 0x0080000 0:ART          <- wifi calibration, keep forever
0x0180000 0x0100000 0:MIBIB       0x1180000 ..       (slot A firmware starts)
0x0280000 0x0080000 0:BOOTCONFIG  0x1b00000 0x4e0000  kernel  (mtd23, signed container + rootfs uImage hdr)
0x0300000 0x0080000 0:BOOTCONFIG1 0x1fe0000 +slot    rootfs  (mtd24, squashfs, CRC32-only in the uImage hdr)
0x0380000 0x0380000 0:QSEE        <slot B base>      firmware2 (= kernel2 + rootfs2)
0x0700000 0x0380000 0:QSEE_1      ..                 language / cert / mtdoops / router_analytics
0x0a80000 0x0080000 0:DEVCFG      ..                 ntgrdata  (UBI: config, traffic, devtable, ...)
0x0b00000 0x0080000 0:DEVCFG_1    ..                 reserved  (unused)
0x0b80000 0x0080000 0:RPM         ..                 nand0     (whole chip)
0x0c00000 0x0080000 0:RPM_1
0x0c80000 0x0080000 0:CDT
0x0d00000 0x0080000 0:CDT_1
0x0d80000 0x0080000 0:APPSBLENV    <- U-Boot env (saveenv writes here)
0x0e00000 0x0180000 0:APPSBL       <- SIGNED U-Boot, fused secure boot verifies it
0x0f80000 0x0180000 0:APPSBL_1
```

`boarddata1`/`boarddata2` (`0x1300000`/`0x1400000`) hold the serial, model id, MAC base and the A/B
boot selector - read-only for this port.

## Boot chain

```
PBL -> SBL1 -> QSEE -> RPM -> APPSBL (U-Boot "dni1" 2016.01) -> signed ELF container -> FIT kernel
```

* **Secure boot is fused ON** (`is_sec_boot_enabled` -> `secure boot fuse is enabled`).  SBL1 verifies
  QSEE/RPM/APPSBL; **U-Boot itself verifies the kernel** - but that check is *implemented in bootloader
  commands* (`bootdni` -> `secure_authenticate`), not in hardware.  A custom `bootcmd` skips it
  entirely, which is the whole basis of this port.
* The kernel container is a Netgear-signed ELF: X.509/RSA-PSS chain in segment 2, coverage =
  `0x0..0x94`, `0x1000..0x2a38`, `0x3000..0x4c6c48` (`sw_id 0x17`).
* The **rootfs is not signed**: the uImage header at container `0x4dffc0` is CRC32-checked only, and
  the squashfs at `0x4e0000+` is not covered by any signature - that is why rootfs swapping works even
  without the `bootcmd` trick.
* U-Boot prompt: `IPQ6018#` (no `=>`), reached by pressing a key during `bootdelay=2`; it waits
  forever.  There is **no `boot` and no `reboot` command** - resume with `reset` or `run bootcmd`.
  Default env: `bootcmd=mii write 0x01 0x0 0x800; sleep 2; nmrp; bootdni; boot_DNI_secureboot`,
  `ipaddr=192.168.1.1`, `serverip=192.168.1.10`, `bootargs=console=ttyMSM0,115200n8`.
  The env is **invalid on arrival** (`*** Warning - bad CRC, using default environment`) but
  `saveenv` works and persists (verified by writing a test variable and rebooting).
* Useful U-Boot commands present on both variants: `nand read/write/erase/erase.part`,
  `nand set_partition_offset`, `ubi part/info/read/write/create/remove`, `bootm`, `bootdni`, `nmrp`,
  `tftpboot`, `mtdparts`, `boot_partition_set/show`, `delenv`, `is_sec_boot_enabled`.
  **Never run `fuseipq`** (permanent QFPROM fusing).

## Vendor userspace (why some steps look odd)

* Stock rootfs = **OpenWrt Chaos Calmer 15.05.1** (ipq target), squashfs + tmpfs overlay; kernel
  4.4.60, armv7, soft-float, musl.  Everything is 32-bit - an aarch64 userspace can only come from a
  *replacement* kernel, which is exactly what this port installs.
* No dropbear on the stock rootfs (`:22` closed): the network path is `telnetd -l /bin/sh -p 2323`
  started by hand from the UART console.  All transfers are therefore **host-initiated** (works behind
  a firewall that blocks inbound connections to the workstation).
* The vendor web UI is lighttpd + `net-cgi` on `:80`/`:443`; `hyd` + `led-control` periodically grab
  the serial console, so send **Ctrl-C** before typing (that is what `console_cmd.py` does).
* `/proc/mtd`: 35 NAND partitions + 14 UBI volumes from `ntgrdata` (`mtd0..mtd48`).

## What OpenWrt sees after the port (custom DTB, SXR30 example)

```
mtd0..mtd15  0:sbl1 .. 0:art          (fixed-partitions, read-only)
mtd16        vendor_hdr   0x1fc0000   (slot A rootfs uImage header block - maintenance window)
mtd17        boarddata    0x1300000   (nvmem: base MAC)
mtd18        rootfs       0x8800000 + 0x6d00000   <- our UBI (kernel/rootfs/rootfs_data)
```

The OpenWrt `qualcommax` kernel has `CONFIG_MTD_CMDLINE_PARTS` **off**, so `mtdparts=` on the kernel
command line is ignored - the partition table *must* come from the DTB (upstream uses
`qcom,smem-part`, i.e. the bootloader's SMEM table, which contains only the 16 QTI partitions).
