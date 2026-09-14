#!/usr/bin/env python3
"""Shared JavaScript snippets for local-debug Playwright web scripts."""

# Native, site-agnostic playback probe. Picks the video that is actually
# playing (largest active element, so it survives feed pages with multiple
# <video> nodes) and reports the decoded-frame counter from
# getVideoPlaybackQuality() — the ground truth for "frames are being
# presented", immune to looping/short clips and live streams where the
# currentTime delta lies. Falls back to webkitDecodedFrameCount on WebKit.
WEB_JS_VIDEO_STATUS = r"""
(() => {
  const vids = Array.from(document.querySelectorAll('video'));
  if (!vids.length) return { found: false };
  const score = (v) => {
    let area = 0;
    try { const r = v.getClientRects(); if (r.length) area = r[0].width * r[0].height; } catch (_) {}
    const active = (!v.paused && !v.ended && v.readyState >= 2) ? 1e12 : 0;
    return active + area;
  };
  const v = vids.slice().sort((a, b) => score(b) - score(a))[0];
  let totalVideoFrames = null, droppedVideoFrames = null;
  try {
    if (typeof v.getVideoPlaybackQuality === 'function') {
      const q = v.getVideoPlaybackQuality();
      totalVideoFrames = q.totalVideoFrames;
      droppedVideoFrames = q.droppedVideoFrames;
    } else if (typeof v.webkitDecodedFrameCount === 'number') {
      totalVideoFrames = v.webkitDecodedFrameCount;
    }
  } catch (_) {}
  let buffered = 0;
  try { buffered = v.buffered.length ? v.buffered.end(v.buffered.length - 1) : 0; } catch (_) {}
  return {
    found: true,
    videoCount: vids.length,
    currentTime: v.currentTime,
    duration: v.duration,
    paused: v.paused,
    ended: v.ended,
    readyState: v.readyState,
    networkState: v.networkState,
    buffered: buffered,
    totalVideoFrames: totalVideoFrames,
    droppedVideoFrames: droppedVideoFrames,
    error: v.error ? v.error.code : null,
    src: v.currentSrc || v.src || ''
  };
})()
"""

# First-frame / startup-buffering probe. Install this as early as possible after
# the video page has navigated (it must run on the freshly-navigated document so
# performance.now() is measured from that navigation's timeOrigin). It records
# the moment the FIRST video frame is actually presented to screen, using the
# browser's own signal — requestVideoFrameCallback — when available, and falling
# back to the 'playing'/'timeupdate' media events otherwise.
#
# firstFrameMs is performance.now() at that first frame == milliseconds from the
# video-page navigation to the first painted frame == the real startup/buffering
# time, measured entirely in the page and therefore immune to the Python-side
# ad-handling sleeps that used to dominate the old wall-clock metric.
#
# Semantics: "first frame of whatever plays" (an ad counts) — the probe does not
# try to distinguish ad vs content. If a video is already presenting frames when
# the probe installs (we arrived late), it records the install time as a floor.
WEB_JS_INSTALL_FIRST_FRAME_PROBE = r"""
(() => {
  if (window.__vptFF) return { installed: 'already', firstFrameMs: window.__vptFF.firstFrameMs };
  const st = { firstFrameMs: null, method: null, mediaTime: null, installedAtMs: Math.round(performance.now()) };
  window.__vptFF = st;
  const area = (v) => { try { const r = v.getClientRects(); return r.length ? r[0].width * r[0].height : 0; } catch (_) { return 0; } };
  const pick = () => {
    const vids = Array.from(document.querySelectorAll('video'));
    if (!vids.length) return null;
    return vids.sort((a, b) => ((!b.paused ? 1e12 : 0) + area(b)) - ((!a.paused ? 1e12 : 0) + area(a)))[0];
  };
  const mark = (method, mediaTime) => {
    if (st.firstFrameMs != null) return;
    st.firstFrameMs = Math.round(performance.now());
    st.method = method;
    if (typeof mediaTime === 'number') st.mediaTime = mediaTime;
  };
  const attach = (v) => {
    if (!v || v.__vptFFa) return;
    v.__vptFFa = true;
    if (typeof v.requestVideoFrameCallback === 'function') {
      try { v.requestVideoFrameCallback((now, md) => mark('rvfc', md && md.mediaTime)); } catch (_) {}
    }
    v.addEventListener('playing', () => { if (v.currentTime > 0 && v.readyState >= 3) mark('playing', v.currentTime); });
    v.addEventListener('timeupdate', () => { if (v.currentTime > 0) mark('timeupdate', v.currentTime); });
  };
  const v0 = pick();
  if (v0) {
    attach(v0);
    if (!v0.paused && v0.readyState >= 3 && v0.currentTime > 0) mark('already-playing', v0.currentTime);
  }
  try {
    const obs = new MutationObserver(() => { const v = pick(); if (v) attach(v); });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  } catch (_) {}
  return { installed: true, hasVideo: !!v0 };
})()
"""

WEB_JS_GET_FIRST_FRAME = r"""
(() => {
  const s = window.__vptFF;
  if (!s) return { available: false };
  return {
    available: true,
    firstFrameMs: s.firstFrameMs,
    method: s.method,
    mediaTime: s.mediaTime,
    installedAtMs: s.installedAtMs,
  };
})()
"""

