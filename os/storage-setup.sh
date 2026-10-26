#!/bin/sh
# NetworkMeasureBox — Phase 1 OS baseline: tmpfs layout + microSD longevity.
# Idempotent. Works on Debian (systemd) and Alpine (OpenRC). Run as root.
set -eu

NMB_USER=nmb
TMPFS_DB_SIZE=${TMPFS_DB_SIZE:-256M}
FSTAB=/etc/fstab
MARK="# nmb-managed"

log() { printf '[nmb-storage] %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "must run as root" >&2; exit 1; }

# 1. Service user
if ! id "$NMB_USER" >/dev/null 2>&1; then
    if command -v adduser >/dev/null && [ -f /etc/alpine-release ]; then
        addgroup -S "$NMB_USER"; adduser -S -D -H -G "$NMB_USER" -s /sbin/nologin "$NMB_USER"
    else
        useradd --system --no-create-home --shell /usr/sbin/nologin "$NMB_USER"
    fi
fi
NMB_UID=$(id -u "$NMB_USER"); NMB_GID=$(id -g "$NMB_USER")

# 2. Directories
install -d -m 0775 -o root -g "$NMB_USER" /etc/nmb
install -d -m 0755 /opt/nmb
install -d -m 2775 -o "$NMB_USER" -g "$NMB_USER" /var/lib/nmb /var/lib/nmb/persist /var/lib/nmb/persist/reports
install -d -m 2775 -o "$NMB_USER" -g "$NMB_USER" /var/lib/nmb/live /var/log/nmb /run/nmb

# 3. fstab: tmpfs mounts (+ noatime/commit on root)
sed -i "/$MARK/d" "$FSTAB"
cat >>"$FSTAB" <<EOF
tmpfs /tmp              tmpfs defaults,noatime,nosuid,nodev,mode=1777,size=128M 0 0 $MARK
tmpfs /var/tmp          tmpfs defaults,noatime,nosuid,nodev,mode=1777,size=32M  0 0 $MARK
tmpfs /var/log          tmpfs defaults,noatime,nosuid,nodev,mode=0755,size=48M  0 0 $MARK
tmpfs /var/lib/nmb/live tmpfs defaults,noatime,nosuid,nodev,noexec,mode=2775,uid=$NMB_UID,gid=$NMB_GID,size=$TMPFS_DB_SIZE 0 0 $MARK
EOF

# root ext4: noatime + 10 min commit interval (fewer journal flushes)
if awk '$2=="/" && $3=="ext4"' "$FSTAB" | grep -q .; then
    awk -v OFS='\t' '$2=="/" && $3=="ext4" && $4 !~ /commit=/ {
        $4=$4",noatime,commit=600"; gsub(/,relatime|,atime/,"",$4) } {print}' "$FSTAB" >"$FSTAB.nmb" \
        && mv "$FSTAB.nmb" "$FSTAB"
fi

# 4. Logging to RAM
if [ -d /etc/systemd ]; then
    install -d /etc/systemd/journald.conf.d
    cat >/etc/systemd/journald.conf.d/50-nmb-volatile.conf <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=32M
RuntimeMaxFileSize=4M
Compress=yes
ForwardToSyslog=no
EOF
    rm -rf /var/log/journal
    # tmpfiles: recreate /var/log/nmb and /run/nmb on each boot
    cat >/etc/tmpfiles.d/nmb.conf <<EOF
d /run/nmb         2775 $NMB_USER $NMB_USER -
d /var/log/nmb     2775 $NMB_USER $NMB_USER -
d /var/lib/nmb/live 2775 $NMB_USER $NMB_USER -
EOF
else
    # Alpine busybox syslog -> circular in-memory buffer
    [ -f /etc/conf.d/syslog ] && sed -i 's/^SYSLOGD_OPTS=.*/SYSLOGD_OPTS="-C512"/' /etc/conf.d/syslog
fi

# 5. Swap off (swapping kills SD cards)
swapoff -a 2>/dev/null || true
sed -i '/\sswap\s/s/^[^#]/#&/' "$FSTAB"
command -v dphys-swapfile >/dev/null && { dphys-swapfile swapoff || true; systemctl disable --now dphys-swapfile 2>/dev/null || true; }

# 6. Writeback tuning: batch dirty pages longer
install -d /etc/sysctl.d
cat >/etc/sysctl.d/60-nmb-storage.conf <<'EOF'
vm.swappiness = 1
vm.dirty_writeback_centisecs = 6000
vm.dirty_expire_centisecs = 6000
vm.dirty_background_ratio = 20
vm.dirty_ratio = 40
EOF
sysctl -q -p /etc/sysctl.d/60-nmb-storage.conf || true

# 7. Disable SD-chatty timers where present
for u in apt-daily.timer apt-daily-upgrade.timer man-db.timer e2scrub_all.timer; do
    systemctl disable --now "$u" 2>/dev/null || true
done

# 8. Mount the tmpfs now (no reboot needed)
for m in /tmp /var/tmp /var/lib/nmb/live; do
    mountpoint -q "$m" || mount "$m"
done
log "storage baseline applied. Reboot recommended to move /var/log to tmpfs."
