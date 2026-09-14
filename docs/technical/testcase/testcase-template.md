# Testcase Description Template

## Overview

This document defines the standard format for testcase descriptions in VirtualPyTest. Use this template when creating testcases to ensure consistency, clarity, and maintainability.

---

## Template Format

```markdown
## [TestCase_ID]: [Short Descriptive Name]

**Requirement:** [Link to requirement code or description]
**Priority:** [P1 (Critical) | P2 (High) | P3 (Medium)]
**Reusable across:** [List of applications this test applies to]

**Steps:**
1. [Step description with action]
2. [Step description with action]
3. [Step description with action]
...

**Expected:**
- ✅ [Expected outcome 1]
- ✅ [Expected outcome 2]
- ✅ [Expected outcome 3]
...

**MCP Implementation:**
- Nodes: [node1 → node2 → node3]
- Verifications: [List of verification commands used]
- Actions: [List of action types used]

**Prerequisites:**
- [Prerequisite condition or testcase 1]
- [Prerequisite condition or testcase 2]
...

**Notes:**
- [Any additional notes, edge cases, or known issues]
```

---

## Example 1: Playback Test

```markdown
## Playback_001: Basic Video Playback

**Requirement:** REQ_PLAYBACK_001 - User can play video content
**Priority:** P1 (Critical)
**Reusable across:** Netflix, YouTube, Disney+, Prime Video

**Steps:**
1. Navigate to home
2. Select first available content
3. Click play button
4. Verify video starts within 5 seconds
5. Verify playback controls visible
6. Verify video plays for 30 seconds without buffering

**Expected:**
- ✅ Video starts within 5 seconds
- ✅ Controls visible (play/pause, timeline, volume)
- ✅ No buffering or errors
- ✅ Audio synchronized

**MCP Implementation:**
- Nodes: home → content_detail → player
- Verifications: waitForElement("play_button"), verifyVideoPlaying, checkBuffering
- Actions: navigate, click, wait

**Prerequisites:**
- User must be logged in
- At least one piece of content available in catalog

**Notes:**
- Test works on both mobile and TV platforms
- Adjust timeout values for slower devices
```

---

## Example 2: Authentication Test

```markdown
## Auth_001: User Login with Valid Credentials

**Requirement:** REQ_AUTH_001 - User can log in with email and password
**Priority:** P1 (Critical)
**Reusable across:** All streaming apps with email/password authentication

**Steps:**
1. Navigate to login screen
2. Enter valid email address
3. Enter valid password
4. Click login button
5. Verify redirect to home screen
6. Verify user profile visible

**Expected:**
- ✅ Login successful within 3 seconds
- ✅ Redirect to home screen
- ✅ User profile/avatar visible in header
- ✅ No error messages displayed

**MCP Implementation:**
- Nodes: entry → login → home
- Verifications: waitForElement("email_field"), waitForElement("password_field"), verifyElement("user_avatar")
- Actions: navigate, type_text, click, wait

**Prerequisites:**
- Valid test user credentials available
- App not already logged in

**Notes:**
- Credentials stored in environment variables
- Test clears app data before execution
```

---

## Example 3: Navigation Test

```markdown
## Nav_001: Navigate to Settings

**Requirement:** REQ_NAV_003 - User can access settings menu
**Priority:** P2 (High)
**Reusable across:** Netflix, YouTube, Disney+, Prime Video, Spotify

**Steps:**
1. Start from home screen
2. Click menu/hamburger icon
3. Select "Settings" option
4. Verify settings screen loads
5. Verify settings sections visible (Account, Playback, Accessibility)

**Expected:**
- ✅ Menu opens on click
- ✅ Settings option visible and clickable
- ✅ Settings screen loads within 2 seconds
- ✅ All main sections visible

**MCP Implementation:**
- Nodes: home → menu → settings
- Verifications: waitForElement("settings_button"), waitForElement("account_section"), waitForElement("playback_section")
- Actions: click, wait

**Prerequisites:**
- None

**Notes:**
- Menu icon location varies by platform (top-left on mobile, side panel on TV)
```

---

## Example 4: Search Test

```markdown
## Search_001: Search for Content by Title

**Requirement:** REQ_SEARCH_001 - User can search for content by title
**Priority:** P1 (Critical)
**Reusable across:** Netflix, YouTube, Disney+, Prime Video

**Steps:**
1. Navigate to search screen
2. Click search input field
3. Type "Stranger Things"
4. Verify search results appear
5. Verify at least one result matches query
6. Click first result
7. Verify content detail page loads

**Expected:**
- ✅ Search input accepts text
- ✅ Results appear as user types (auto-suggest)
- ✅ Results match search query
- ✅ Clicking result opens detail page

**MCP Implementation:**
- Nodes: home → search → search_results → content_detail
- Verifications: waitForElement("search_input"), verifyTextOnScreen("Stranger Things"), waitForElement("result_item")
- Actions: navigate, click, type_text, wait

**Prerequisites:**
- Content "Stranger Things" must be available in catalog
- Network connectivity required

**Notes:**
- Search behavior differs between apps (some show instant results, others require submit)
- Test uses platform-specific keyboard input method
```