# YouTube's anti-bot interstitial. Seen from the Hetzner CI runner (datacenter IP, fresh
# profile) on 2026-09-08: the watch page renders only "Sign in to confirm you're not a bot",
# no <video>, so playback checks fail for a reason that has nothing to do with playback.
YOUTUBE_JS_CHECK_BOT_WALL = """
(() => {
    const text = (document.body && document.body.innerText) || '';
    const patterns = [
        /sign in to confirm you.re not a bot/i,
        /confirm you.re not a bot/i,
        /this helps protect our community/i,
        /connectez-vous pour confirmer que vous n.êtes pas un robot/i,
        /melde dich an, um zu bestätigen, dass du kein bot bist/i,
    ];
    for (const re of patterns) {
        const m = text.match(re);
        if (m) return m[0];
    }
    return null;
})()
"""

YOUTUBE_JS_CHECK_CONSENT_MODAL = """
(() => {
    const selectors = [
        'ytd-consent-bump-v2-lightbox',
        '[aria-label="Before you continue to YouTube"]',
        'tp-yt-paper-dialog[aria-label*="consent"]',
        '#dialog[aria-label*="Before you continue"]',
    ];
    for (const sel of selectors) {
        if (document.querySelector(sel)) return sel;
    }
    return null;
})()
"""

YOUTUBE_JS_DISMISS_CONSENT_MODAL = """
(() => {
    const patterns = [
        /accept all/i,
        /i agree/i,
        /agree to all/i,
        /accept/i,
        /akzeptieren/i,
        /zustimmen/i,
        /tout accepter/i,
        /accepter/i,
        /aceptar/i,
        /accetta/i
    ];

    const candidates = [];
    const selectors = 'button, [role="button"], tp-yt-paper-button, input[type="submit"]';

    function walk(root) {
        if (!root) return;
        const found = root.querySelectorAll ? root.querySelectorAll(selectors) : [];
        for (const el of found) candidates.push(el);

        const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
        for (const el of all) {
            if (el.shadowRoot) walk(el.shadowRoot);
        }
    }

    walk(document);

    function getLabel(el) {
        return (
            el.innerText ||
            el.textContent ||
            el.getAttribute('aria-label') ||
            el.value ||
            ''
        ).trim();
    }

    for (const el of candidates) {
        const label = getLabel(el);
        if (!label) continue;
        if (!patterns.some((re) => re.test(label))) continue;
        const visible = el.getClientRects && el.getClientRects().length > 0;
        if (!visible) continue;
        try {
            el.click();
            return { clicked: true, label, scanned: candidates.length };
        } catch (e) {
            // continue trying other candidates
        }
    }

    return { clicked: false, scanned: candidates.length };
})()
"""

YOUTUBE_JS_CHECK_COOKIES = """
(() => {
    const cookies = document.cookie;
    const hasConsent = cookies.includes('CONSENT=') || cookies.includes('SOCS=');
    const cookieList = cookies.split(';').map(c => c.trim()).filter(c =>
        c.startsWith('CONSENT=') || c.startsWith('SOCS=') || c.startsWith('YSC=') || c.startsWith('VISITOR_INFO')
    );
    return {
        hasConsent: hasConsent,
        cookieList: cookieList,
        allCookies: cookies.substring(0, 500)
    };
})()
"""

YOUTUBE_JS_DISMISS_PREMIUM_POPUP = """
(() => {
    const patterns = [
        /^no thanks$/i,
        /^not now$/i,
        /no thanks/i,
        /not now/i,
        /maybe later/i,
        /continue without/i,
    ];
    const selectors = 'button, [role="button"], div[role="button"], tp-yt-paper-button';

    function isVisible(el) {
        if (!el || !el.getClientRects) return false;
        return el.getClientRects().length > 0;
    }

    function isDisabled(el) {
        return !!(
            el.disabled ||
            el.getAttribute('aria-disabled') === 'true'
        );
    }

    function getLabel(el) {
        return (
            el.innerText ||
            el.textContent ||
            el.getAttribute('aria-label') ||
            el.value ||
            ''
        ).trim();
    }

    function clickElement(el) {
        if (!el) return false;
        try {
            el.click();
            return true;
        } catch (_) {}
        try {
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
            return true;
        } catch (_) {}
        return false;
    }

    const buttons = Array.from(document.querySelectorAll(selectors));
    for (const btn of buttons) {
        const label = getLabel(btn);
        if (!label || !patterns.some((re) => re.test(label))) continue;
        if (!isVisible(btn) || isDisabled(btn)) continue;
        if (clickElement(btn)) {
            return { clicked: true, label };
        }
    }

    return { clicked: false, scanned: buttons.length };
})()
"""

YOUTUBE_JS_FIND_SKIP_AD = """
(() => {
    // Find the visible skip-ad button and return its CSS selector. Does NOT click.
    // YouTube's skip button rejects synthesized (untrusted) events, so the caller
    // must perform the click via Playwright's native click_element() (real CDP click).
    const skipSelectors = [
        '.ytp-skip-ad-button',
        '.ytp-ad-skip-button',
        '.ytp-ad-skip-button-modern',
        '.ytp-skip-ad-button__button',
        'button.ytp-skip-ad-button',
        'button[class*="skip-ad"]',
        'button[class*="skipAd"]',
    ];

    function isVisible(el) {
        if (!el || !el.getClientRects) return false;
        if (el.getClientRects().length === 0) return false;
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return true;
    }

    function isDisabled(el) {
        return !!(
            el.disabled ||
            el.getAttribute('aria-disabled') === 'true' ||
            el.classList?.contains('ytp-button-disabled')
        );
    }

    for (const sel of skipSelectors) {
        const btn = document.querySelector(sel);
        if (!btn || !isVisible(btn) || isDisabled(btn)) continue;
        return { found: true, selector: sel };
    }

    return { found: false, selector: null };
})()
"""

