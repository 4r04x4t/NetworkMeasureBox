#!/bin/sh
# NetworkMeasureBox — NIC Hardware Acceleration & Buffer Tuning
# Maximizes ring buffers, hardware offload (TSO/GRO), and disables EEE jitter.
set -eu

log() { printf '[nmb-nic] %s\n' "$*"; }

IFACE=${1:-""}

tune_interface() {
    dev="$1"
    [ -d "/sys/class/net/$dev" ] || return 0
    [ "$dev" = "lo" ] && return 0
    # Skip virtual bridges and tun/tap
    [ -d "/sys/class/net/$dev/bridge" ] && return 0

    log "tuning network interface $dev..."

    if command -v ethtool >/dev/null 2>&1; then
        # 1. Expand Ring Buffers to maximum hardware support (e.g. 4096 descriptors)
        max_rx=$(ethtool -g "$dev" 2>/dev/null | awk '/Pre-set maximums:/,/RX:/' | awk '/RX:/ {print $2}' | tail -n1 || echo "")
        max_tx=$(ethtool -g "$dev" 2>/dev/null | awk '/Pre-set maximums:/,/TX:/' | awk '/TX:/ {print $2}' | tail -n1 || echo "")

        if [ -n "$max_rx" ] && [ "$max_rx" -gt 0 ] 2>/dev/null; then
            log "setting $dev ring buffers: rx $max_rx, tx ${max_tx:-$max_rx}"
            ethtool -G "$dev" rx "$max_rx" tx "${max_tx:-$max_rx}" 2>/dev/null || true
        fi

        # 2. Hardware Offloading: TSO, GSO, GRO, Checksumming
        log "enabling hardware offloads on $dev (TSO, GSO, GRO, TX/RX chksum)"
        ethtool -K "$dev" tso on gso on gro on rx on tx on 2>/dev/null || true

        # 3. Interrupt Coalescing (Adaptive RX/TX mitigation)
        ethtool -C "$dev" adaptive-rx on adaptive-tx on 2>/dev/null || true

        # 4. Disable Energy Efficient Ethernet (EEE) to prevent latency spikes during packet bursts
        ethtool --set-eee "$dev" eee off 2>/dev/null || true
    fi

    # 5. Interface transmit queue length (txqueuelen)
    if command -v ip >/dev/null 2>&1; then
        TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 1048576)
        TXQ=$([ "$TOTAL_RAM_KB" -le 800000 ] && echo 1000 || echo 10000)
        ip link set dev "$dev" txqueuelen "$TXQ" 2>/dev/null || true
    fi

    # 6. Multi-core Packet Steering (RPS/RFS/XPS)
    cpus=$(nproc 2>/dev/null || echo 1)
    mask=$(printf '%x' $(( (1 << cpus) - 1 )))
    for rq in /sys/class/net/"$dev"/queues/rx-*; do
        [ -e "$rq" ] || continue
        echo "$mask" > "$rq/rps_cpus" 2>/dev/null || true
        echo 4096 > "$rq/rps_flow_cnt" 2>/dev/null || true
    done
    for tq in /sys/class/net/"$dev"/queues/tx-*; do
        [ -e "$tq" ] || continue
        echo "$mask" > "$tq/xps_cpus" 2>/dev/null || true
    done
}

if [ -n "$IFACE" ]; then
    tune_interface "$IFACE"
else
    # Tune all physical interfaces found in /sys/class/net
    for d in /sys/class/net/*; do
        [ -e "$d" ] || continue
        name=$(basename "$d")
        # Check if interface has a physical device backing it
        if [ -d "$d/device" ]; then
            tune_interface "$name"
        fi
    done
fi
log "NIC tuning complete."
