# Testcase Naming Convention

## 🎯 Overview

Comprehensive naming convention for testcases in VirtualPyTest that ensures consistency, reusability, and traceability to requirements.

**Key Principle**: Testcases should be **generic and reusable** across apps with similar functionality. App-specific navigation is handled by the **userinterface model** (navigation tree), not the testcase name.

---

## 📐 Naming Format

### **Standard Format:**
```
TC_<CATEGORY>_<NUMBER>_<CamelCaseAction>

Components:
- TC: Fixed prefix (TestCase)
- CATEGORY: 3-4 char uppercase code (APP, AUTH, NAV, PLAY, SRCH, etc.)
- NUMBER: 2-digit zero-padded (01-99) within category
- Action: CamelCase descriptor, 2-4 words describing what the test does

Examples:
✅ TC_APP_01_LaunchApp
✅ TC_AUTH_01_LoginLogout
✅ TC_NAV_01_MainTabs
✅ TC_PLAY_01_BasicPlayback
✅ TC_SRCH_01_ContentSearch
✅ TC_VOD_01_HomeContent
```

### **Description Format:**
```
Generic, action-oriented sentence describing the test flow.
No app names unless functionality is truly app-specific.

Format: "Action + verification" or "Navigate to X, perform Y, verify Z"

Examples:
✅ "Navigate from home to player and verify video starts"
✅ "Search for content and verify results appear"
✅ "Navigate through all main tabs and verify each screen loads"
✅ "Verify back button navigation works from multiple screens"

Avoid:
❌ "Navigate Netflix home to Netflix player and play Netflix video"
❌ "Test search in Netflix app"
❌ "YouTube video playback test"
```

---

## 📊 Category Mapping

### **Aligned with Requirements Categories**

| Category Code | Category Name | Testcase Prefix | Example Testcase |
|---------------|---------------|-----------------|------------------|
| **APP** | App Lifecycle | TC_APP_XX_ | TC_APP_01_LaunchApp |
| **AUTH** | Authentication | TC_AUTH_XX_ | TC_AUTH_01_LoginLogout |
| **NAV** | Navigation | TC_NAV_XX_ | TC_NAV_01_MainTabs |
| **LIVE** | Live TV | TC_LIVE_XX_ | TC_LIVE_01_ChannelZapping |
| **EPG** | Program Guide | TC_EPG_XX_ | TC_EPG_01_ViewGuide |
| **VOD** | On-Demand | TC_VOD_XX_ | TC_VOD_01_BrowseCatalog |
| **PLAY** | Player/Playback | TC_PLAY_XX_ | TC_PLAY_01_BasicPlayback |
| **REC** | Recording/DVR | TC_REC_XX_ | TC_REC_01_ScheduleRecording |
| **SRCH** | Search | TC_SRCH_XX_ | TC_SRCH_01_ContentSearch |
| **CONT** | Content Detail | TC_CONT_XX_ | TC_CONT_01_DetailView |
| **SETT** | Settings | TC_SETT_XX_ | TC_SETT_01_ChangeQuality |
| **DOWN** | Downloads | TC_DOWN_XX_ | TC_DOWN_01_DownloadContent |
| **PROF** | Profile | TC_PROF_XX_ | TC_PROF_01_SwitchProfile |
| **PERF** | Performance | TC_PERF_XX_ | TC_PERF_01_LaunchTime |
| **NET** | Network | TC_NET_XX_ | TC_NET_01_OfflineMode |
| **ERR** | Error Handling | TC_ERR_XX_ | TC_ERR_01_NetworkError |
| **A11Y** | Accessibility | TC_A11Y_XX_ | TC_A11Y_01_ScreenReader |

---

## 🔄 Generic vs App-Specific Testcases

### **Core Concept: Reusability Through UserInterface Models**

**How It Works:**
1. **Same testcase graph** (nodes + edges) runs on multiple apps
2. **Only change**: `userinterface_name` in scriptConfig
3. **Navigation tree** per app defines app-specific navigation paths
4. **Generic node labels** (home, search, player) map to different screens per app

### **Generic Testcases (90% of cases)**

**Use generic names that apply to ANY app with similar functionality.**

#### Example: `TC_PLAY_01_BasicPlayback`