YOUTUBE_JS_CHECK_AD = """
(() => {
    const player = document.querySelector('.html5-video-player');
    const adOverlay = document.querySelector('.ytp-ad-player-overlay, .ytp-ad-survey, .video-ads');
    const adBadge = document.querySelector('.ytp-ad-simple-ad-badge, .ytp-ad-text, .ytp-ad-preview-text');
    const adContainer = document.querySelector('.video-ads.ytp-ad-module, .ytp-ad-module');
    const skipBtn = document.querySelector(
        '.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-skip-ad-button__button'
    );
    const adCountdown = document.querySelector(
        '.ytp-ad-duration-remaining, .ytp-ad-text.ytp-ad-preview-text, .ytp-ad-preview-container'
    );
    const playerClassName = player && typeof player.className === 'string' ? player.className : '';
    const adShowing = !!(player && player.classList && player.classList.contains('ad-showing'));
    const playerSuggestsAd = /(^|\\s)ad-showing(\\s|$)|(^|\\s)ad-interrupting(\\s|$)/.test(playerClassName);
    const sponsorTextNodes = Array.from(document.querySelectorAll('span, div'))
        .map((el) => (el.textContent || '').trim())
        .filter((text) => /^sponsored$/i.test(text) || /^advertisement$/i.test(text));
    return {
        adPlaying: !!(adShowing || playerSuggestsAd || adOverlay || adBadge || adContainer || sponsorTextNodes.length),
        skipAvailable: !!(skipBtn && skipBtn.offsetParent !== null),
        countdownText: adCountdown ? adCountdown.textContent.trim() : null,
        playerClassName,
        sponsorTextDetected: sponsorTextNodes.length > 0,
    };
})()
"""

YOUTUBE_JS_VIDEO_STATUS = WEB_JS_VIDEO_STATUS
YOUTUBE_JS_INSTALL_FIRST_FRAME_PROBE = WEB_JS_INSTALL_FIRST_FRAME_PROBE
YOUTUBE_JS_GET_FIRST_FRAME = WEB_JS_GET_FIRST_FRAME

YOUTUBE_JS_FORCE_PLAY = """
(() => {
    const video = document.querySelector('video');
    if (!video) return { found: false, attempted: false };
    try {
        video.muted = true;
        const maybePromise = video.play();
        return {
            found: true,
            attempted: true,
            paused: video.paused,
            currentTime: video.currentTime,
            hasPromise: !!maybePromise
        };
    } catch (e) {
        return { found: true, attempted: true, error: String(e) };
    }
})()
"""

YOUTUBE_JS_ENTER_FULLSCREEN = """
(() => {
    try {
        const video = document.querySelector('video');
        const player = document.querySelector('.html5-video-player');
        const target = player || video;
        if (!target) return { success: false, error: 'No video/player element' };

        function fullscreenState() {
            return !!(
                document.fullscreenElement ||
                player?.classList?.contains('ytp-fullscreen')
            );
        }

        if (fullscreenState()) {
            return { success: true, method: 'already-fullscreen', isFullscreen: true };
        }

        try { target.focus?.(); } catch (_) {}
        try { video?.focus?.(); } catch (_) {}

        try {
            const eventInit = { key: 'f', code: 'KeyF', keyCode: 70, which: 70, bubbles: true };
            target.dispatchEvent(new KeyboardEvent('keydown', eventInit));
            target.dispatchEvent(new KeyboardEvent('keyup', eventInit));
            document.dispatchEvent(new KeyboardEvent('keydown', eventInit));
            document.dispatchEvent(new KeyboardEvent('keyup', eventInit));
        } catch (_) {}
        if (fullscreenState()) {
            return { success: true, method: 'keyboard-f', isFullscreen: true };
        }

        if (target.requestFullscreen) {
            target.requestFullscreen();
            return {
                success: fullscreenState(),
                method: 'requestFullscreen',
                isFullscreen: fullscreenState(),
            };
        }

        return {
            success: false,
            error: 'Fullscreen API not available',
            isFullscreen: fullscreenState(),
        };
    } catch (e) {
        return { success: false, error: String(e) };
    }
})()
"""

FACEBOOK_JS_CLOSE_COOKIES = r"""
(() => {
  const labels = [
    /allow all cookies/i, /allow cookies/i, /accept all/i, /accept/i,
    /zulassen/i, /akzeptieren/i, /tout accepter/i, /accepter/i
  ];
  const els = document.querySelectorAll('button, [role="button"], div[role="button"]');
  let clicks = 0;
  for (const el of els) {
    const txt = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
    if (!txt) continue;
    if (!labels.some((re) => re.test(txt))) continue;
    if (!(el.getClientRects && el.getClientRects().length > 0)) continue;
    try { el.click(); clicks += 1; if (clicks >= 3) break; } catch (_) {}
  }
  return {clicked: clicks};
})()
"""

FACEBOOK_JS_CLOSE_LOGIN_POPUP = r"""
(() => {
  const sels = [
    'div[aria-label="Close"]',
    '[aria-label="Close"]',
    'div[role="button"][aria-label*="Close"]'
  ];
  for (const s of sels) {
    const el = document.querySelector(s);
    if (!el) continue;
    if (!(el.getClientRects && el.getClientRects().length > 0)) continue;
    try { el.click(); return {closed: true, selector: s}; } catch (_) {}
  }
  return {closed: false};
})()
"""