---

## Example 5: Error Handling Test

```markdown
## Playback_007: Playback Error Handling

**Requirement:** REQ_PLAYBACK_007 - App gracefully handles playback errors
**Priority:** P1 (Critical)
**Reusable across:** All streaming apps

**Steps:**
1. Navigate to content that will trigger playback error (network timeout, DRM failure, etc.)
2. Attempt to play content
3. Verify error message displayed
4. Verify error message is user-friendly (not technical stack trace)
5. Verify retry option available
6. Click retry button
7. Verify app attempts to replay content

**Expected:**
- ✅ Error message displayed within 10 seconds
- ✅ Message is user-friendly ("Unable to play. Please try again.")
- ✅ Retry button visible
- ✅ App doesn't crash or freeze
- ✅ User can navigate back to previous screen

**MCP Implementation:**
- Nodes: home → content_detail → player_error
- Verifications: waitForElement("error_message"), verifyTextOnScreen("Unable to play"), waitForElement("retry_button")
- Actions: navigate, click, wait

**Prerequisites:**
- Test content configured to trigger playback error
- Or: Network simulation to inject failure

**Notes:**
- This test requires special test content or network simulation
- Error messages vary by platform and app
```

---

## Example 6: Prerequisite Chain Test

```markdown
## Playback_002: Pause and Resume

**Requirement:** REQ_PLAYBACK_002 - User can pause and resume video playback
**Priority:** P1 (Critical)
**Reusable across:** Netflix, YouTube, Disney+, Prime Video

**Steps:**
1. Start playback (prerequisite: Playback_001)
2. Click pause button
3. Verify playback paused
4. Verify timeline position noted
5. Wait 2 seconds
6. Click play button
7. Verify playback resumed from same position

**Expected:**
- ✅ Video pauses immediately
- ✅ Pause icon changes to play icon
- ✅ Resume continues from exact pause point
- ✅ Timeline position preserved
- ✅ No buffering on resume

**MCP Implementation:**
- Nodes: player (assumes already in player state)
- Verifications: verifyVideoPlaying, verifyVideoPaused, verifyTimelinePosition
- Actions: click, wait

**Prerequisites:**
- **Playback_001: Basic Video Playback** must pass (video must be playing)
- Video must have at least 30 seconds of content

**Notes:**
- Some apps have slight timeline drift (±1 second) on resume
- Test verifies position within 1-second tolerance
```

---

## Field Descriptions

### **TestCase_ID**
- **Format:** `Category_###` (e.g., `Playback_001`, `Auth_002`)
- **Purpose:** Unique identifier for the test case
- **Naming Convention:**
  - `Playback_###` - Video playback tests
  - `Auth_###` - Authentication tests
  - `Nav_###` - Navigation tests
  - `Search_###` - Search functionality tests
  - `UI_###` - UI/UX tests
  - `Perf_###` - Performance tests

### **Requirement**
- **Format:** `REQ_CATEGORY_### - Description` or direct description
- **Purpose:** Links test to specific requirement for traceability
- **Example:** `REQ_PLAYBACK_001 - User can play video content`

### **Priority**
- **P1 (Critical):** Must pass for basic functionality, blocks release if failing
- **P2 (High):** Important functionality, should be fixed before release
- **P3 (Medium):** Nice-to-have, can be fixed in next release

### **Reusable across**
- **Purpose:** Identifies which applications/platforms this test applies to
- **Example:** `Netflix, YouTube, Disney+` or `All streaming apps`
- **Note:** Maps to `userinterface_name` in database

### **Steps**
- **Format:** Numbered list of actions to perform
- **Purpose:** Human-readable test steps for manual verification or documentation
- **Note:** Should match the MCP graph execution flow

### **Expected**
- **Format:** Bulleted list with ✅ checkmarks
- **Purpose:** Clear pass/fail criteria for the test
- **Note:** Each item should be verifiable programmatically

### **MCP Implementation**
- **Nodes:** Navigation path through UI tree (`home → content_detail → player`)
- **Verifications:** MCP verification commands used
- **Actions:** Types of actions executed (navigate, click, type, wait, etc.)
- **Purpose:** Technical details for test automation engineers

### **Prerequisites**
- **Purpose:** Conditions that must be true before test can run
- **Types:**
  - System state (user logged in, network available)
  - Data availability (content in catalog)
  - Other testcases (must run after another test)
- **Example:** `Playback_001 must pass`, `Valid user credentials available`

### **Notes**
- **Purpose:** Additional context, edge cases, platform differences
- **Example:** `Test works on mobile and TV`, `Timeout values may need adjustment for slower devices`

---

## Usage in Database

### **Storing in `testcase_definitions` Table**

