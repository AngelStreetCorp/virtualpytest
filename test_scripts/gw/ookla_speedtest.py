#!/usr/bin/env python3
"""
Ookla Speedtest Script for VirtualPyTest

Performs internet speed tests using Ookla's official speedtest CLI.
Measures download/upload speeds, latency, jitter, and packet loss.

Usage:
    python test_scripts/gw/ookla_speedtest.py [--server <server_id>] [--interface <interface>]

Examples:
    python test_scripts/gw/ookla_speedtest.py                                        # Auto server and interface selection
    python test_scripts/gw/ookla_speedtest.py --server 12345                         # Specific server, auto interface
    python test_scripts/gw/ookla_speedtest.py --interface eth0                       # Auto server, specific interface
    python test_scripts/gw/ookla_speedtest.py --server 12345 --interface wlan0       # Specific server and interface

"""

import sys
import os
import json
import subprocess
import shutil
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args
from test_scripts.gw.utils_gw_network import (
    get_default_interface, list_ipv4_interfaces, get_interface_ipv4_address,
    ping_via_interface, select_working_interface,
)

# Script arguments
_script_args = [
    '--server:str:auto',  # Ookla server ID or 'auto' for automatic selection
    '--interface:str:auto',  # Network interface name or 'auto' for default detection
]
_script_description = "Run an Ookla speed test measuring download, upload, and latency."
_arg_descriptions = {
    "server": "Ookla server ID or auto for best server.",
    "interface": "Network interface to test on or auto.",
}


def find_speedtest_cli() -> Optional[str]:
    """Find speedtest executable - prioritize Ookla CLI over speedtest-cli"""

    # First priority: System-installed Ookla CLI (check common system paths)
    system_paths = [
        '/usr/local/bin/speedtest',
        '/usr/bin/speedtest',
    ]

    for path in system_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            # Verify it's Ookla CLI by checking version
            try:
                result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
                if 'ookla' in (result.stdout + result.stderr).lower():
                    return path
            except Exception:
                pass

    # Second priority: Any speedtest in PATH (might be Ookla CLI)
    speedtest_cmd = shutil.which('speedtest')
    if speedtest_cmd:
        # Check if it's Ookla CLI
        try:
            result = subprocess.run([speedtest_cmd, '--version'], capture_output=True, text=True, timeout=5)
            if 'ookla' in (result.stdout + result.stderr).lower():
                return speedtest_cmd
        except Exception:
            pass
        # If not Ookla CLI, we'll still use it as fallback

    # Third priority: System paths (any speedtest, even if not Ookla)
    for path in system_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path

    # Last resort: Virtual environment speedtest-cli
    if sys.platform == 'win32':
        venv_paths = [
            os.path.join(os.environ.get('VIRTUALPYTEST_ROOT', r'C:\virtualpytest\virtualpytest'), 'venv', 'Scripts', 'speedtest.exe'),
            r'.\venv\Scripts\speedtest.exe',
            os.path.join(sys.prefix, 'Scripts', 'speedtest.exe'),
        ]
    else:
        venv_paths = [
            '/opt/virtualpytest/venv/bin/speedtest',
            './venv/bin/speedtest',
        ]

    for path in venv_paths:
        if os.path.exists(path) and (sys.platform == 'win32' or os.access(path, os.X_OK)):
            return path

    return None