FACEBOOK_JS_PLAYER_STATE = r"""
(() => {
  const video = document.querySelector('video');
  const playBtn = document.querySelector('[aria-label="Play"], [aria-label*="Play"], div[role="button"][aria-label*="Play"]');
  const muteBtn = document.querySelector('[aria-label*="Mute"], [aria-label*="Unmute"]');
  const fsBtn = document.querySelector('[aria-label*="full screen"], [aria-label*="Full screen"], [aria-label*="Fullscreen"], [aria-label*="full screen mode"]');
  const replayBtn = document.querySelector('[aria-label*="Replay"], [aria-label*="Restart"]');
  return {
    hasVideo: !!video,
    playVisible: !!(playBtn && playBtn.getClientRects && playBtn.getClientRects().length > 0),
    muteVisible: !!(muteBtn && muteBtn.getClientRects && muteBtn.getClientRects().length > 0),
    fullscreenVisible: !!(fsBtn && fsBtn.getClientRects && fsBtn.getClientRects().length > 0),
    replayVisible: !!(replayBtn && replayBtn.getClientRects && replayBtn.getClientRects().length > 0),
    paused: video ? video.paused : null,
    currentTime: video ? video.currentTime : null,
    duration: video ? video.duration : null,
    readyState: video ? video.readyState : null
  };
})()
"""

FACEBOOK_JS_PLAY = r"""
(() => {
  const video = document.querySelector('video');
  const btn = document.querySelector(
    '[aria-label="Play"], [aria-label*="Play"], div[role="button"][aria-label*="Play"], ' +
    '[aria-label*="Replay"], [aria-label*="Restart"], div[role="button"][aria-label*="Replay"], div[role="button"][aria-label*="Restart"]'
  );
  if (btn) { try { btn.click(); } catch (_) {} }
  if (video) {
    try {
      video.muted = true;
      video.play();
      return {success: true, via: 'video.play', paused: video.paused, currentTime: video.currentTime};
    } catch (e) {
      return {success: false, via: 'video.play', error: String(e)};
    }
  }
  return {success: !!btn, via: btn ? 'play-button' : 'none'};
})()
"""

FACEBOOK_JS_ENSURE_UNMUTED = r"""
(() => {
  const video = document.querySelector('video');
  if (!video) return {success: false, error: 'video not found'};

  try { video.muted = false; } catch (_) {}
  if (!video.muted) {
    return {success: true, via: 'video.muted=false', muted: video.muted};
  }

  const btn = document.querySelector('[aria-label*="Unmute"], div[role="button"][aria-label*="Unmute"]');
  if (btn) {
    try { btn.click(); } catch (_) {}
  }
  return {success: !video.muted, via: btn ? 'unmute-button' : 'none', muted: video.muted};
})()
"""

FACEBOOK_JS_ENTER_FULLSCREEN = r"""
(() => {
  const btn = document.querySelector('[aria-label*="full screen"], [aria-label*="Full screen"], [aria-label*="Fullscreen"], [aria-label*="full screen mode"]');
  if (btn) {
    try { btn.click(); return {success: true, via: 'button'}; } catch (_) {}
  }
  const video = document.querySelector('video');
  const el = video || document.documentElement;
  try {
    if (!document.fullscreenElement && el.requestFullscreen) {
      el.requestFullscreen();
      return {success: true, via: 'requestFullscreen'};
    }
    return {success: !!document.fullscreenElement, via: 'already'};
  } catch (e) {
    return {success: false, error: String(e)};
  }
})()
"""

FACEBOOK_JS_VIDEO_STATUS = WEB_JS_VIDEO_STATUS
FACEBOOK_JS_INSTALL_FIRST_FRAME_PROBE = WEB_JS_INSTALL_FIRST_FRAME_PROBE
FACEBOOK_JS_GET_FIRST_FRAME = WEB_JS_GET_FIRST_FRAME

NETFLIX_JS_WAIT_FOR_LOGIN_RESULT = """
(() => {
    const href = window.location.href || '';
    const onBrowse = /\\/browse|\\/watch/.test(href);
    const profileGate = !!document.querySelector('.profile-gate-container, .choose-profile, .profile-gate-label');
    const loginForm = !!document.querySelector('form[action*="login"], input[name="userLoginId"], input[type="password"]');
    const errorNode = document.querySelector('[data-uia="text-login-error"], .ui-message-error, .inputError');
    return {
        href,
        onBrowse,
        profileGate,
        loginForm,
        errorText: errorNode ? (errorNode.textContent || '').trim() : ''
    };
})()
"""

NETFLIX_JS_VIDEO_STATUS = WEB_JS_VIDEO_STATUS

NETFLIX_JS_FORCE_PLAY = """
(() => {
    const video = document.querySelector('video');
    if (!video) return { found: false, played: false };
    try {
        video.muted = true;
        const p = video.play();
        return { found: true, played: true, paused: video.paused, hasPromise: !!p, currentTime: video.currentTime };
    } catch (e) {
        return { found: true, played: false, error: String(e) };
    }
})()
"""

NETFLIX_JS_CLICK_GENERIC_PLAY = """
(() => {
    const selectors = [
        '[aria-label*="Play"]',
        'button[data-uia*="play"]',
        '.watch-video--player-view button',
        '.button-nfplayerPlay',
        '.nf-player-container button'
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.getClientRects && el.getClientRects().length > 0) {
            el.click();
            return { clicked: true, selector: sel };
        }
    }
    return { clicked: false };
})()
"""

