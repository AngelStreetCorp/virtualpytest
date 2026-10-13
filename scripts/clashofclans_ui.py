#!/usr/bin/env python3
"""
Build the Clash of Clans user interface (TASK-81 §81.1) as .vptree bundles.

The CoC farm bot targets the S21 FE (vpt-pi1 / device1) over HDMI capture
(1080x2340 phone, 1280x720 capture stream). The §81.1.1 install sub-tree
opens the Play Store with `open_url(market://details?id=com.supercell.clashofclans,
com.android.vending)`, OCR-taps "Install", waits for "Open", and lands on the
village. When CoC is already installed, entry goes straight through `launch_app`.

Two UIs are built; only the android-mobile one is real today:

  clashofclans-android-mobile   S21 FE over HDMI (the §81.1 target)
  clashofclans-web              web stub (reserved for §81.2 / future work)

Tree shape (android-mobile):

  entry ─┬─ launch ──────────────→ home
         └─ install_game ─→ install ──────────→ home

  home ─┬─ collect (taps gold mine, elixir collector, dark elixir drill)
        ├─ train    (opens army, queues troops)
        ├─ donate   (clan chat: tap request row, donate per slot)
        ├─ clan_capital (collects the clan-capital weekly chest)
        ├─ daily    (collects the daily reward)
        ├─ settings (guard reads account state)
        ├─ clan     (clan page)
        ├─ attack   (DISABLED: disabled_by: attack_opt_in)        # §R1, §Out-of-scope
        ├─ shop     (DISABLED: disabled_by: shop_enabled)         # §R3 real-money
        └─ builder  (DISABLED: disabled_by: builder_enabled)      # §Out-of-scope

  Back edges go from every screen back to home (back=True adds the reverse set).

Tap strategy: `click_element` with visible button text wherever possible
(GAME_BOTS.md rule 3). `tap_coordinates` is only used on the village where
collectors / army / clan / settings have no text label; coords are placeholders
until the first live run calibrates them per building.

After bundling, import with `POST /server/userinterface/import (file=<bundle>,
name=<name>)`.

Usage:
  python scripts/clashofclans_ui.py --out /tmp/coc_bundles
"""

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared.src.lib.game.vptree import edge, manifest, node, write_bundle  # noqa: E402

PACKAGE = "com.supercell.clashofclans"
PLAY_STORE_URL = f"market://details?id={PACKAGE}"
PLAY_STORE_PACKAGE = "com.android.vending"

# Capture stream (HDMI) is 1280x720; the S21 FE's INTERNAL display is 2340x1080
# in landscape (rotation=1, `mOverrideDisplayInfo` `real 2340 x 1080`).
# `adb shell input tap` events fire on the internal display, so the vptree
# coords are in landscape 2340x1080 phone space.
# The earlier portrait (`PHONE_W=1080, PHONE_H=2340`) defaults fired off-screen
# taps on every cycle — every `y` was >1080, hitting nothing on the landscape
# device. This pin switches to landscape and uses live-calibrated building
# positions sampled on 2026-10-11.
PHONE_W, PHONE_H = 2340, 1080

# Tap positions in landscape phone coordinates (2340x1080). Calibrated on a
# live S21 FE tutorial village, measured on the 2340x1080 device screencap:
#   gold mine (left of village, small mine with coin) at ~(1240, 540)
#   elixir collector (well to the right of the mine) at ~(1290, 410)
#   town hall (large building, lower centre) at ~(1170, 660)
#   top-left settings gear at ~(95, 95)
GOLD_MINE_TAP = (1240, 540)
ELIXIR_COLLECTOR_TAP = (1290, 410)
DARK_ELIXIR_DRILL_TAP = (780, 410)         # not built on a tutorial account; kept for TH4+
ARMY_BUTTON_TAP = (150, 1010)              # bottom-left; the tutorial hides this initially
CLAN_BUTTON_TAP = (540, 1020)              # bottom-centre; tutorial hides this
SETTINGS_BUTTON_TAP = (95, 95)              # top-left gear
ATTACK_BUTTON_TAP = (540, 540)             # centre of the village; DISABLED by attack_opt_in

