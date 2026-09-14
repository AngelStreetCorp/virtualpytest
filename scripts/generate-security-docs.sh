#!/bin/bash

# Generate security reports directly in docs/security/
# Run this manually when you want to update security documentation
# Requirements: bandit, safety (install in venv from backend_server/requirements.txt)

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Security Documentation Generator            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════╝${NC}"
echo ""

# Define output directories
DOCS_SECURITY="docs/security"
TEMP_DIR="$DOCS_SECURITY/temp"

mkdir -p "$DOCS_SECURITY"
mkdir -p "$TEMP_DIR"

# Define temp report files
HOST_BANDIT_JSON="$TEMP_DIR/host_bandit.json"
SERVER_BANDIT_JSON="$TEMP_DIR/server_bandit.json"
SHARED_BANDIT_JSON="$TEMP_DIR/shared_bandit.json"
HOST_SAFETY_TXT="$TEMP_DIR/host_safety.txt"
SERVER_SAFETY_TXT="$TEMP_DIR/server_safety.txt"
FRONTEND_AUDIT_JSON="$TEMP_DIR/frontend_audit.json"

# ==================== CHECK TOOLS ====================
echo -e "${YELLOW}→${NC} Checking security tools..."

BANDIT_AVAILABLE=false
SAFETY_AVAILABLE=false

if command -v bandit &> /dev/null; then
    BANDIT_AVAILABLE=true
    echo -e "${GREEN}  ✓ Bandit available${NC}"
else
    echo -e "${RED}  ✗ Bandit not found${NC}"
    echo -e "${YELLOW}     Install: pip install bandit (from backend_server/requirements.txt)${NC}"
fi

if command -v safety &> /dev/null; then
    SAFETY_AVAILABLE=true
    echo -e "${GREEN}  ✓ Safety available${NC}"
else
    echo -e "${YELLOW}  ⚠ Safety not found${NC}"
    echo -e "${YELLOW}     Install: pip install safety (from backend_server/requirements.txt)${NC}"
fi

if [ "$BANDIT_AVAILABLE" = false ]; then
    echo -e "${RED}Error: Bandit is required. Install with: pip install bandit${NC}"
    exit 1
fi

echo ""

# ==================== BANDIT SCANS ====================
echo -e "${YELLOW}→${NC} Running Bandit security scans..."

# Scan backend_host
if [ -d "backend_host/src" ]; then
    echo -e "${BLUE}  • Scanning backend_host...${NC}"
    bandit -c bandit.yaml -r backend_host/src -f json -o "$HOST_BANDIT_JSON" 2>/dev/null || true
    echo -e "${GREEN}  ✓ Host scan complete${NC}"
else
    echo -e "${RED}  ✗ backend_host/src not found${NC}"
fi

# Scan backend_server
if [ -d "backend_server/src" ]; then
    echo -e "${BLUE}  • Scanning backend_server...${NC}"
    bandit -c bandit.yaml -r backend_server/src -f json -o "$SERVER_BANDIT_JSON" 2>/dev/null || true
    echo -e "${GREEN}  ✓ Server scan complete${NC}"
else
    echo -e "${RED}  ✗ backend_server/src not found${NC}"
fi

# Scan shared (DB layer + portability + utils — imported by both host and server)
if [ -d "shared/src" ]; then
    echo -e "${BLUE}  • Scanning shared...${NC}"
    bandit -c bandit.yaml -r shared/src -f json -o "$SHARED_BANDIT_JSON" 2>/dev/null || true
    echo -e "${GREEN}  ✓ Shared scan complete${NC}"
else
    echo -e "${RED}  ✗ shared/src not found${NC}"
fi

echo ""

# ==================== SAFETY SCANS ====================
if [ "$SAFETY_AVAILABLE" = true ]; then
    echo -e "${YELLOW}→${NC} Running Safety dependency scans..."

    # Scan backend_host requirements
    if [ -f "backend_host/requirements.txt" ]; then
        echo -e "${BLUE}  • Scanning host dependencies...${NC}"
        safety check -r backend_host/requirements.txt > "$HOST_SAFETY_TXT" 2>&1 || true
        echo -e "${GREEN}  ✓ Host dependencies scanned${NC}"
    fi

    # Scan backend_server requirements
    if [ -f "backend_server/requirements.txt" ]; then
        echo -e "${BLUE}  • Scanning server dependencies...${NC}"
        safety check -r backend_server/requirements.txt > "$SERVER_SAFETY_TXT" 2>&1 || true
        echo -e "${GREEN}  ✓ Server dependencies scanned${NC}"
    fi

    echo ""
else
    echo -e "${YELLOW}⚠ Skipping Safety scans - tool not installed${NC}"
    echo "Safety tool not installed" > "$HOST_SAFETY_TXT"
    echo "Safety tool not installed" > "$SERVER_SAFETY_TXT"
    echo ""
fi

