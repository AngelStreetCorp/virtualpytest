"""Constants for the device-farm feature: env keys, provider endpoints, defaults.

Every provider-specific string lives here or in the provider module, never in a
controller. **The URL templates below are taken from each vendor's public docs and
have NOT been exercised against a live account** (TASK-20 §7 blocker 1) — when the
first real session runs, a wrong host or path shows up here and nowhere else.
"""

# ---- env keys (per device slot, DEVICE{i}_...) -------------------------------
# Reuses the existing APPIUM_* keys where the meaning is unchanged, so a farm slot
# reads like the local Appium slot it replaces.
ENV_PROVIDER = 'FARM_PROVIDER'            # saucelabs | browserstack | lambdatest
ENV_USER = 'FARM_USER'
ENV_KEY = 'FARM_KEY'                      # access key — never logged, never in a URL
ENV_REGION = 'FARM_REGION'                # provider datacenter, e.g. us-west-1
ENV_DEVICE_QUERY = 'FARM_DEVICE'          # device name or pattern, e.g. "Google Pixel 8"
ENV_PLATFORM_VERSION = 'FARM_OS_VERSION'  # e.g. "14"
ENV_APP = 'FARM_APP'                      # provider app reference (storage:… / bs:// / lt://)
ENV_BUILD = 'FARM_BUILD'                  # build label grouping sessions in the farm UI
ENV_IDLE_TIMEOUT = 'FARM_IDLE_TIMEOUT'    # seconds the farm keeps an idle session
ENV_MAX_DURATION = 'FARM_MAX_DURATION'    # seconds before the farm kills the session
ENV_SCREENSHOT_FPS = 'FARM_SCREENSHOT_FPS'
ENV_PLATFORM_NAME = 'APPIUM_PLATFORM_NAME'  # iOS | Android (shared with local Appium)

# Host-wide cap on concurrent farm sessions; a farm account's parallel-session limit
# is contractual, so this defaults low and is raised deliberately.
ENV_HOST_MAX_SESSIONS = 'FARM_MAX_SESSIONS'
DEFAULT_MAX_SESSIONS = 2

# ---- defaults ---------------------------------------------------------------
DEFAULT_PROVIDER = 'saucelabs'
DEFAULT_IDLE_TIMEOUT = 180       # seconds; farm-side idle reaper
DEFAULT_MAX_DURATION = 1800      # seconds; 30 min, the usual farm default
DEFAULT_SCREENSHOT_FPS = 1.0     # every screenshot is a metered round-trip
MAX_SCREENSHOT_FPS = 5.0
# Reconnect margin: treat a session as expired this many seconds before the farm
# would, so a command never lands on a session the farm just reaped.
SESSION_EXPIRY_MARGIN = 15

# ---- capability keys --------------------------------------------------------
# W3C requires an extension capability to carry a vendor prefix; 'appium:' is
# Appium's own. Anything unprefixed below is a standard capability.
CAP_PLATFORM_NAME = 'platformName'
CAP_AUTOMATION_NAME = 'appium:automationName'
CAP_DEVICE_NAME = 'appium:deviceName'
CAP_PLATFORM_VERSION = 'appium:platformVersion'
CAP_APP = 'appium:app'
CAP_NEW_COMMAND_TIMEOUT = 'appium:newCommandTimeout'

AUTOMATION_ANDROID = 'UiAutomator2'
AUTOMATION_IOS = 'XCUITest'

# Capability keys whose value is a credential. Anything listed here is masked by
# lib/config.py::redact() before a caps dict reaches a log line.
SECRET_CAP_KEYS = frozenset({
    'accessKey', 'access_key', 'accesskey',
    'userName', 'username', 'user',
    'key', 'password', 'token',
})

# ---- provider endpoint templates -------------------------------------------
SAUCE_HUB_URL = 'https://ondemand.{region}.saucelabs.com/wd/hub'
SAUCE_API_URL = 'https://api.{region}.saucelabs.com'
SAUCE_APP_URL = 'https://app.{region}.saucelabs.com/tests/{session_id}'
SAUCE_DEFAULT_REGION = 'us-west-1'
SAUCE_OPTIONS_KEY = 'sauce:options'
SAUCE_APP_PREFIX = 'storage:'
# Sauce refuses a session on Android 14+ unless the job asks for Appium 2 explicitly:
# "Android 14 and above must be used with the W3C protocol and Appium 2" (confirmed
# against a live account 2026-09-17). 'latest' is Sauce's own recommendation for new
# jobs; pin a version here if a farm-side Appium bump ever breaks a run.
SAUCE_APPIUM_VERSION = 'latest'

BROWSERSTACK_HUB_URL = 'https://hub-cloud.browserstack.com/wd/hub'
BROWSERSTACK_API_URL = 'https://api-cloud.browserstack.com/app-automate'
BROWSERSTACK_OPTIONS_KEY = 'bstack:options'
BROWSERSTACK_APP_PREFIX = 'bs://'

LAMBDATEST_HUB_URL = 'https://mobile-hub.lambdatest.com/wd/hub'
LAMBDATEST_API_URL = 'https://manual-api.lambdatest.com/app/uploadFramework'
LAMBDATEST_OPTIONS_KEY = 'lt:options'
LAMBDATEST_APP_PREFIX = 'lt://'

HTTP_TIMEOUT = 30

# An app upload is a multi-megabyte POST, not a REST round-trip: a 36 MB APK on a
# normal connection overran HTTP_TIMEOUT and died as 'write operation timed out'.
UPLOAD_TIMEOUT = 600
