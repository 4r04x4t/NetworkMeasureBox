#!/bin/sh
# ==============================================================================
# NetworkMeasureBox (NMB) — Production Unattended Automated Installer
# Works on Debian, Ubuntu, Raspberry Pi OS, and Alpine Linux.
# Run as root: sudo ./setup.sh
# ==============================================================================
set -eu

INSTALL_DIR="/opt/nmb"
CONFIG_DIR="/etc/nmb"
CONFIG_FILE="$CONFIG_DIR/nmb.conf"
NMB_USER="nmb"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

info()  { printf '\033[1;36m[NMB-INSTALL]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[NMB-WARNING]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[NMB-ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

ookla_sha256() {
    case "$1" in
        x86_64) echo 5690596c54ff9bed63fa3732f818a05dbc2db19ad36ed68f21ca5f64d5cfeeb7 ;;
        aarch64) echo 3953d231da3783e2bf8904b6dd72767c5c6e533e163d3742fd0437affa431bd3 ;;
        armhf) echo e45fcdebbd8a185553535533dd032d6b10bc8c64eee4139b1147b9c09835d08d ;;
    esac
}

# Download the Ookla archive into $2 and accept it only with the expected checksum.
fetch_ookla() {
    curl -fsSL "https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-$1.tgz" -o "$2/ookla.tgz" || return 1
    if [ "$(sha256sum "$2/ookla.tgz" | cut -d' ' -f1)" != "$(ookla_sha256 "$1")" ]; then
        warn "Ookla download failed its checksum; not installing it."
        return 1
    fi
    tar -xzf "$2/ookla.tgz" -C "$2"
}

[ "$(id -u)" -eq 0 ] || error "setup.sh must be executed with root privileges (sudo ./setup.sh)."

info "Starting NetworkMeasureBox production installation..."

# ------------------------------------------------------------------------------
# 1. OS & Init System Detection
# ------------------------------------------------------------------------------
OS_TYPE="debian"
INIT_SYSTEM="systemd"

if [ -f /etc/alpine-release ]; then
    OS_TYPE="alpine"
    INIT_SYSTEM="openrc"
elif [ -f /etc/debian_version ] || grep -q -E "debian|ubuntu|raspbian" /etc/os-release 2>/dev/null; then
    OS_TYPE="debian"
    INIT_SYSTEM="systemd"
else
    error "Unsupported operating system. NetworkMeasureBox officially supports Debian, Ubuntu, Raspberry Pi OS, and Alpine Linux."
fi
info "Detected platform: $OS_TYPE with $INIT_SYSTEM"