# ==================== NPM AUDIT ====================
if command -v npm &> /dev/null; then
    echo -e "${YELLOW}→${NC} Running npm audit for frontend..."

    if [ -f "frontend/package.json" ]; then
        echo -e "${BLUE}  • Scanning frontend dependencies...${NC}"
        cd frontend
        npm audit --json > "../$FRONTEND_AUDIT_JSON" 2>&1 || true
        cd ..
        echo -e "${GREEN}  ✓ Frontend dependencies scanned${NC}"
    else
        echo -e "${RED}  ✗ frontend/package.json not found${NC}"
        echo '{"error": "package.json not found"}' > "$FRONTEND_AUDIT_JSON"
    fi

    echo ""
else
    echo -e "${YELLOW}⚠ npm not found - skipping frontend scan${NC}"
    echo '{"error": "npm not installed"}' > "$FRONTEND_AUDIT_JSON"
    echo ""
fi

# ==================== SNYK CODE ANALYSIS ====================
SNYK_HOST_JSON="$TEMP_DIR/snyk_host_code.json"
SNYK_SERVER_JSON="$TEMP_DIR/snyk_server_code.json"
SNYK_SHARED_JSON="$TEMP_DIR/snyk_shared_code.json"

if command -v snyk &> /dev/null; then
    echo -e "${YELLOW}→${NC} Running Snyk code analysis (SAST)..."

    # Scan backend_host
    if [ -d "backend_host/src" ]; then
        echo -e "${BLUE}  • Scanning backend_host code...${NC}"
        snyk code test backend_host/src --json > "$SNYK_HOST_JSON" 2>/dev/null || true
        echo -e "${GREEN}  ✓ Host code analysis complete${NC}"
    else
        echo -e "${RED}  ✗ backend_host/src not found${NC}"
        echo '{"error": "backend_host/src not found"}' > "$SNYK_HOST_JSON"
    fi

    # Scan backend_server
    if [ -d "backend_server/src" ]; then
        echo -e "${BLUE}  • Scanning backend_server code...${NC}"
        snyk code test backend_server/src --json > "$SNYK_SERVER_JSON" 2>/dev/null || true
        echo -e "${GREEN}  ✓ Server code analysis complete${NC}"
    else
        echo -e "${RED}  ✗ backend_server/src not found${NC}"
        echo '{"error": "backend_server/src not found"}' > "$SNYK_SERVER_JSON"
    fi

    # Scan shared
    if [ -d "shared/src" ]; then
        echo -e "${BLUE}  • Scanning shared code...${NC}"
        snyk code test shared/src --json > "$SNYK_SHARED_JSON" 2>/dev/null || true
        echo -e "${GREEN}  ✓ Shared code analysis complete${NC}"
    else
        echo -e "${RED}  ✗ shared/src not found${NC}"
        echo '{"error": "shared/src not found"}' > "$SNYK_SHARED_JSON"
    fi

    echo ""
else
    echo -e "${YELLOW}⚠ Snyk not found - skipping code analysis${NC}"
    echo -e "${YELLOW}     Install: npm install -g snyk && snyk auth${NC}"
    # Do NOT write stub temp files here. Leaving SNYK_*_JSON absent makes the parser
    # fall back to any existing docs/security/snyk-*-report.json and NOT overwrite it,
    # so a run without Snyk preserves previously-generated real SARIF reports instead
    # of clobbering them with "snyk not installed" stubs.
    echo ""
fi

# ==================== GENERATE HTML ====================
echo -e "${YELLOW}→${NC} Generating HTML documentation..."

python3 scripts/parse-security-to-html.py

echo -e "${GREEN}✓ Security documentation generated!${NC}"
echo ""
echo -e "${BLUE}Generated files:${NC}"
echo -e "  • docs/security/index.html"
echo -e "  • docs/security/host-report.json"
echo -e "  • docs/security/server-report.json"
echo -e "  • docs/security/shared-report.json"
echo -e "  • docs/security/frontend-report.json"
echo -e "  • docs/security/snyk-host-report.json (if Snyk available)"
echo -e "  • docs/security/snyk-server-report.json (if Snyk available)"
echo ""
echo -e "${YELLOW}Access at: /docs/security/index.html${NC}"
echo ""

# Also copy Snyk reports to security_report/ folder (best-effort; must never abort the
# run before cleanup — a missing dir here previously tripped `set -e` and left the
# temp/ scratch files behind, which then got committed).
SECURITY_REPORT_DIR="security_report"
mkdir -p "$SECURITY_REPORT_DIR"
if [ -f "$DOCS_SECURITY/snyk-host-report.json" ]; then
    cp "$DOCS_SECURITY/snyk-host-report.json" "$SECURITY_REPORT_DIR/snyk_host_code.json" || true
fi
if [ -f "$DOCS_SECURITY/snyk-server-report.json" ]; then
    cp "$DOCS_SECURITY/snyk-server-report.json" "$SECURITY_REPORT_DIR/snyk_server_code.json" || true
fi

# Cleanup temp scratch files (never commit these — see docs/security temp gitignore)
rm -rf "$TEMP_DIR"