def detect_speedtest_variant(speedtest_cmd: str) -> str:
    """
    Detect whether the speedtest binary is Ookla CLI or Python speedtest-cli.
    Returns: 'ookla' or 'python-cli'
    """
    try:
        result = subprocess.run(
            [speedtest_cmd, '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        output = (result.stdout + result.stderr).lower()
        if 'ookla' in output:
            return 'ookla'
    except Exception:
        pass
    return 'python-cli'


def run_ookla_speedtest(server_id: Optional[str] = None, interface: Optional[str] = None, timeout: int = 90) -> Dict:
    """
    Run Ookla speedtest and return detailed results.

    Args:
        server_id: Optional Ookla server ID (e.g. "12345"). If None, auto-selects.
        timeout: Timeout in seconds

    Returns:
        Dict with speedtest results or error information
    """
    print("🌐 [ookla_speedtest] Finding Ookla speedtest CLI...")

    speedtest_cmd = find_speedtest_cli()
    if not speedtest_cmd:
        print("❌ [ookla_speedtest] speedtest not found in PATH or common locations")
        print("   💡 Install Ookla CLI from: https://www.speedtest.net/apps/cli")
        print("   💡 Or install speedtest-cli with: pip install speedtest-cli")
        return {
            'success': False,
            'error': 'speedtest command not found',
            'error_details': 'Install from https://www.speedtest.net/apps/cli or pip install speedtest-cli'
        }

    # Detect variant
    variant = detect_speedtest_variant(speedtest_cmd)
    print(f"🚀 [ookla_speedtest] Found speedtest at: {speedtest_cmd} (variant: {variant})")

    if variant == 'ookla':
        print("✅ [ookla_speedtest] Using official Ookla CLI")
    else:
        print("ℹ️  [ookla_speedtest] Using speedtest-cli (Python implementation)")

    try:
        # Build command
        if variant == 'ookla':
            cmd = [speedtest_cmd, '--format=json', '--accept-license', '--accept-gdpr']
            if server_id and server_id.lower() != 'auto':
                cmd.extend(['--server-id', server_id])
            if interface and interface.lower() != 'auto':
                # On Windows, interface from auto-detection is an IP address (from route table).
                # Ookla CLI --interface expects an adapter name, so use --ip for IP addresses.
                if re.match(r'\d+\.\d+\.\d+\.\d+$', interface):
                    cmd.extend(['--ip', interface])
                else:
                    cmd.extend(['--interface', interface])
        else:
            # Python speedtest-cli can bind to a source IP, so map interface -> IPv4.
            cmd = [speedtest_cmd, '--json', '--timeout', '120']
            if server_id and server_id.lower() != 'auto':
                cmd.extend(['--server', server_id])
            if interface and interface.lower() != 'auto':
                try:
                    source_ip = get_interface_ipv4_address(interface)
                    cmd.extend(['--source', source_ip])
                    print(
                        f"🔌 [ookla_speedtest] Using interface {interface} via source IP {source_ip} "
                        f"with speedtest-cli fallback"
                    )
                except ValueError as exc:
                    print(
                        f"⚠️  [ookla_speedtest] Could not resolve IPv4 for interface {interface}: {exc}. "
                        f"Using system default route"
                    )

        print(f"🚀 [ookla_speedtest] Executing: {' '.join(cmd)}")
        print(f"⏱️  [ookla_speedtest] Timeout: {timeout}s")

        start_time = datetime.now()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        duration = (datetime.now() - start_time).total_seconds()

        if result.returncode != 0:
            print(f"❌ [ookla_speedtest] Command failed (exit code: {result.returncode})")
            if result.stderr:
                print(f"   🚨 STDERR: {result.stderr[:500]}")
            if result.stdout:
                print(f"   📄 STDOUT: {result.stdout[:500]}")

            return {
                'success': False,
                'error': f'speedtest command failed (exit code {result.returncode})',
                'error_details': result.stderr[:500] if result.stderr else result.stdout[:500],
                'duration_seconds': duration
            }

        if not result.stdout:
            print("❌ [ookla_speedtest] No output from speedtest")
            return {
                'success': False,
                'error': 'No output from speedtest',
                'duration_seconds': duration
            }

        # Parse JSON output
        try:
            if variant == 'ookla':
                # Ookla CLI outputs JSONL: find the line with "type":"result"
                data = None
                for line in result.stdout.strip().splitlines():
                    try:
                        parsed = json.loads(line)
                        if parsed.get('type') == 'result':
                            data = parsed
                            break
                    except json.JSONDecodeError:
                        continue

                if not data:
                    print("❌ [ookla_speedtest] No result line found in Ookla JSONL output")
                    print(f"   📄 Raw output: {result.stdout[:500]}...")
                    return {
                        'success': False,
                        'error': 'No result line in Ookla output',
                        'raw_output': result.stdout[:1000],
                        'duration_seconds': duration
                    }

                # Extract metrics from Ookla format
                download_bw = data.get('download', {}).get('bandwidth', 0)
                upload_bw = data.get('upload', {}).get('bandwidth', 0)

                # Convert bytes/sec to Mbps: bytes * 8 / 1_000_000
                download_mbps = round(download_bw * 8 / 1_000_000, 2)
                upload_mbps = round(upload_bw * 8 / 1_000_000, 2)

                # Extract latency metrics
                ping_latency = data.get('ping', {}).get('latency', 0)
                ping_jitter = data.get('ping', {}).get('jitter', 0)

                download_latency = data.get('download', {}).get('latency', {}).get('iqm', 0)
                upload_latency = data.get('upload', {}).get('latency', {}).get('iqm', 0)

                # Packet loss
                packet_loss = data.get('packetLoss', 0)

                # Server info
                server = data.get('server', {})
                server_id_result = server.get('id', 0)
                server_name = server.get('name', 'Unknown')
                server_location = server.get('location', 'Unknown')
                server_country = server.get('country', 'Unknown')
                server_host = server.get('host', 'Unknown')
                server_sponsor = server.get('name', 'Unknown')

                # Result URL
                result_url = data.get('result', {}).get('url', '')
                result_id = data.get('result', {}).get('id', '')

                # ISP info
                isp = data.get('isp', 'Unknown')

                # Interface info
                interface_info = data.get('interface', {})
                interface_name = interface_info.get('name', 'Unknown')
                interface_mac = interface_info.get('macAddr', 'Unknown')
                external_ip = interface_info.get('externalIp', 'Unknown')

            else:
                # Python speedtest-cli format (fallback)
                data = json.loads(result.stdout)
                download_mbps = round(data['download'] / 1_000_000, 2)
                upload_mbps = round(data['upload'] / 1_000_000, 2)
                ping_latency = data.get('ping', 0)
                ping_jitter = 0  # Not available in speedtest-cli
                download_latency = 0
                upload_latency = 0
                packet_loss = 0

                server = data.get('server', {})
                server_id_result = server.get('id', 0)
                server_name = server.get('name', 'Unknown')
                server_location = f"{server.get('name', 'Unknown')}, {server.get('country', 'Unknown')}"
                server_country = server.get('country', 'Unknown')
                server_host = server.get('host', 'Unknown')
                server_sponsor = server.get('sponsor', 'Unknown')

                result_url = data.get('share', '')
                result_id = ''

                isp = data.get('client', {}).get('isp', 'Unknown')
                interface_name = 'Unknown'
                interface_mac = 'Unknown'
                external_ip = data.get('client', {}).get('ip', 'Unknown')

            # Validate results
            if download_mbps == 0.0 or upload_mbps == 0.0:
                print("❌ [ookla_speedtest] CRITICAL: Speedtest returned 0.0 Mbps!")
                print(f"   📊 Raw results: Download={download_mbps}, Upload={upload_mbps}")
                return {
                    'success': False,
                    'error': 'Speedtest returned 0.0 Mbps',
                    'duration_seconds': duration
                }

            print(f"✅ [ookla_speedtest] Test completed successfully")
            print(f"   📥 Download: {download_mbps} Mbps")
            print(f"   📤 Upload: {upload_mbps} Mbps")
            print(f"   📡 Ping: {ping_latency} ms")
            print(f"   📊 Jitter: {ping_jitter} ms")
            print(f"   📦 Packet Loss: {packet_loss}%")
            print(f"   🌐 Server: {server_name} ({server_location})")
            print(f"   🔗 Result: {result_url}")

            return {
                'success': True,
                'download_mbps': download_mbps,
                'upload_mbps': upload_mbps,
                'ping_latency_ms': ping_latency,
                'ping_jitter_ms': ping_jitter,
                'download_latency_ms': download_latency,
                'upload_latency_ms': upload_latency,
                'packet_loss_percent': packet_loss,
                'server_id': server_id_result,
                'server_name': server_name,
                'server_location': server_location,
                'server_country': server_country,
                'server_host': server_host,
                'server_sponsor': server_sponsor,
                'result_url': result_url,
                'result_id': result_id,
                'isp': isp,
                'interface_name': interface_name,
                'interface_mac': interface_mac,
                'external_ip': external_ip,
                'duration_seconds': duration,
                'raw_output': result.stdout[:2000]  # Store first 2000 chars for debugging
            }

        except (json.JSONDecodeError, KeyError) as parse_error:
            print(f"❌ [ookla_speedtest] Failed to parse JSON output: {parse_error}")
            print(f"   📄 Raw output: {result.stdout[:500]}...")
            return {
                'success': False,
                'error': f'Failed to parse speedtest output: {parse_error}',
                'raw_output': result.stdout[:1000],
                'duration_seconds': duration
            }

    except subprocess.TimeoutExpired:
        print(f"⏰ [ookla_speedtest] Speedtest timed out after {timeout}s")
        return {
            'success': False,
            'error': f'Speedtest timed out after {timeout}s',
            'duration_seconds': timeout
        }
    except Exception as e:
        print(f"💥 [ookla_speedtest] Unexpected error: {e}")
        return {
            'success': False,
            'error': f'Unexpected error: {str(e)}',
        }


@script("ookla_speedtest", "Internet speed test using Ookla Speedtest CLI", capture_artifacts=False)
def main():
    """Execute Ookla speedtest and store results in metadata"""
    args = get_args()
    context = get_context()

    server_param = args.server if args.server.lower() != 'auto' else None
    interface_param = args.interface if args.interface.lower() != 'auto' else None
    interface_attempts: List[Dict[str, str]] = []

    print(f"🌐 [ookla_speedtest] Starting Ookla Speedtest")
    print(f"🖥️  [ookla_speedtest] Host: {context.host.host_name}")
    if server_param:
        print(f"🎯 [ookla_speedtest] Server: {server_param} (manual selection)")
        print(f"   📋 Firewall: Only needs outbound TCP to specific server IP/port")
    else:
        print(f"🎯 [ookla_speedtest] Server: auto (automatic selection)")
        print(f"   ⚠️  Firewall: May need broad outbound TCP range (5000-65000) for auto-selected servers")

    # Interface detection/selection
    if interface_param:
        print(f"🔌 [ookla_speedtest] Interface: {interface_param} (manual selection)")
        ping_result = ping_via_interface('8.8.8.8', interface_param)
        interface_attempts.append({
            'interface': interface_param,
            'success': str(ping_result.get('success', False)).lower(),
            'error': ping_result.get('error') or '',
        })
        if ping_result.get('success'):
            print(f"   ✅ Connectivity check passed: ping 8.8.8.8 via {interface_param}")
        else:
            error = ping_result.get('error', 'Ping failed')
            print(f"   ❌ Connectivity check failed: ping 8.8.8.8 via {interface_param} -> {error}")
            context.error_message = f"Interface {interface_param} has no internet connectivity: {error}"
            context.overall_success = False
            context.metadata = {
                'server_selection': args.server,
                'interface_selection': args.interface,
                'interface_used': interface_param,
                'interface_attempts': interface_attempts,
                'timestamp': datetime.now().isoformat(),
                'host_name': context.host.host_name,
                'error': context.error_message,
            }
            context.execution_summary = f"""🚀 OOKLA SPEEDTEST SUMMARY
🖥️ Host: {context.host.host_name}
🔌 Interface: {interface_param}
🎯 Server: {args.server}

❌ FAILED: Interface connectivity check failed
Ping 8.8.8.8 via {interface_param} did not work: {error}

🎯 Status: FAILED"""
            return False
    else:
        selected_interface, interface_attempts = select_working_interface('8.8.8.8')
        if selected_interface:
            interface_param = selected_interface
            print(f"🔌 [ookla_speedtest] Interface: {interface_param} (auto-selected after connectivity check)")
            for attempt in interface_attempts:
                status = 'OK' if attempt['success'] == 'true' else 'FAILED'
                suffix = f" - {attempt['error']}" if attempt['error'] else ''
                print(f"   • {attempt['interface']}: {status}{suffix}")
        else:
            print(f"🔌 [ookla_speedtest] Interface: auto (no interface with internet connectivity found)")
            for attempt in interface_attempts:
                suffix = f" - {attempt['error']}" if attempt['error'] else ''
                print(f"   • {attempt['interface']}: FAILED{suffix}")
            context.error_message = "No network interface with internet connectivity found"
            context.overall_success = False
            context.metadata = {
                'server_selection': args.server,
                'interface_selection': args.interface,
                'interface_used': None,
                'interface_attempts': interface_attempts,
                'timestamp': datetime.now().isoformat(),
                'host_name': context.host.host_name,
                'error': context.error_message,
            }
            context.execution_summary = f"""🚀 OOKLA SPEEDTEST SUMMARY
🖥️ Host: {context.host.host_name}
🔌 Interface: auto
🎯 Server: {args.server}

❌ FAILED: No interface with internet connectivity found
Tried ping 8.8.8.8 on available interfaces before running speedtest.

🎯 Status: FAILED"""
            return False

    print(f"\n{'='*80}")
    print(f"🚀 OOKLA SPEEDTEST")
    print(f"{'='*80}")

    # Run speedtest
    step_start = time.time()
    result = run_ookla_speedtest(server_id=server_param, interface=interface_param, timeout=90)
    step_end = time.time()

    # Record speedtest execution step
    success = result.get('success', False)
    if success:
        details = f"Download: {result.get('download_mbps')} Mbps, Upload: {result.get('upload_mbps')} Mbps, Ping: {result.get('ping_latency_ms')} ms"
    else:
        details = result.get('error', 'Unknown error')
    context.record_step_immediately({
        "message": "Run Ookla speedtest",
        "success": success,
        "actions": [{"command": "speedtest"}],
        "verifications": [{"success": success, "label": "speedtest executed", "details": details}],
        "start_time": step_start,
        "end_time": step_end,
    })

    if not result.get('success'):
        error = result.get('error', 'Unknown error')
        error_details = result.get('error_details', '')
        context.error_message = f"Speedtest failed: {error}"
        if error_details:
            context.error_message += f" - {error_details}"
        context.overall_success = False

        # Store partial metadata for debugging
        context.metadata = {
            'server_selection': args.server,
            'interface_selection': args.interface,
            'interface_used': interface_param,
            'interface_attempts': interface_attempts,
            'timestamp': datetime.now().isoformat(),
            'host_name': context.host.host_name,
            'error': error,
            'error_details': error_details,
            'duration_seconds': result.get('duration_seconds', 0)
        }

        # Build error summary
        interface_info = f" ({interface_param})" if interface_param else ""
        context.execution_summary = f"""🚀 OOKLA SPEEDTEST SUMMARY
🖥️ Host: {context.host.host_name}
🔌 Interface: {args.interface}{interface_info}
🎯 Server: {args.server}

❌ FAILED: {error}
{error_details if error_details else ''}

🎯 Status: FAILED"""
        return False

    print(f"\n{'='*80}")
    print(f"📊 SPEEDTEST RESULTS")
    print(f"{'='*80}")
    print(f"📥 Download Speed:    {result['download_mbps']} Mbps")
    print(f"📤 Upload Speed:      {result['upload_mbps']} Mbps")
    print(f"📡 Ping Latency:      {result['ping_latency_ms']} ms")
    print(f"📊 Ping Jitter:       {result['ping_jitter_ms']} ms")
    if result.get('packet_loss_percent', 0) > 0:
        print(f"📦 Packet Loss:       {result['packet_loss_percent']}%")
    print(f"")
    print(f"🌐 Server Information:")
    print(f"   ID:                {result['server_id']}")
    print(f"   Name:              {result['server_name']}")
    print(f"   Location:          {result['server_location']}")
    print(f"   Host:              {result['server_host']}")
    print(f"")
    print(f"🔗 Result URL:        {result.get('result_url', 'N/A')}")
    print(f"🌍 ISP:               {result.get('isp', 'Unknown')}")
    print(f"🌐 External IP:       {result.get('external_ip', 'Unknown')}")
    print(f"⏱️  Duration:          {result['duration_seconds']:.2f}s")
    print(f"{'='*80}\n")

    # Build metadata
    context.metadata = {
        'timestamp': datetime.now().isoformat(),
        'host_name': context.host.host_name,

        # Speed metrics
        'download_mbps': result['download_mbps'],
        'upload_mbps': result['upload_mbps'],

        # Latency metrics
        'ping_latency_ms': result['ping_latency_ms'],
        'ping_jitter_ms': result['ping_jitter_ms'],
        'download_latency_ms': result.get('download_latency_ms', 0),
        'upload_latency_ms': result.get('upload_latency_ms', 0),

        # Quality metrics
        'packet_loss_percent': result.get('packet_loss_percent', 0),

        # Server info
        'server_id': result['server_id'],
        'server_name': result['server_name'],
        'server_location': result['server_location'],
        'server_country': result.get('server_country', 'Unknown'),
        'server_host': result['server_host'],
        'server_sponsor': result.get('server_sponsor', result['server_name']),
        'server_selection': args.server,  # Track if auto or manual

        # Result info
        'result_url': result.get('result_url', ''),
        'result_id': result.get('result_id', ''),

        # Network info
        'isp': result.get('isp', 'Unknown'),
        'external_ip': result.get('external_ip', 'Unknown'),
        'interface_name': result.get('interface_name', 'Unknown'),
        'interface_selection': args.interface,  # Track user selection
        'interface_used': interface_param,  # Track what was actually used
        'interface_attempts': interface_attempts,

        # Timing
        'duration_seconds': result['duration_seconds'],
    }

    # Set execution summary
    interface_info = f" ({interface_param})" if interface_param else ""
    context.execution_summary = f"""🚀 OOKLA SPEEDTEST SUMMARY
🖥️ Host: {context.host.host_name}
🔌 Interface: {args.interface}{interface_info}

📊 SPEED RESULTS
📥 Download: {result['download_mbps']} Mbps
📤 Upload:   {result['upload_mbps']} Mbps

📡 LATENCY & QUALITY
⏱️  Ping:    {result['ping_latency_ms']} ms
📊 Jitter:   {result['ping_jitter_ms']} ms
📦 Loss:     {result.get('packet_loss_percent', 0)}%

🌐 SERVER
   {result['server_name']} ({result['server_location']})
   ID: {result['server_id']}

🔗 Result: {result.get('result_url', 'N/A')}
🎯 Status: SUCCESS"""

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
