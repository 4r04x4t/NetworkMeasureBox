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
        python3 iproute2 nftables iptables ethtool \
        dnsmasq hostapd ppp pppoe udhcpc curl ca-certificates procps libcap2-bin \
        wireguard-tools openvpn easy-rsa python3-qrcode qrencode

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
        curl ca-certificates busybox-extras libcap

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

# Grant strictly parameterized administration rights via nmb-helper in sudoers
if [ -d /etc/sudoers.d ]; then
    echo "$NMB_USER ALL=(ALL) NOPASSWD: /usr/bin/nmcli, /usr/bin/ip, /usr/sbin/ip, /usr/bin/mtr, /usr/local/bin/nmb-helper" > /etc/sudoers.d/020_nmb-net
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
cp -r "$SCRIPT_DIR/docs" "$INSTALL_DIR/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/bin/"* "$INSTALL_DIR/os/"*.sh

# Configuration file
install -d -m 0770 -o root -g "$NMB_USER" "$CONFIG_DIR"
if [ ! -f "$CONFIG_FILE" ]; then
    if [ -f "$SCRIPT_DIR/config/nmb.conf.example" ]; then
        cp "$SCRIPT_DIR/config/nmb.conf.example" "$CONFIG_FILE"
    fi
    info "Created default configuration at $CONFIG_FILE"
fi

# Generate strong random admin password on installation if default "admin"
if grep -q "admin_password = admin" "$CONFIG_FILE" 2>/dev/null; then
    NEW_ADMIN_PASS=$(head -c 16 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 14)
    sed -i "s/admin_password = admin/admin_password = $NEW_ADMIN_PASS/" "$CONFIG_FILE"
    info "Generated secure random Web UI admin password: $NEW_ADMIN_PASS"
fi

chown "$NMB_USER":"$NMB_USER" "$CONFIG_FILE"
chmod 0600 "$CONFIG_FILE"

# Symlink executables into /usr/local/bin
for b in nmb-netd nmb-probe nmb-speed nmb-report nmb-telegram nmb-web nmb-helper; do
    ln -sf "$INSTALL_DIR/bin/$b" "/usr/local/bin/$b"
done

# ------------------------------------------------------------------------------
# 7. Initialize Database (Restore from SD or bootstrap new schema)
# ------------------------------------------------------------------------------
info "Initializing SQLite database..."
PYTHONPATH="$INSTALL_DIR" python3 -m nmb.db.database restore

# Set ownership and group sticky bits for cross-process access
install -d -m 2775 -o "$NMB_USER" -g "$NMB_USER" /var/lib/nmb /var/lib/nmb/live /var/lib/nmb/persist /var/lib/nmb/persist/reports /var/log/nmb /run/nmb 2>/dev/null || true
chown -R "$NMB_USER:$NMB_USER" /var/lib/nmb /var/log/nmb /run/nmb 2>/dev/null || true
chmod -R u+rwX,g+rwX /var/lib/nmb /var/log/nmb /run/nmb 2>/dev/null || true
chmod 2775 /var/lib/nmb /var/lib/nmb/live /var/lib/nmb/persist /var/lib/nmb/persist/reports /var/log/nmb /run/nmb 2>/dev/null || true

# ------------------------------------------------------------------------------
# 8. Service Units Deployment & Activation
# ------------------------------------------------------------------------------
if [ "$INIT_SYSTEM" = "systemd" ]; then
    info "Installing systemd units to /etc/systemd/system/..."
    cp "$SCRIPT_DIR/systemd/"* /etc/systemd/system/
    systemctl daemon-reload

    info "Enabling and starting NetworkMeasureBox systemd target..."
    systemctl enable nmb-db.service nmb-tune.service nmb-netd.service nmb-probe.service nmb-web.service
    systemctl enable nmb-maintain.timer nmb-snapshot.timer nmb-speed.timer nmb-report.timer
    systemctl enable nmb.target

    systemctl restart nmb-db.service nmb-tune.service nmb-netd.service nmb-probe.service nmb-web.service
    systemctl start nmb-maintain.timer nmb-snapshot.timer nmb-speed.timer nmb-report.timer

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
  * Management Web UI  : \033[1;34mhttp://${HOST_IP}:8080\033[0m
  * Configuration File : \033[1;33m/etc/nmb/nmb.conf\033[0m
  * Live Database      : /var/lib/nmb/live/nmb.db (tmpfs RAM)
  * Persistent SD DB   : /var/lib/nmb/persist/nmb.db (15-min snapshots)
  * Reports Directory  : /var/lib/nmb/persist/reports/

  CLI Tools Installed:
    nmb-netd     - Network mode manager (--status, --switch auto|standalone|mode_a|mode_b)
    nmb-probe    - High-performance ICMP latency/jitter engine
    nmb-speed    - Speedtest & port throttling runner (--trigger manual)
    nmb-report   - HTML dossier generator & ISP fault dispatcher (--window 24h)
    nmb-telegram - Management Telegram bot daemon
    nmb-web      - Embedded management web server

  Next Steps:
    1. Open \033[1;34mhttp://${HOST_IP}:8080\033[0m in your browser to access the dashboard.
    2. Edit \033[1;33m/etc/nmb/nmb.conf\033[0m to configure your ISP SLA plan, Telegram token, or Wi-Fi.
    3. Check overall system status: \033[1;37msystemctl status nmb.target\033[0m
================================================================================
EOF