**Description:** "Navigate from home to player and verify video starts"

**Reusability:**
- **Netflix**: Uses netflix_mobile navigation tree
  - home (Netflix Home Screen) → content_detail (Netflix Detail) → player (Netflix Player)
- **YouTube**: Uses youtube_mobile navigation tree
  - home (YouTube Home) → content_detail (Video Detail) → player (YouTube Player)
- **Hulu**: Uses hulu_mobile navigation tree
  - home (Hulu Home) → content_detail (Show Detail) → player (Hulu Player)

**Same testcase, different userinterface_name, different UI elements!**

#### More Generic Examples:

| Testcase | Description | Works On |
|----------|-------------|----------|
| TC_NAV_01_MainTabs | Navigate through all main tabs | Netflix, YouTube, Hulu, Disney+ |
| TC_SRCH_01_ContentSearch | Search for content and verify results | Netflix, YouTube, Spotify, Amazon |
| TC_VOD_01_ContinueWatching | Access continue watching section | Netflix, Hulu, Disney+, HBO Max |
| TC_AUTH_01_LoginLogout | Login and logout flow | Any app with auth |
| TC_PLAY_02_PauseResume | Pause and resume video playback | Any video player app |
| TC_PROF_01_SwitchProfile | Switch between user profiles | Netflix, Disney+, Hulu |

### **App-Specific Testcases (10% of cases)**

**Only use app names when functionality is UNIQUE to that app.**

#### When to Use App-Specific Names:

✅ **Unique features:**
- `TC_VOD_01_NetflixProfileKids` - Netflix-specific Kids profile mode
- `TC_PLAY_01_YouTubeMiniPlayer` - YouTube's unique mini player
- `TC_VOD_01_SpotifyDiscoverWeekly` - Spotify's unique discover weekly
- `TC_LIVE_01_virtualpyTVTimeshift` - virtualpy TV's specific timeshift implementation

❌ **Common features (use generic names):**
- ~~TC_PLAY_01_NetflixPlayback~~ → TC_PLAY_01_BasicPlayback
- ~~TC_SRCH_01_YouTubeSearch~~ → TC_SRCH_01_ContentSearch
- ~~TC_VOD_01_HuluBrowsing~~ → TC_VOD_01_BrowseCatalog

---

## 📝 Testcase Components

### **1. Testcase Name (field: testcase_name)**
```
Format: TC_<CATEGORY>_<NUMBER>_<CamelCase>
Example: TC_PLAY_01_BasicPlayback
```

### **2. Description (field: description)**
```
Format: "Action-oriented sentence describing the test flow"
Example: "Navigate from home to player and verify video starts"
```

### **3. UserInterface Name (field: userinterface_name)**
```
Format: <app>_<platform>
Examples: netflix_mobile, youtube_tv, hulu_web
```

### **4. Tags (field: tags)**
```
Format: Array of strings for organization
Examples: ["P1", "playback", "smoke"], ["P2", "search", "regression"]
```

---

## 🎯 Category-Specific Examples

### **APP (App Lifecycle)**
- TC_APP_01_LaunchApp - "Launch app and verify home screen loads"
- TC_APP_02_ResumeFromBackground - "Resume app from background and verify state"
- TC_APP_03_AppUpdate - "Update app and verify functionality after update"

### **AUTH (Authentication)**
- TC_AUTH_01_LoginLogout - "Login with valid credentials and logout"
- TC_AUTH_02_InvalidCredentials - "Attempt login with invalid credentials"
- TC_AUTH_03_SessionExpiry - "Verify session expiry and re-authentication"

### **NAV (Navigation)**
- TC_NAV_01_MainTabs - "Navigate through all main tabs and verify each screen"
- TC_NAV_02_BackButton - "Verify back button navigation from multiple screens"
- TC_NAV_03_DeepLink - "Open app via deep link and verify target screen"

### **LIVE (Live TV)**
- TC_LIVE_01_ChannelZapping - "Switch between channels and verify stream"
- TC_LIVE_02_ChannelList - "Navigate channel list and tune to channel"
- TC_LIVE_03_Timeshift - "Pause and resume live TV stream"

