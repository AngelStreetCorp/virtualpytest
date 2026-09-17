#!/usr/bin/env python3
"""
DNS Lookup Time Script for VirtualPyTest

Performs DNS lookup and measures response time, storing results in metadata.

Usage:
    python test_scripts/gw/dns_lookuptime.py [--url <hostname>] [--dns <dns_server>]

Examples:
    python test_scripts/gw/dns_lookuptime.py                                         # Default: google.com via system resolver ('--dns system')
    python test_scripts/gw/dns_lookuptime.py --url google.com                        # Custom hostname
    python test_scripts/gw/dns_lookuptime.py --url google.com --dns system           # Use the system resolver explicitly
    python test_scripts/gw/dns_lookuptime.py --url api.example.com
    python test_scripts/gw/dns_lookuptime.py --dns 8.8.8.8 --url api.example.com   # Use a specific DNS server
    python test_scripts/gw/dns_lookuptime.py --dns 2001:4860:4860::8888 --url api.example.com

"""

import sys
import os
import subprocess
import time
import re
from datetime import datetime

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args

# Script arguments
# Sentinel default for --dns: shown pre-filled in the frontend, but treated as
# "not specified" so the nslookup command runs against the host's system resolver.
DNS_SYSTEM_DEFAULT = 'system'

_script_args = [
    '--url:str:google.com',
    '--dns:str:system',
]

_script_description = "Measure DNS lookup time for a hostname using nslookup"
_arg_descriptions = {
    "url": "Hostname to resolve",
    "dns": f"DNS server to query (e.g. 8.8.8.8 or 2001:4860:4860::8888); '{DNS_SYSTEM_DEFAULT}' or empty uses the host's system resolver",
}


def parse_nslookup_output(output: str) -> dict:
    """Parse nslookup output to extract server, addresses, and CNAME"""
    data = {
        'server': None,
        'server_port': None,
        'canonical_name': None,
        'ipv4_addresses': [],
        'ipv6_addresses': []
    }
    
    for line in output.split('\n'):
        line = line.strip()
        
        # Server address
        if line.startswith('Server:'):
            data['server'] = line.split('Server:')[1].strip()
        elif line.startswith('Address:') and '#' in line and not data['server_port']:
            match = re.search(r'(\d+\.\d+\.\d+\.\d+)#(\d+)', line)
            if match:
                data['server'] = match.group(1)
                data['server_port'] = match.group(2)
        
        # Canonical name (CNAME)
        elif 'canonical name' in line.lower():
            match = re.search(r'canonical name = (.+)', line)
            if match:
                data['canonical_name'] = match.group(1).strip().rstrip('.')
        
        # IPv4 addresses
        elif line.startswith('Address:') and '.' in line and ':' not in line.split('Address:')[1]:
            match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
            if match:
                data['ipv4_addresses'].append(match.group(1))
        
        # IPv6 addresses
        elif line.startswith('Address:') and '::' in line:
            match = re.search(r'Address:\s*(.+)', line)
            if match:
                data['ipv6_addresses'].append(match.group(1).strip())
    
    return data