# Capture-stream OCR areas (1280x720). Live.
CAPTURE_HOME_AREA = {"x": 480, "y": 60, "width": 320, "height": 120}
CAPTURE_INSTALL_AREA = {"x": 540, "y": 540, "width": 200, "height": 120}
CAPTURE_COLLECT_AREA = {"x": 400, "y": 300, "width": 480, "height": 120}


def disable_edge(e, by):
    """Add disabled_by to the edge's data dict for the guard rail.

    Post-process helper: the vptree.edge() helper does not expose `disabled_by`,
    so we mutate the returned dict. The runner / tactics use this marker as a
    human-visible hint and to refuse the edge at runtime when the gating config
    is False (attack / shop / builder are all off by default per §R3 and
    §Out-of-scope).
    """
    e["data"]["disabled_by"] = by
    return e


def mobile_actions():
    return {
        # entry → launch (CoC is already installed; the typical case after the first run)
        "enter": [
            {"command": "launch_app", "action_type": "remote",
             "params": {"package": PACKAGE, "wait_time": 4000}},
        ],
        # entry → install_game (Play Store detail page)
        "install_open": [
            {"command": "open_url", "action_type": "remote",
             "params": {"url": PLAY_STORE_URL, "package": PLAY_STORE_PACKAGE, "wait_time": 4000}},
        ],
        # install_game → install (the "Install" button is up; brief says coords are
        # known-bad until first run, so click by visible button text)
        "install_tap_install": [
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Install", "wait_time": 15000}},
        ],
        # install → home (Play Store has flipped "Install" → "Open"; tap it, then
        # launch the app explicitly so the script recovers if Play Store lingers)
        "install_complete": [
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Open", "wait_time": 2000}},
            {"command": "launch_app", "action_type": "remote",
             "params": {"package": PACKAGE, "wait_time": 4000}},
        ],
        # launch → home (no action needed; home verification waits for "Village")
        "home_settle": [
            {"command": "dump_elements", "action_type": "remote", "params": {"wait_time": 1000}},
        ],
        # home → collect: tap each ready-to-collect icon. The popup that appears
        # has a "Collect" button which we tap via click_element (text). Coords
        # are placeholders; first run should refine per building position.
        "collect": [
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": GOLD_MINE_TAP[0], "y": GOLD_MINE_TAP[1], "wait_time": 1500}},
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Collect", "wait_time": 1500}},
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": ELIXIR_COLLECTOR_TAP[0], "y": ELIXIR_COLLECTOR_TAP[1], "wait_time": 1500}},
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Collect", "wait_time": 1500}},
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": DARK_ELIXIR_DRILL_TAP[0], "y": DARK_ELIXIR_DRILL_TAP[1], "wait_time": 1500}},
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Collect", "wait_time": 1500}},
        ],
        # home → train: open army overlay, queue troops. Coords are placeholders.
        "train": [
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": ARMY_BUTTON_TAP[0], "y": ARMY_BUTTON_TAP[1], "wait_time": 2000}},
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Train", "wait_time": 2000}},
        ],
        # home → donate: open clan chat, tap request row, tap donate per available slot.
        "donate": [
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": CLAN_BUTTON_TAP[0], "y": CLAN_BUTTON_TAP[1], "wait_time": 2000}},
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Donate", "wait_time": 1000}},
        ],
        # home → clan_capital: navigate to clan capital, collect the weekly chest.
        "clan_capital": [
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Capital", "wait_time": 2000}},
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Collect", "wait_time": 1500}},
        ],
        # home → daily: open the daily reward popup and claim it.
        "daily": [
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Daily", "wait_time": 2000}},
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Claim", "wait_time": 1500}},
        ],
        # home → settings: open the settings panel. The §R5 guard reads account
        # state from here on every cycle.
        "settings": [
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": SETTINGS_BUTTON_TAP[0], "y": SETTINGS_BUTTON_TAP[1], "wait_time": 2000}},
        ],
        # home → clan: open the clan page (used by donate as an entry point).
        "clan": [
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": CLAN_BUTTON_TAP[0], "y": CLAN_BUTTON_TAP[1], "wait_time": 2000}},
        ],
        # DISABLED edges — actions are placeholders only; the runner never picks
        # them. See the brief: §R1 (attack), §R3 (shop / gems / pass / offer),
        # §Out-of-scope (Builder Base). Gating config defaults are off; the
        # --attack_opt_in flag exists for ad-hoc non-farming testing only.
        "attack": [
            {"command": "tap_coordinates", "action_type": "remote",
             "params": {"x": ATTACK_BUTTON_TAP[0], "y": ATTACK_BUTTON_TAP[1], "wait_time": 1000}},
        ],
        "shop": [
            # Even the "free" claim is gated by shop_enabled (default false).
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Shop", "wait_time": 2000}},
        ],
        "builder": [
            # Builder Base — same detection story as Attack, plus it adds no
            # resources to the home village.
            {"command": "click_element", "action_type": "remote",
             "params": {"element_id": "Builder", "wait_time": 2000}},
        ],
        # Verifications (one per screen node).
        "home_check": {"verification_type": "text", "command": "waitForTextToAppear",
                       "params": {"text": "Village", "timeout": 30000, "area": CAPTURE_HOME_AREA}},
        "install_game_check": {"verification_type": "text", "command": "waitForTextToAppear",
                               "params": {"text": "Install", "timeout": 15000, "area": CAPTURE_INSTALL_AREA}},
        "install_check": {"verification_type": "text", "command": "waitForTextToAppear",
                          "params": {"text": "Open", "timeout": 120000, "area": CAPTURE_INSTALL_AREA}},
        "collect_check": {"verification_type": "text", "command": "waitForTextToAppear",
                          "params": {"text": "Collect", "timeout": 10000, "area": CAPTURE_COLLECT_AREA}},
        "settings_check": {"verification_type": "text", "command": "waitForTextToAppear",
                           "params": {"text": "Settings", "timeout": 10000, "area": CAPTURE_HOME_AREA}},
    }


