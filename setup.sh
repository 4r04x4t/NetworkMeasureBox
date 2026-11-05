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
        python3 iproute2 nftables iptables ethtool pciutils usbutils \
        dnsmasq hostapd ppp pppoe udhcpc curl ca-certificates procps libcap2-bin \
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

    # Unattended onboarding for OONI Probe
    if command -v ooniprobe >/dev/null 2>&1; then
        ooniprobe onboard --yes 2>/dev/null || true
    fi

    # Compile native Open-RMBT C measurement engine if source is present
    if [ -d "$SCRIPT_DIR/components/open-rmbt" ]; then
        info "Compiling native Open-RMBT C measurement client (/usr/local/bin/rmbt-client)..."
        (cd "$SCRIPT_DIR/components/open-rmbt" && make clean >/dev/null 2>&1 && make >/dev/null 2>&1 && make install >/dev/null 2>&1) || warn "Open-RMBT native compilation deferred; pure Python engine will remain active."
    fi

    # Stop and disable OS-packaged dnsmasq & hostapd so nmb-netd has exclusive control
    systemctl disable --now dnsmasq hostapd 2>/dev/null || true
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
        if curl -sSL "https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-$OOKLA_ARCH.tgz" | tar -xz -C "$TMP_DIR" 2>/dev/null; then
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
        curl -sSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash 2>/dev/null || true
        apt-get install -y speedtest 2>/dev/null || warn "Ookla repository install deferred; native high-speed fallback will be active."
    fi

elif [ "$OS_TYPE" = "alpine" ]; then
    apk update
    apk add --no-cache \
        python3 iproute2 nftables iptables ethtool dnsmasq hostapd ppp \
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
        curl -sSL "https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-$OOKLA_ARCH.tgz" | tar -xz -C "$TMP_DIR" 2>/dev/null || true
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

# Grant full administration rights to NMB in sudoers
if [ -d /etc/sudoers.d ]; then
    echo "$NMB_USER ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/020_nmb-net
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

# Configuration file
install -d -m 0775 -o root -g "$NMB_USER" "$CONFIG_DIR"
if [ ! -f "$CONFIG_FILE" ]; then
    if [ -f "$SCRIPT_DIR/config/nmb.conf.example" ]; then
        cp "$SCRIPT_DIR/config/nmb.conf.example" "$CONFIG_FILE"
    fi
    info "Created default configuration at $CONFIG_FILE"
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

# Mirror to FAT32 boot partition if present (accessible via PC/Mac SD card reader)
if [ -d /boot/firmware ]; then
    cp "$CRED_FILE" /boot/firmware/nmb_credentials.txt 2>/dev/null || true
    chmod 0644 /boot/firmware/nmb_credentials.txt 2>/dev/null || true
elif [ -d /boot ]; then
    cp "$CRED_FILE" /boot/nmb_credentials.txt 2>/dev/null || true
    chmod 0644 /boot/nmb_credentials.txt 2>/dev/null || true
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
for b in nmb-netd nmb-probe nmb-speed nmb-report nmb-telegram nmb-web nmb-helper nmb-vpn nmb-wifi nmb-iperf nmb-ooni nmb-invasive-log nmb-factory-reset nmb-driver nmb-adblock nmb-heal; do
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
    cp "$SCRIPT_DIR/systemd/"* /etc/systemd/system/
    systemctl daemon-reload

    info "Enabling and starting NetworkMeasureBox systemd target..."
    systemctl enable nmb-db.service nmb-tune.service nmb-netd.service nmb-probe.service nmb-web.service nmb-iperf3.service nmb-adblock.service
    systemctl enable nmb-maintain.timer nmb-snapshot.timer nmb-speed.timer nmb-report.timer nmb-invasive-log.timer nmb-ooni.timer nmb-adblock-update.timer nmb-heal.timer
    systemctl enable nmb.target

    # Preserve and auto-start WireGuard / OpenVPN servers if configured
    if [ -f /etc/wireguard/wg0.conf ]; then
        info "Preserving active WireGuard configuration (/etc/wireguard/wg0.conf)..."
        systemctl enable --now wg-quick@wg0.service 2>/dev/null || true
    fi
    if [ -f /etc/openvpn/server.conf ] || [ -f /etc/openvpn/server/server.conf ]; then
        info "Preserving active OpenVPN configuration..."
        systemctl enable --now openvpn.service 2>/dev/null || true
    fi

    systemctl restart nmb-db.service nmb-tune.service nmb-netd.service nmb-probe.service nmb-web.service nmb-iperf3.service nmb-adblock.service
    systemctl start nmb-maintain.timer nmb-snapshot.timer nmb-speed.timer nmb-report.timer nmb-invasive-log.timer nmb-ooni.timer nmb-adblock-update.timer nmb-heal.timer

elif [ "$INIT_SYSTEM" = "openrc" ]; then
    info "Installing OpenRC init scripts to /etc/init.d/..."
    cp "$SCRIPT_DIR/os/openrc/"* /etc/init.d/
    chmod +x /etc/init.d/nmb-*

    rc-update add nmb-db default
    rc-update add nmb-netd default
    rc-update add nmb-probe default
    rc-update add nmb-web default
    rc-update add nmb-telegram default 2>/dev/null || true

    rc-service nmb-db restart || rc-service nmb-db start
    rc-service nmb-netd restart || rc-service nmb-netd start
    rc-service nmb-probe restart || rc-service nmb-probe start
    rc-service nmb-web restart || rc-service nmb-web start

    # Deploy crontab for Alpine Busybox crond (/etc/crontabs/root format, no username column)
    install -d /etc/crontabs
    cat >/etc/crontabs/root <<'EOF'
*/5 * * * * PYTHONPATH=/opt/nmb /usr/bin/python3 -m nmb.db.database maintain >/dev/null 2>&1
*/15 * * * * PYTHONPATH=/opt/nmb /usr/bin/python3 -m nmb.db.database snapshot >/dev/null 2>&1
0 */6 * * * /usr/local/bin/nmb-speed --trigger schedule >/dev/null 2>&1
5 0 * * * /usr/local/bin/nmb-report --window 24h >/dev/null 2>&1
EOF
    rc-update add crond default 2>/dev/null || true
    rc-service crond restart 2>/dev/null || rc-service crond start 2>/dev/null || true
fi

# Detect primary IP address
HOST_IP=$(ip -4 addr show scope global 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1 || echo "127.0.0.1")

# ------------------------------------------------------------------------------
# 9. Installation Summary Banner
# ------------------------------------------------------------------------------
printf '\n\033[1;32m'
cat <<EOF
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
    nmb-ooni         - OONI Probe censorship & net-neutrality diagnostic suite
    rmbt-client      - Official native C Open-RMBT regulatory speedtest engine
    nmb-invasive-log - Deep invasive technical diagnostic snapshot generator
    nmb-factory-reset- Factory reset utility
    nmb-driver       - Hardware network adapter & kernel firmware scanner/installer
    nmb-adblock/pihole- Built-in OS-independent DNS ad-blocker & sinkhole engine
    nmb-heal         - Automated self-healing engine & stable updates with rollback

  Next Steps:
    1. Open \033[1;34mhttp://${HOST_IP}\033[0m in your browser to access the dashboard.
    2. Log in with user '\033[1;32madmin\033[0m' and password '\033[1;33m${ADMIN_PASS}\033[0m'.
    3. Edit \033[1;33m/etc/nmb/nmb.conf\033[0m to configure your ISP SLA plan, Telegram token, or Wi-Fi.
    4. Check overall system status: \033[1;37msystemctl status nmb.target\033[0m
================================================================================
EOF
