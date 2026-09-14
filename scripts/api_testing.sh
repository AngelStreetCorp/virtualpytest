#!/bin/bash

# API Testing Script - Minimalist endpoint testing
# Usage: ./api_testing.sh [quick|full]

set -e

# Load environment variables from .env file if it exists
if [ -f .env ]; then
    echo "Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
fi

# Configuration - Use environment variables with defaults
BASE_URL="${SERVER_URL:-http://localhost:5109}"
TEAM_ID="${TEAM_ID:-7fdeb4bb-3639-4ec3-959f-b54769a219ce}"
HOST_NAME="${HOST_NAME:-host1}"
DEVICE_ID="${DEVICE_ID:-device1}"
TIMEOUT=90

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Get git commit
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

echo -e "${BLUE}🚀 API Testing Suite${NC}"
echo -e "${BLUE}===================${NC}"
echo "Git Commit: $GIT_COMMIT"
echo "Base URL: $BASE_URL"
echo "Timestamp: $(date)"
echo ""

# Test function
test_endpoint() {
    local name="$1"
    local method="$2"
    local endpoint="$3"
    local data="$4"
    local expected_codes="$5"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo -n "Testing $name... "
    
    # Build curl command
    local curl_cmd="curl -s -w '%{http_code}' --max-time $TIMEOUT"
    
    if [ "$method" = "POST" ] && [ -n "$data" ]; then
        curl_cmd="$curl_cmd -X POST -H 'Content-Type: application/json' -d '$data'"
    fi
    
    # Execute request
    local response
    local http_code
    
    if response=$(eval "$curl_cmd '$BASE_URL$endpoint'" 2>/dev/null); then
        http_code="${response: -3}"
        
        # Check if status code is expected
        if [[ "$expected_codes" == *"$http_code"* ]]; then
            echo -e "${GREEN}✅ PASS${NC} ($http_code)"
            PASSED_TESTS=$((PASSED_TESTS + 1))
        else
            echo -e "${RED}❌ FAIL${NC} ($http_code, expected: $expected_codes)"
            FAILED_TESTS=$((FAILED_TESTS + 1))
        fi
    else
        echo -e "${RED}❌ FAIL${NC} (Network error)"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
}

# Test suites
run_quick_tests() {
    echo -e "${YELLOW}Running Quick Tests (Critical Endpoints)${NC}"
    echo "----------------------------------------"
    
    test_endpoint "System Health" "GET" "/server/system/health" "" "200"
    test_endpoint "AI Task Execution" "POST" "/server/ai-execution/executeTask?team_id=$TEAM_ID" \
        '{"task_description":"go to live","userinterface_name":"example_mobile","host_name":"'$HOST_NAME'","device_id":"'$DEVICE_ID'"}' \
        "200 202 400"
}

run_full_tests() {
    echo -e "${YELLOW}Running Full Test Suite${NC}"
    echo "----------------------"
    
    # System endpoints
    test_endpoint "System Health" "GET" "/server/system/health" "" "200"
    test_endpoint "System Status" "GET" "/server/system/status" "" "200"
    
    # AI execution endpoints
    test_endpoint "AI Task Execution" "POST" "/server/ai-execution/executeTask?team_id=$TEAM_ID" \
        '{"task_description":"go to live","userinterface_name":"example_mobile","host_name":"'$HOST_NAME'","device_id":"'$DEVICE_ID'"}' \
        "200 202 400"
    
    # Navigation endpoints
    test_endpoint "Get Navigation Nodes" "GET" "/server/navigation/getNodes?device_model=android_mobile&userinterface_name=example_mobile&team_id=$TEAM_ID" "" "200 404"
    
    # Action endpoints
    test_endpoint "Get Actions" "GET" "/server/action/getActions?device_model=android_mobile" "" "200"
    
    # Verification endpoints
    test_endpoint "Get Verifications" "GET" "/server/verification/getVerifications?device_model=android_mobile" "" "200"
    
    # Control endpoints
    test_endpoint "Take Control" "POST" "/server/control/takeControl" \
        '{"host_name":"'$HOST_NAME'","device_id":"'$DEVICE_ID'"}' \
        "200 400 404"
}

# Generate simple HTML report
generate_html_report() {
    local percentage=$((PASSED_TESTS * 100 / TOTAL_TESTS))
    local filename="api-test-report-$GIT_COMMIT-$(date +%s).html"
    
    cat > "$filename" << EOF
<!DOCTYPE html>
<html>
<head>
    <title>API Test Report - $(date)</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .summary { background: #f5f5f5; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
        .pass { color: #4caf50; font-weight: bold; }
        .fail { color: #f44336; font-weight: bold; }
    </style>
</head>
<body>
    <div class="summary">
        <h1>API Test Report</h1>
        <p><strong>Git Commit:</strong> $GIT_COMMIT</p>
        <p><strong>Timestamp:</strong> $(date)</p>
        <p><strong>Results:</strong> <span class="pass">$PASSED_TESTS passed</span>, <span class="fail">$FAILED_TESTS failed</span> ($percentage%)</p>
    </div>
    <p>Detailed results available in terminal output.</p>
</body>
</html>
EOF
    
    echo "HTML report generated: $filename"
}

# Main execution
MODE="${1:-full}"

case "$MODE" in
    "quick")
        run_quick_tests
        ;;
    "full")
        run_full_tests
        ;;
    *)
        echo "Usage: $0 [quick|full]"
        echo "  quick - Test critical endpoints only"
        echo "  full  - Test all endpoints (default)"
        exit 1
        ;;
esac

# Summary
echo ""
echo -e "${BLUE}Test Summary${NC}"
echo "============"
echo "Total Tests: $TOTAL_TESTS"
echo -e "Passed: ${GREEN}$PASSED_TESTS${NC}"
echo -e "Failed: ${RED}$FAILED_TESTS${NC}"

if [ $TOTAL_TESTS -gt 0 ]; then
    PERCENTAGE=$((PASSED_TESTS * 100 / TOTAL_TESTS))
    echo "Success Rate: $PERCENTAGE%"
    
    if [ "$PERCENTAGE" -eq 100 ]; then
        echo -e "${GREEN}🎉 All tests passed!${NC}"
        exit 0
    else
        echo -e "${YELLOW}⚠️  Some tests failed${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ No tests executed${NC}"
    exit 1
fi