def web_actions():
    """Stub web actions for clashofclans-web. Reserved for future work (§81.2+).

    Today the tree builds with no actions so the import path can be exercised
    without a real browser target. Same node / edge shape as android-mobile so
    the structure stays uniform when the web variant lands.
    """
    no_actions = []
    web_verif = {"verification_type": "text", "command": "waitForTextToAppear",
                 "params": {"text": "Village", "timeout": 5000}}
    return {
        "enter": list(no_actions), "install_open": list(no_actions),
        "install_tap_install": list(no_actions), "install_complete": list(no_actions),
        "home_settle": list(no_actions), "collect": list(no_actions),
        "train": list(no_actions), "donate": list(no_actions),
        "clan_capital": list(no_actions), "daily": list(no_actions),
        "settings": list(no_actions), "clan": list(no_actions),
        "attack": list(no_actions), "shop": list(no_actions),
        "builder": list(no_actions),
        "home_check": web_verif,
        "install_game_check": web_verif, "install_check": web_verif,
        "collect_check": web_verif, "settings_check": web_verif,
    }


def build_manifest(name, models, spec):
    tree_id = str(uuid.uuid4())
    nodes = [
        node(tree_id, "entry-node", "Entry", "entry", 0, 0),
        # Top-level entry children: launch (already installed) and install_game.
        node(tree_id, "launch", "launch", "action", -200, 200, parent="entry-node"),
        node(tree_id, "install_game", "install_game", "action", 200, 200, parent="entry-node",
             verifications=[spec["install_game_check"]]),
        node(tree_id, "install", "install", "action", 400, 400, parent="install_game",
             verifications=[spec["install_check"]]),
        node(tree_id, "home", "home", "screen", 0, 400, [spec["home_check"]]),
        # Home children: every action from §81.1.1 plus the disabled attack/shop/builder.
        node(tree_id, "collect", "collect", "action", -800, 600, parent="home"),
        node(tree_id, "train", "train", "action", -600, 600, parent="home"),
        node(tree_id, "donate", "donate", "action", -400, 600, parent="home"),
        node(tree_id, "clan_capital", "clan_capital", "action", -200, 600, parent="home"),
        node(tree_id, "daily", "daily", "action", 0, 600, parent="home"),
        node(tree_id, "settings", "settings", "action", 200, 600, parent="home",
             verifications=[spec["settings_check"]]),
        node(tree_id, "clan", "clan", "action", 400, 600, parent="home"),
        # Disabled children: attack (R5), shop (R3), builder (out-of-scope).
        node(tree_id, "attack", "attack", "action", -400, 800, parent="home"),
        node(tree_id, "shop", "shop", "action", 0, 800, parent="home"),
        node(tree_id, "builder", "builder", "action", 400, 800, parent="home"),
    ]
    edges = [
        # entry → launch (already installed) and entry → install_game (not installed)
        edge(tree_id, "entry-node", "launch", spec["enter"], wait=1000),
        edge(tree_id, "entry-node", "install_game", spec["install_open"], wait=1000),
        # launch → home; install_game → install → home (install sub-tree)
        edge(tree_id, "launch", "home", spec["home_settle"], wait=0, back=True),
        edge(tree_id, "install_game", "install", spec["install_tap_install"], wait=0, back=True),
        edge(tree_id, "install", "home", spec["install_complete"], wait=0, back=True),
        # Home action children. back=True adds an empty reverse action set so
        # "every screen back to home" is encoded as a no-op edge.
        edge(tree_id, "home", "collect", spec["collect"], wait=0, back=True),
        edge(tree_id, "home", "train", spec["train"], wait=0, back=True),
        edge(tree_id, "home", "donate", spec["donate"], wait=0, back=True),
        edge(tree_id, "home", "clan_capital", spec["clan_capital"], wait=0, back=True),
        edge(tree_id, "home", "daily", spec["daily"], wait=0, back=True),
        edge(tree_id, "home", "settings", spec["settings"], wait=0, back=True),
        edge(tree_id, "home", "clan", spec["clan"], wait=0, back=True),
        # Disabled edges: defined in the tree, marked disabled_by in the data
        # dict. The runner / tactics never call navigate(attack/shop/builder)
        # unless the gating config flips to True. Per §R3 and §Out-of-scope.
        disable_edge(edge(tree_id, "home", "attack", spec["attack"], wait=0, back=True), "attack_opt_in"),
        disable_edge(edge(tree_id, "home", "shop", spec["shop"], wait=0, back=True), "shop_enabled"),
        disable_edge(edge(tree_id, "home", "builder", spec["builder"], wait=0, back=True), "builder_enabled"),
    ]
    return manifest(name, models, tree_id, nodes, edges)


UIS = {
    # v1 — S21 FE on vpt-pi1 over HDMI. Landscape 2340x1080 phone / 1280x720
    # capture. Coords calibrated on 2026-10-11 against a real tutorial
    # village; the earlier portrait (1080x2340) defaults fired off-screen
    # taps and the bot never actually advanced the tutorial.
    "clashofclans-android-mobile": (["android_mobile"], mobile_actions),
    # v1.1 stub — web variant reserved for §81.2 / future work.
    "clashofclans-web": (["web"], web_actions),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="Output directory for the .vptree bundles")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for name, (models, spec_fn) in UIS.items():
        path = os.path.join(args.out, f"{name}.vptree")
        write_bundle(path, build_manifest(name, models, spec_fn()))
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()