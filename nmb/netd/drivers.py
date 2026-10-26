"""Network Hardware Driver, Chipset Detection, and Driver Installation Subsystem.

Provides comprehensive detection of PCI, PCIe, USB, and onboard network adapters,
driver and firmware inspection via sysfs, ethtool, and kernel ring buffer diagnostics,
along with automated missing driver and firmware installation routines.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.netd.drivers")

SYS_CLASS_NET = Path("/sys/class/net")
SYS_BUS_PCI = Path("/sys/bus/pci/devices")
SYS_BUS_USB = Path("/sys/bus/usb/devices")

# Known PCI and USB Network Vendors
KNOWN_VENDORS = {
    "0x10ec": "Realtek Semiconductor",
    "0x8086": "Intel Corporation",
    "0x14e4": "Broadcom Inc.",
    "0x1d6a": "Aquantia / Marvell",
    "0x14c3": "MediaTek Inc.",
    "0x168c": "Qualcomm Atheros",
    "0x0b95": "ASIX Electronics",
    "0x0bda": "Realtek (USB)",
    "0x04e8": "Samsung",
    "0x2357": "TP-Link",
    "0x0846": "Netgear",
    "0x13b1": "Linksys",
}

# Known Network Chipsets (Vendor, Device ID)
KNOWN_CHIPSETS = {
    # Realtek PCI/PCIe
    ("0x10ec", "0x8168"): "Realtek RTL8168/8111 Gigabit Ethernet",
    ("0x10ec", "0x8169"): "Realtek RTL8169 Gigabit Ethernet",
    ("0x10ec", "0x8161"): "Realtek RTL8111G/H Gigabit Ethernet",
    ("0x10ec", "0x8125"): "Realtek RTL8125 2.5GbE Multi-Gigabit Controller",
    ("0x10ec", "0x8126"): "Realtek RTL8126 5GbE Multi-Gigabit Controller",
    ("0x10ec", "0x3000"): "Realtek RTL8125B 2.5GbE Controller",
    # Realtek Wi-Fi
    ("0x10ec", "0xb822"): "Realtek RTL8822BE 802.11ac Wireless",
    ("0x10ec", "0xc821"): "Realtek RTL8821CE 802.11ac Wireless",
    ("0x10ec", "0xc852"): "Realtek RTL8852AE Wi-Fi 6 Wireless",
    # Intel Ethernet
    ("0x8086", "0x15f2"): "Intel Ethernet Controller I225-V (2.5GbE)",
    ("0x8086", "0x15f3"): "Intel Ethernet Controller I225-LM (2.5GbE)",
    ("0x8086", "0x125b"): "Intel Ethernet Controller I226-V (2.5GbE)",
    ("0x8086", "0x125c"): "Intel Ethernet Controller I226-LM (2.5GbE)",
    ("0x8086", "0x125d"): "Intel Ethernet Controller I226-IT (2.5GbE)",
    ("0x8086", "0x1539"): "Intel Ethernet Controller I211 Gigabit",
    ("0x8086", "0x1533"): "Intel Ethernet Controller I210 Gigabit",
    ("0x8086", "0x15b7"): "Intel Ethernet Connection I219-V Gigabit",
    ("0x8086", "0x15b8"): "Intel Ethernet Connection I219-LM Gigabit",
    ("0x8086", "0x10d3"): "Intel 82574L Gigabit Ethernet",
    ("0x8086", "0x1528"): "Intel Ethernet Converged Network Adapter X540 (10GbE)",
    ("0x8086", "0x1563"): "Intel Ethernet Controller X550 (10GbE)",
    # Intel Wi-Fi
    ("0x8086", "0x2723"): "Intel Wi-Fi 6 AX200 Wireless",
    ("0x8086", "0x2725"): "Intel Wi-Fi 6E AX210 Wireless",
    ("0x8086", "0x7a70"): "Intel Wi-Fi 7 BE200 Wireless",
    # Broadcom
    ("0x14e4", "0x1687"): "Broadcom NetXtreme BCM57786 Gigabit Ethernet",
    ("0x14e4", "0x165f"): "Broadcom NetXtreme BCM5720 Gigabit Ethernet",
    # Aquantia / Marvell Multi-Gig
    ("0x1d6a", "0xd107"): "Aquantia AQtion AQC107 10GbE Multi-Gigabit",
    ("0x1d6a", "0x07b1"): "Marvell AQtion AQC113 10GbE Multi-Gigabit",
    ("0x1d6a", "0x11b1"): "Marvell AQtion AQC113C 10GbE Multi-Gigabit",
    # MediaTek Wi-Fi
    ("0x14c3", "0x7961"): "MediaTek MT7921 Wi-Fi 6 Wireless Adapter",
    ("0x14c3", "0x7922"): "MediaTek MT7922 Wi-Fi 6E Wireless Adapter",
    ("0x14c3", "0x7902"): "MediaTek MT7902 Wireless Adapter",
    # Qualcomm Atheros
    ("0x168c", "0x003e"): "Qualcomm Atheros QCA6174 802.11ac Wireless",
    ("0x168c", "0x0042"): "Qualcomm Atheros QCA9377 802.11ac Wireless",
}


def _run_cmd(cmd: List[str], timeout: float = 6.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def get_ethtool_driver_info(iface: str) -> Dict[str, str]:
    """Retrieve driver name, version, firmware version, and bus info via ethtool."""
    res = {
        "driver": "unknown",
        "version": "",
        "firmware": "",
        "bus_info": "",
    }

    # 1. Sysfs driver symlink check
    driver_link = SYS_CLASS_NET / iface / "device" / "driver"
    if driver_link.exists():
        try:
            res["driver"] = driver_link.resolve().name
        except Exception:
            pass

    # 2. Sysfs firmware version if exposed
    fw_file = SYS_CLASS_NET / iface / "device" / "firmware_version"
    if fw_file.exists():
        try:
            res["firmware"] = fw_file.read_text().strip()
        except Exception:
            pass

    # 3. Query ethtool -i
    ethtool_bin = shutil.which("ethtool") or "/usr/sbin/ethtool"
    if os.path.exists(ethtool_bin):
        try:
            r = _run_cmd([ethtool_bin, "-i", iface], timeout=2.5)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k, v = k.strip().lower(), v.strip()
                        if k == "driver" and v:
                            res["driver"] = v
                        elif k == "version" and v:
                            res["version"] = v
                        elif k == "firmware-version" and v:
                            res["firmware"] = v
                        elif k == "bus-info" and v:
                            res["bus_info"] = v
        except Exception:
            pass

    return res


def get_supported_link_modes(iface: str) -> List[str]:
    """Parse supported speed capabilities (e.g. 10M, 100M, 1G, 2.5G, 5G, 10G)."""
    modes = []
    ethtool_bin = shutil.which("ethtool") or "/usr/sbin/ethtool"
    if not os.path.exists(ethtool_bin):
        return ["Auto-negotiate"]

    try:
        r = _run_cmd([ethtool_bin, iface], timeout=2.5)
        if r.returncode == 0:
            text = r.stdout
            if "10000base" in text or "10000baseT" in text:
                modes.append("10 Gbps (10G)")
            if "5000baseT" in text:
                modes.append("5 Gbps (5G)")
            if "2500baseT" in text or "2500baseX" in text:
                modes.append("2.5 Gbps (2.5G)")
            if "1000baseT" in text or "1000baseX" in text:
                modes.append("1 Gbps (1000M)")
            if "100baseT" in text:
                modes.append("100 Mbps (100M)")
            if "10baseT" in text:
                modes.append("10 Mbps")
    except Exception:
        pass

    return modes or ["Standard Ethernet"]


def detect_all_physical_interfaces() -> List[Dict[str, Any]]:
    """Inspect all physical network interfaces present on the system."""
    from nmb.netd.interfaces import get_ip_addresses, get_mac_address

    interfaces = []
    if not SYS_CLASS_NET.exists():
        return interfaces

    for iface_path in sorted(SYS_CLASS_NET.glob("*")):
        name = iface_path.name
        # Skip loopback and purely virtual software interfaces
        if name == "lo" or name.startswith(("docker", "veth", "br", "tun", "tap", "wg", "dummy", "ppp")):
            continue

        dev_path = iface_path / "device"
        # Only true hardware-backed interfaces have a 'device' link
        if not dev_path.exists():
            continue

        is_wireless = (iface_path / "wireless").exists() or (iface_path / "phy80211").exists()

        # Carrier
        carrier = False
        try:
            cp = iface_path / "carrier"
            if cp.exists() and cp.read_text().strip() == "1":
                carrier = True
        except (OSError, ValueError):
            carrier = False

        # Operstate
        operstate = "unknown"
        try:
            op = iface_path / "operstate"
            if op.exists():
                operstate = op.read_text().strip()
        except OSError:
            pass

        # Speed (catch EINVAL when link down or wifi)
        speed_mbps = None
        try:
            sp = iface_path / "speed"
            if sp.exists():
                val = int(sp.read_text().strip())
                if val > 0:
                    speed_mbps = val
        except (OSError, ValueError):
            speed_mbps = None

        # Duplex
        duplex = ""
        try:
            dp = iface_path / "duplex"
            if dp.exists():
                duplex = dp.read_text().strip()
        except OSError:
            pass

        # MTU
        mtu = 1500
        try:
            mp = iface_path / "mtu"
            if mp.exists():
                mtu = int(mp.read_text().strip())
        except (OSError, ValueError):
            pass

        # Driver details
        drv_info = get_ethtool_driver_info(name)

        # Bus Type & Hardware ID
        bus_type = "onboard"
        bus_path = ""
        chipset_name = ""
        vendor_id = ""
        device_id = ""

        try:
            real_dev = dev_path.resolve()
            bus_path = str(real_dev)
            if "pci" in bus_path:
                bus_type = "pci"
                vf = real_dev / "vendor"
                df = real_dev / "device"
                if vf.exists() and df.exists():
                    vendor_id = vf.read_text().strip().lower()
                    device_id = df.read_text().strip().lower()
                    chipset_name = KNOWN_CHIPSETS.get((vendor_id, device_id), "")
                    if not chipset_name and vendor_id in KNOWN_VENDORS:
                        chipset_name = f"{KNOWN_VENDORS[vendor_id]} Controller ({device_id})"
            elif "usb" in bus_path:
                bus_type = "usb"
                # Scan parents for USB vendor/product
                curr = real_dev
                for _ in range(4):
                    if (curr / "idVendor").exists():
                        vendor_id = (curr / "idVendor").read_text().strip().lower()
                        device_id = (curr / "idProduct").read_text().strip().lower()
                        chipset_name = KNOWN_CHIPSETS.get((f"0x{vendor_id}", f"0x{device_id}"), "")
                        prod_file = curr / "product"
                        if not chipset_name and prod_file.exists():
                            chipset_name = prod_file.read_text().strip()
                        break
                    curr = curr.parent
            elif "sdio" in bus_path:
                bus_type = "sdio"
                chipset_name = "Broadcom / Cypress SDIO Wi-Fi"
            elif "platform" in bus_path:
                bus_type = "platform"
                if "bcmgenet" in drv_info["driver"]:
                    chipset_name = "Broadcom BCM54213 Gigabit (Raspberry Pi)"
        except Exception:
            pass

        if not chipset_name:
            if is_wireless:
                chipset_name = f"Wireless Network Adapter ({drv_info['driver']})"
            else:
                chipset_name = f"Ethernet Controller ({drv_info['driver']})"

        supported_modes = get_supported_link_modes(name)

        interfaces.append({
            "name": name,
            "mac": get_mac_address(name),
            "carrier": carrier,
            "operstate": operstate,
            "speed_mbps": speed_mbps,
            "duplex": duplex,
            "mtu": mtu,
            "ip_addresses": get_ip_addresses(name),
            "is_wireless": is_wireless,
            "driver": drv_info["driver"],
            "driver_version": drv_info["version"],
            "firmware_version": drv_info["firmware"],
            "bus_info": drv_info["bus_info"] or (name if bus_type == "platform" else ""),
            "bus_type": bus_type,
            "vendor_id": vendor_id,
            "device_id": device_id,
            "chipset_name": chipset_name,
            "supported_modes": supported_modes,
        })

    return interfaces


def detect_hardware_controllers() -> List[Dict[str, Any]]:
    """Scan PCI and USB buses to detect network controllers, including those lacking drivers."""
    controllers = []

    # 1. PCI scan
    if SYS_BUS_PCI.exists():
        for pci_path in sorted(SYS_BUS_PCI.glob("*")):
            class_file = pci_path / "class"
            if not class_file.exists():
                continue
            try:
                class_hex = class_file.read_text().strip().lower()
                # 0x020000 = Ethernet, 0x028000 = Network/Wi-Fi
                if class_hex.startswith("0x02"):
                    vendor_file = pci_path / "vendor"
                    device_file = pci_path / "device"
                    driver_link = pci_path / "driver"

                    vendor = vendor_file.read_text().strip().lower() if vendor_file.exists() else ""
                    device = device_file.read_text().strip().lower() if device_file.exists() else ""
                    driver = driver_link.resolve().name if driver_link.exists() else ""

                    chipset = KNOWN_CHIPSETS.get((vendor, device), "")
                    vendor_name = KNOWN_VENDORS.get(vendor, vendor)
                    if not chipset:
                        chipset = f"{vendor_name} Network Controller ({device})"

                    # Find associated network interface if bound
                    iface_name = ""
                    net_dirs = list((pci_path / "net").glob("*")) if (pci_path / "net").exists() else []
                    if net_dirs:
                        iface_name = net_dirs[0].name

                    controllers.append({
                        "bus": "pci",
                        "bus_id": pci_path.name,
                        "vendor_id": vendor,
                        "device_id": device,
                        "vendor_name": vendor_name,
                        "chipset_name": chipset,
                        "driver": driver,
                        "has_driver": bool(driver),
                        "interface_name": iface_name,
                        "is_ethernet": class_hex.startswith("0x0200"),
                        "is_wireless": class_hex.startswith("0x0280"),
                    })
            except Exception:
                pass

    # 2. USB scan
    if SYS_BUS_USB.exists():
        for usb_path in sorted(SYS_BUS_USB.glob("*")):
            prod_file = usb_path / "product"
            vendor_file = usb_path / "idVendor"
            device_file = usb_path / "idProduct"

            if not (vendor_file.exists() and device_file.exists()):
                continue

            try:
                vid = "0x" + vendor_file.read_text().strip().lower()
                pid = "0x" + device_file.read_text().strip().lower()
                prod = prod_file.read_text().strip() if prod_file.exists() else ""

                # Look for child network interfaces
                net_dirs = list(usb_path.glob("*/net/*")) + list(usb_path.glob("*/*/net/*"))
                has_net = len(net_dirs) > 0
                is_net_kw = any(k in prod.lower() for k in ("ethernet", "lan", "wi-fi", "wireless", "802.11", "network", "nic", "gigabit", "2.5g"))

                if has_net or is_net_kw or vid in ("0x0bda", "0x0b95"):
                    chipset = KNOWN_CHIPSETS.get((vid, pid), prod)
                    vendor_name = KNOWN_VENDORS.get(vid, vid)
                    iface_name = net_dirs[0].name if net_dirs else ""

                    controllers.append({
                        "bus": "usb",
                        "bus_id": usb_path.name,
                        "vendor_id": vid,
                        "device_id": pid,
                        "vendor_name": vendor_name,
                        "chipset_name": chipset or prod or "USB Network Adapter",
                        "driver": "active" if has_net else "",
                        "has_driver": has_net,
                        "interface_name": iface_name,
                        "is_ethernet": not any(k in (chipset or prod).lower() for k in ("wi-fi", "wireless", "802.11")),
                        "is_wireless": any(k in (chipset or prod).lower() for k in ("wi-fi", "wireless", "802.11")),
                    })
            except Exception:
                pass

    return controllers


def detect_missing_firmware() -> List[Dict[str, str]]:
    """Scan kernel diagnostics for firmware loading failures."""
    missing = []
    try:
        r = _run_cmd(["dmesg"], timeout=3.0)
        out = r.stdout
        if not out and Path("/var/log/dmesg").exists():
            out = Path("/var/log/dmesg").read_text(errors="replace")

        pattern = re.compile(r"(?:firmware:\s*failed to load|Direct firmware load for)\s+([^\s]+)", re.I)
        seen = set()
        for line in out.splitlines():
            m = pattern.search(line)
            if m:
                fw_file = m.group(1).strip()
                if fw_file not in seen:
                    seen.add(fw_file)
                    missing.append({
                        "firmware_file": fw_file,
                        "error_line": line.strip()
                    })
    except Exception:
        pass

    return missing


def get_recommended_driver_packages() -> List[Dict[str, Any]]:
    """Recommend distribution-specific packages to install for detected hardware."""
    from nmb.netd.os_detector import detect_os_info

    os_info = detect_os_info()
    pm = os_info.get("package_manager", "apt")
    controllers = detect_hardware_controllers()
    all_chipsets_text = " ".join(c.get("chipset_name", "").lower() for c in controllers)

    pkgs = []
    if pm in ("apt", "apt-get"):
        # Realtek
        if "realtek" in all_chipsets_text or not controllers:
            pkgs.append({
                "package": "firmware-realtek",
                "description": "Realtek RTL8111/RTL8168/RTL8125 PCIe & RTL8152/RTL8153 USB Ethernet and Wi-Fi firmware.",
                "recommended": True
            })
        # Intel
        if "intel" in all_chipsets_text or not controllers:
            pkgs.append({
                "package": "firmware-linux-nonfree",
                "description": "Intel, Broadcom, and Marvell Gigabit/10G Ethernet firmware.",
                "recommended": True
            })
            pkgs.append({
                "package": "firmware-iwlwifi",
                "description": "Intel Wi-Fi 5 / 6 / 6E / 7 (AX200, AX210, BE200) wireless adapter firmware.",
                "recommended": "intel" in all_chipsets_text
            })
        # Atheros / Broadcom / MediaTek
        pkgs.append({
            "package": "firmware-atheros",
            "description": "Qualcomm Atheros wireless and Ethernet firmware.",
            "recommended": "atheros" in all_chipsets_text
        })
        pkgs.append({
            "package": "firmware-brcm80211",
            "description": "Broadcom / Cypress Wi-Fi and Bluetooth firmware (Raspberry Pi & USB).",
            "recommended": True
        })
        pkgs.append({
            "package": "pciutils",
            "description": "PCI hardware diagnostic utility (lspci).",
            "recommended": True
        })
        pkgs.append({
            "package": "usbutils",
            "description": "USB hardware diagnostic utility (lsusb).",
            "recommended": True
        })
        pkgs.append({
            "package": "ethtool",
            "description": "Ethernet controller link speed and offload diagnostic utility.",
            "recommended": True
        })
    elif pm == "opkg":
        pkgs.extend([
            {"package": "kmod-usb-net-rtl8152", "description": "Kernel driver for Realtek RTL8152/RTL8153 USB Ethernet adapters.", "recommended": True},
            {"package": "kmod-usb-net-asix-ax88179", "description": "Kernel driver for ASIX AX88179 USB 3.0 Gigabit adapters.", "recommended": True},
            {"package": "kmod-r8169", "description": "Kernel driver for Realtek RTL8168/8111 PCIe Gigabit.", "recommended": True},
            {"package": "kmod-igc", "description": "Kernel driver for Intel I225/I226 2.5GbE controllers.", "recommended": True},
            {"package": "kmod-e1000e", "description": "Kernel driver for Intel Gigabit PCIe controllers.", "recommended": True},
        ])
    elif pm == "apk":
        pkgs.extend([
            {"package": "linux-firmware-realtek", "description": "Realtek firmware for Alpine Linux.", "recommended": True},
            {"package": "linux-firmware-other", "description": "Non-free firmware for Alpine Linux.", "recommended": True},
            {"package": "ethtool", "description": "Ethtool utility.", "recommended": True},
        ])
    else:
        pkgs.append({
            "package": "linux-firmware",
            "description": "Complete Linux hardware firmware bundle.",
            "recommended": True
        })

    return pkgs


def get_full_driver_status() -> Dict[str, Any]:
    """Compile comprehensive network hardware, interface, driver, and firmware telemetry."""
    ifaces = detect_all_physical_interfaces()
    controllers = detect_hardware_controllers()
    missing_fw = detect_missing_firmware()
    recs = get_recommended_driver_packages()

    unsupported_count = sum(1 for c in controllers if not c.get("has_driver"))
    missing_fw_count = len(missing_fw)

    return {
        "status": "ok",
        "interfaces": ifaces,
        "controllers": controllers,
        "missing_firmware": missing_fw,
        "recommended_packages": recs,
        "unsupported_controllers_count": unsupported_count,
        "missing_firmware_count": missing_fw_count,
        "all_drivers_ready": (unsupported_count == 0 and missing_fw_count == 0),
        "install_status": get_driver_install_status(),
    }


_driver_install_lock = threading.Lock()
_driver_install_status: Dict[str, Any] = {
    "in_progress": False,
    "package": "",
    "status": "idle",
    "output": "",
    "error": None,
    "last_run": None,
}


def get_driver_install_status() -> Dict[str, Any]:
    """Retrieve the current driver installation task state."""
    with _driver_install_lock:
        return dict(_driver_install_status)


def execute_driver_install(package: str = "all") -> Dict[str, Any]:
    """Execute parameterized driver installation synchronously via nmb-helper."""
    helper_bin = "/usr/local/bin/nmb-helper"
    if not os.path.exists(helper_bin):
        # Look in workspace bin
        candidate = Path(__file__).resolve().parent.parent.parent / "bin" / "nmb-helper"
        if candidate.exists():
            helper_bin = str(candidate)

    cmd = ["sudo", "-n", helper_bin, "install-drivers", package]
    try:
        r = _run_cmd(cmd, timeout=180.0)
        return {
            "status": "ok" if r.returncode == 0 else "error",
            "returncode": r.returncode,
            "stdout": r.stdout,
            "stderr": r.stderr,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


def trigger_driver_install(package: str = "all") -> Dict[str, Any]:
    """Asynchronously execute driver and firmware installation via worker thread."""
    global _driver_install_status
    with _driver_install_lock:
        if _driver_install_status["in_progress"]:
            return {"status": "busy", "message": "Driver installation is already in progress."}
        _driver_install_status["in_progress"] = True
        _driver_install_status["package"] = package
        _driver_install_status["status"] = "running"
        _driver_install_status["output"] = f"=== Initiating Driver/Firmware Installation [{package}] ===\n"
        _driver_install_status["error"] = None
        _driver_install_status["last_run"] = time.time()

    def _worker():
        try:
            res = execute_driver_install(package)
            with _driver_install_lock:
                _driver_install_status["in_progress"] = False
                _driver_install_status["status"] = res.get("status", "error")
                out_txt = (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")
                _driver_install_status["output"] = out_txt.strip() or "Installation process finished with no output."
                if res.get("status") != "ok":
                    _driver_install_status["error"] = res.get("message") or f"Exited with code {res.get('returncode')}"
        except Exception as e:
            with _driver_install_lock:
                _driver_install_status["in_progress"] = False
                _driver_install_status["status"] = "error"
                _driver_install_status["error"] = str(e)
                _driver_install_status["output"] += f"\nInternal failure: {e}\n"

    t = threading.Thread(target=_worker, daemon=True, name="nmb-driver-installer")
    t.start()
    return {"status": "started", "package": package, "message": "Driver installation started in background."}


def get_interfaces_matrix(cfg: Any) -> Dict[str, Any]:
    """Compile physical interfaces mapped against their configured network roles."""
    physical_ifaces = detect_all_physical_interfaces()

    wan1 = getattr(cfg.network, "wan_interface", "eth0")
    wan2 = getattr(cfg.network, "wan2_interface", "")
    lan_ports_raw = getattr(cfg.network, "lan_ports", "")
    if isinstance(lan_ports_raw, list):
        lan_ports_list = [str(p).strip() for p in lan_ports_raw if str(p).strip()]
        lan_ports_str = ",".join(lan_ports_list)
    else:
        lan_ports_str = str(lan_ports_raw).strip()
        lan_ports_list = [p.strip() for p in lan_ports_str.split(",") if p.strip()]
    lan_single = getattr(cfg.network, "lan_interface", "eth1")
    guest_iface = getattr(getattr(cfg, "guest_wifi", None), "interface", "wlan0")
    dmz_iface = getattr(cfg.network, "dmz_interface", "")

    annotated = []
    for iface in physical_ifaces:
        name = iface.get("name", "")
        # Determine current assigned role
        if name == wan1:
            role = "wan1"
        elif wan2 and name == wan2:
            role = "wan2"
        elif name in lan_ports_list or (not lan_ports_list and name == lan_single):
            role = "lan"
        elif guest_iface and name == guest_iface:
            role = "guest"
        elif dmz_iface and name == dmz_iface:
            role = "dmz"
        else:
            role = "unassigned"

        item = dict(iface)
        item["role"] = role
        annotated.append(item)

    return {
        "status": "ok",
        "wan_mode": getattr(cfg.network, "wan_mode", "single"),
        "wan_interface": wan1,
        "wan2_interface": wan2,
        "lan_interface": lan_single,
        "lan_ports": lan_ports_str,
        "guest_interface": guest_iface,
        "dmz_interface": dmz_iface,
        "interfaces": annotated,
    }

