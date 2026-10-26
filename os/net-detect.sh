#!/bin/sh
# NetworkMeasureBox — Low-level network interface and link carrier inspection script
set -eu

WAN_IFACE=${1:-eth0}
LAN_IFACE=${2:-eth1}
WLAN_IFACE=${3:-wlan0}

printf "===============================================\n"
printf "NetworkMeasureBox Interface Link Diagnostic\n"
printf "===============================================\n"

check_iface() {
    dev="$1"
    role="$2"
    if [ ! -d "/sys/class/net/$dev" ]; then
        printf "[ %-4s ] %-10s : NOT PRESENT\n" "$role" "$dev"
        return
    fi

    carrier="0"
    [ -f "/sys/class/net/$dev/carrier" ] && carrier=$(cat "/sys/class/net/$dev/carrier" 2>/dev/null || echo "0")
    operstate=$(cat "/sys/class/net/$dev/operstate" 2>/dev/null || echo "unknown")
    mac=$(cat "/sys/class/net/$dev/address" 2>/dev/null || echo "")

    status="DOWN"
    [ "$carrier" = "1" ] && status="UP (Carrier Active)"

    printf "[ %-4s ] %-10s : %-20s (mac: %s, operstate: %s)\n" "$role" "$dev" "$status" "$mac" "$operstate"
}

check_iface "$WAN_IFACE" "WAN"
check_iface "$LAN_IFACE" "LAN"
check_iface "$WLAN_IFACE" "WLAN"

printf "\nBridge & Route Status:\n"
if [ -d "/sys/class/net/br0" ]; then
    printf "Bridge br0       : ACTIVE\n"
else
    printf "Bridge br0       : NOT ACTIVE\n"
fi

default_dev=$(ip route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' | head -n1 || echo "none")
printf "Default Gateway  : via dev %s\n" "${default_dev:-none}"

printf "\nNMB Netd Status Snapshot:\n"
if [ -f "/run/nmb/netd_state.json" ]; then
    cat "/run/nmb/netd_state.json"
else
    printf "(No active netd_state.json found in /run/nmb)\n"
fi
printf "\n"
