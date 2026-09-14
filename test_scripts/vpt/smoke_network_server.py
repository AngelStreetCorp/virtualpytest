#!/usr/bin/env python3
"""
VirtualPyTest Smoke — Server Infrastructure Connectivity

Verifies that wherever this script runs (server VM or Raspberry Pi)
can reach all external services that VirtualPyTest depends on:

  Supabase   → PostgreSQL database
  Cloudflare → R2 object storage (screenshots/videos)
  Redis      → Task queue and cache  (localhost or configured host)
  OpenRouter → AI/LLM for analysis
  GitHub     → Code deployment git pulls

Unlike VPT-NETWORK-DIAGNOSTICS-001 (which tests network *performance*
via gw/ scripts on the gateway device), this script tests *reachability*
of the VPT platform's own infrastructure dependencies.

Usage:
    python test_scripts/vpt/smoke_network_server.py
"""

import sys
import os
import time
import socket
import subprocess

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_args, get_context

# VPT infrastructure endpoints to verify
INFRA_DNS = [
    ("supabase.co",        "Supabase (PostgreSQL database)"),
    ("pub.r2.dev",         "Cloudflare R2 (object storage)"),
    ("openrouter.ai",      "OpenRouter (AI/LLM API)"),
    ("github.com",         "GitHub (code deployment)"),
    ("api.anthropic.com",  "Anthropic API"),
]

INFRA_TCP = [
    ("github.com",  443,  "GitHub HTTPS"),
    ("openrouter.ai", 443, "OpenRouter HTTPS"),
]


def dns_lookup(host: str, timeout: float = 5.0) -> tuple[bool, float, str]:
    """Returns (success, elapsed_ms, ip_or_error)."""
    t0 = time.time()
    try:
        socket.setdefaulttimeout(timeout)
        ip = socket.gethostbyname(host)
        return True, round((time.time() - t0) * 1000, 1), ip
    except socket.gaierror as e:
        return False, round((time.time() - t0) * 1000, 1), str(e)


def tcp_connect(host: str, port: int, timeout: float = 5.0) -> tuple[bool, float, str]:
    """Returns (success, elapsed_ms, error_or_empty)."""
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, round((time.time() - t0) * 1000, 1), ""
    except Exception as e:
        return False, round((time.time() - t0) * 1000, 1), str(e)


def ping_once(host: str) -> tuple[bool, float]:
    """Returns (success, rtt_ms). Cross-platform."""
    try:
        flag = "-n" if sys.platform == "win32" else "-c"
        result = subprocess.run(
            ["ping", flag, "1", "-W", "3", host],
            capture_output=True, text=True, timeout=6,
        )
        return result.returncode == 0, 0.0
    except Exception:
        return False, 0.0


def capture_summary(context) -> str:
    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    lines = [
        "-" * 60,
        "🎯 [VPT SMOKE NETWORK SERVER] EXECUTION SUMMARY",
        "-" * 60,
        f"🖥️  Running on: {socket.gethostname()}",
        f"⏱️ Total Time: {context.get_execution_time_ms() / 1000:.1f}s",
        f"📊 Checks: {total}  ✅ {passed}  ❌ {total - passed}",
        "",
        "📋 Infrastructure Reachability:",
    ]
    for s in context.step_results:
        icon = "✅" if s["success"] else "❌"
        err = f" — {s['error']}" if s.get("error") else ""
        ms_str = f" ({s['response_time_ms']:.0f}ms)" if s.get("response_time_ms") else ""
        lines.append(f"   {icon} {s['description']}{ms_str}{err}")
    lines += ["", f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}", "-" * 60]
    return "\n".join(lines)


@script("smoke_network_server", "Verify VPT platform infrastructure is reachable from this machine")
def main():
    context = get_context()

    print(f"🔍 [smoke_network_server] Checking VPT infrastructure from {socket.gethostname()}")

    # ── DNS resolution checks ──────────────────────────────────────────────────
    print("\n  DNS resolution:")
    for host, label in INFRA_DNS:
        ok, ms, result = dns_lookup(host)
        detail = f"→ {result}" if ok else f": {result}"
        icon = "✅" if ok else "❌"
        print(f"    {icon} {label} ({host}){detail} ({ms:.0f}ms)")
        context.step_results.append({
            "action": f"DNS {host}",
            "description": f"DNS: {label}",
            "timestamp": time.time(),
            "success": ok,
            "error": result if not ok else None,
            "response_time_ms": ms,
        })

    # ── TCP connect checks ─────────────────────────────────────────────────────
    print("\n  TCP connect:")
    for host, port, label in INFRA_TCP:
        ok, ms, err = tcp_connect(host, port)
        icon = "✅" if ok else "❌"
        err_str = f": {err}" if err else ""
        print(f"    {icon} {label} ({host}:{port}) ({ms:.0f}ms){err_str}")
        context.step_results.append({
            "action": f"TCP {host}:{port}",
            "description": f"TCP: {label}",
            "timestamp": time.time(),
            "success": ok,
            "error": err if err else None,
            "response_time_ms": ms,
        })

    # ── Redis check (local) ────────────────────────────────────────────────────
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    print(f"\n  Redis ({redis_host}:{redis_port}):")
    ok, ms, err = tcp_connect(redis_host, redis_port)
    icon = "✅" if ok else "❌"
    err_str = f": {err}" if err else ""
    print(f"    {icon} Redis task queue{err_str} ({ms:.0f}ms)")
    context.step_results.append({
        "action": f"TCP {redis_host}:{redis_port}",
        "description": f"TCP: Redis task queue ({redis_host}:{redis_port})",
        "timestamp": time.time(),
        "success": ok,
        "error": err if err else None,
        "response_time_ms": ms,
    })

    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    # Allow Redis to fail without failing overall (it may not be on same host)
    critical = [s for s in context.step_results if "Redis" not in s["description"]]
    context.overall_success = all(s["success"] for s in critical) and len(critical) > 0

    context.execution_summary = capture_summary(context)
    print(f"\n{'✅' if context.overall_success else '❌'} [smoke_network_server] {passed}/{total} checks OK")
    return context.overall_success


main._script_args = [
    "--userinterface:str:virtualpytest_web",  # tags script_results so the Self-Test dashboard picks the run up
]

if __name__ == "__main__":
    main()