```python
# When creating a testcase
testcase_data = {
    'testcase_name': 'Playback_001_BasicVideoPlayback',
    'description': '''## Playback_001: Basic Video Playback

**Requirement:** REQ_PLAYBACK_001 - User can play video content
**Priority:** P1 (Critical)
**Reusable across:** Netflix, YouTube, Disney+, Prime Video

**Steps:**
1. Navigate to home
2. Select first available content
3. Click play button
4. Verify video starts within 5 seconds
5. Verify playback controls visible

**Expected:**
- ✅ Video starts within 5 seconds
- ✅ Controls visible (play/pause, timeline, volume)
- ✅ No buffering or errors

**MCP Implementation:**
- Nodes: home → content_detail → player
- Verifications: waitForElement("play_button"), verifyVideoPlaying
- Actions: navigate, click, wait

**Prerequisites:**
- User must be logged in
- At least one piece of content available

**Notes:**
- Test works on both mobile and TV platforms
''',
    'tags': ['P1', 'playback', 'critical', 'reusable:netflix', 'reusable:youtube', 'reusable:disney+'],
    'folder': 'playback',
    'userinterface_name': 'netflix_mobile',
    'graph_json': {...}
}
```

### **Using Tags for Filtering**

```python
# Find all P1 tests
tags_filter = ['P1']

# Find all playback tests
tags_filter = ['playback']

# Find all tests reusable for Netflix
tags_filter = ['reusable:netflix']

# Combine filters (P1 playback tests for Netflix)
tags_filter = ['P1', 'playback', 'reusable:netflix']
```

---

## Tag Conventions

### **Priority Tags**
- `P1` - Critical priority
- `P2` - High priority
- `P3` - Medium priority

### **Category Tags**
- `playback` - Video playback tests
- `auth` - Authentication tests
- `navigation` - Navigation/menu tests
- `search` - Search functionality tests
- `ui` - UI/UX tests
- `performance` - Performance tests
- `accessibility` - Accessibility tests

### **Reusability Tags**
- `reusable:netflix` - Works with Netflix
- `reusable:youtube` - Works with YouTube
- `reusable:disney+` - Works with Disney+
- `reusable:prime_video` - Works with Prime Video
- `reusable:all` - Works with all streaming apps

### **Platform Tags**
- `mobile` - Mobile-specific test
- `tv` - TV-specific test
- `web` - Web-specific test
- `cross-platform` - Works on all platforms

### **Type Tags**
- `smoke` - Smoke test (quick validation)
- `regression` - Regression test
- `integration` - Integration test
- `e2e` - End-to-end test

---

## Best Practices

### **DO:**
✅ Use consistent formatting for all testcases
✅ Include all sections (even if some are "None" or "N/A")
✅ Write clear, actionable steps
✅ Define measurable expected outcomes
✅ Link to requirements for traceability
✅ Include prerequisites for chained tests
✅ Add notes for platform-specific behavior
✅ Use appropriate tags for filtering

### **DON'T:**
❌ Skip sections (use "N/A" if truly not applicable)
❌ Write vague steps ("Test the feature")
❌ Forget to update description when test changes
❌ Ignore prerequisites (causes flaky tests)
❌ Use technical jargon without explanation
❌ Duplicate information between description and graph
❌ Forget to tag priority level

---

## Rendering in Frontend

### **Markdown Preview**

Use a React markdown library like `react-markdown` to display formatted descriptions:

```typescript
import ReactMarkdown from 'react-markdown';

<ReactMarkdown>{testcase.description}</ReactMarkdown>
```

### **Tag Display**

Show tags as chips with color coding:
- **P1** → Red chip
- **P2** → Orange chip
- **P3** → Blue chip
- **Category** → Gray chip
- **Reusability** → Green chip

---

## Migration Path

For existing testcases without rich descriptions:

1. **Minimal Description:** Add at least testcase name and priority
2. **Standard Description:** Add steps and expected outcomes
3. **Full Description:** Add all sections including MCP implementation details

**Priority order:**
1. P1 tests first (most critical)
2. Frequently-run tests (regression suite)
3. Recently-created tests (easier to document while fresh)
4. All remaining tests

---

## Examples by Category

### **Authentication**
- Login with valid credentials
- Login with invalid credentials
- Logout
- Session timeout handling
- Password reset flow

### **Playback**
- Basic video playback
- Pause and resume
- Skip forward/backward
- Volume control
- Quality settings
- Subtitle toggle
- Error handling

### **Navigation**
- Navigate to settings
- Navigate to profile
- Menu navigation
- Back button behavior
- Deep linking

### **Search**
- Search by title
- Search by actor
- Search by genre
- Empty search results
- Search suggestions

### **UI/UX**
- Button states (enabled/disabled)
- Loading indicators
- Toast notifications
- Modal dialogs
- Responsive layout

---

## Conclusion

Use this template consistently across all testcases to ensure:
- ✅ **Clarity** - Anyone can understand what the test does
- ✅ **Traceability** - Tests linked to requirements
- ✅ **Maintainability** - Easy to update when requirements change
- ✅ **Reusability** - Clear which apps/platforms the test applies to
- ✅ **Reportability** - Rich data for test reports and dashboards

**Remember:** The description is documentation for humans. The graph is execution for machines. Both are essential!

