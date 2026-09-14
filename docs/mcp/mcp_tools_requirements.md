## 🎉 What's New in v4.3.0 (November 2025)

### 📋 **Requirements Management Tools**

**10 New Tools for Requirements & Coverage Tracking:**
- ✅ **`create_requirement`** - Create requirements with app_type/device_model for reusability
- ✅ **`list_requirements`** - List requirements with filters (category, priority, status)
- ✅ **`get_requirement`** - Get requirement details by ID
- ✅ **`update_requirement`** - Update requirements including app_type and device_model (**NEW**)
- ✅ **`link_testcase_to_requirement`** - Link testcases for coverage tracking
- ✅ **`unlink_testcase_from_requirement`** - Remove testcase links
- ✅ **`get_testcase_requirements`** - Get requirements covered by testcase
- ✅ **`get_requirement_coverage`** - Get detailed coverage for requirement
- ✅ **`get_coverage_summary`** - Get overall coverage metrics with breakdowns
- ✅ **`get_uncovered_requirements`** - Identify coverage gaps

**Why Requirements Management?**
- **Hybrid Approach** - Generic streaming requirements (`app_type: "streaming"`) reusable across Netflix, YouTube, Disney+
- **App-Specific** - Netflix-specific requirements (`app_type: "netflix"`) for unique features
- **Device-Specific** - Platform behaviors (`device_model: "android_mobile"`)
- **Coverage Tracking** - Link testcases to requirements, track coverage metrics
- **Gap Analysis** - Identify uncovered requirements automatically

**Hybrid Requirements Strategy:**
```python
# Generic streaming requirement (reusable across apps)
create_requirement({
    "requirement_code": "REQ_STREAM_PLAY_001",
    "requirement_name": "User can play video content",
    "app_type": "streaming",        # Works for Netflix, YouTube, etc.
    "device_model": "all",
    "priority": "P1"
})

# App-specific requirement
create_requirement({
    "requirement_code": "REQ_NETFLIX_PROFILES_001",
    "requirement_name": "User can switch Netflix profiles",
    "app_type": "netflix",          # Netflix-specific
    "device_model": "all",
    "priority": "P1"
})

# Update existing requirement to be generic
update_requirement({
    "requirement_id": "abc-123",
    "app_type": "streaming",        # Make it reusable
    "device_model": "android_mobile"
})
```

**Example Workflow:**
```python
# 1. Create requirements
req_id = create_requirement({
    "requirement_code": "REQ_PLAYBACK_001",
    "requirement_name": "User can play video",
    "app_type": "streaming",
    "device_model": "all",
    "priority": "P1",
    "category": "playback"
})

# 2. Create testcase
testcase_id = save_testcase({
    "testcase_name": "Basic Playback Test",
    "graph_json": {...}
})

# 3. Link testcase to requirement
link_testcase_to_requirement({
    "testcase_id": testcase_id,
    "requirement_id": req_id,
    "coverage_type": "full"
})

# 4. Get coverage summary
summary = get_coverage_summary()
# Returns: Total: 12, Covered: 8, Uncovered: 4, Coverage: 66.7%

# 5. Find gaps
gaps = get_uncovered_requirements()
# Returns: List of requirements without test coverage
```

**Tool Count:** 49 tools (was 39 in v4.2.1)