@script("dns_lookuptime", "Perform DNS lookup and measure response time", capture_artifacts=False)
def main():
    """Execute nslookup, measure time, and store results in metadata"""
    args = get_args()
    context = get_context()
    domain = args.url
    dns_server = (args.dns or '').strip()
    # Sentinel/empty -> use the system resolver (do not append a server to nslookup)
    if dns_server.lower() == DNS_SYSTEM_DEFAULT:
        dns_server = ''

    print(f"\n[dns_lookuptime] domain={domain} dns_server={dns_server or '(system default)'}")

    # Step 1: Execute nslookup
    print(f"\n[Step 1] Running nslookup for {domain}...")
    # nslookup <host> [dns_server] — appending a server overrides the system resolver
    cmd = ['nslookup', domain] + ([dns_server] if dns_server else [])
    cmd_str = ' '.join(cmd)
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        end_time = time.time()
        elapsed_time = end_time - start_time
        output = result.stdout
        success = result.returncode == 0

        print(f"\n{'='*80}")
        print(f"[nslookup] RAW OUTPUT (return_code={result.returncode}, duration={elapsed_time*1000:.1f}ms)")
        print(f"{'='*80}")
        print(output or "(empty)")
        if result.stderr:
            print(result.stderr)
        print(f"{'='*80}\n")

        context.record_step_immediately({
            "message": f"Run nslookup for {domain}",
            "success": success,
            "actions": [{"command": cmd_str}],
            "verifications": [{"success": success, "label": "nslookup executed", "details": f"return_code={result.returncode}, duration={elapsed_time*1000:.1f}ms"}],
            "start_time": start_time,
            "end_time": end_time,
        })

        if not success:
            context.error_message = f"nslookup failed: {result.stderr}"
            context.overall_success = False
            return False

    except subprocess.TimeoutExpired:
        context.record_step_immediately({
            "message": f"Run nslookup for {domain}",
            "success": False,
            "actions": [{"command": cmd_str}],
            "verifications": [{"success": False, "label": "nslookup executed", "details": "Timeout after 10s"}],
            "start_time": start_time,
            "end_time": time.time(),
        })
        context.error_message = "DNS lookup timeout after 10s"
        context.overall_success = False
        return False
    except Exception as e:
        context.record_step_immediately({
            "message": f"Run nslookup for {domain}",
            "success": False,
            "actions": [{"command": cmd_str}],
            "verifications": [{"success": False, "label": "nslookup executed", "details": str(e)}],
            "start_time": start_time,
            "end_time": time.time(),
        })
        context.error_message = f"DNS lookup failed: {str(e)}"
        context.overall_success = False
        return False

    # Step 2: Parse results
    print(f"[Step 2] Parsing nslookup output...")
    parse_start = time.time()
    parsed_data = parse_nslookup_output(output)
    parse_end = time.time()

    print(f"\n{'='*80}")
    print(f"[nslookup] PARSED RESULTS")
    print(f"{'='*80}")
    print(f"  Domain: {domain}")
    print(f"  Lookup Time: {elapsed_time*1000:.1f}ms ({elapsed_time:.3f}s)")
    print(f"  DNS Server: {parsed_data['server']}#{parsed_data['server_port']}")
    if parsed_data['canonical_name']:
        print(f"  CNAME: {parsed_data['canonical_name']}")
    if parsed_data['ipv4_addresses']:
        print(f"  IPv4: {', '.join(parsed_data['ipv4_addresses'])}")
    if parsed_data['ipv6_addresses']:
        print(f"  IPv6: {', '.join(parsed_data['ipv6_addresses'])}")
    print(f"{'='*80}\n")

    has_addresses = bool(parsed_data['ipv4_addresses'] or parsed_data['ipv6_addresses'])
    context.record_step_immediately({
        "message": "Parse DNS lookup results",
        "success": has_addresses,
        "verifications": [
            {"success": parsed_data['server'] is not None, "label": "DNS server identified", "details": f"{parsed_data['server']}#{parsed_data['server_port']}"},
            {"success": has_addresses, "label": "Addresses resolved", "details": f"IPv4: {len(parsed_data['ipv4_addresses'])}, IPv6: {len(parsed_data['ipv6_addresses'])}"},
            {"success": True, "label": "Lookup time measured", "details": f"{elapsed_time*1000:.1f}ms"},
        ],
        "start_time": parse_start,
        "end_time": parse_end,
    })

    # Store in metadata
    context.metadata = {
        'domain': domain,
        'lookup_time_seconds': round(elapsed_time, 3),
        'lookup_time_ms': round(elapsed_time * 1000, 1),
        'timestamp': datetime.now().isoformat(),
        'host_name': context.host.host_name,
        'requested_dns_server': dns_server or None,
        'dns_server': parsed_data['server'],
        'dns_server_port': parsed_data['server_port'],
        'canonical_name': parsed_data['canonical_name'],
        'ipv4_addresses': parsed_data['ipv4_addresses'],
        'ipv6_addresses': parsed_data['ipv6_addresses'],
        'raw_output': output
    }

    context.execution_summary = (
        "DNS LOOKUP SUMMARY\n"
        f"Host: {context.host.host_name}\n"
        f"Domain: {domain}\n"
        f"Requested DNS Server: {dns_server or '(system default)'}\n"
        f"Lookup Time: {elapsed_time*1000:.1f}ms\n"
        f"DNS Server: {parsed_data['server']}\n"
        f"IPv4 Addresses: {len(parsed_data['ipv4_addresses'])}\n"
        f"IPv6 Addresses: {len(parsed_data['ipv6_addresses'])}\n"
        "Result: SUCCESS"
    )

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
