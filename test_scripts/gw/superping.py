#!/usr/bin/env python3
"""
Superping Script for VirtualPyTest

Performs network path analysis with ping, traceroute, and QoS metrics.
Measures RTT, jitter, packet loss, and maps the complete path to target.

Usage:
    python test_scripts/gw/superping.py [--target <url:port>] [--protocol <icmp|tcp|udp>] [--count <n>] [--max_hops <n>] [--interface <ifname>]

Examples:
    python test_scripts/gw/superping.py                                              # Default: ICMP to google.com
    python test_scripts/gw/superping.py --target youtube.com:443 --protocol tcp      # TCP to YouTube
    python test_scripts/gw/superping.py --target 8.8.8.8 --protocol icmp --count 10  # 10 ICMP pings to Google DNS
    python test_scripts/gw/superping.py --target example.com:443 --protocol tcp
    python test_scripts/gw/superping.py --target example.org:443 --protocol tcp
    python test_scripts/gw/superping.py --target google.com --interface ens19
    
"""

import sys
import os
import socket
import subprocess
import time
import re
import statistics
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args
from test_scripts.gw.utils_gw_network import (
    get_default_interface, list_ipv4_interfaces, get_interface_ipv4_address,
    ping_via_interface, select_working_interface, resolve_source_ip,
)

# Script arguments
_script_args = [
    '--target:str:google.com',
    '--protocol:str:icmp:icmp|tcp|udp',
    '--count:int:5',
    '--max_hops:int:255',
    '--interface:str:auto',
    '--ip_version:int:4:4|6',
]
_script_description = "Network path analysis with ping, traceroute, and QoS scoring."
_arg_descriptions = {
    "target": "Hostname or IP, optionally with port.",
    "protocol": "Ping protocol: icmp, tcp, or udp.",
    "count": "Number of ping packets to send.",
    "max_hops": "Maximum traceroute hops.",
    "interface": "Optional network interface to use for probes, e.g. ens19.",
    "ip_version": "IP version: 4 (default) or 6.",
}


def resolve_target(target: str, ip_version: int = 4) -> Tuple[str, str, int]:
    """
    Resolve target to (hostname, IP address, port) for the requested IP version.
    For IPv6 targets, accept bracketed syntax '[2001:db8::1]:443' so the ':' in
    the address is not confused with the port separator.
    """
    if target.startswith('['):
        # Bracketed IPv6, e.g. [2001:db8::1]:443
        end = target.find(']')
        if end == -1:
            raise ValueError(f"Invalid bracketed target '{target}'")
        host = target[1:end]
        rest = target[end + 1:]
        if rest.startswith(':'):
            try:
                port = int(rest[1:])
            except ValueError:
                port = 443
        else:
            port = 443
    elif target.count(':') == 1:
        # hostname:port or ipv4:port
        host, port_str = target.rsplit(':', 1)
        try:
            port = int(port_str)
        except ValueError:
            host = target
            port = 443
    elif ':' in target:
        # Bare IPv6 literal without brackets
        host = target
        port = 443
    else:
        host = target
        port = 443

    family = socket.AF_INET6 if ip_version == 6 else socket.AF_INET
    label = "IPv6" if ip_version == 6 else "IPv4"
    try:
        addrinfo = socket.getaddrinfo(host, None, family, socket.SOCK_STREAM)
        if not addrinfo:
            raise socket.gaierror(f"No {label} address found")
        ip = addrinfo[0][4][0]
        return host, ip, port
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve {label} hostname '{host}': {e}")