### **EPG (Electronic Program Guide)**
- TC_EPG_01_ViewGuide - "Open EPG and verify program information displays"
- TC_EPG_02_NavigateDays - "Navigate through EPG days and verify dates"
- TC_EPG_03_SetReminder - "Set program reminder and verify confirmation"

### **VOD (Video On Demand)**
- TC_VOD_01_BrowseCatalog - "Browse content catalog and verify categories"
- TC_VOD_02_ContinueWatching - "Access continue watching section"
- TC_VOD_03_MyList - "Add content to my list and verify"

### **PLAY (Player/Playback)**
- TC_PLAY_01_BasicPlayback - "Navigate from home to player and verify video starts"
- TC_PLAY_02_PauseResume - "Pause and resume video playback"
- TC_PLAY_03_SeekForward - "Seek forward in video timeline"
- TC_PLAY_04_SeekBackward - "Seek backward in video timeline"
- TC_PLAY_05_SubtitleToggle - "Enable and disable subtitles during playback"
- TC_PLAY_06_AudioTrackSwitch - "Switch audio track during playback"
- TC_PLAY_07_ExitPlayer - "Exit video player and return to previous screen"

### **REC (Recording/DVR)**
- TC_REC_01_ScheduleRecording - "Schedule program recording and verify"
- TC_REC_02_PlayRecording - "Play recorded program from DVR"
- TC_REC_03_DeleteRecording - "Delete recording and verify removal"

### **SRCH (Search)**
- TC_SRCH_01_ContentSearch - "Search for content and verify results"
- TC_SRCH_02_SearchToDetail - "Search and navigate to content detail"
- TC_SRCH_03_VoiceSearch - "Perform voice search and verify results"

### **CONT (Content Detail)**
- TC_CONT_01_DetailView - "Access content detail and verify information displays"
- TC_CONT_02_RelatedContent - "View related content from detail page"
- TC_CONT_03_TrailerPlay - "Play content trailer from detail page"

### **SETT (Settings)**
- TC_SETT_01_ChangeQuality - "Change video quality setting and verify"
- TC_SETT_02_ChangeLanguage - "Change app language and verify UI updates"
- TC_SETT_03_ParentalControls - "Enable parental controls and verify"

### **DOWN (Downloads)**
- TC_DOWN_01_DownloadContent - "Download content and verify completion"
- TC_DOWN_02_PlayOffline - "Play downloaded content in offline mode"
- TC_DOWN_03_DeleteDownload - "Delete downloaded content and verify"

### **PROF (Profile)**
- TC_PROF_01_SwitchProfile - "Switch between user profiles"
- TC_PROF_02_EditProfile - "Edit profile settings and verify changes"
- TC_PROF_03_CreateProfile - "Create new profile and verify"

### **PERF (Performance)**
- TC_PERF_01_LaunchTime - "Measure app launch time"
- TC_PERF_02_VideoStartTime - "Measure video start time"
- TC_PERF_03_ZappingTime - "Measure channel zapping time"

### **NET (Network)**
- TC_NET_01_OfflineMode - "Verify app behavior in offline mode"
- TC_NET_02_NetworkSwitch - "Switch between WiFi and mobile data"
- TC_NET_03_Reconnection - "Verify automatic reconnection after network loss"

### **ERR (Error Handling)**
- TC_ERR_01_NetworkError - "Trigger network error and verify handling"
- TC_ERR_02_PlaybackError - "Trigger playback error and verify recovery"
- TC_ERR_03_ContentUnavailable - "Access unavailable content and verify message"

### **A11Y (Accessibility)**
- TC_A11Y_01_ScreenReader - "Navigate app with screen reader enabled"
- TC_A11Y_02_HighContrast - "Verify high contrast mode functionality"
- TC_A11Y_03_FontSize - "Adjust font size and verify readability"

---

## ✅ Naming Best Practices

### **DO:**
✅ Use generic, descriptive action names
✅ Match category with linked requirements (PLAY testcase → PLAY requirements)
✅ Keep CamelCase action concise (2-4 words)
✅ Use sequential numbering within category (01, 02, 03...)
✅ Write descriptions that apply to multiple apps
✅ Focus on WHAT is tested, not HOW or WHERE

