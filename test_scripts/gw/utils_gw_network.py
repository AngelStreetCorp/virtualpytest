#!/usr/bin/env python3
"""
Shared network interface detection and connectivity utilities for gateway test scripts.

Provides cross-platform (Windows/Linux/macOS) functions to:
- Detect default network interfaces from routing tables
- List IPv4 interfaces
- Test interface connectivity via ICMP ping
- Select the best working interface automatically

Used by: superping.py, ookla_speedtest.py, and other gw/ test scripts.
"""

import sys
import os
import socket
import subprocess
import re
from typing import List, Dict, Optional, Tuple

LOG_TAG = 'net_utils'


def _win_decode(raw: bytes) -> str:
    """Decode Windows command output, trying OEM codepage first."""
    for enc in ('oem', 'cp850', 'cp437', 'utf-8'):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode('utf-8', errors='replace')


def _parse_win_route_table(stdout: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse Windows 'route print' output.

    Returns:
        (default_routes, all_interface_ips)
        - default_routes: list of {'interface': ip, 'metric': int} sorted by metric (lowest first)
        - all_interface_ips: unique non-loopback interface IPs from all route entries
    """
    routes: List[Dict] = []
    all_interfaces: List[str] = []
    in_ipv4_table = False

    for line in stdout.split('\n'):
        line = line.strip()
        if 'IPv4' in line and 'Route' in line:
            in_ipv4_table = True
            continue
        if in_ipv4_table and not line:
            break
        if not in_ipv4_table:
            continue
        # Windows route print columns: Destination, Netmask, Gateway, Interface, Metric
        parts = re.split(r'\s+', line)
        if len(parts) >= 5:
            iface_ip = parts[3]
            if re.match(r'\d+\.\d+\.\d+\.\d+', iface_ip) and iface_ip != '127.0.0.1' and iface_ip not in all_interfaces:
                all_interfaces.append(iface_ip)
        # Collect default routes (0.0.0.0 destination)
        if line.startswith('0.0.0.0'):
            if len(parts) >= 5:
                try:
                    metric = int(parts[4])
                except ValueError:
                    metric = 9999
                iface_ip = parts[3]
                if iface_ip and iface_ip != '0.0.0.0':
                    routes.append({'interface': iface_ip, 'metric': metric})

    routes.sort(key=lambda r: r['metric'])
    return routes, all_interfaces


def get_default_interface() -> Optional[str]:
    """
    Get the default network interface used for internet connectivity.

    On Windows, returns the IP address of the interface with the lowest-metric default route.
    On Linux/macOS, returns the interface name (e.g. 'eth0', 'en0').
    """
    try:
        if sys.platform == 'win32':
            cmd = ['route', 'print']
            print(f"🔧 [{LOG_TAG}] CMD: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            stdout = _win_decode(result.stdout)
            stderr = _win_decode(result.stderr)
            print(f"🔧 [{LOG_TAG}] route print rc={result.returncode}")
            if stdout:
                print(f"🔧 [{LOG_TAG}] route print stdout:\n{stdout[:2000]}")
            if stderr:
                print(f"🔧 [{LOG_TAG}] route print stderr:\n{stderr[:500]}")
            if result.returncode == 0:
                routes, all_ifaces = _parse_win_route_table(stdout)
                print(f"🔧 [{LOG_TAG}] Default routes (sorted by metric): {routes}")
                print(f"🔧 [{LOG_TAG}] All route-table interfaces: {all_ifaces}")
                if routes:
                    best = routes[0]['interface']
                    print(f"🔧 [{LOG_TAG}] Best default interface: {best} (metric {routes[0]['metric']})")
                    return best
                print(f"🔧 [{LOG_TAG}] No default interface found in route table")
        else:
            result = subprocess.run(['ip', 'route', 'show'], capture_output=True, text=True, timeout=5)
            print(f"🔧 [{LOG_TAG}] ip route show rc={result.returncode}, stdout: {result.stdout[:500]}")
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'default via' in line:
                        match = re.search(r'default via \d+\.\d+\.\d+\.\d+ dev (\w+)', line)
                        if match:
                            print(f"🔧 [{LOG_TAG}] Default interface from ip route: {match.group(1)}")
                            return match.group(1)

            result = subprocess.run(['route', '-n'], capture_output=True, text=True, timeout=5)
            print(f"🔧 [{LOG_TAG}] route -n rc={result.returncode}, stdout: {result.stdout[:500]}")
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('0.0.0.0'):
                        parts = line.split()
                        if len(parts) >= 8:
                            print(f"🔧 [{LOG_TAG}] Default interface from route -n: {parts[7]}")
                            return parts[7]

            result = subprocess.run(['netstat', '-rn'], capture_output=True, text=True, timeout=5)
            print(f"🔧 [{LOG_TAG}] netstat -rn rc={result.returncode}, stdout: {result.stdout[:500]}")
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('default'):
                        parts = line.split()
                        if len(parts) >= 6:
                            print(f"🔧 [{LOG_TAG}] Default interface from netstat: {parts[5]}")
                            return parts[5]

        print(f"🔧 [{LOG_TAG}] get_default_interface: no interface found")
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        print(f"🔧 [{LOG_TAG}] get_default_interface exception: {type(e).__name__}: {e}")
        return None


def list_ipv4_interfaces() -> List[str]:
    """
    List non-loopback interfaces that have an IPv4 address.

    On Windows, returns IP addresses (from route table, with ipconfig fallback).
    On Linux/macOS, returns interface names.
    """
    interfaces: List[str] = []

    if sys.platform == 'win32':
        # Primary: get interface IPs from route table (reliable, no encoding issues)
        try:
            cmd = ['route', 'print']
            print(f"🔧 [{LOG_TAG}] CMD (list_ifaces): {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            stdout = _win_decode(result.stdout)
            if result.returncode == 0:
                _, route_interfaces = _parse_win_route_table(stdout)
                if route_interfaces:
                    interfaces = route_interfaces
                    print(f"🔧 [{LOG_TAG}] Interfaces from route table: {interfaces}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"🔧 [{LOG_TAG}] route print (list_ifaces) exception: {type(e).__name__}: {e}")

        # Fallback: try ipconfig if route table gave nothing
        if not interfaces:
            try:
                cmd = ['ipconfig']
                print(f"🔧 [{LOG_TAG}] CMD: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                stdout = _win_decode(result.stdout)
                print(f"🔧 [{LOG_TAG}] ipconfig rc={result.returncode}")
                if stdout:
                    print(f"🔧 [{LOG_TAG}] ipconfig stdout:\n{stdout[:3000]}")
                if result.returncode == 0:
                    current_name = None
                    has_ipv4 = False
                    for raw_line in stdout.splitlines():
                        line = raw_line.rstrip()
                        stripped = line.strip()
                        if not stripped:
                            current_name = None
                            has_ipv4 = False
                            continue
                        if not raw_line.startswith((' ', '\t')) and stripped.endswith(':'):
                            current_name = stripped[:-1]
                            has_ipv4 = False
                            print(f"🔧 [{LOG_TAG}] ipconfig section: '{current_name}'")
                            continue
                        # Extract any IPv4 address from lines containing a dotted quad after a colon
                        if current_name:
                            ip_match = re.search(r':\s*(\d+\.\d+\.\d+\.\d+)', stripped)
                            if ip_match:
                                ip_addr = ip_match.group(1)
                                if not ip_addr.startswith('127.') and not ip_addr.startswith('255.'):
                                    has_ipv4 = True
                                    print(f"🔧 [{LOG_TAG}] ipconfig IPv4 found for: '{current_name}' -> {ip_addr}")
                        if current_name and has_ipv4 and current_name not in interfaces:
                            interfaces.append(current_name)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                print(f"🔧 [{LOG_TAG}] ipconfig exception: {type(e).__name__}: {e}")

        print(f"🔧 [{LOG_TAG}] list_ipv4_interfaces (win32) result: {interfaces}")
        return interfaces

    try:
        cmd = ['ip', '-o', '-4', 'addr', 'show', 'up']
        print(f"🔧 [{LOG_TAG}] CMD: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"🔧 [{LOG_TAG}] ip addr rc={result.returncode}, stdout: {result.stdout[:500]}")
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    interface = parts[1]
                    if interface != 'lo' and interface not in interfaces:
                        interfaces.append(interface)
            if interfaces:
                print(f"🔧 [{LOG_TAG}] list_ipv4_interfaces result: {interfaces}")
                return interfaces
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"🔧 [{LOG_TAG}] ip addr exception: {type(e).__name__}: {e}")

    try:
        cmd = ['ifconfig']
        print(f"🔧 [{LOG_TAG}] CMD: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"🔧 [{LOG_TAG}] ifconfig rc={result.returncode}, stdout: {result.stdout[:500]}")
        if result.returncode == 0:
            current_interface = None
            for line in result.stdout.splitlines():
                if line and not line.startswith((' ', '\t')):
                    current_interface = line.split(':', 1)[0]
                    continue
                if current_interface in ('lo', 'lo0'):
                    continue
                if current_interface and 'inet ' in line and '127.0.0.1' not in line and current_interface not in interfaces:
                    interfaces.append(current_interface)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"🔧 [{LOG_TAG}] ifconfig exception: {type(e).__name__}: {e}")

    print(f"🔧 [{LOG_TAG}] list_ipv4_interfaces result: {interfaces}")
    return interfaces


def get_interface_ipv4_address(interface: str) -> str:
    """
    Return the IPv4 address assigned to an interface.

    On Windows, if the interface is already an IP address, returns it directly.
    On Linux/macOS, queries the system for the IP of the named interface.
    """
    if not interface:
        raise ValueError("Interface name is required")

    # On Windows, interface from route table is already an IP
    if re.match(r'\d+\.\d+\.\d+\.\d+$', interface):
        return interface

    commands = [
        ['ip', '-4', 'addr', 'show', 'dev', interface],
        ['ifconfig', interface],
    ]

    for cmd in commands:
        try:
            cmd_str = ' '.join(cmd)
            print(f"🔧 [{LOG_TAG}] CMD: {cmd_str}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            print(f"🔧 [{LOG_TAG}] {cmd[0]} rc={result.returncode}, stdout: {result.stdout[:300]}, stderr: {result.stderr[:300]}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"🔧 [{LOG_TAG}] {cmd[0]} exception: {type(e).__name__}: {e}")
            continue

        if result.returncode != 0:
            continue

        output = result.stdout + result.stderr
        ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', output)
        if ip_match:
            print(f"🔧 [{LOG_TAG}] Interface '{interface}' has IPv4: {ip_match.group(1)}")
            return ip_match.group(1)

    raise ValueError(f"Cannot determine IPv4 address for interface '{interface}'")


def resolve_source_ip(target_ip: str, ip_version: int = 4, interface: Optional[str] = None) -> Optional[str]:
    """
    Determine the local source IP (IPv4 or IPv6) the OS would use to reach
    target_ip, optionally constrained to a given interface.

    Strategy:
      1. Linux/macOS: 'ip route get <target> [oif <interface>]' -> parse 'src <ip>'
      2. Fallback (all platforms): UDP-connect trick + getsockname() (no packets sent)
    """
    # 1. 'ip route get' (Linux; harmless elsewhere if iproute2 is absent)
    if not sys.platform.startswith('win'):
        cmd = ['ip', '-6' if ip_version == 6 else '-4', 'route', 'get', target_ip]
        if interface:
            cmd += ['oif', interface]
        try:
            cmd_str = ' '.join(cmd)
            print(f"🔧 [{LOG_TAG}] CMD: {cmd_str}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            print(f"🔧 [{LOG_TAG}] ip route get rc={result.returncode}, stdout: {result.stdout[:300]}, stderr: {result.stderr[:300]}")
            if result.returncode == 0:
                m = re.search(r'\bsrc\s+([0-9a-fA-F:.]+)', result.stdout)
                if m:
                    print(f"🔧 [{LOG_TAG}] Source IP for {target_ip} via {interface or 'default'}: {m.group(1)}")
                    return m.group(1)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"🔧 [{LOG_TAG}] ip route get exception: {type(e).__name__}: {e}")

    # 2. UDP-connect fallback (connect() on a DGRAM socket sends nothing)
    family = socket.AF_INET6 if ip_version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        if interface and ip_version == 4:
            try:
                sock.bind((get_interface_ipv4_address(interface), 0))
            except (ValueError, OSError) as e:
                print(f"🔧 [{LOG_TAG}] resolve_source_ip bind skipped: {type(e).__name__}: {e}")
        sock.connect((target_ip, 443))
        src = sock.getsockname()[0]
        print(f"🔧 [{LOG_TAG}] Source IP (socket) for {target_ip}: {src}")
        return src
    except OSError as e:
        print(f"🔧 [{LOG_TAG}] resolve_source_ip socket fallback failed: {type(e).__name__}: {e}")
        return None
    finally:
        sock.close()


def ping_via_interface(target: str, interface: str, timeout: int = 2) -> Dict:
    """
    Run a single ICMP ping through a specific interface.

    On Windows, uses -S <source_ip> to bind to interface.
    On Linux/macOS, uses -I <interface_name>.
    """
    try:
        if sys.platform == 'darwin':
            cmd = ['ping', '-4', '-c', '1', '-W', str(timeout * 1000)]
            if interface:
                cmd.extend(['-I', interface])
            cmd.append(target)
        elif sys.platform == 'win32':
            source_ip = get_interface_ipv4_address(interface)
            cmd = ['ping', '-n', '1', '-w', str(timeout * 1000), '-S', source_ip, target]
        else:
            cmd = ['ping', '-4', '-c', '1', '-W', str(timeout)]
            if interface:
                cmd.extend(['-I', interface])
            cmd.append(target)

        cmd_str = ' '.join(cmd)
        print(f"🔧 [{LOG_TAG}] CMD: {cmd_str}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        output = (result.stdout + result.stderr).strip()
        print(f"🔧 [{LOG_TAG}] ping rc={result.returncode}")
        if output:
            print(f"🔧 [{LOG_TAG}] ping output:\n{output[:1000]}")

        success = result.returncode == 0
        error = None
        if not success:
            output_lines = output.splitlines()[:3]
            error = 'Ping failed'
            if output_lines:
                error = f"{error}: {' | '.join(output_lines)}"

        return {
            'success': success,
            'error': error,
            'raw_output': output,
        }
    except Exception as exc:
        print(f"🔧 [{LOG_TAG}] ping exception: {type(exc).__name__}: {exc}")
        return {
            'success': False,
            'error': str(exc),
            'raw_output': '',
        }


def select_working_interface(connectivity_target: str = '8.8.8.8') -> Tuple[Optional[str], List[Dict[str, str]]]:
    """
    Choose the first interface with working internet connectivity.

    On Windows, tries all default routes sorted by metric (lowest first).
    Then adds any remaining IPv4 interfaces as fallback candidates.
    """
    attempts: List[Dict[str, str]] = []
    candidates: List[str] = []

    print(f"🔧 [{LOG_TAG}] select_working_interface: target={connectivity_target}")

    # On Windows, get ALL default routes sorted by metric as candidates
    if sys.platform == 'win32':
        try:
            result = subprocess.run(['route', 'print'], capture_output=True, timeout=5)
            stdout = _win_decode(result.stdout)
            if result.returncode == 0:
                routes, _ = _parse_win_route_table(stdout)
                for r in routes:
                    if r['interface'] not in candidates:
                        candidates.append(r['interface'])
                print(f"🔧 [{LOG_TAG}] All default route candidates (by metric): {candidates}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if not candidates:
        default_interface = get_default_interface()
        print(f"🔧 [{LOG_TAG}] default_interface={default_interface}")
        if default_interface:
            candidates.append(default_interface)

    ipv4_interfaces = list_ipv4_interfaces()
    print(f"🔧 [{LOG_TAG}] ipv4_interfaces={ipv4_interfaces}")
    for interface in ipv4_interfaces:
        if interface not in candidates:
            candidates.append(interface)

    print(f"🔧 [{LOG_TAG}] candidates={candidates}")
    if not candidates:
        print(f"🔧 [{LOG_TAG}] WARNING: No candidate interfaces found!")
        return None, attempts

    for interface in candidates:
        print(f"🔧 [{LOG_TAG}] Testing connectivity via interface: '{interface}'")
        ping_result = ping_via_interface(connectivity_target, interface)
        print(f"🔧 [{LOG_TAG}] Ping result for '{interface}': success={ping_result.get('success')}, error={ping_result.get('error')}")
        attempts.append({
            'interface': interface,
            'success': str(ping_result.get('success', False)).lower(),
            'error': ping_result.get('error') or '',
        })
        if ping_result.get('success'):
            print(f"🔧 [{LOG_TAG}] ✅ Selected interface: '{interface}'")
            return interface, attempts

    print(f"🔧 [{LOG_TAG}] ❌ No interface passed connectivity check. Attempts: {attempts}")
    return None, attempts
