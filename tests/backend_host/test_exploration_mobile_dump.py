"""
tests/backend_host/test_exploration_mobile_dump.py — what AI exploration proposes from an Android dump.

The host dumps with `uiautomator dump --windows`, which returns every window on screen: the
status bar and navigation bar (com.android.systemui) and Samsung's edge panel (launcher) sit
next to the app. Before TASK-40 the analyzer read them all and proposed `Recents`, `Back`,
the clock and `Four bars of phone signal` as screens of Google TV, plus the feed's tiles.

The dump below is a trimmed copy of the S21x's on Google TV's Home tab (2026-10-02).
"""
import pytest

adb_utils = pytest.importorskip('backend_host.src.lib.utils.adb_utils')
screen_analyzer = pytest.importorskip('backend_host.src.services.ai_exploration.screen_analyzer')

GOOGLE_TV_HOME = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<displays><display id="0">
<window index="0" title="Navigation bar" focused="false" type="TYPE_SYSTEM"><hierarchy rotation="0">
 <node class="android.widget.FrameLayout" package="com.android.systemui" resource-id="com.android.systemui:id/navigation_bar_frame" text="" content-desc="" clickable="false" focusable="false" enabled="true" bounds="[0,2196][1080,2340]">
  <node class="android.widget.ImageView" package="com.android.systemui" resource-id="com.android.systemui:id/recent_apps" text="" content-desc="Recents" clickable="true" focusable="true" enabled="true" bounds="[118,2196][357,2340]" />
  <node class="android.widget.ImageView" package="com.android.systemui" resource-id="com.android.systemui:id/back" text="" content-desc="Back" clickable="true" focusable="true" enabled="true" bounds="[723,2196][962,2340]" />
 </node>
</hierarchy></window>
<window index="1" title="" focused="false" type="TYPE_SYSTEM"><hierarchy rotation="0">
 <node class="android.widget.RelativeLayout" package="com.sec.android.app.launcher" resource-id="com.sec.android.app.launcher:id/trigger_layout_container" text="" content-desc="Edge panels" clickable="false" focusable="false" enabled="true" bounds="[1013,448][1080,790]" />
</hierarchy></window>
<window index="2" title="" focused="false" type="TYPE_SYSTEM"><hierarchy rotation="0">
 <node class="android.widget.FrameLayout" package="com.android.systemui" resource-id="com.android.systemui:id/status_bar" text="" content-desc="" clickable="false" focusable="false" enabled="true" bounds="[0,0][1080,99]">
  <node class="android.widget.TextView" package="com.android.systemui" resource-id="com.android.systemui:id/clock" text="08:23" content-desc="08:23" clickable="false" focusable="false" enabled="true" bounds="[67,28][167,99]" />
  <node class="android.widget.FrameLayout" package="com.android.systemui" resource-id="com.android.systemui:id/mobile_combo" text="" content-desc="Four bars of phone signal" clickable="false" focusable="false" enabled="true" bounds="[852,44][893,83]" />
 </node>
</hierarchy></window>
<window index="3" title="Google TV" focused="true" type="TYPE_APPLICATION"><hierarchy rotation="0">
 <node class="android.view.ViewGroup" package="com.google.android.videos" resource-id="com.google.android.videos:id/page_container" text="" content-desc="" clickable="false" focusable="false" enabled="true" bounds="[0,0][1080,2340]">
  <node class="android.widget.ScrollView" package="com.google.android.videos" resource-id="" text="" content-desc="" clickable="false" focusable="true" enabled="true" bounds="[0,0][1080,1999]">
   <node class="androidx.viewpager.widget.ViewPager" package="com.google.android.videos" resource-id="com.google.android.videos:id/destination_view_pager" text="" content-desc="" clickable="false" focusable="true" enabled="true" bounds="[0,0][1080,1999]">
    <node class="androidx.recyclerview.widget.RecyclerView" package="com.google.android.videos" resource-id="com.google.android.videos:id/recycler_view" text="" content-desc="" clickable="false" focusable="true" enabled="true" bounds="[0,0][1080,1999]">
     <node class="android.widget.FrameLayout" package="com.google.android.videos" resource-id="com.google.android.videos:id/featured_carousel_card_component" text="" content-desc="" clickable="true" focusable="true" enabled="true" bounds="[0,312][1080,1973]">
      <node class="android.widget.TextView" package="com.google.android.videos" resource-id="com.google.android.videos:id/title" text="Dune: Part Two" content-desc="" clickable="false" focusable="false" enabled="true" bounds="[48,1081][1032,1432]" />
      <node class="android.widget.Button" package="com.google.android.videos" resource-id="com.google.android.videos:id/action_button" text="Watch now" content-desc="" clickable="true" focusable="true" enabled="true" bounds="[48,1622][440,1793]" />
     </node>
     <node class="android.widget.LinearLayout" package="com.google.android.videos" resource-id="com.google.android.videos:id/channel_header_view" text="" content-desc="" clickable="true" focusable="true" enabled="true" bounds="[0,1847][1080,1991]">
      <node class="android.widget.TextView" package="com.google.android.videos" resource-id="com.google.android.videos:id/channel_header_title" text="Top picks for you" content-desc="" clickable="false" focusable="false" enabled="true" bounds="[48,1881][816,1956]" />
     </node>
    </node>
   </node>
   <node class="android.view.ViewGroup" package="com.google.android.videos" resource-id="" text="" content-desc="Google TV" clickable="false" focusable="false" enabled="true" bounds="[72,145][360,220]" />
   <node class="android.widget.ImageButton" package="com.google.android.videos" resource-id="com.google.android.videos:id/search_button" text="" content-desc="Search" clickable="true" focusable="true" enabled="true" bounds="[771,123][927,243]" />
   <node class="android.widget.FrameLayout" package="com.google.android.videos" resource-id="com.google.android.videos:id/selected_account_disc" text="" content-desc="Signed in as Test User test@example.com&#10;Account and settings." clickable="true" focusable="true" enabled="true" bounds="[927,123][1080,267]" />
  </node>
  <node class="android.view.ViewGroup" package="com.google.android.videos" resource-id="" text="" content-desc="" clickable="false" focusable="false" enabled="true" bounds="[0,1999][1080,2196]">
   <node class="android.widget.FrameLayout" package="com.google.android.videos" resource-id="" text="" content-desc="Home" clickable="false" focusable="true" enabled="true" selected="true" bounds="[0,1999][270,2196]" />
   <node class="android.widget.FrameLayout" package="com.google.android.videos" resource-id="" text="" content-desc="Shop" clickable="true" focusable="true" enabled="true" bounds="[270,1999][540,2196]" />
   <node class="android.widget.FrameLayout" package="com.google.android.videos" resource-id="" text="" content-desc="Library" clickable="true" focusable="true" enabled="true" bounds="[540,1999][810,2196]" />
   <node class="android.widget.FrameLayout" package="com.google.android.videos" resource-id="" text="" content-desc="Watchlist" clickable="true" focusable="true" enabled="true" bounds="[810,1999][1080,2196]" />
  </node>
 </node>