NETFLIX_JS_DISMISS_COOKIE_BANNER = """
(() => {
    const patterns = [/accept/i, /accept all/i, /allow all/i, /agree/i, /annehmen/i, /akzeptieren/i, /zustimmen/i, /tout accepter/i, /aceptar/i, /accetta/i];
    const selectors = ['button#onetrust-accept-btn-handler', '#onetrust-banner-sdk button', '[data-uia*="cookie"] button', 'button'];

    function label(el) {
        return (el.innerText || el.textContent || el.getAttribute('aria-label') || el.value || '').trim();
    }

    for (const sel of selectors) {
        const nodes = document.querySelectorAll(sel);
        for (const btn of nodes) {
            const txt = label(btn);
            if (!txt) continue;
            if (!patterns.some((re) => re.test(txt))) continue;
            const visible = btn.getClientRects && btn.getClientRects().length > 0;
            if (!visible) continue;
            try {
                btn.click();
                return { clicked: true, label: txt };
            } catch (e) {}
        }
    }

    return { clicked: false };
})()
"""

NETFLIX_JS_DETECT_DRM_BLOCK = """
(() => {
    const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
    const hasM7701 = /M7701-1003/i.test(bodyText);
    const hasProtectedContent = /protected content/i.test(bodyText);
    return {
        blocked: hasM7701 || hasProtectedContent,
        hasM7701,
        hasProtectedContent
    };
})()
"""

exampletv_JS_DISMISS_COOKIES = """
(() => {
    const acceptPatterns = [
        /accept all/i,
        /allow all/i,
        /alle zulassen/i,
        /alle akzeptieren/i,
        /akzeptieren/i,
        /zustimmen/i,
        /tout accepter/i,
        /accepter tout/i,
        /aceptar todo/i,
        /accetta tutto/i
    ];
    const rejectPatterns = [
        /cookie[-\\s]?richtlinie/i,
        /cookie policy/i,
        /manage settings/i,
        /einstellungen verwalten/i,
        /preferences/i,
        /details/i,
        /learn more/i,
        /mehr erfahren/i
    ];

    const selectors = 'button, [role="button"], input[type="button"], input[type="submit"], a[role="button"]';
    const candidates = document.querySelectorAll(selectors);

    function labelOf(el) {
        return (
            el.innerText ||
            el.textContent ||
            el.getAttribute('aria-label') ||
            el.getAttribute('title') ||
            el.value ||
            ''
        ).trim();
    }

    for (const el of candidates) {
        const label = labelOf(el);
        if (!label) continue;
        if (rejectPatterns.some((re) => re.test(label))) continue;
        if (!acceptPatterns.some((re) => re.test(label))) continue;
        if (!el.getClientRects || el.getClientRects().length === 0) continue;
        try {
            el.click();
            return { clicked: true, label };
        } catch (e) {
            // continue
        }
    }

    return { clicked: false, label: null };
})()
"""