# ------------------------------------------------------------------------------
# 2. Package Dependencies Installation & Daemon Isolation
# ------------------------------------------------------------------------------
info "Installing required operating system packages and network utilities..."
if [ "$OS_TYPE" = "debian" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends \
        python3 iproute2 nftables iptables ethtool pciutils usbutils polkitd \
        dnsmasq hostapd iw wireless-regdb ppp pppoe udhcpc curl ca-certificates procps libcap2-bin \
        wireguard-tools openvpn easy-rsa python3-qrcode qrencode \
        traceroute iputils-tracepath mtr-tiny iperf3 sqlite3 gnupg dirmngr \
        gcc make libc-dev libssl-dev libcurl4-openssl-dev pkg-config
    # Install common hardware firmware if available in repositories
    apt-get install -y --no-install-recommends firmware-realtek 2>/dev/null || true

    # Install OONI Probe (Censorship & Internet Freedom Engine)
    if ! command -v ooniprobe >/dev/null 2>&1 && ! command -v ooniprobe-cli >/dev/null 2>&1; then
        info "Configuring official OONI Probe repository..."
        mkdir -p /etc/apt/keyrings
        curl -sL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xB5A08F01796E7F521861B449372D1FF271F2DD50" | gpg --dearmor >/etc/apt/keyrings/ooni-apt-keyring.gpg 2>/dev/null || true
        chmod 644 /etc/apt/keyrings/ooni-apt-keyring.gpg 2>/dev/null || true
        echo "deb [signed-by=/etc/apt/keyrings/ooni-apt-keyring.gpg] https://deb.ooni.org/ unstable main" >/etc/apt/sources.list.d/ooniprobe.list
        apt-get update -y 2>/dev/null || true
        DEBIAN_FRONTEND=noninteractive apt-get install -y ooniprobe-cli 2>/dev/null || true

        # Fallback to standalone miniooni binary if debian repo failed
        if ! command -v ooniprobe >/dev/null 2>&1 && ! command -v ooniprobe-cli >/dev/null 2>&1; then
            ARCH=$(uname -m)
            OONI_ARCH=""
            [ "$ARCH" = "x86_64" ] && OONI_ARCH="amd64"
            [ "$ARCH" = "aarch64" ] && OONI_ARCH="arm64"
            [ "$ARCH" = "armv7l" ] && OONI_ARCH="armv7"
            if [ -n "$OONI_ARCH" ]; then
                info "Downloading standalone miniooni binary for $OONI_ARCH..."
                curl -sL "https://github.com/ooni/probe-cli/releases/download/v3.31.1/miniooni-linux-$OONI_ARCH" -o /usr/local/bin/ooniprobe 2>/dev/null || true
                chmod +x /usr/local/bin/ooniprobe 2>/dev/null || true
            fi
        fi
    fi

    # ooniprobe-cli pulls in Tor; NMB does not use it, so it must not run as a service.
    systemctl disable --now tor 2>/dev/null || true


    # Stop and disable OS-packaged dnsmasq & hostapd so nmb-netd has exclusive control
    systemctl disable --now dnsmasq hostapd 2>/dev/null || true
    # dnsmasq often fails when installed next to another DNS service; do not leave the system degraded.
    systemctl reset-failed dnsmasq hostapd 2>/dev/null || true
    systemctl mask hostapd 2>/dev/null || true

    NMB_MODE="${NMB_MODE:-standalone}"
    if [ "$NMB_MODE" != "standalone" ]; then
        # Prevent NetworkManager from managing NMB internal interfaces
        if [ -d /etc/NetworkManager/conf.d ]; then
            info "Configuring NetworkManager to unmanage NMB network interfaces..."
            cat >/etc/NetworkManager/conf.d/99-nmb-unmanaged.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:eth0;interface-name:eth1;interface-name:br0;interface-name:ppp0
EOF
            systemctl reload NetworkManager 2>/dev/null || true
        fi

        # Prevent dhcpcd from interfering with NMB interfaces if present
        if [ -f /etc/dhcpcd.conf ]; then
            if ! grep -q "denyinterfaces eth0 eth1 br0 ppp0" /etc/dhcpcd.conf; then
                info "Configuring dhcpcd to ignore NMB interfaces..."
                printf '\ndenyinterfaces eth0 eth1 br0 ppp0\n' >> /etc/dhcpcd.conf
                systemctl restart dhcpcd 2>/dev/null || true
            fi
        fi
    else
        info "Standalone Mode: physical network interfaces remain under host OS management."
    fi

    # Install official Ookla Speedtest CLI (try standalone binary first for reliable multi-distro support)
    ARCH=$(uname -m)
    OOKLA_ARCH=""
    [ "$ARCH" = "x86_64" ] && OOKLA_ARCH="x86_64"
    [ "$ARCH" = "aarch64" ] && OOKLA_ARCH="aarch64"
    [ "$ARCH" = "armv7l" ] && OOKLA_ARCH="armhf"

    if [ -n "$OOKLA_ARCH" ] && ! command -v speedtest >/dev/null 2>&1; then
        info "Downloading standalone Ookla speedtest binary for $OOKLA_ARCH..."
        TMP_DIR=$(mktemp -d)
        if fetch_ookla "$OOKLA_ARCH" "$TMP_DIR"; then
            if [ -f "$TMP_DIR/speedtest" ]; then
                mv "$TMP_DIR/speedtest" /usr/local/bin/speedtest
                chmod +x /usr/local/bin/speedtest
                info "Installed /usr/local/bin/speedtest"
            fi
        fi
        rm -rf "$TMP_DIR"
    fi

    if ! command -v speedtest >/dev/null 2>&1; then
        info "Trying Ookla repository package..."
        # Running a remote script as root is opt-in; the built-in engine works without it.
        if [ "${INSTALL_OOKLA_REPO:-0}" = "1" ]; then
            curl -sSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash 2>/dev/null || true
        fi
        apt-get install -y speedtest 2>/dev/null || warn "Ookla repository install deferred; native high-speed fallback will be active."
    fi

elif [ "$OS_TYPE" = "alpine" ]; then
    apk update
    apk add --no-cache \
        python3 iproute2 nftables iptables ethtool dnsmasq hostapd iw wireless-regdb ppp \
        curl ca-certificates busybox-extras libcap traceroute iputils mtr \
        iperf3 sqlite openvpn wireguard-tools build-base gcc make openssl-dev curl-dev pkgconfig

    ARCH=$(uname -m)
    OOKLA_ARCH=""
    [ "$ARCH" = "x86_64" ] && OOKLA_ARCH="x86_64"
    [ "$ARCH" = "aarch64" ] && OOKLA_ARCH="aarch64"
    [ "$ARCH" = "armv7l" ] && OOKLA_ARCH="armhf"

    if [ -n "$OOKLA_ARCH" ] && ! command -v speedtest >/dev/null 2>&1; then
        info "Downloading standalone Ookla speedtest binary for $OOKLA_ARCH..."
        TMP_DIR=$(mktemp -d)
        fetch_ookla "$OOKLA_ARCH" "$TMP_DIR" || true
        if [ -f "$TMP_DIR/speedtest" ]; then
            mv "$TMP_DIR/speedtest" /usr/local/bin/speedtest
            chmod +x /usr/local/bin/speedtest
            info "Installed /usr/local/bin/speedtest"
        fi
        rm -rf "$TMP_DIR"
    fi

    # Install standalone OONI probe for Alpine
    if ! command -v ooniprobe >/dev/null 2>&1 && ! command -v ooniprobe-cli >/dev/null 2>&1; then
        OONI_ARCH=""
        [ "$ARCH" = "x86_64" ] && OONI_ARCH="amd64"
        [ "$ARCH" = "aarch64" ] && OONI_ARCH="arm64"
        [ "$ARCH" = "armv7l" ] && OONI_ARCH="armv7"
        if [ -n "$OONI_ARCH" ]; then
            info "Downloading standalone miniooni binary for $OONI_ARCH..."
            curl -sL "https://github.com/ooni/probe-cli/releases/download/v3.31.1/miniooni-linux-$OONI_ARCH" -o /usr/local/bin/ooniprobe 2>/dev/null || true
            chmod +x /usr/local/bin/ooniprobe 2>/dev/null || true
        fi
    fi
fi

# Both Debian and Alpine install the build tools above.
# Compile native Open-RMBT C measurement engine if source is present
if [ -d "$SCRIPT_DIR/components/open-rmbt" ]; then
    info "Compiling native Open-RMBT C measurement client (/usr/local/bin/rmbt-client)..."
    (cd "$SCRIPT_DIR/components/open-rmbt" && make clean >/dev/null 2>&1 && make >/dev/null 2>&1 && make install >/dev/null 2>&1) || warn "Open-RMBT native compilation deferred; pure Python engine will remain active."
fi

# ------------------------------------------------------------------------------
# 3. System User & Group
# ------------------------------------------------------------------------------
if ! id "$NMB_USER" >/dev/null 2>&1; then
    info "Creating unprivileged system account '$NMB_USER'..."
    if [ "$OS_TYPE" = "alpine" ]; then
        addgroup -S "$NMB_USER"
        adduser -S -D -H -G "$NMB_USER" -s /sbin/nologin "$NMB_USER"
    else
        useradd --system --no-create-home --shell /usr/sbin/nologin "$NMB_USER"
    fi
fi

# Allow NMB only the privileged commands it needs
if [ -d /etc/sudoers.d ]; then
    cat > /etc/sudoers.d/020_nmb-net <<SUDOERS
$NMB_USER ALL=(root) NOPASSWD: /usr/local/bin/nmb-helper, /usr/bin/systemctl reboot, /usr/bin/tee /etc/nmb/nmb.conf, /usr/sbin/iw, /usr/sbin/rfkill, /usr/bin/resolvectl
SUDOERS
    chmod 0440 /etc/sudoers.d/020_nmb-net
fi

# ------------------------------------------------------------------------------
# 4. Storage & MicroSD Longevity Baseline (tmpfs, noatime, commit=600, volatile logs)
# ------------------------------------------------------------------------------
info "Applying storage baseline and flash longevity tuning..."
if [ -f "$SCRIPT_DIR/os/storage-setup.sh" ]; then
    sh "$SCRIPT_DIR/os/storage-setup.sh"
else
    install -d -m 0775 -o root -g "$NMB_USER" "$CONFIG_DIR"
    install -d -m 2775 -o "$NMB_USER" -g "$NMB_USER" /var/lib/nmb /var/lib/nmb/persist /var/lib/nmb/persist/reports
    install -d -m 2775 -o "$NMB_USER" -g "$NMB_USER" /var/lib/nmb/live /var/log/nmb /run/nmb
fi

# ------------------------------------------------------------------------------
# 5. Kernel Sysctl Performance & 10G Buffer Tuning
# ------------------------------------------------------------------------------
info "Deploying kernel modules and sysctl tuning (/etc/sysctl.d/99-nmb-performance.conf)..."
install -d /etc/modules-load.d
cat >/etc/modules-load.d/nmb.conf <<'EOF'
tcp_bbr
br_netfilter
EOF
modprobe tcp_bbr 2>/dev/null || true
modprobe br_netfilter 2>/dev/null || true

install -d /etc/sysctl.d
if [ -f "$SCRIPT_DIR/os/99-nmb-performance.conf" ]; then
    cp "$SCRIPT_DIR/os/99-nmb-performance.conf" /etc/sysctl.d/99-nmb-performance.conf
    sysctl -q -p /etc/sysctl.d/99-nmb-performance.conf || true
fi

# ------------------------------------------------------------------------------
# 6. Deploy NetworkMeasureBox Application Files to /opt/nmb
# ------------------------------------------------------------------------------
info "Deploying software package to $INSTALL_DIR..."
install -d -m 0755 "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/nmb" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/bin" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/os" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/components" "$INSTALL_DIR/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/docs" "$INSTALL_DIR/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/bin/"* "$INSTALL_DIR/os/"*.sh
# Services run this code as root, so only root may change it.
chown -R root:root "$INSTALL_DIR"
chmod -R go-w "$INSTALL_DIR"

# Configuration file
install -d -m 0775 -o root -g "$NMB_USER" "$CONFIG_DIR"
if [ ! -f "$CONFIG_FILE" ]; then
    if [ -f "$SCRIPT_DIR/config/nmb.conf.example" ]; then
        cp "$SCRIPT_DIR/config/nmb.conf.example" "$CONFIG_FILE"
    fi
    info "Created default configuration at $CONFIG_FILE"
    # Interface names differ between systems (eth0, ens3, enp1s0...); use the ones that exist here.
    if [ ! -e /sys/class/net/eth0 ]; then
        WAN_IF=$(ip route show default 2>/dev/null | awk '{print $5; exit}')
        LAN_IF=""
        for n in /sys/class/net/*; do
            n=$(basename "$n")
            [ "$n" = "$WAN_IF" ] && continue
            [ -e "/sys/class/net/$n/device" ] && [ ! -e "/sys/class/net/$n/wireless" ] && { LAN_IF="$n"; break; }
        done
        if [ -n "$WAN_IF" ]; then
            sed -i "s/^wan_interface = .*/wan_interface = $WAN_IF/" "$CONFIG_FILE"
            info "Using $WAN_IF as the WAN interface"
        fi
        if [ -n "$LAN_IF" ]; then
            sed -i "s/^lan_interface = .*/lan_interface = $LAN_IF/; s/^lan_ports = .*/lan_ports = $LAN_IF/" "$CONFIG_FILE"
            info "Using $LAN_IF as the LAN interface"
        fi
    fi
fi

# A shared factory Wi-Fi password would be identical on every box.
if grep -q "wifi_psk = NetworkMeasureBox123" "$CONFIG_FILE" 2>/dev/null; then
    WIFI_PSK=$(head -c 16 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)
    sed -i "s/wifi_psk = NetworkMeasureBox123/wifi_psk = $WIFI_PSK/" "$CONFIG_FILE"
    info "Generated diagnostic Wi-Fi password: $WIFI_PSK"
fi

# Read or preserve admin password from config (factory router default: admin / admin)
if [ "${RANDOM_ADMIN_PASSWORD:-0}" = "1" ] && grep -q "admin_password = admin" "$CONFIG_FILE" 2>/dev/null; then
    ADMIN_PASS=$(head -c 16 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 14)
    sed -i "s/admin_password = admin/admin_password = $ADMIN_PASS/" "$CONFIG_FILE"
    info "Generated secure random Web UI admin password: $ADMIN_PASS"
else
    ADMIN_PASS=$(grep -E '^\s*admin_password\s*=' "$CONFIG_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo "admin")
    [ -z "$ADMIN_PASS" ] && ADMIN_PASS="admin"
    info "Standard router Web UI admin credentials: admin / $ADMIN_PASS"
fi

# Detect primary IP address
HOST_IP=$(ip -4 addr show scope global 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1 || echo "127.0.0.1")

# Write headless first-boot credentials file to /var/lib/nmb and /boot partition
CRED_FILE="/var/lib/nmb/credentials.txt"
install -d -m 2775 -o "$NMB_USER" -g "$NMB_USER" /var/lib/nmb 2>/dev/null || true
cat > "$CRED_FILE" <<EOF
================================================================================
  NetworkMeasureBox — Device Management Credentials
================================================================================
  Web UI URL  : http://${HOST_IP:-localhost} (Default HTTP Port 80)
  Username    : admin
  Password    : ${ADMIN_PASS}
  Config File : ${CONFIG_FILE}
================================================================================
EOF
chmod 0600 "$CRED_FILE"
chown "$NMB_USER:$NMB_USER" "$CRED_FILE" 2>/dev/null || true

# Mirror to the FAT32 boot partition (readable with any SD card reader) only while the password is the
# documented default or was generated just now; a password the user chose must not be stored there.
BOOT_CRED_FILE=""
[ -d /boot ] && BOOT_CRED_FILE="/boot/nmb_credentials.txt"
[ -d /boot/firmware ] && BOOT_CRED_FILE="/boot/firmware/nmb_credentials.txt"
if [ -n "$BOOT_CRED_FILE" ]; then
    if [ "$ADMIN_PASS" = "admin" ] || [ "${RANDOM_ADMIN_PASSWORD:-0}" = "1" ]; then
        cp "$CRED_FILE" "$BOOT_CRED_FILE" 2>/dev/null || true
    else
        rm -f "$BOOT_CRED_FILE" 2>/dev/null || true
    fi
fi

# Detect low-memory embedded target (512MB RAM router / Pi Zero)
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 1048576)
if [ "$TOTAL_RAM_KB" -le 800000 ]; then
    info "Low-memory target detected (${TOTAL_RAM_KB} kB RAM). Optimizing for 512MB RAM embedded router..."
    if grep -q "memory_profile = " "$CONFIG_FILE" 2>/dev/null; then
        sed -i "s/memory_profile = .*/memory_profile = low/" "$CONFIG_FILE"
    fi
    SWAP_TOTAL=$(free -m 2>/dev/null | awk '/Swap:/ {print $2}' || echo 0)
    if [ "$SWAP_TOTAL" -eq 0 ]; then
        warn "No swap space detected on 512MB system. Enabling compressed zram swap for maximum stability..."
        if [ "$OS_TYPE" = "debian" ] && command -v apt-get >/dev/null 2>&1; then
            apt-get install -y zram-tools 2>/dev/null || true
            systemctl enable --now zramswap 2>/dev/null || true
        fi
    fi
fi

chown "$NMB_USER":"$NMB_USER" "$CONFIG_FILE"
chmod 0640 "$CONFIG_FILE"

# Add the invoking sudo user to the nmb group so developers/admins can read NMB status
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    usermod -aG "$NMB_USER" "$SUDO_USER" 2>/dev/null || true
fi

# Symlink executables into /usr/local/bin
for b in nmb-netd nmb-probe nmb-speed nmb-report nmb-telegram nmb-web nmb-helper nmb-vpn nmb-wifi nmb-iperf nmb-ooni nmb-invasive-log nmb-factory-reset nmb-driver nmb-adblock nmb-heal nmb-cli; do
    if [ -f "$INSTALL_DIR/bin/$b" ]; then
        ln -sf "$INSTALL_DIR/bin/$b" "/usr/local/bin/$b"
    fi
done
# Symlink pivpn to nmb-vpn for drop-in PiVPN CLI compatibility
ln -sf "$INSTALL_DIR/bin/nmb-vpn" "/usr/local/bin/pivpn"
# Symlink pihole to nmb-adblock for drop-in Pi-hole CLI compatibility
ln -sf "$INSTALL_DIR/bin/nmb-adblock" "/usr/local/bin/pihole"

# ------------------------------------------------------------------------------
# 7. Initialize Database (Restore from SD or bootstrap new schema)
# ------------------------------------------------------------------------------
info "Initializing SQLite database..."
PYTHONPATH="$INSTALL_DIR" python3 -m nmb.db.database restore

# Set ownership and group sticky bits for cross-process access
install -d -m 2775 -o "$NMB_USER" -g "$NMB_USER" /var/lib/nmb /var/lib/nmb/live /var/lib/nmb/persist /var/lib/nmb/persist/reports /var/lib/nmb/adblock /var/log/nmb /run/nmb 2>/dev/null || true
chown -R "$NMB_USER:$NMB_USER" /var/lib/nmb /var/log/nmb /run/nmb 2>/dev/null || true
chmod -R u+rwX,g+rwX /var/lib/nmb /var/log/nmb /run/nmb 2>/dev/null || true
chmod 2775 /var/lib/nmb /var/lib/nmb/live /var/lib/nmb/persist /var/lib/nmb/persist/reports /var/lib/nmb/adblock /var/log/nmb /run/nmb 2>/dev/null || true

# ------------------------------------------------------------------------------
# 8. Service Units Deployment & Activation
# ------------------------------------------------------------------------------
if [ "$INIT_SYSTEM" = "systemd" ]; then
    info "Installing systemd units to /etc/systemd/system/..."
    # The nmb-web scheduler now starts speed tests from schedule_cron; remove the old fixed timer.
    systemctl disable --now nmb-speed.timer 2>/dev/null || true
    rm -f /etc/systemd/system/nmb-speed.timer
    cp "$SCRIPT_DIR/systemd/"* /etc/systemd/system/
    systemctl daemon-reload

    info "Enabling and starting NetworkMeasureBox systemd target..."
    install -d /etc/polkit-1/rules.d
    cp "$SCRIPT_DIR/os/90-nmb.rules" /etc/polkit-1/rules.d/90-nmb.rules
    systemctl enable --now nmb-guard.service
    systemctl restart nmb-guard.service
    systemctl enable nmb-db.service nmb-tune.service nmb-netd.service nmb-probe.service nmb-web.service nmb-iperf3.service nmb-adblock.service
    systemctl enable nmb-maintain.timer nmb-snapshot.timer nmb-report.timer nmb-invasive-log.timer nmb-ooni.timer nmb-adblock-update.timer nmb-heal.timer
    systemctl enable nmb.target
    # Replace a boot partition copy that may still hold secrets.
    "$INSTALL_DIR/bin/nmb-helper" sync-drive-config 2>/dev/null || true

    # Preserve and auto-start WireGuard / OpenVPN servers if configured
    if [ -f /etc/wireguard/wg0.conf ]; then
        info "Preserving active WireGuard configuration (/etc/wireguard/wg0.conf)..."
        systemctl enable --now wg-quick@wg0.service 2>/dev/null || true
    fi
    if [ -f /etc/openvpn/server.conf ] || [ -f /etc/openvpn/server/server.conf ]; then
        info "Preserving active OpenVPN configuration..."
        systemctl enable --now openvpn.service 2>/dev/null || true
    fi

    systemctl start nmb.target
    systemctl restart nmb-db.service nmb-tune.service nmb-netd.service nmb-probe.service nmb-web.service nmb-iperf3.service nmb-adblock.service
    # Restart, not start, so an upgrade applies changed timer schedules.
    systemctl restart nmb-maintain.timer nmb-snapshot.timer nmb-report.timer nmb-invasive-log.timer nmb-ooni.timer nmb-adblock-update.timer nmb-heal.timer

elif [ "$INIT_SYSTEM" = "openrc" ]; then
    info "Installing OpenRC init scripts to /etc/init.d/..."
    cp "$SCRIPT_DIR/os/openrc/"* /etc/init.d/
    chmod +x /etc/init.d/nmb-*

    rc-update add nmb-db default
    rc-update add nmb-netd default
    rc-update add nmb-probe default
    rc-update add nmb-web default
    rc-update add nmb-telegram default 2>/dev/null || true

    # Restarting nmb-db also restarts the services that need it, so a later restart can collide; check the result instead.
    for svc in nmb-db nmb-netd nmb-probe nmb-web; do
        rc-service "$svc" restart >/dev/null 2>&1 || rc-service "$svc" start >/dev/null 2>&1 || true
    done
    sleep 3
    for svc in nmb-db nmb-netd nmb-probe nmb-web; do
        rc-service "$svc" status >/dev/null 2>&1 || warn "$svc is not running; check /var/log/nmb/"
    done

    # Deploy crontab for Alpine Busybox crond (/etc/crontabs/root format, no username column)
    install -d /etc/crontabs
    cat >/etc/crontabs/root <<'EOF'
*/5 * * * * PYTHONPATH=/opt/nmb /usr/bin/python3 -m nmb.db.database maintain >/dev/null 2>&1
*/15 * * * * PYTHONPATH=/opt/nmb /usr/bin/python3 -m nmb.db.database snapshot >/dev/null 2>&1
5 0 * * * /usr/local/bin/nmb-report --window 24h >/dev/null 2>&1
30 3 * * 0 /usr/local/bin/nmb-ooni enabled && /usr/local/bin/nmb-ooni run websites >/dev/null 2>&1
EOF
    rc-update add crond default 2>/dev/null || true
    rc-service crond restart 2>/dev/null || rc-service crond start 2>/dev/null || true
fi

# Detect primary IP address
HOST_IP=$(ip -4 addr show scope global 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1 || echo "127.0.0.1")

# ------------------------------------------------------------------------------
# 9. Installation Summary Banner
# ------------------------------------------------------------------------------
STATUS_CMD="systemctl status nmb.target"
[ "$INIT_SYSTEM" = "openrc" ] && STATUS_CMD="rc-status default"
printf '\n\033[1;32m'
BANNER=$(cat <<EOF
================================================================================
   NetworkMeasureBox (NMB) — Installation Complete Successfully!
================================================================================
\033[0m
  * Management Web UI  : \033[1;34mhttp://${HOST_IP}\033[0m (Standard HTTP Port 80)
  * Web UI Credentials : Username: \033[1;32madmin\033[0m | Password: \033[1;33m${ADMIN_PASS}\033[0m
  * Credentials Saved  : /var/lib/nmb/credentials.txt (mirrored to /boot/firmware/)
  * Configuration File : \033[1;33m/etc/nmb/nmb.conf\033[0m
  * Live Database      : /var/lib/nmb/live/nmb.db (tmpfs RAM)
  * Persistent SD DB   : /var/lib/nmb/persist/nmb.db (15-min snapshots)
  * Reports Directory  : /var/lib/nmb/persist/reports/
  * Developer Telemetry: /var/log/nmb/invasive_dev_snapshot.md (3-min timer)

  CLI Tools Installed:
    nmb-netd         - Network mode manager (--status, --switch auto|standalone|mode_a|mode_b)
    nmb-probe        - High-performance ICMP latency/jitter engine
    nmb-speed        - Multi-engine speedtest & port throttling runner (--trigger manual)
    nmb-report       - HTML dossier generator & ISP fault dispatcher (--window 24h)
    nmb-telegram     - Management Telegram bot daemon
    nmb-web          - Embedded management web server (Router Port 80 / dev 8080)
    nmb-vpn / pivpn  - Unified PiVPN-style WireGuard & OpenVPN management CLI
    nmb-wifi         - Wi-Fi scanner, connector (hidden SSID support), and saved profiles
    nmb-iperf        - iPerf3 client bandwidth benchmark & background server manager
    nmb-ooni         - Optional weekly OONI Probe censorship audit (off by default; enable in the Web UI)
    rmbt-client      - Official native C Open-RMBT regulatory speedtest engine
    nmb-invasive-log - Deep invasive technical diagnostic snapshot generator
    nmb-factory-reset- Factory reset utility
    nmb-driver       - Hardware network adapter & kernel firmware scanner/installer
    nmb-adblock/pihole- Built-in OS-independent DNS ad-blocker & sinkhole engine
    nmb-cli          - WebGUI menus in the terminal (SSH, mouse and hotkeys) and JSON commands
    nmb-heal         - Automated self-healing engine & stable updates with rollback

  Next Steps:
    1. Open \033[1;34mhttp://${HOST_IP}\033[0m in your browser to access the dashboard.
    2. Log in with user '\033[1;32madmin\033[0m' and password '\033[1;33m${ADMIN_PASS}\033[0m'.
    3. Edit \033[1;33m/etc/nmb/nmb.conf\033[0m to configure your ISP SLA plan, Telegram token, or Wi-Fi.
    4. Check overall system status: \033[1;37m$STATUS_CMD\033[0m
================================================================================
EOF
)
# The heredoc holds \033 colour codes; %b turns them into real escapes.
printf '%b\n' "$BANNER"