def run_icmp_ping(host: str, count: int, timeout: int = 3, interface: Optional[str] = None, ip_version: int = 4) -> Dict:
    """Run ICMP ping using system ping command and parse results"""
    try:
        is_windows = sys.platform.startswith('win')
        v_flag = '-6' if ip_version == 6 else '-4'

        # Use platform-appropriate ping command
        if sys.platform == 'darwin':  # macOS
            cmd = ['ping', v_flag, '-c', str(count), '-W', str(timeout * 1000)]
            if interface:
                cmd.extend(['-I', interface])
            cmd.append(host)
        elif is_windows:
            # Windows timeout is in milliseconds and uses -n for count, -S for source IP
            cmd = ['ping', v_flag, '-n', str(count), '-w', str(timeout * 1000)]
            if interface and re.match(r'\d+\.\d+\.\d+\.\d+', interface):
                cmd.extend(['-S', interface])
            cmd.append(host)
        else:  # Linux
            cmd = ['ping', v_flag, '-c', str(count), '-W', str(timeout)]
            if interface:
                cmd.extend(['-I', interface])
            cmd.append(host)

        cmd_str = ' '.join(cmd)
        print(f"🔧 [superping] CMD: {cmd_str}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * count + 5)
        output = result.stdout + result.stderr
        print(f"🔧 [superping] ping rc={result.returncode}")
        if output:
            print(f"🔧 [superping] ping output:\n{output[:1000]}")

        # Parse ping statistics
        rtts = []
        packets_transmitted = 0
        packets_received = 0

        for line in output.split('\n'):
            # Parse RTT lines (Linux/macOS): "time=25.4 ms"
            time_match = re.search(r'time[=:]?\s*([0-9.<>]+)\s*ms', line, re.IGNORECASE)
            if time_match:
                time_val = time_match.group(1).replace('<', '')
                try:
                    rtts.append(float(time_val))
                except ValueError:
                    pass

            # Parse packet statistics (Linux/macOS)
            stats_match = re.search(r'(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received', line)
            if stats_match:
                packets_transmitted = int(stats_match.group(1))
                packets_received = int(stats_match.group(2))

            # Parse packet statistics (Windows)
            if is_windows:
                win_stats = re.search(
                    r'Packets:\s+Sent\s*=\s*(\d+),\s+Received\s*=\s*(\d+),\s+Lost\s*=\s*(\d+)',
                    line,
                    re.IGNORECASE
                )
                if win_stats:
                    packets_transmitted = int(win_stats.group(1))
                    packets_received = int(win_stats.group(2))

        # Parse summary statistics if available
        rtt_stats = {}
        stats_line_match = re.search(
            r'min/avg/max/(?:stddev|mdev)\s*=\s*(\d+\.?\d*)/(\d+\.?\d*)/(\d+\.?\d*)/(\d+\.?\d*)',
            output
        )
        if stats_line_match:
            rtt_stats = {
                'min': float(stats_line_match.group(1)),
                'avg': float(stats_line_match.group(2)),
                'max': float(stats_line_match.group(3)),
                'stddev': float(stats_line_match.group(4)),
            }
        else:
            # Windows summary: "Minimum = 11ms, Maximum = 15ms, Average = 12ms"
            win_rtt = re.search(
                r'Minimum\s*=\s*(\d+)\s*ms,\s*Maximum\s*=\s*(\d+)\s*ms,\s*Average\s*=\s*(\d+)\s*ms',
                output,
                re.IGNORECASE
            )
            if win_rtt:
                rtt_stats = {
                    'min': float(win_rtt.group(1)),
                    'avg': float(win_rtt.group(3)),
                    'max': float(win_rtt.group(2)),
                    'stddev': 0,
                }
            elif rtts:
                rtt_stats = {
                    'min': min(rtts),
                    'avg': statistics.mean(rtts),
                    'max': max(rtts),
                    'stddev': statistics.stdev(rtts) if len(rtts) > 1 else 0,
                }

        packet_loss = ((packets_transmitted - packets_received) / packets_transmitted * 100) if packets_transmitted > 0 else 100
        success = result.returncode == 0 and packets_received > 0
        error = None
        if not success:
            output_head = output.strip().splitlines()[:3]
            error = "Ping failed"
            if output_head:
                error = f"{error}: {' | '.join(output_head)}"

        return {
            'success': success,
            'error': error,
            'rtts': rtts,
            'rtt_stats': rtt_stats,
            'packets_transmitted': packets_transmitted,
            'packets_received': packets_received,
            'packet_loss_percent': packet_loss,
            'raw_output': output
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Ping timeout',
            'rtts': [],
            'rtt_stats': {},
            'packet_loss_percent': 100
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'rtts': [],
            'rtt_stats': {},
            'packet_loss_percent': 100
        }


def run_tcp_ping(host: str, port: int, count: int, timeout: int = 3, interface: Optional[str] = None, ip_version: int = 4) -> Dict:
    """Run TCP connect test (TCP ping equivalent)"""
    rtts = []
    successful = 0
    source_ip = None
    bound_source_ip = None
    family = socket.AF_INET6 if ip_version == 6 else socket.AF_INET

    # Source-IP binding via interface is IPv4-only here; IPv6 uses interface at
    # the ping/traceroute level only, not on raw sockets.
    if interface and ip_version == 4:
        try:
            source_ip = get_interface_ipv4_address(interface)
        except ValueError as e:
            return {
                'success': False,
                'error': str(e),
                'rtts': [],
                'rtt_stats': {},
                'packet_loss_percent': 100
            }

    for i in range(count):
        start = time.time()
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        if source_ip:
            sock.bind((source_ip, 0))
        
        try:
            result = sock.connect_ex((host, port))
            elapsed = (time.time() - start) * 1000  # Convert to ms

            if result == 0:
                rtts.append(elapsed)
                successful += 1
                if bound_source_ip is None:
                    bound_source_ip = sock.getsockname()[0]
        except Exception as e:
            pass
        finally:
            sock.close()

        # Small delay between attempts
        if i < count - 1:
            time.sleep(0.5)
    
    rtt_stats = {}
    if rtts:
        rtt_stats = {
            'min': min(rtts),
            'avg': statistics.mean(rtts),
            'max': max(rtts),
            'stddev': statistics.stdev(rtts) if len(rtts) > 1 else 0,
        }
    
    packet_loss = ((count - successful) / count * 100) if count > 0 else 100
    
    return {
        'success': successful > 0,
        'rtts': rtts,
        'rtt_stats': rtt_stats,
        'packets_transmitted': count,
        'packets_received': successful,
        'packet_loss_percent': packet_loss,
        'source_ip': bound_source_ip,
        'raw_output': f'TCP connect to {host}:{port} - {successful}/{count} successful'
    }


def run_udp_ping(host: str, port: int, count: int, timeout: int = 3, interface: Optional[str] = None, ip_version: int = 4) -> Dict:
    """Run UDP probe test"""
    rtts = []
    successful = 0
    source_ip = None
    bound_source_ip = None
    family = socket.AF_INET6 if ip_version == 6 else socket.AF_INET

    if interface and ip_version == 4:
        try:
            source_ip = get_interface_ipv4_address(interface)
        except ValueError as e:
            return {
                'success': False,
                'error': str(e),
                'rtts': [],
                'rtt_stats': {},
                'packet_loss_percent': 100
            }

    # Use common UDP ports if not specified
    test_port = port if port != 443 else 53  # Use DNS port for UDP

    for i in range(count):
        start = time.time()
        sock = socket.socket(family, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        if source_ip:
            sock.bind((source_ip, 0))
        
        try:
            # Send UDP packet
            sock.sendto(b'\x00' * 32, (host, test_port))
            if bound_source_ip is None:
                bound_source_ip = sock.getsockname()[0]

            # Try to receive (may timeout, which is normal for UDP)
            try:
                data, addr = sock.recvfrom(1024)
                elapsed = (time.time() - start) * 1000
                rtts.append(elapsed)
                successful += 1
            except socket.timeout:
                # For UDP, timeout doesn't mean failure - we just don't get a response
                elapsed = (time.time() - start) * 1000
                rtts.append(elapsed)
                successful += 1
        except Exception as e:
            pass
        finally:
            sock.close()
        
        if i < count - 1:
            time.sleep(0.5)
    
    rtt_stats = {}
    if rtts:
        rtt_stats = {
            'min': min(rtts),
            'avg': statistics.mean(rtts),
            'max': max(rtts),
            'stddev': statistics.stdev(rtts) if len(rtts) > 1 else 0,
        }
    
    packet_loss = ((count - successful) / count * 100) if count > 0 else 100
    
    return {
        'success': successful > 0,
        'rtts': rtts,
        'rtt_stats': rtt_stats,
        'packets_transmitted': count,
        'packets_received': successful,
        'packet_loss_percent': packet_loss,
        'source_ip': bound_source_ip,
        'raw_output': f'UDP probe to {host}:{test_port} - {successful}/{count} successful'
    }


def run_traceroute(host: str, protocol: str, max_hops: int = 30, interface: Optional[str] = None, ip_version: int = 4) -> Dict:
    """Run traceroute to map network path"""
    cmd_str = None
    timeout_seconds = None
    try:
        is_windows = sys.platform.startswith('win')
        v_flag = '-6' if ip_version == 6 else '-4'

        if is_windows:
            # Windows tracert uses -6 for IPv6 (-d skipped to keep hostname resolution)
            cmd = ['tracert', v_flag, '-h', str(max_hops), host]
            timeout_seconds = max_hops * 2 + 15
            cmd_str = ' '.join(cmd)
            print(f"🧭 [superping] Traceroute cmd: {cmd_str} (timeout {timeout_seconds}s)")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
            output = result.stdout + result.stderr

            hops = []
            hop_idx = 0
            for line in output.split('\n'):
                line = line.strip()
                if not line or line.lower().startswith('tracing') or line.lower().startswith('over a maximum'):
                    continue

                # Example: "  1    <1 ms    <1 ms    <1 ms  router [192.168.1.1]"
                hop_match = re.match(r'^\s*(\d+)\s+(.+)$', line)
                if not hop_match:
                    continue

                ttl = int(hop_match.group(1))
                rest = hop_match.group(2)

                # Handle timeouts
                if 'request timed out' in rest.lower():
                    hops.append({
                        'idx': hop_idx,
                        'ttl': ttl,
                        'hostname': '*',
                        'ip': '*',
                        'delay_ms': None,
                    })
                    hop_idx += 1
                    continue

                # Extract first RTT value
                delay = None
                rtt_match = re.search(r'([0-9.<>]+)\s*ms', rest, re.IGNORECASE)
                if rtt_match:
                    delay_val = rtt_match.group(1).replace('<', '')
                    try:
                        delay = float(delay_val)
                    except ValueError:
                        delay = None

                # Extract hostname/ip at end
                host_match = re.search(r'([A-Za-z0-9\.\-]+)\s*\[([0-9\.]+)\]\s*$', rest)
                if host_match:
                    hostname = host_match.group(1)
                    ip = host_match.group(2)
                else:
                    ip_match = re.search(r'([0-9]{1,3}(?:\.[0-9]{1,3}){3})\s*$', rest)
                    ip = ip_match.group(1) if ip_match else '*'
                    hostname = ip

                hops.append({
                    'idx': hop_idx,
                    'ttl': ttl,
                    'hostname': hostname,
                    'ip': ip,
                    'delay_ms': delay,
                })
                hop_idx += 1

            return {
                'success': len(hops) > 0,
                'hops': hops,
                'hop_count': len(hops),
                'raw_output': output,
                'command': cmd_str
            }

        # Find traceroute command (may be in /usr/sbin or /usr/bin)
        traceroute_cmd = None
        for path in ['/usr/sbin/traceroute', '/usr/bin/traceroute', 'traceroute']:
            try:
                result = subprocess.run(['which', path] if path == 'traceroute' else ['test', '-f', path],
                                       capture_output=True, timeout=1)
                if result.returncode == 0 or os.path.exists(path):
                    traceroute_cmd = path
                    break
            except:
                continue

        if not traceroute_cmd:
            return {
                'success': False,
                'error': 'traceroute command not found. Install with: sudo apt-get install traceroute',
                'hops': [],
                'hop_count': 0
            }

        # Build traceroute command based on protocol
        if protocol == 'tcp':
            cmd = [traceroute_cmd, v_flag, '-T', '-m', str(max_hops), '-q', '1']
        elif protocol == 'udp':
            cmd = [traceroute_cmd, v_flag, '-U', '-m', str(max_hops), '-q', '1']
        else:  # icmp (default)
            cmd = [traceroute_cmd, v_flag, '-I', '-m', str(max_hops), '-q', '1']

        if interface:
            cmd.extend(['-i', interface])
        cmd.append(host)

        timeout_seconds = max_hops * 2 + 10
        cmd_str = ' '.join(cmd)
        print(f"🧭 [superping] Traceroute cmd: {cmd_str} (timeout {timeout_seconds}s)")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
        output = result.stdout

        # Parse traceroute output
        hops = []
        hop_idx = 0

        for line in output.split('\n'):
            line = line.strip()
            if not line or line.startswith('traceroute'):
                continue

            # Parse hop line: " 1  gateway (192.168.1.1)  1.234 ms"
            hop_match = re.match(r'\s*(\d+)\s+(.+?)(?:\s+\(([^\)]+)\))?\s+(\d+\.?\d*)\s*ms', line)
            if hop_match:
                ttl = int(hop_match.group(1))
                hostname = hop_match.group(2).strip()
                ip = hop_match.group(3) if hop_match.group(3) else hostname
                delay = float(hop_match.group(4))

                hops.append({
                    'idx': hop_idx,
                    'ttl': ttl,
                    'hostname': hostname,
                    'ip': ip,
                    'delay_ms': delay,
                })
                hop_idx += 1
            # Handle * * * (no response)
            elif re.match(r'\s*(\d+)\s+\*', line):
                ttl_match = re.match(r'\s*(\d+)', line)
                if ttl_match:
                    ttl = int(ttl_match.group(1))
                    hops.append({
                        'idx': hop_idx,
                        'ttl': ttl,
                        'hostname': '*',
                        'ip': '*',
                        'delay_ms': None,
                    })
                    hop_idx += 1

        return {
            'success': len(hops) > 0,
            'hops': hops,
            'hop_count': len(hops),
            'raw_output': output,
            'command': cmd_str
        }
    except subprocess.TimeoutExpired as e:
        error = 'Traceroute timeout'
        if cmd_str:
            error = f"{error} (cmd: {cmd_str})"
        if timeout_seconds is not None:
            error = f"{error} (timeout {timeout_seconds}s)"
        output = ''
        if hasattr(e, 'stdout') and e.stdout:
            output += e.stdout if isinstance(e.stdout, str) else e.stdout.decode(errors='ignore')
        if hasattr(e, 'stderr') and e.stderr:
            output += e.stderr if isinstance(e.stderr, str) else e.stderr.decode(errors='ignore')
        if output:
            output_head = output.strip().splitlines()[:3]
            if output_head:
                error = f"{error}: {' | '.join(output_head)}"
        return {
            'success': False,
            'error': error,
            'hops': [],
            'hop_count': 0
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'hops': [],
            'hop_count': 0
        }


def calculate_superping_score(ping_data: Dict, trace_data: Dict) -> float:
    """
    Calculate Superping score (0-100) based on network quality.
    Higher score = better network performance.
    """
    score = 100.0
    
    # Penalty for packet loss (0-40 points)
    packet_loss = ping_data.get('packet_loss_percent', 100)
    score -= min(40, packet_loss * 0.4)
    
    # Penalty for high RTT (0-30 points)
    rtt_stats = ping_data.get('rtt_stats', {})
    avg_rtt = rtt_stats.get('avg', 0)
    if avg_rtt > 200:
        score -= 30
    elif avg_rtt > 100:
        score -= 20
    elif avg_rtt > 50:
        score -= 10
    
    # Penalty for high jitter (0-20 points)
    jitter = rtt_stats.get('stddev', 0)
    if jitter > 50:
        score -= 20
    elif jitter > 20:
        score -= 10
    elif jitter > 10:
        score -= 5
    
    # Penalty for long path (0-10 points)
    hop_count = trace_data.get('hop_count', 0)
    if hop_count > 20:
        score -= 10
    elif hop_count > 15:
        score -= 5
    
    return max(0, min(100, score))


def determine_status(score: float, reachable: bool) -> Tuple[str, str]:
    """Determine network status and label based on score"""
    if not reachable:
        return 'DOWN', '❌ Service unreachable'
    elif score >= 80:
        return 'EXCELLENT', '✅ Excellent network quality'
    elif score >= 60:
        return 'GOOD', '✅ Good network quality'
    elif score >= 40:
        return 'DEGRADED', '⚠️  Degraded network quality'
    else:
        return 'POOR', '⚠️  Poor network quality'


@script("superping", "Network path analysis with QoS metrics (ping, traceroute, jitter)", capture_artifacts=False)
def main():
    """Execute Superping analysis and store results in metadata"""
    args = get_args()
    context = get_context()

    target = args.target
    protocol = args.protocol.lower()
    count = args.count
    max_hops = args.max_hops
    interface = (args.interface or '').strip()
    ip_version = int(getattr(args, 'ip_version', 4) or 4)
    interface_attempts: List[Dict[str, str]] = []

    if not interface or interface.lower() == 'auto':
        interface = ''

    # Validate protocol
    if protocol not in ['icmp', 'tcp', 'udp']:
        context.error_message = f"Invalid protocol '{protocol}'. Must be icmp, tcp, or udp"
        context.overall_success = False
        return False

    if ip_version not in (4, 6):
        context.error_message = f"Invalid ip_version '{ip_version}'. Must be 4 or 6"
        context.overall_success = False
        return False

    print(f"🌐 [superping] Target: {target}")
    print(f"📡 [superping] Protocol: {protocol.upper()}")
    print(f"🖥️  [superping] Host: {context.host.host_name}")
    print(f"🌍 [superping] IP Version: IPv{ip_version}")
    # The interface pre-check pings 8.8.8.8 (IPv4) and only makes sense for v4.
    # For v6 we skip the pre-check and trust the user's interface choice.
    if ip_version == 6:
        if interface:
            print(f"🔌 [superping] Interface: {interface} (IPv6, no pre-check)")
        else:
            print("🔌 [superping] Interface: default (IPv6, no pre-check)")
    elif interface:
        print(f"🔌 [superping] Interface: {interface} (manual selection)")
        ping_result = ping_via_interface('8.8.8.8', interface)
        interface_attempts.append({
            'interface': interface,
            'success': str(ping_result.get('success', False)).lower(),
            'error': ping_result.get('error') or '',
        })
        if ping_result.get('success'):
            print(f"   ✅ Connectivity check passed: ping 8.8.8.8 via {interface}")
        else:
            error = ping_result.get('error', 'Ping failed')
            print(f"   ❌ Connectivity check failed: ping 8.8.8.8 via {interface} -> {error}")
            context.error_message = f"Interface {interface} has no internet connectivity: {error}"
            context.overall_success = False
            context.metadata = {
                'target': target,
                'protocol': protocol,
                'interface_selection': args.interface,
                'interface_used': interface,
                'source_ip': None,
                'interface_attempts': interface_attempts,
                'timestamp': datetime.now().isoformat(),
                'host_name': context.host.host_name,
                'error': context.error_message,
            }
            return False
    else:
        selected_interface, interface_attempts = select_working_interface('8.8.8.8')
        if selected_interface:
            interface = selected_interface
            print(f"🔌 [superping] Interface: {interface} (auto-selected after connectivity check)")
            for attempt in interface_attempts:
                status = 'OK' if attempt['success'] == 'true' else 'FAILED'
                suffix = f" - {attempt['error']}" if attempt['error'] else ''
                print(f"   • {attempt['interface']}: {status}{suffix}")
        else:
            print("🔌 [superping] Interface: auto (no interface with internet connectivity found)")
            for attempt in interface_attempts:
                suffix = f" - {attempt['error']}" if attempt['error'] else ''
                print(f"   • {attempt['interface']}: FAILED{suffix}")
            context.error_message = "No network interface with internet connectivity found"
            context.overall_success = False
            context.metadata = {
                'target': target,
                'protocol': protocol,
                'interface_selection': args.interface,
                'interface_used': None,
                'source_ip': None,
                'interface_attempts': interface_attempts,
                'timestamp': datetime.now().isoformat(),
                'host_name': context.host.host_name,
                'error': context.error_message,
            }
            return False
    
    # Resolve target
    try:
        hostname, ip, port = resolve_target(target, ip_version=ip_version)
        display_ip = f"[{ip}]" if ip_version == 6 else ip
        print(f"🔍 [superping] Resolved: {hostname} -> {display_ip}:{port}")
    except ValueError as e:
        context.error_message = str(e)
        context.overall_success = False
        return False

    # Determine the local source IP (IPv4 or IPv6) used to reach the target.
    # TCP/UDP refine this below from the live socket; ICMP relies on this value.
    source_ip = resolve_source_ip(ip, ip_version=ip_version, interface=interface or None)
    if source_ip:
        print(f"🧷 [superping] Source IP: {source_ip} (via {interface or 'default route'})")
    else:
        print("🧷 [superping] Source IP: unknown")

    # Run ping based on protocol
    print(f"\n{'='*80}")
    print(f"🏓 PING TEST ({protocol.upper()})")
    print(f"{'='*80}")
    
    start_time = time.time()
    
    if protocol == 'icmp':
        ping_data = run_icmp_ping(ip, count, interface=interface, ip_version=ip_version)
    elif protocol == 'tcp':
        ping_data = run_tcp_ping(ip, port, count, interface=interface, ip_version=ip_version)
    else:  # udp
        ping_data = run_udp_ping(ip, port, count, interface=interface, ip_version=ip_version)
    
    ping_end = time.time()
    ping_duration = ping_end - start_time

    # TCP/UDP expose the real bound source IP from the live socket — prefer it
    if ping_data.get('source_ip'):
        source_ip = ping_data['source_ip']

    # Record step for ping command execution
    ping_success = ping_data.get('success', False)
    ping_error = ping_data.get('error')
    ping_rtt = ping_data.get('rtt_stats', {})
    ping_cmd_label = f"{protocol.upper()} ping to {ip}" + (f":{port}" if protocol != 'icmp' else "")
    if interface:
        ping_cmd_label += f" via {interface}"
    ping_details = f"success={ping_success}, duration={ping_duration*1000:.1f}ms"
    if ping_rtt.get('avg'):
        ping_details += f", avg_rtt={ping_rtt['avg']:.2f}ms"
    ping_details += f", loss={ping_data.get('packet_loss_percent', 100):.1f}%"
    if ping_error:
        ping_details += f", error={ping_error}"
    context.record_step_immediately({
        "message": f"Run {protocol.upper()} ping to {ip}",
        "success": ping_success,
        "actions": [{"command": ping_cmd_label}],
        "verifications": [{"success": ping_success, "label": f"{protocol.upper()} ping executed", "details": ping_details}],
        "start_time": start_time,
        "end_time": ping_end,
    })

    if not ping_data.get('success'):
        error = ping_data.get('error', 'Ping failed')
        context.error_message = f"Ping failed: {error}"
        context.overall_success = False
        return False
    
    # Print ping results
    print(ping_data.get('raw_output', ''))
    rtt_stats = ping_data.get('rtt_stats', {})
    if rtt_stats:
        print(f"\n📊 RTT Statistics:")
        print(f"   Min:    {rtt_stats.get('min', 0):.2f} ms")
        print(f"   Avg:    {rtt_stats.get('avg', 0):.2f} ms")
        print(f"   Max:    {rtt_stats.get('max', 0):.2f} ms")
        print(f"   Jitter: {rtt_stats.get('stddev', 0):.2f} ms")
    print(f"📦 Packets: {ping_data.get('packets_received', 0)}/{ping_data.get('packets_transmitted', 0)} received")
    print(f"📉 Loss: {ping_data.get('packet_loss_percent', 0):.1f}%")
    print(f"{'='*80}\n")
    
    # Run traceroute
    print(f"{'='*80}")
    print(f"🗺️  TRACEROUTE ({protocol.upper()})")
    print(f"{'='*80}")
    
    trace_start = time.time()
    trace_data = run_traceroute(ip, protocol, max_hops, interface=interface, ip_version=ip_version)
    trace_end = time.time()
    trace_duration = trace_end - trace_start

    # Record step for traceroute command execution
    trace_success = trace_data.get('success', False)
    trace_error = trace_data.get('error')
    trace_cmd = trace_data.get('command', f"traceroute to {ip}")
    trace_details = f"success={trace_success}, duration={trace_duration*1000:.1f}ms, hops={trace_data.get('hop_count', 0)}"
    if trace_error:
        trace_details += f", error={trace_error}"
    context.record_step_immediately({
        "message": f"Run traceroute to {ip}",
        "success": trace_success,
        "actions": [{"command": trace_cmd}],
        "verifications": [{"success": trace_success, "label": "traceroute executed", "details": trace_details}],
        "start_time": trace_start,
        "end_time": trace_end,
    })

    if trace_data.get('success'):
        print(trace_data.get('raw_output', ''))
        print(f"\n🛤️  Path: {trace_data.get('hop_count', 0)} hops")
        
        # Show hop summary
        for hop in trace_data.get('hops', [])[:5]:  # Show first 5 hops
            delay = hop.get('delay_ms')
            delay_str = f"{delay:.2f} ms" if delay is not None else "* * *"
            print(f"   {hop['ttl']:2d}. {hop['hostname']:30s} {delay_str}")
        
        if trace_data.get('hop_count', 0) > 5:
            print(f"   ... ({trace_data.get('hop_count', 0) - 5} more hops)")
    else:
        print(f"⚠️  Traceroute failed: {trace_data.get('error', 'Unknown error')}")
    
    print(f"{'='*80}\n")
    
    # Calculate Superping score
    score = calculate_superping_score(ping_data, trace_data)
    reachable = ping_data.get('success', False)
    status, status_label = determine_status(score, reachable)
    
    # Build metadata
    context.metadata = {
        'target': target,
        'hostname': hostname,
        'ip': ip,
        'port': port,
        'protocol': protocol,
        'ip_version': ip_version,
        'interface': interface or None,
        'interface_selection': args.interface,
        'interface_used': interface or None,
        'source_ip': source_ip,
        'interface_attempts': interface_attempts,
        'timestamp': datetime.now().isoformat(),
        'host_name': context.host.host_name,
        
        # Superping metrics
        'superping_score': round(score, 1),
        'service_reachability': reachable,
        'status': status,
        'status_label': status_label,
        
        # Ping metrics
        'rtt_min_ms': rtt_stats.get('min', 0),
        'rtt_avg_ms': rtt_stats.get('avg', 0),
        'rtt_max_ms': rtt_stats.get('max', 0),
        'jitter_ms': rtt_stats.get('stddev', 0),
        'rtt_values_ms': [round(rtt, 2) for rtt in ping_data.get('rtts', [])],  # Individual RTT values
        'packets_transmitted': ping_data.get('packets_transmitted', 0),
        'packets_received': ping_data.get('packets_received', 0),
        'packet_loss_percent': ping_data.get('packet_loss_percent', 0),
        
        # Traceroute metrics
        'hop_count': trace_data.get('hop_count', 0),
        'hops': trace_data.get('hops', []),
        
        # Timing
        'ping_duration_seconds': round(ping_duration, 2),
        'trace_duration_seconds': round(trace_duration, 2),
        'total_duration_seconds': round(ping_duration + trace_duration, 2),
    }
    
    # Print summary
    print(f"{'='*80}")
    print(f"🎯 Superping SUMMARY")
    print(f"{'='*80}")
    print(f"🌐 Target: {hostname} ({display_ip}:{port})")
    print(f"📡 Protocol: {protocol.upper()}")
    print(f"🌍 IP Version: IPv{ip_version}")
    if interface:
        print(f"🔌 Interface: {interface}")
    if source_ip:
        print(f"🧷 Source IP: {source_ip}")
    if context.selected_device:
        print(f"📱 Device: {context.selected_device.device_name}")
    print(f"🖥️ Host: {context.host.host_name}")
    print(f"")
    print(f"🏆 Superping Score: {score:.1f}/100")
    print(f"📊 Status: {status_label}")
    print(f"")
    print(f"⏱️  RTT: {rtt_stats.get('avg', 0):.2f} ms (min: {rtt_stats.get('min', 0):.2f}, max: {rtt_stats.get('max', 0):.2f})")
    print(f"📶 Jitter: {rtt_stats.get('stddev', 0):.2f} ms")
    print(f"📦 Packets: {ping_data.get('packets_received', 0)}/{ping_data.get('packets_transmitted', 0)} received ({100 - ping_data.get('packet_loss_percent', 0):.1f}% success)")
    print(f"🛤️  Hops: {trace_data.get('hop_count', 0)}")
    print(f"⏱️ Total Time: {ping_duration + trace_duration:.2f}s")
    print(f"{'='*80}\n")
    
    # Build traceroute path summary for execution summary
    path_summary = ""
    hops = trace_data.get('hops', [])
    if hops and len(hops) > 0:
        path_summary = "\n🛤️  Network Path:\n"
        
        # Show first hop (gateway)
        if len(hops) > 0:
            first_hop = hops[0]
            delay_str = f"{first_hop.get('delay_ms', 0):.1f}ms" if first_hop.get('delay_ms') else "* ms"
            path_summary += f"   1. {first_hop.get('hostname', 'unknown'):20s} {delay_str:>8s}\n"
        
        # Show middle hops if path is long (condensed)
        if len(hops) > 3:
            path_summary += f"   ... ({len(hops) - 2} intermediate hops)\n"
        elif len(hops) == 3:
            # Show middle hop for 3-hop paths
            mid_hop = hops[1]
            delay_str = f"{mid_hop.get('delay_ms', 0):.1f}ms" if mid_hop.get('delay_ms') else "* ms"
            path_summary += f"   {mid_hop.get('ttl', 2)}. {mid_hop.get('hostname', 'unknown'):20s} {delay_str:>8s}\n"
        
        # Show last hop (destination)
        if len(hops) > 1:
            last_hop = hops[-1]
            delay_str = f"{last_hop.get('delay_ms', 0):.1f}ms" if last_hop.get('delay_ms') else "* ms"
            path_summary += f"   {last_hop.get('ttl', len(hops))}. {last_hop.get('hostname', 'unknown'):20s} {delay_str:>8s}\n"
    else:
        path_summary = f"\n🛤️  Network Path: {trace_data.get('hop_count', 0)} hops\n"
    
    # Set execution summary
    context.execution_summary = f"""🌐 Superping ANALYSIS SUMMARY
🖥️ Host: {context.host.host_name}
🎯 Target: {hostname} ({ip}:{port})
📡 Protocol: {protocol.upper()}
🌍 IP Version: IPv4
🔌 Interface: {interface or "auto"}
🧷 Source IP: {source_ip or "unknown"}

🏆 Superping Score: {score:.1f}/100
📊 Status: {status_label}

⏱️  RTT: {rtt_stats.get('avg', 0):.2f} ms (±{rtt_stats.get('stddev', 0):.2f} ms jitter)
📦 Packets: {ping_data.get('packets_received', 0)}/{ping_data.get('packets_transmitted', 0)} ({100 - ping_data.get('packet_loss_percent', 0):.1f}% success){path_summary}
🎯 Result: {status}"""
    
    context.overall_success = True
    return True


main._script_args = _script_args
main._target_rules = {
    "target_type": "host",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