exampletv_JS_STATE = """
(() => {
    const href = window.location.href || '';
    const title = document.title || '';
    const bodyText = (document.body?.innerText || '').slice(0, 5000);

    const passwordField = document.querySelector('input[type="password"], input[name*="pass" i], input[id*="pass" i]');
    const emailField = document.querySelector(
        'input[type="email"], input[name*="mail" i], input[id*="mail" i], input[name*="user" i], input[id*="user" i], input[name*="login" i], input[id*="login" i]'
    );
    const loginButton = document.querySelector(
        'button[type="submit"], input[type="submit"], button[name*="login" i], button[id*="login" i], button[class*="login" i]'
    );

    const loginTextMatch = /melde dich bitte mit deinen zugangsdaten|anmeldung überspringen/i.test(bodyText);
    const loginCta = Array.from(document.querySelectorAll('button, a, [role="button"]')).find((el) => {
        const txt = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
        if (!txt) return false;
        const visible = el.getClientRects && el.getClientRects().length > 0;
        return visible && /^(anmelden|einloggen|sign in|log in|connexion|accedi)$/i.test(txt);
    });
    const skipLoginCta = Array.from(document.querySelectorAll('a, button, [role="button"]')).find((el) => {
        const txt = (el.innerText || el.textContent || '').trim();
        if (!txt) return false;
        const visible = el.getClientRects && el.getClientRects().length > 0;
        return visible && /anmeldung überspringen|skip login|continue as guest/i.test(txt);
    });
    // Semantics-aware home signals. Example is Flutter Web — all UI is
    // canvas-rendered, so sidebar labels and buttons only appear in the DOM as
    // flt-semantics elements AFTER flt-semantics-placeholder has been clicked.
    // The caller is expected to activate semantics before evaluating this state.
    const semanticsButtons = Array.from(document.querySelectorAll('flt-semantics[role="button"]'));
    const semanticsLabels = semanticsButtons
        .map((el) => (el.textContent || el.getAttribute('aria-label') || '').trim().toLowerCase())
        .filter((s) => s.length > 0);

    // Sidebar items exposed by the home shell across locales:
    //   DE: Home / TV Guide / Replay / Filme & Serien / Gespeichert / Suche
    //   EN: Home / TV Guide / Replay / Movies & Series / Saved / Search
    //   FR: Accueil / Guide TV / Replay / Films & Séries / Sauvegardés / Rechercher
    //   IT: Home / Guida TV / Replay / Film e Serie / Salvati / Cerca
    const sidebarLabelPatterns = [
        /^home$|^accueil$/,
        /^tv[-\\s]?guide$|^guida\\s*tv$|^guide\\s*tv$/,
        /^replay$/,
        /^movies?\\s*[&e]\\s*series?$|^filme\\s*&\\s*serien$|^films?\\s*&\\s*s[eé]ries?$|^film\\s*e\\s*serie$/,
        /^saved$|^gespeichert$|^sauvegard[eé]s?$|^salvati$/,
        /^search$|^suche$|^rechercher$|^cerca$/,
    ];
    const matchedSidebarLabels = sidebarLabelPatterns
        .map((re) => semanticsLabels.find((l) => re.test(l)) || '')
        .filter((l) => l.length > 0);
    const homeSidebarDetected = matchedSidebarLabels.length >= 2;

    // Strong positive: Example home mounts a Shaka-backed <video> inside an
    // flt-platform-view for the live preview. Login gate / loading states do not.
    const hasLivePlayer = !!document.querySelector('flt-platform-view video, flt-platform-view .shaka-text-container');

    // Legacy body-text scan kept as a weak tie-breaker, but NO LONGER sufficient alone.
    const homeTextMatch = /tv-guide|live\\s*tv|watchlist|fortsetzen|meine\\s+liste/i.test(bodyText);

    const loginGateOverlayDetected = loginTextMatch || (!!skipLoginCta) || (
        /datenschutzrichtlinie|geschäftsbedingungen/i.test(bodyText) && !!loginCta
    );

    const cookieBannerVisible = Array.from(document.querySelectorAll('button, [role="button"]')).some((el) => {
        const txt = (el.innerText || el.textContent || '').trim();
        if (!txt) return false;
        const visible = el.getClientRects && el.getClientRects().length > 0;
        return visible && /alle zulassen|allow all|einstellungen verwalten|manage settings|ablehnen|reject/i.test(txt);
    });
    // Only check <title>; the Example home page has "Cookie-Richtlinie" as a
    // footer link in bodyText (via flt-semantics), which would false-positive
    // if we scanned body. The cookie-acceptance page itself sets <title>.
    const cookiePolicyDetected =
        /cookie[-\\s]?richtlinie|cookie policy|politique des cookies|informativa cookie/i.test(title);

    // Additional login-gate signal: after semantics activation, a visible
    // top-level ANMELDEN button means we're on the pre-login overlay.
    const semanticsAnmelden = semanticsLabels.some((l) => /^(anmelden|einloggen|sign in|log in|connexion|accedi)$/i.test(l));

    const loginFormDetected =
        !!passwordField ||
        (!!emailField && !!loginButton) ||
        loginGateOverlayDetected ||
        semanticsAnmelden;

    const homeUrlMatch = /\\/(de|en|fr|it)\\/home/i.test(href);
    // Strong-signal home: must be on home URL, no login indicators, no cookie
    // banner, AND either the live player is mounted or the sidebar has real
    // menu labels. A blank /de/home loading screen no longer qualifies.
    const likelyHome = homeUrlMatch &&
        !loginFormDetected &&
        !cookieBannerVisible &&
        !cookiePolicyDetected &&
        (hasLivePlayer || homeSidebarDetected);

    return {
        href,
        title,
        hasPasswordField: !!passwordField,
        hasEmailField: !!emailField,
        hasLoginButton: !!loginButton,
        hasLoginCta: !!loginCta,
        hasSkipLoginCta: !!skipLoginCta,
        semanticsAnmelden,
        semanticsLabels,
        matchedSidebarLabels,
        hasLivePlayer,
        homeSidebarDetected,
        homeTextMatch,
        loginGateOverlayDetected,
        cookieBannerVisible,
        cookiePolicyDetected,
        loginFormDetected,
        likelyHome,
    };
})()
"""

exampletv_JS_ACTIVATE_SEMANTICS = """
(() => {
    // Clicking flt-semantics-placeholder tells Flutter Web to populate the
    // flt-semantics DOM tree. Without it, UI buttons rendered on the canvas
    // are invisible to DOM queries, so _JS_STATE can't see sidebar labels or
    // the ANMELDEN button. Idempotent: returns {activated: true} when the
    // placeholder was clicked, false otherwise (already active or missing).
    const placeholder = document.querySelector('flt-semantics-placeholder');
    if (!placeholder) {
        return { activated: false, reason: 'no placeholder' };
    }
    try {
        placeholder.click();
        return { activated: true };
    } catch (e) {
        return { activated: false, reason: String(e) };
    }
})()
"""

exampletv_JS_CLICK_LOGIN_CTA = """
(() => {
    const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));
    for (const el of candidates) {
        const txt = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
        if (!txt) continue;
        const visible = el.getClientRects && el.getClientRects().length > 0;
        if (!visible) continue;
        if (/anmelden|einloggen|sign in|log in|connexion|accedi/i.test(txt)) {
            try {
                el.click();
                return { clicked: true, label: txt };
            } catch (e) {
                // continue
            }
        }
    }
    return { clicked: false, label: null };
})()
"""

