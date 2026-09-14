#!/usr/bin/env python3
"""
Redis Connection Test - Simulates Agent Behavior

Tests both raw socket connection and redis-py library (same as agents)
"""

import socket
import json
import time
from urllib.parse import urlparse

def test_redis_socket(host, port=6379, password=None, timeout=5):
    """Test Redis connection with raw socket (original test)"""
    print(f"🔍 Testing Redis at {host}:{port} (raw socket)")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        print(f"   ✅ Connected")

        # Authenticate if password provided
        if password:
            auth_cmd = f"*2\r\n$4\r\nAUTH\r\n${len(password)}\r\n{password}\r\n"
            sock.send(auth_cmd.encode())
            response = sock.recv(1024).decode().strip()
            if not response.startswith("+OK"):
                print(f"   ❌ Auth failed: {response}")
                sock.close()
                return False
            print(f"   ✅ Authenticated")

        # Test with PING
        sock.send(b"*1\r\n$4\r\nPING\r\n")
        response = sock.recv(1024).decode().strip()
        sock.close()

        if response.startswith("+PONG"):
            print(f"   ✅ PING successful")
            print(f"🎉 Redis at {host}:{port} is working!")
            return True
        else:
            print(f"   ❌ Bad response: {response}")
            return False

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_redis_agent_simulation(redis_url, test_operations=True):
    """Test Redis using redis-py library (same as agents)"""
    print(f"\n🔍 Testing Redis URL: {redis_url} (agent simulation)")

    try:
        import redis
    except ImportError:
        print(f"   ❌ redis-py library not installed. Install: pip install redis")
        return False

    try:
        # Parse URL like agents do
        parsed = urlparse(redis_url)
        if not (parsed.scheme.startswith('redis')):
            print(f"   ❌ Invalid Redis URL scheme: {parsed.scheme}")
            return False

        host = parsed.hostname or 'localhost'
        port = parsed.port or 6379
        password = parsed.password
        db = int(parsed.path.strip('/')) if parsed.path and parsed.path != '/' else 0
        use_ssl = (parsed.scheme == 'rediss')

        print(f"   📋 Parsed: host={host}, port={port}, db={db}, ssl={use_ssl}")
        print(f"   🔐 Password: {'SET' if password else 'NOT SET'}")

        # Create Redis client with SAME parameters as agents
        redis_client = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=db,
            decode_responses=True,
            socket_timeout=5,        # Same as agents
            socket_connect_timeout=5, # Same as agents
            ssl=use_ssl
        )

        print(f"   🤝 Client created, testing connection...")

        # Test PING (health check like agents)
        start_time = time.time()
        try:
            result = redis_client.ping()
            ping_time = time.time() - start_time
            print(f"   ✅ PING: {result} ({ping_time:.2f}s)")
        except Exception as e:
            print(f"   ❌ PING failed: {e}")
            return False

        if not test_operations:
            print(f"🎉 Redis connection successful!")
            return True

        # Test operations agents perform
        print(f"   🔧 Testing agent operations...")

        # Test LLEN (queue length check)
        try:
            test_queue = "test_agent_queue"
            length = redis_client.llen(test_queue)
            print(f"   ✅ LLEN {test_queue}: {length}")
        except Exception as e:
            print(f"   ❌ LLEN failed: {e}")
            return False

        # Test LPUSH (add to queue)
        try:
            test_data = {"type": "test", "id": "test123", "timestamp": time.time()}
            result = redis_client.lpush(test_queue, json.dumps(test_data))
            print(f"   ✅ LPUSH {test_queue}: {result}")
        except Exception as e:
            print(f"   ❌ LPUSH failed: {e}")
            return False

        # Test LPOP (get from queue like background loop)
        try:
            result = redis_client.lpop(test_queue)
            if result:
                data = json.loads(result)
                print(f"   ✅ LPOP {test_queue}: {data['type']}:{data['id']}")
            else:
                print(f"   ✅ LPOP {test_queue}: empty (expected)")
        except Exception as e:
            print(f"   ❌ LPOP failed: {e}")
            return False

        # Clean up test data
        try:
            redis_client.delete(test_queue)
            print(f"   🧹 Cleaned up test queue")
        except Exception as e:
            print(f"   ⚠️  Cleanup failed: {e}")

        print(f"🎉 All Redis operations successful!")
        return True

    except Exception as e:
        print(f"   ❌ Agent simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_redis_url_parsing(redis_url):
    """Test URL parsing logic (for debugging)"""
    print(f"\n🔍 Testing URL parsing: {redis_url}")

    try:
        parsed = urlparse(redis_url)
        print(f"   Scheme: {parsed.scheme}")
        print(f"   Host: {parsed.hostname}")
        print(f"   Port: {parsed.port}")
        print(f"   Password: {'***' if parsed.password else None}")
        print(f"   Path: {parsed.path}")
        print(f"   DB: {int(parsed.path.strip('/')) if parsed.path and parsed.path != '/' else 0}")
        return True
    except Exception as e:
        print(f"   ❌ URL parsing failed: {e}")
        return False

# Test configurations
print("=== Redis Connection Tests ===\n")

# Original socket test (what you were using)
print("1. RAW SOCKET TEST (original)")
socket_success = test_redis_socket("192.168.0.101", 6379, "admin1234")

# Agent simulation test (what agents actually do)
print("\n2. AGENT SIMULATION TEST")
redis_url = "redis://:admin1234@192.168.0.101:6379/0"  # Same format as agents use
url_parse_success = test_redis_url_parsing(redis_url)
agent_success = test_redis_agent_simulation(redis_url, test_operations=True)

# Summary
print(f"\n=== RESULTS ===")
print(f"Socket test: {'✅ PASS' if socket_success else '❌ FAIL'}")
print(f"URL parsing: {'✅ PASS' if url_parse_success else '❌ FAIL'}")
print(f"Agent simulation: {'✅ PASS' if agent_success else '❌ FAIL'}")

if socket_success and not agent_success:
    print(f"\n⚠️  Socket works but agents fail - this indicates redis-py library issue!")
    print(f"   Possible causes:")
    print(f"   - redis-py library not installed or wrong version")
    print(f"   - Different timeout behavior between socket and redis-py")
    print(f"   - SSL/TLS configuration issues")
    print(f"   - Connection pooling problems")
elif not socket_success and not agent_success:
    print(f"\n❌ Both tests fail - Redis server connectivity issue")
else:
    print(f"\n✅ All tests pass - Redis should work for agents")