### **DON'T:**
❌ Include app names unless truly unique functionality
❌ Use abbreviations that aren't clear (VerBtn → VerifyButton)
❌ Mix categories (don't put search tests in NAV category)
❌ Duplicate numbers within same category
❌ Write descriptions specific to one app's UI
❌ Make names too long (TC_PLAY_01_NavigateToPlayerAndStartVideoAndVerifyPlaybackStarts)

---

## 🔗 Linking to Requirements

### **Testcase-to-Requirement Mapping**

Testcases should link to requirements with matching categories:

| Testcase | Links To Requirements |
|----------|----------------------|
| TC_PLAY_01_BasicPlayback | PLAY_P101, PLAY_P105 |
| TC_PLAY_02_PauseResume | PLAY_P102 |
| TC_SRCH_01_ContentSearch | SRCH_P101 |
| TC_NAV_01_MainTabs | NAV_P101, NAV_P102 |

**Example:**
```python
# Create testcase
testcase_id = create_testcase(
    team_id="...",
    testcase_name="TC_PLAY_01_BasicPlayback",
    description="Navigate from home to player and verify video starts",
    userinterface_name="netflix_mobile",
    tags=["P1", "playback", "smoke"]
)

# Link to requirements
link_testcase_to_requirement(
    testcase_id=testcase_id,
    requirement_id="PLAY_P101",  # User can play video content
    coverage_type="full"
)
```

---

## 🔄 Migration Guide

### **Old Format → New Format**

| Old Name | New Name | Rationale |
|----------|----------|-----------|
| Playback_001_BasicVideoPlayback | TC_PLAY_01_BasicPlayback | Add TC prefix, standardize number format |
| Search_002_SearchToDetail | TC_SRCH_02_SearchToDetail | Add TC prefix, use SRCH code |
| Nav_004_DeepNavigation | TC_NAV_04_DeepNavigation | Add TC prefix |
| UI_001_HomeScreenContent | TC_VOD_01_HomeContent | Reclassify as VOD, add TC prefix |
| device_get_info | TC_APP_01_GetDeviceInfo | Add TC prefix, proper category |
| Profile_001_AccessProfile | TC_PROF_01_AccessProfile | Add TC prefix |
| Downloads_001_AccessDownloads | TC_DOWN_01_AccessDownloads | Add TC prefix, use DOWN code |

---

## 📊 Complete Example

### **Testcase Creation:**

```json
{
  "testcase_name": "TC_PLAY_01_BasicPlayback",
  "description": "Navigate from home to player and verify video starts",
  "userinterface_name": "netflix_mobile",
  "tags": ["P1", "playback", "smoke"],
  "graph_json": {
    "nodes": [...],
    "edges": [...],
    "scriptConfig": {
      "inputs": [
        {
          "name": "userinterface_name",
          "type": "string",
          "default": "netflix_mobile",
          "required": true
        }
      ]
    }
  }
}
```

### **Running on Different Apps:**

```python
# Same testcase, different app
execute_testcase(
    testcase_name="TC_PLAY_01_BasicPlayback",
    userinterface_name="netflix_mobile"  # Netflix
)

execute_testcase(
    testcase_name="TC_PLAY_01_BasicPlayback",
    userinterface_name="youtube_mobile"  # YouTube
)

execute_testcase(
    testcase_name="TC_PLAY_01_BasicPlayback",
    userinterface_name="hulu_web"  # Hulu
)
```

**Key Point:** Same testcase name, same graph, different userinterface → Different navigation paths!

---

## 🎓 Summary

### **Naming Formula:**
```
TC_<CATEGORY>_<NUMBER>_<CamelCaseAction>

Where:
- CATEGORY matches requirements categories (APP, AUTH, NAV, PLAY, etc.)
- NUMBER is zero-padded 2-digit (01-99)
- CamelCase describes the action being tested
- Description is generic and reusable
```

### **Reusability Principle:**
- **Testcases are generic** (same graph works on multiple apps)
- **UserInterface model** provides app-specific navigation
- **Generic node labels** (home, search, player) map to app screens
- **Only 10%** of testcases should be app-specific

### **Category Alignment:**
- Testcase categories match requirement categories
- Easy traceability: TC_PLAY_XX → PLAY_PXX
- Consistent organization across system

---

**Version**: 1.0.0  
**Created**: 2025-11-10  
**Aligned with**: requirements.md v2.0.0