exampletv_JS_DISMISS_POPUPS = """
(() => {
    // Dismiss patterns localised across DE/EN/FR/IT for known Example popups:
    //   - Generic close ("OK", "Schliessen", "Close"...)
    //   - "Maximale Anzahl erreicht" blocker → click close
    //   - Post-login "Installiere die Example TV App" blocker → click NICHT JETZT / Not now
    const patterns = [
        /^ok$/i,
        /^schliessen$/i,
        /^schließen$/i,
        /^close$/i,
        /^fermer$/i,
        /^chiudi$/i,
        /^verstanden$/i,
        /^got it$/i,
        /^dismiss$/i,
        /^nicht\\s*jetzt$/i,
        /^not\\s*now$/i,
        /^pas\\s*maintenant$/i,
        /^non\\s*ora$/i,
        /^später$/i,
        /^later$/i,
        /^überspringen$/i,
        /^skip$/i
    ];

    // Flutter Web: flt-semantics[role="button"] doesn't respond to .click() —
    // need pointer event dispatch. Try flt-semantics first since the install
    // popup is canvas-rendered, then fall back to standard DOM buttons.
    const flutterButtons = Array.from(document.querySelectorAll('flt-semantics[role="button"]'));
    for (const el of flutterButtons) {
        const txt = (el.textContent || el.getAttribute('aria-label') || '').trim();
        if (!txt) continue;
        if (!patterns.some((re) => re.test(txt))) continue;
        const visible = el.getClientRects && el.getClientRects().length > 0;
        if (!visible) continue;
        try {
            const rect = el.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            ['pointerdown', 'pointerup', 'click'].forEach((type) => {
                el.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x, clientY: y }));
            });
            return { clicked: true, label: txt, via: 'flt-semantics' };
        } catch (e) {
            // continue
        }
    }

    const nodes = Array.from(document.querySelectorAll('button, [role="button"], a'));
    for (const el of nodes) {
        const txt = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
        if (!txt) continue;
        const visible = el.getClientRects && el.getClientRects().length > 0;
        if (!visible) continue;
        if (!patterns.some((re) => re.test(txt))) continue;
        try {
            el.click();
            return { clicked: true, label: txt, via: 'dom' };
        } catch (e) {
            // continue
        }
    }
    return { clicked: false, label: null };
})()
"""

exampletv_JS_FLUTTER_DUMP = """
(() => {
    const glassPane = document.querySelector('flt-glass-pane');
    const semanticsHost = document.querySelector('flt-semantics-host');
    const semanticsPlaceholder = document.querySelector('flt-semantics-placeholder');
    const semanticsNodes = document.querySelectorAll('flt-semantics').length;
    const bodyLen = (document.body?.innerText || '').length;

    const raw = glassPane ? (glassPane.outerHTML || '') : '';
    const compact = raw.replace(/\\s+/g, ' ').trim();

    return {
        hasGlassPane: !!glassPane,
        hasSemanticsHost: !!semanticsHost,
        hasSemanticsPlaceholder: !!semanticsPlaceholder,
        semanticsNodes,
        bodyTextLength: bodyLen,
        glassPaneSnippet: compact.slice(0, 2500),
    };
})()
"""

DAILYMOTION_JS_CHECK_CONSENT_MODAL = """
(() => {
    // NOTE: position:fixed elements report offsetParent === null, so we must
    // use getComputedStyle + boundingRect for visibility checks, not offsetParent.
    function isVisible(el) {
        if (!el) return false;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 20 && rect.height > 20;
    }

    // Try classic CMP selectors first (match all, return the first visible one)
    const knownSelectors = [
        '#didomi-notice',
        '#didomi-host',
        '[id^="didomi-popup"]',
        '.didomi-popup-container',
        '[role="dialog"]',
        '[role="alertdialog"]',
        'dialog[open]',
    ];
    for (const sel of knownSelectors) {
        const matches = document.querySelectorAll(sel);
        for (const el of matches) {
            if (!isVisible(el)) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width > 100 && rect.height > 50) return sel;
        }
    }

    // Fallback: any visible container whose innerText mentions both
    // "accepter/accept" AND a privacy term ("confidentialité/cookies/données/privacy")
    const containers = document.querySelectorAll('div, section, aside, dialog, main');
    for (const el of containers) {
        if (!isVisible(el)) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width < 200 || rect.height < 100) continue;
        if (rect.width > window.innerWidth * 0.95 && rect.height > window.innerHeight * 0.95) continue;
        const txt = (el.innerText || '').slice(0, 800);
        const hasAccept = /accepter|j'accepte|tout accepter|accept all|i agree|got it/i.test(txt);
        const hasPrivacy = /confidentialité|cookies?|données personnelles|privacy|traceurs|trackers/i.test(txt);
        if (hasAccept && hasPrivacy) {
            return `heuristic:${el.tagName.toLowerCase()}.${(el.className||'').toString().split(/\\s+/)[0]}`;
        }
    }
    return null;
})()
"""