</hierarchy></window>
</display></displays>"""


def proposals(xml):
    elements = adb_utils.ADBUtils()._parse_ui_elements(xml)
    analyzer = screen_analyzer.ScreenAnalyzer.__new__(screen_analyzer.ScreenAnalyzer)
    return analyzer._extract_interactive_elements_mobile(elements)


def test_parser_records_window_list_and_clickable_ancestry():
    elements = {e.content_desc if e.content_desc != '<no content-desc>' else e.text: e
                for e in adb_utils.ADBUtils()._parse_ui_elements(GOOGLE_TV_HOME)}
    assert not elements['Recents'].in_focused_window
    assert elements['Recents'].package == 'com.android.systemui'
    assert elements['Shop'].in_focused_window and not elements['Shop'].in_list
    assert elements['Dune: Part Two'].in_list and elements['Dune: Part Two'].under_clickable


def test_google_tv_home_proposes_the_app_navigation_only():
    assert proposals(GOOGLE_TV_HOME) == ['Search', 'Shop', 'Library', 'Watchlist']


def test_plain_dump_without_windows_is_the_focused_app():
    # `uiautomator dump` without --windows has no <window> wrapper: it is the app window only.
    app_only = GOOGLE_TV_HOME.split('<window index="3"', 1)[1].split('>', 1)[1].split('</window>')[0]
    xml = "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>" + app_only
    assert proposals(xml) == ['Search', 'Shop', 'Library', 'Watchlist']


def test_a_screen_whose_navigation_is_a_list_falls_back_to_its_rows():
    # Settings' first level is a RecyclerView of rows, with no tab bar around it.
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
 <node class="androidx.recyclerview.widget.RecyclerView" package="com.android.settings" resource-id="com.android.settings:id/recycler_view" text="" content-desc="" clickable="false" focusable="true" enabled="true" bounds="[0,300][1080,2196]">
  <node class="android.widget.LinearLayout" package="com.android.settings" resource-id="" text="" content-desc="" clickable="true" focusable="true" enabled="true" bounds="[0,300][1080,500]">
   <node class="android.widget.TextView" package="com.android.settings" resource-id="android:id/title" text="Connections" content-desc="" clickable="false" focusable="false" enabled="true" bounds="[200,320][900,380]" />
  </node>
  <node class="android.widget.LinearLayout" package="com.android.settings" resource-id="" text="" content-desc="" clickable="true" focusable="true" enabled="true" bounds="[0,500][1080,700]">
   <node class="android.widget.TextView" package="com.android.settings" resource-id="android:id/title" text="Sounds and vibration" content-desc="" clickable="false" focusable="false" enabled="true" bounds="[200,520][900,580]" />
  </node>
 </node>
</hierarchy>"""
    assert proposals(xml) == ['Connections', 'Sounds and vibration']


def test_a_search_for_home_taps_the_app_tab_not_android_home():
    # The app's "Home" tab and Android's navigation-bar Home button tie on every other
    # criterion, and the navigation bar comes first in a --windows dump.
    back = 'bounds="[723,2196][962,2340]" />'
    xml = GOOGLE_TV_HOME.replace(back, back + (
        '\n  <node class="android.widget.ImageView" package="com.android.systemui" '
        'resource-id="com.android.systemui:id/home" text="" content-desc="Home" clickable="true" '
        'focusable="true" enabled="true" bounds="[420,2196][659,2340]" />'), 1)
    utils = adb_utils.ADBUtils()
    utils.dump_elements = lambda device_id, reason='dump': (True, utils._parse_ui_elements(xml), '')
    found, element, _ = utils.check_element_exists('phone', 'Home')
    assert found and element.bounds == '[0,1999][270,2196]'
    found, element, _ = utils.check_element_exists('phone', 'Back')
    assert found and element.bounds == '[723,2196][962,2340]'