DAILYMOTION_JS_DISMISS_CONSENT_MODAL = """
(() => {
    const result = { clicked: false, method: null };

    function isVisible(el) {
        if (!el) return false;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 5 && rect.height > 5;
    }

    // Preferred: classic Didomi agree button
    const didomiBtn = document.querySelector('#didomi-notice-agree-button');
    if (didomiBtn && isVisible(didomiBtn)) {
        didomiBtn.click();
        result.clicked = true;
        result.method = 'didomi-notice-agree-button';
        return result;
    }

    // Find the modal container via the same heuristic as the check
    function findModal() {
        const directMatches = document.querySelectorAll('[role="dialog"], [role="alertdialog"], dialog[open]');
        for (const el of directMatches) {
            if (isVisible(el)) return el;
        }
        const containers = document.querySelectorAll('div, section, aside');
        let best = null;
        let bestArea = Infinity;
        for (const el of containers) {
            if (!isVisible(el)) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width < 200 || rect.height < 100) continue;
            if (rect.width > window.innerWidth * 0.95 && rect.height > window.innerHeight * 0.95) continue;
            const txt = (el.innerText || '').slice(0, 800);
            const hasAccept = /accepter|j'accepte|tout accepter|accept all|i agree/i.test(txt);
            const hasPrivacy = /confidentialité|cookies?|données personnelles|privacy|traceurs|trackers/i.test(txt);
            if (hasAccept && hasPrivacy) {
                const area = rect.width * rect.height;
                // Prefer the smallest container that still matches (tightest scope)
                if (area < bestArea) { best = el; bestArea = area; }
            }
        }
        return best;
    }

    const modal = findModal();
    const scope = modal || document;

    // Look for a primary accept button inside the modal
    const buttons = scope.querySelectorAll('button, a, [role="button"]');
    const primaryPatterns = [
        /^tout accepter$/i, /^accepter.*tout/i, /^j'accepte$/i, /^accept all$/i,
        /^accepter$/i, /^accepter & fermer$/i, /^accepter et fermer$/i,
        /^i agree$/i, /^agree$/i, /^got it$/i, /^ok$/i,
    ];
    const fallbackPatterns = [
        /accepter/i, /accept/i, /agree/i, /got it/i,
    ];

    // First pass: exact-ish match to primary patterns (excluding negatives)
    for (const btn of buttons) {
        if (!isVisible(btn)) continue;
        const label = ((btn.getAttribute('aria-label') || '') + ' ' + (btn.textContent || '')).trim();
        if (!label) continue;
        if (/sans accepter|refuser|reject|decline|non merci|plus tard|gérer/i.test(label)) continue;
        if (primaryPatterns.some(p => p.test(label))) {
            btn.click();
            result.clicked = true;
            result.method = `primary:${label.slice(0, 40)}`;
            return result;
        }
    }
    // Second pass: fallback (still excluding negatives)
    for (const btn of buttons) {
        if (!isVisible(btn)) continue;
        const label = ((btn.getAttribute('aria-label') || '') + ' ' + (btn.textContent || '')).trim();
        if (!label) continue;
        if (/sans accepter|refuser|reject|decline|non merci|plus tard|gérer|manage/i.test(label)) continue;
        if (fallbackPatterns.some(p => p.test(label))) {
            btn.click();
            result.clicked = true;
            result.method = `fallback:${label.slice(0, 40)}`;
            return result;
        }
    }
    return result;
})()
"""

DAILYMOTION_JS_DISMISS_PLAYER_BANNER = """
(() => {
    // Dailymotion's embed player shows a tracker dialog with a close (×) button.
    const candidates = [
        ...document.querySelectorAll('button[aria-label="Fermer"], button[aria-label="Close"]'),
        ...document.querySelectorAll('.close_button, .dialog_container button'),
    ];
    for (const btn of candidates) {
        if (!btn) continue;
        const cs = getComputedStyle(btn);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        btn.click();
        return { clicked: true, method: btn.getAttribute('aria-label') || btn.className || 'close_button' };
    }
    return { clicked: false, method: null };
})()
"""

DAILYMOTION_JS_CLICK_PLAYER_OVERLAY = """
(() => {
    // The embed player has a .vod_click overlay that starts playback on click.
    const overlay = document.querySelector('.vod_click');
    if (!overlay) return { clicked: false };
    const rect = overlay.getBoundingClientRect();
    overlay.dispatchEvent(new MouseEvent('click', {
        bubbles: true, cancelable: true,
        clientX: rect.x + rect.width / 2,
        clientY: rect.y + rect.height / 2,
    }));
    return { clicked: true };
})()
"""

DAILYMOTION_JS_VIDEO_STATUS = WEB_JS_VIDEO_STATUS
DAILYMOTION_JS_INSTALL_FIRST_FRAME_PROBE = WEB_JS_INSTALL_FIRST_FRAME_PROBE
DAILYMOTION_JS_GET_FIRST_FRAME = WEB_JS_GET_FIRST_FRAME

DAILYMOTION_JS_FORCE_PLAY = """
(() => {
    const video = document.querySelector('video');
    if (!video) return { found: false, attempted: false };
    try {
        video.muted = true;
        const maybePromise = video.play();
        return {
            found: true,
            attempted: true,
            paused: video.paused,
            currentTime: video.currentTime,
            hasPromise: !!maybePromise
        };
    } catch (e) {
        return { found: true, attempted: true, error: String(e) };
    }
})()
"""

DAILYMOTION_JS_ENTER_FULLSCREEN = """
(() => {
    try {
        const video = document.querySelector('video');
        const player = document.querySelector('[class*="Player"], [data-testid*="player"], .dmp_Player') || video?.closest('div');
        const target = player || video;
        if (!target) return { success: false, error: 'No video/player element' };

        function fullscreenState() {
            return !!document.fullscreenElement;
        }

        if (fullscreenState()) {
            return { success: true, method: 'already-fullscreen', isFullscreen: true };
        }

        if (target.requestFullscreen) {
            try { target.requestFullscreen(); } catch (_) {}
            return {
                success: fullscreenState(),
                method: 'requestFullscreen',
                isFullscreen: fullscreenState(),
            };
        }

        return {
            success: false,
            error: 'Fullscreen API not available',
            isFullscreen: fullscreenState(),
        };
    } catch (e) {
        return { success: false, error: String(e) };
    }
})()
"""
