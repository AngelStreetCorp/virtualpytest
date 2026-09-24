"""
BFS App Crawler — Universal recursive exploration for web and Android apps.

Crawls an app by navigating screens, extracting elements, classifying
navigable items, and building a structured site map tree.

Supports:
- Web (Playwright): navigate_to_url + dump_elements (DOM)
- Android (ADB): click_element/press_key + uiautomator dump
"""

import time
import asyncio
import hashlib
from collections import deque
from typing import Dict, Any, List, Optional, Set
from urllib.parse import urlparse, urljoin, urlunparse


# URL path patterns low-value for QA (web only)
DEFAULT_WEB_SKIP_PATTERNS = [
    'terms', 'privacy', 'cookie', 'legal', 'imprint', 'impressum',
    'about', 'contact', 'help', 'faq', 'support',
    'sitemap', 'robots', 'feeds', 'rss', 'atom',
    'cdn-cgi', 'wp-admin', 'wp-json', 'wp-content',
    'mailto:', 'tel:', 'javascript:', '#',
]

# Android element labels low-value for QA
DEFAULT_ANDROID_SKIP_PATTERNS = [
    'clock', 'battery', 'status bar', 'notification',
    'system ui', 'keyboard', 'ime',
]


# ============================================================================
# WEB HELPERS
# ============================================================================

def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip('/') or '/'
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, ''))


def _same_origin(url: str, base_url: str) -> bool:
    return urlparse(url).netloc == urlparse(base_url).netloc


def _should_skip(name: str, skip_patterns: List[str]) -> bool:
    name_lower = name.lower()
    for pattern in skip_patterns:
        if pattern in name_lower:
            return True
    return False


def _extract_links_from_elements(elements: List[Dict], base_url: str) -> List[Dict[str, str]]:
    links = []
    seen_hrefs = set()
    for el in elements:
        href = el.get('attributes', {}).get('href', '')
        if not href:
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.scheme not in ('http', 'https'):
            continue
        normalized = _normalize_url(full_url)
        if normalized in seen_hrefs:
            continue
        seen_hrefs.add(normalized)
        text = el.get('textContent', '').strip()[:80]
        links.append({'url': normalized, 'text': text, 'tag': el.get('tagName', ''), 'selector': el.get('selector', '')})
    return links


def _extract_clickable_elements(elements: List[Dict], base_url: str) -> List[Dict[str, str]]:
    """Extract clickable elements that DON'T have navigable href links (SPA buttons, # links)."""
    items = []
    seen = set()
    for el in elements:
        tag = el.get('tagName', '')
        attrs = el.get('attributes', {})
        href = attrs.get('href', '')
        text = el.get('textContent', '').strip()[:60]
        selector = el.get('selector', '')
        role = attrs.get('role', '')

        # Skip if it has a real navigable href that goes to a DIFFERENT page
        # (already handled by _extract_links_from_elements)
        # Keep: # anchors (even fully resolved like "https://site.com/page#"),
        #       javascript: links, and same-page links
        if href:
            normalized_href = _normalize_url(href) if href.startswith('http') else href
            normalized_base = _normalize_url(base_url)
            is_same_page = normalized_href == normalized_base or href.startswith('#') or href.startswith('javascript:')
            if not is_same_page:
                continue

        # Only keep interactive elements
        is_clickable = (
            tag in ('button', 'a') or
            role in ('link', 'button', 'tab', 'menuitem') or
            attrs.get('onclick') or
            (tag == 'a' and href.startswith('#'))
        )
        if not is_clickable or not text:
            continue

        if text in seen:
            continue
        seen.add(text)

        items.append({
            'text': text,
            'selector': selector,
            'tag': tag,
        })
    return items[:15]  # Cap at 15 clickable items


def _summarize_web_elements(elements: List[Dict]) -> List[str]:
    summary = []
    for el in elements:
        tag = el.get('tagName', '')
        text = el.get('textContent', '').strip()[:60]
        attrs = el.get('attributes', {})
        role = attrs.get('role', '')
        if tag == 'a' and attrs.get('href'):
            summary.append(f"link: {text or attrs.get('href', '')}")
        elif tag in ('button', 'input', 'select', 'textarea') or role == 'button':
            input_type = attrs.get('type', '')
            label = text or attrs.get('placeholder', '') or attrs.get('name', '') or input_type
            summary.append(f"{tag}({input_type}): {label}" if input_type else f"{tag}: {label}")
        elif tag in ('h1', 'h2', 'h3') and text:
            summary.append(f"{tag}: {text}")
        elif tag == 'form':
            summary.append(f"form: {attrs.get('name', attrs.get('id', 'unnamed'))}")
        elif tag == 'img':
            summary.append(f"img: {attrs.get('alt', attrs.get('title', 'no alt'))}")
    return summary[:30]


# ============================================================================
# ANDROID HELPERS
# ============================================================================

def _clean_adb_field(value: str) -> str:
    """Strip ADB placeholder values like '<no text>', '<no content-desc>'."""
    if not value:
        return ''
    v = value.strip()
    if v.startswith('<no ') and v.endswith('>'):
        return ''
    return v


def _extract_navigable_android_items(elements: List[Dict]) -> List[Dict[str, str]]:
    """Extract clickable OR focusable items from ADB UI dump that are worth navigating to."""
    items = []
    seen_texts = set()
    for el in elements:
        clickable = el.get('clickable', False)
        focusable = el.get('focusable', False)
        enabled = el.get('enabled', True)
        if not (clickable or focusable) or not enabled:
            continue

        text = _clean_adb_field(el.get('text', ''))
        content_desc = _clean_adb_field(el.get('content_desc', ''))
        resource_id = _clean_adb_field(el.get('resource_id', ''))
        label = text or content_desc or resource_id
        if not label or label in seen_texts:
            continue
        seen_texts.add(label)

        items.append({
            'text': label,
            'class_name': el.get('class_name', ''),
            'clickable': clickable,
            'focusable': focusable,
            'resource_id': resource_id,
            'bounds': el.get('bounds', ''),
        })
    return items


def _summarize_android_elements(elements: List[Dict]) -> List[str]:
    """Create concise summary of Android UI elements, including resource_id for stable verification."""
    summary = []
    for el in elements:
        text = _clean_adb_field(el.get('text', ''))
        content_desc = _clean_adb_field(el.get('content_desc', ''))
        resource_id = _clean_adb_field(el.get('resource_id', ''))
        class_name = el.get('class_name', '').split('.')[-1]
        clickable = el.get('clickable', False)
        label = text or content_desc
        if not label:
            continue
        prefix = 'button' if clickable else 'text'
        if 'EditText' in el.get('class_name', ''):
            prefix = 'input'
        elif 'ImageView' in el.get('class_name', ''):
            prefix = 'image'
        elif 'Switch' in el.get('class_name', '') or 'Toggle' in el.get('class_name', ''):
            prefix = 'toggle'
        # Include resource_id for stable verification (agent can use it instead of dynamic text)
        id_suffix = ''
        if resource_id:
            short_id = resource_id.split('/')[-1] if '/' in resource_id else resource_id
            id_suffix = f' (id:{short_id})'
        summary.append(f"{prefix}: {label}{id_suffix}")
    return summary[:30]


# Common dismiss button labels for popup/dialog detection
DISMISS_PATTERNS = [
    'DISMISS', 'SKIP', 'NOT NOW', 'NO THANKS', 'CANCEL', 'CLOSE',
    'LATER', 'GOT IT', 'ACCEPT', 'OK', 'NO, THANKS', 'MAYBE LATER',
    'NICHT JETZT', 'SCHLIESSEN', 'ABBRECHEN',  # German
]


def _android_screen_id(elements: List[Dict]) -> str:
    """Generate a screen ID from visible text for deduplication.
    Filters out volatile text like clock/time (digits+colon pattern)."""
    import re
    time_pattern = re.compile(r'^\d{1,2}:\d{2}$')
    texts = sorted(set(
        _clean_adb_field(el.get('text', ''))
        for el in elements
        if _clean_adb_field(el.get('text', ''))
        and len(_clean_adb_field(el.get('text', ''))) > 1
        and not time_pattern.match(_clean_adb_field(el.get('text', '')))
    ))
    key = '|'.join(texts[:15])
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _build_tree_view(site_map: Dict[str, Dict], root_id: str) -> str:
    lines = []
    root = site_map.get(root_id, {})
    root_title = root.get('title', 'Home')
    lines.append(f"{root_id} ({root_title})")
    children = [sid for sid in site_map if sid != root_id]
    for i, sid in enumerate(children):
        info = site_map[sid]
        title = info.get('title', '')
        is_last = i == len(children) - 1
        prefix = '└── ' if is_last else '├── '
        lines.append(f"{prefix}{sid} ({title})")
    return '\n'.join(lines)


# ============================================================================
# WEB CRAWLER (Playwright)
# ============================================================================

class WebAppCrawler:
    """BFS crawler for web apps using a Playwright web controller."""

    def __init__(self, web_controller, max_depth: int = 2, max_pages: int = 10,
                 skip_patterns: Optional[List[str]] = None,
                 username: Optional[str] = None, password: Optional[str] = None):
        self.web_controller = web_controller
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.skip_patterns = (skip_patterns or []) + DEFAULT_WEB_SKIP_PATTERNS
        self.username = username
        self.password = password

    async def _attempt_login(self) -> bool:
        """Try to fill and submit a login form using web controller's input_text and click_element."""
        if not self.username or not self.password:
            return False

        print(f"[@crawler:web] Credentials provided, attempting login...")

        try:
            # Check if there's a password field (login form indicator)
            dump = await self.web_controller.dump_elements(element_types='interactive')
            if not dump.get('success'):
                return False

            elements = (dump.get('output_data') or dump).get('elements', [])
            has_password = any(
                el.get('attributes', {}).get('type') == 'password'
                for el in elements
            )
            if not has_password:
                print(f"[@crawler:web] No password field — not a login page")
                return False

            # Find username field selector
            user_selectors = ['#user-name', '#username', '#email', 'input[name="username"]', 'input[type="email"]', 'input[type="text"]']
            user_selector = None
            for sel in user_selectors:
                for el in elements:
                    el_selector = el.get('selector', '')
                    el_id = el.get('id', '')
                    el_name = el.get('attributes', {}).get('name', '')
                    if (el_id and f'#{el_id}' == sel) or (sel in el_selector):
                        user_selector = sel
                        break
                if user_selector:
                    break
            if not user_selector:
                # Fallback: first text input
                for el in elements:
                    if el.get('attributes', {}).get('type') in ('text', 'email'):
                        user_selector = el.get('selector', '')
                        break

            if not user_selector:
                print(f"[@crawler:web] Can't find username field")
                return False

            # Type username
            print(f"[@crawler:web] Typing username into {user_selector}")
            await self.web_controller.click_element(user_selector)
            await self.web_controller.input_text(user_selector, self.username)

            # Type password
            print(f"[@crawler:web] Typing password")
            await self.web_controller.input_text('input[type="password"]', self.password)

            # Click submit
            submit_selectors = ['#login-button', 'button[type="submit"]', 'input[type="submit"]', 'Login', 'Sign in', 'Log in']
            for sel in submit_selectors:
                result = await self.web_controller.click_element(sel)
                if result.get('success'):
                    print(f"[@crawler:web] Clicked submit: {sel}")
                    break

            # Wait for navigation

            await asyncio.sleep(3)

            page_info = await self.web_controller.get_page_info()
            new_url = page_info.get('url', '')
            print(f"[@crawler:web] After login: {new_url}")
            return True

        except Exception as e:
            print(f"[@crawler:web] Login failed: {e}")
            return False

    async def crawl(self, start_url: str) -> Dict[str, Any]:
        start_time = time.time()
        site_map = {}
        visited: Set[str] = set()
        skipped: Set[str] = set()
        queue: deque = deque()
        normalized_start = _normalize_url(start_url)
        queue.append((normalized_start, 0))

        print(f"[@crawler:web] Starting BFS from {normalized_start} (max_depth={self.max_depth}, max_pages={self.max_pages})")

        # If credentials provided, navigate to start URL first and try login
        if self.username and self.password:
            nav_result = await self.web_controller.navigate_to_url(start_url)
            if nav_result.get('success'):
                logged_in = await self._attempt_login()
                if logged_in:
                    # Update start URL and mark as already visited (don't re-navigate)
                    page_info = await self.web_controller.get_page_info()
                    new_url = page_info.get('url', start_url)
                    normalized_start = _normalize_url(new_url)
                    # Mark login page as visited so we don't go back
                    visited.add(_normalize_url(start_url))
                    # Don't add to queue — we're already on this page
                    # Process it directly below
                    queue.clear()
                    print(f"[@crawler:web] Login successful, now on: {normalized_start}")

                    # Dump the authenticated page directly (skip navigate_to_url)
                    page_title = page_info.get('title', '')
                    dump_result = await self.web_controller.dump_elements(element_types='all')
                    elements = []
                    if dump_result.get('success'):
                        output = dump_result.get('output_data') or dump_result
                        elements = output.get('elements', [])
                    element_summary = _summarize_web_elements(elements)
                    links = _extract_links_from_elements(elements, normalized_start)
                    visited.add(normalized_start)
                    site_map[normalized_start] = {
                        'title': page_title, 'elements': element_summary,
                        'element_count': len(elements), 'nav_items': len(links),
                        'links': [{'url': l['url'], 'text': l['text']} for l in links[:20]],
                    }

                    # Queue href links
                    for link in links:
                        link_url = link['url']
                        if link_url not in visited and not _should_skip(link_url, self.skip_patterns) and _same_origin(link_url, normalized_start):
                            queue.append((link_url, 1))

                    # SPA: click same-page interactive elements
                    clickable_items = _extract_clickable_elements(elements, normalized_start)
                    if clickable_items:
                        print(f"[@crawler:web:spa] Trying {len(clickable_items)} clickable elements")
            
                        for item in clickable_items:
                            if len(visited) >= self.max_pages:
                                break
                            click_text = item['text']
                            print(f"[@crawler:web:spa] Clicking '{click_text}'")
                            click_result = await self.web_controller.click_element(click_text)
                            if not click_result.get('success'):
                                print(f"[@crawler:web:spa] Click failed for '{click_text}'")
                                continue
                            await asyncio.sleep(1.5)
                            pi = await self.web_controller.get_page_info()
                            new_url = _normalize_url(pi.get('url', normalized_start))
                            if new_url != normalized_start and new_url not in visited:
                                visited.add(new_url)
                                d2 = await self.web_controller.dump_elements(element_types='all')
                                if d2.get('success'):
                                    o2 = d2.get('output_data') or d2
                                    e2 = o2.get('elements', [])
                                    site_map[new_url] = {
                                        'title': pi.get('title', ''), 'elements': _summarize_web_elements(e2),
                                        'element_count': len(e2), 'nav_items': 0, 'links': [],
                                        'click_action': click_text,
                                    }
                                    print(f"[@crawler:web:spa] Found: {pi.get('title','')} ({new_url})")
                                await self.web_controller.press_key('BACK')
                                await asyncio.sleep(1)
                            elif new_url == normalized_start:
                                continue
                            else:
                                await self.web_controller.press_key('BACK')
                                await asyncio.sleep(0.5)

        while queue and len(visited) < self.max_pages:
            url, depth = queue.popleft()
            if url in visited or url in skipped:
                continue
            if _should_skip(url, self.skip_patterns):
                skipped.add(url)
                continue
            if not _same_origin(url, normalized_start):
                skipped.add(url)
                continue

            print(f"[@crawler:web] [{len(visited)+1}/{self.max_pages}] depth={depth} → {url}")
            nav_result = await self.web_controller.navigate_to_url(url)
            if not nav_result.get('success'):
                skipped.add(url)
                continue

            actual_url = _normalize_url(nav_result.get('url', url))
            if actual_url != url and actual_url in visited:
                visited.add(url)
                continue
            visited.add(url)
            if actual_url != url:
                visited.add(actual_url)

            page_title = nav_result.get('title', '')
            # Wait for SPA content on first page only (JS-rendered nav links)
            if len(visited) <= 1:
                await asyncio.sleep(3)
            # Use 'interactive' instead of 'all' — 'all' returns too many divs/spans
            # and truncates before reaching <a href> links on heavy SPAs like YouTube
            dump_result = await self.web_controller.dump_elements(element_types='interactive')
            elements = []
            links = []
            element_summary = []

            if dump_result.get('success'):
                output = dump_result.get('output_data') or dump_result
                elements = output.get('elements', [])
                element_summary = _summarize_web_elements(elements)
                links = _extract_links_from_elements(elements, actual_url)

            # Also dump 'links' type to catch <a href> missed by 'interactive'
            links_dump = await self.web_controller.dump_elements(element_types='links')
            if links_dump.get('success'):
                link_elements = (links_dump.get('output_data') or links_dump).get('elements', [])
                extra_links = _extract_links_from_elements(link_elements, actual_url)
                seen_urls = {l['url'] for l in links}
                for el in extra_links:
                    if el['url'] not in seen_urls:
                        links.append(el)
                        seen_urls.add(el['url'])
                elements.extend(link_elements)
                element_summary.extend(_summarize_web_elements(link_elements))

            site_map[actual_url] = {
                'title': page_title,
                'elements': element_summary,
                'element_count': len(elements),
                'nav_items': len(links),
                'links': [{'url': l['url'], 'text': l['text']} for l in links[:20]],
            }

            if depth < self.max_depth:
                explored_links = []
                skipped_links = []
                for link in links:
                    link_url = link['url']
                    if link_url in visited or link_url in skipped:
                        continue
                    if _should_skip(link_url, self.skip_patterns):
                        skipped.add(link_url)
                        skipped_links.append(link['text'] or link_url)
                        continue
                    if not _same_origin(link_url, normalized_start):
                        skipped.add(link_url)
                        continue
                    explored_links.append(link['text'] or link_url)
                    queue.append((link_url, depth + 1))
                site_map[actual_url]['explored'] = len(explored_links)
                site_map[actual_url]['skipped'] = skipped_links

                # SPA support: if no new href links found, try clicking interactive elements
                # SPA: also try clicking same-page interactive elements
                if len(visited) < self.max_pages:
                    clickable_items = _extract_clickable_elements(elements, actual_url)
                    if clickable_items:
                        print(f"[@crawler:web] No new URLs — trying {len(clickable_items)} clickable elements (SPA mode)")
                        # Collect new page URLs by clicking each item
                        # Don't go back between clicks — just record each new URL for later visiting
                        new_urls_found = []
                        for item in clickable_items:
                            if len(visited) + len(new_urls_found) >= self.max_pages:
                                break
                            click_text = item['text']
                            target = click_text  # Use plain text, not CSS selector (more reliable for Playwright)
                            print(f"[@crawler:web:spa] Clicking '{click_text}'")
                            click_result = await self.web_controller.click_element(target)
                            if not click_result.get('success'):
                                continue

                
                            await asyncio.sleep(1.5)

                            page_info = await self.web_controller.get_page_info()
                            new_url = _normalize_url(page_info.get('url', actual_url))

                            if new_url != actual_url and new_url not in visited:
                                # Record new screen immediately (don't queue — avoids session loss)
                                visited.add(new_url)
                                dump2 = await self.web_controller.dump_elements(element_types='all')
                                if dump2.get('success'):
                                    output2 = dump2.get('output_data') or dump2
                                    elems2 = output2.get('elements', [])
                                    new_title = (await self.web_controller.get_page_info()).get('title', '')
                                    site_map[new_url] = {
                                        'title': new_title,
                                        'elements': _summarize_web_elements(elems2),
                                        'element_count': len(elems2),
                                        'nav_items': 0,
                                        'links': [],
                                        'click_action': click_text,
                                    }
                                    print(f"[@crawler:web:spa] Recorded: {new_title} ({new_url})")

                                # Browser back (preserves session, unlike navigate_to_url)
                                await self.web_controller.press_key('BACK')
                                await asyncio.sleep(1)
                            elif new_url == actual_url:
                                continue
                            else:
                                await self.web_controller.press_key('BACK')
                                await asyncio.sleep(0.5)

        crawl_time_ms = int((time.time() - start_time) * 1000)
        tree_view = _build_tree_view(site_map, normalized_start)
        print(f"[@crawler:web] Done. {len(visited)} explored, {len(skipped)} skipped in {crawl_time_ms}ms")

        return {
            'success': True, 'platform': 'web',
            'screens_found': len(visited) + len(skipped),
            'screens_explored': len(visited), 'screens_skipped': len(skipped),
            'site_map': site_map, 'tree_view': tree_view, 'crawl_time_ms': crawl_time_ms,
        }


# ============================================================================
# ANDROID CRAWLER (ADB)
# ============================================================================

class AndroidAppCrawler:
    """
    BFS crawler for Android apps using ADB remote controller.

    Two modes based on device_model:
    - Mobile/Tablet: click_element (ADB coordinate tap)
    - TV/Fire TV: D-pad remote (DOWN/OK/BACK/LEFT) like a real user
    """

    def __init__(self, remote_controller, adb_utils, device_id: str,
                 device_model: str = 'android_mobile',
                 max_depth: int = 2, max_pages: int = 10,
                 skip_patterns: Optional[List[str]] = None):
        self.remote = remote_controller
        self.adb_utils = adb_utils
        self.device_id = device_id
        self.device_model = device_model
        self.is_tv = device_model in ('android_tv', 'fire_tv')
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.skip_patterns = (skip_patterns or []) + DEFAULT_ANDROID_SKIP_PATTERNS

    def _dump_screen(self) -> List[Dict]:
        """Dump current screen elements via ADB uiautomator."""
        success, elements, error = self.adb_utils.dump_elements(self.device_id)
        if not success:
            print(f"[@crawler:android] dump_elements failed: {error}")
            return []
        return [el.to_dict() for el in elements]

    def _dismiss_popups(self, max_attempts: int = 3):
        """Auto-dismiss common popups/dialogs (setup wizards, permission prompts)."""
        for attempt in range(max_attempts):
            elements = self._dump_screen()
            dismissed = False
            for el in elements:
                text = _clean_adb_field(el.get('text', '')).upper()
                if text in DISMISS_PATTERNS and el.get('clickable', False):
                    print(f"[@crawler:android] Dismissing popup: '{text}'")
                    self.remote.click_element(text)
                    time.sleep(1.0)
                    dismissed = True
                    break
            if not dismissed:
                break

    def _screen_title(self, elements: List[Dict]) -> str:
        """Infer screen title from prominent text elements."""
        for el in elements:
            text = _clean_adb_field(el.get('text', ''))
            content_desc = _clean_adb_field(el.get('content_desc', ''))
            class_name = el.get('class_name', '')
            label = text or content_desc
            if label and 'TextView' in class_name and len(label) > 2:
                return label
        for el in elements:
            label = _clean_adb_field(el.get('text', '')) or _clean_adb_field(el.get('content_desc', ''))
            if label and len(label) > 2:
                return label
        return 'Unknown'

    def _get_foreground_package(self) -> str:
        """Get the currently focused app package."""
        try:
            import subprocess
            # Use argv + shell=False. The previous form interpolated device_id
            # into a shell string (shell=True), which is command injection
            # when device_id is attacker-controllable. ADB itself rejects IDs
            # that don't start with `emulator-`, `localhost:`, or a serial
            # regex; we let adb fail loudly instead of parsing strings ourselves.
            result = subprocess.run(
                ['adb', '-s', self.device_id, 'shell', 'dumpsys', 'window'],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.split('\n'):
                if 'mCurrentFocus' in line and '/' in line:
                    parts = line.split(' ')
                    for part in parts:
                        if '/' in part and '.' in part:
                            return part.split('/')[0].rstrip('}')
        except Exception:
            pass
        return ''

    def _record_screen(self, elements: List[Dict], site_map: Dict, visited_hashes: Set[str],
                       parent_id: Optional[str], action: Optional[str]) -> Optional[str]:
        """Record a screen in the site map if not already visited. Returns screen_id or None."""
        screen_hash = _android_screen_id(elements)
        if screen_hash in visited_hashes:
            return None
        visited_hashes.add(screen_hash)

        title = self._screen_title(elements)
        element_summary = _summarize_android_elements(elements)
        nav_items = _extract_navigable_android_items(elements)

        screen_id = title.lower().replace(' ', '_').replace('&', 'and')[:30] or screen_hash
        if screen_id in site_map:
            screen_id = f"{screen_id}_{screen_hash[:6]}"

        site_map[screen_id] = {
            'title': title,
            'elements': element_summary,
            'element_count': len(elements),
            'nav_items': len(nav_items),
            'navigable': [{'text': item['text'], 'class': item['class_name']} for item in nav_items[:15]],
            'parent': parent_id,
            'action': action,
        }
        print(f"[@crawler:android] Screen '{title}' ({screen_id}): {len(elements)} elements, {len(nav_items)} navigable")
        return screen_id

    def crawl(self, app_package: Optional[str] = None) -> Dict[str, Any]:
        """BFS crawl of the current Android screen."""
        if not app_package:
            app_package = self._get_foreground_package()
            print(f"[@crawler:android] Auto-detected app: {app_package}")

        # Force fresh app state: close + relaunch
        if app_package:
            print(f"[@crawler:android] Restarting app for fresh state: {app_package}")
            self.remote.execute_command('close_app', {'package': app_package})
            time.sleep(1)
            self.remote.execute_command('launch_app', {'package': app_package, 'wait_time': 4000})
            time.sleep(2)

        if self.is_tv:
            return self._crawl_dpad(app_package)
        else:
            return self._crawl_click(app_package)

    # ------------------------------------------------------------------
    # TV MODE: D-pad remote (DOWN/OK/BACK/LEFT)
    # ------------------------------------------------------------------

    def _crawl_dpad(self, app_package: str) -> Dict[str, Any]:
        """Crawl a TV app using D-pad remote — like a real user with a remote."""
        start_time = time.time()
        site_map = {}
        visited_hashes: Set[str] = set()
        skipped_count = 0

        print(f"[@crawler:android:tv] D-pad crawl (app={app_package}, max_pages={self.max_pages})")

        # Phase 0: Dismiss any popups/dialogs
        self._dismiss_popups()

        # Phase 1: Record home screen
        elements = self._dump_screen()
        if not elements:
            return self._build_result(site_map, skipped_count, start_time)

        home_hash = _android_screen_id(elements)
        home_id = self._record_screen(elements, site_map, visited_hashes, None, None)

        # Phase 2: Press DOWN×N + OK to explore each row
        max_rows = min(self.max_pages, 6)
        for row in range(max_rows):
            if len(site_map) >= self.max_pages:
                break

            self.remote.press_key('DOWN')
            time.sleep(0.3)
            self.remote.press_key('OK')
            time.sleep(1.0)

            elements = self._dump_screen()
            if elements:
                self._record_screen(elements, site_map, visited_hashes, home_id, f'DOWN×{row+1}+OK')

            self.remote.press_key('BACK')
            time.sleep(0.5)

        # Phase 3: Side menu via LEFT
        if len(site_map) < self.max_pages:
            # Return to home first
            self.remote.press_key('HOME')
            time.sleep(0.5)
            self.remote.press_key('LEFT')
            time.sleep(0.5)

            elements = self._dump_screen()
            if elements:
                menu_hash = _android_screen_id(elements)
                if menu_hash != home_hash:
                    menu_id = self._record_screen(elements, site_map, visited_hashes, home_id, 'LEFT (menu)')

                    max_menu = min(5, self.max_pages - len(site_map))
                    for i in range(max_menu):
                        self.remote.press_key('DOWN')
                        time.sleep(0.2)
                        self.remote.press_key('OK')
                        time.sleep(1.0)

                        elements = self._dump_screen()
                        if elements:
                            self._record_screen(elements, site_map, visited_hashes,
                                                menu_id or home_id, f'MENU→{i+1}')

                        self.remote.press_key('BACK')
                        time.sleep(0.3)

        return self._build_result(site_map, skipped_count, start_time)

    # ------------------------------------------------------------------
    # MOBILE/TABLET MODE: click_element (ADB coordinate tap)
    # ------------------------------------------------------------------

    def _crawl_click(self, app_package: str) -> Dict[str, Any]:
        """Crawl a mobile/tablet app using click_element (ADB tap)."""
        start_time = time.time()
        site_map = {}
        visited_hashes: Set[str] = set()
        skipped_count = 0

        queue: deque = deque()
        queue.append((None, None, 0))

        print(f"[@crawler:android:click] Click crawl (app={app_package}, max_pages={self.max_pages})")

        # Dismiss any popups/dialogs
        self._dismiss_popups()

        while queue and len(site_map) < self.max_pages:
            parent_id, click_item, depth = queue.popleft()

            if click_item:
                click_text = click_item['text']
                print(f"[@crawler:android:click] [{len(site_map)+1}/{self.max_pages}] depth={depth} → '{click_text}'")
                result = self.remote.click_element(click_text)
                success = result.get('success', False) if isinstance(result, dict) else bool(result)
                if not success:
                    skipped_count += 1
                    continue
                time.sleep(1.0)

                if app_package:
                    current_pkg = self._get_foreground_package()
                    if current_pkg and current_pkg != app_package:
                        self.remote.press_key('BACK')
                        time.sleep(0.8)
                        skipped_count += 1
                        continue

            elements = self._dump_screen()
            if not elements:
                if click_item:
                    self.remote.press_key('BACK')
                    time.sleep(0.5)
                continue

            screen_id = self._record_screen(elements, site_map, visited_hashes,
                                            parent_id, click_item['text'] if click_item else None)
            if not screen_id:
                if click_item:
                    self.remote.press_key('BACK')
                    time.sleep(0.5)
                continue

            if depth < self.max_depth:
                nav_items = _extract_navigable_android_items(elements)
                for item in nav_items:
                    if len(site_map) >= self.max_pages:
                        break
                    if _should_skip(item['text'], self.skip_patterns):
                        skipped_count += 1
                        continue
                    queue.append((screen_id, item, depth + 1))

            if click_item:
                self.remote.press_key('BACK')
                time.sleep(0.8)

        return self._build_result(site_map, skipped_count, start_time)

    # ------------------------------------------------------------------

    def _build_result(self, site_map: Dict, skipped_count: int, start_time: float) -> Dict[str, Any]:
        crawl_time_ms = int((time.time() - start_time) * 1000)
        root_id = list(site_map.keys())[0] if site_map else 'home'
        tree_view = _build_tree_view(site_map, root_id)
        mode = 'dpad' if self.is_tv else 'click'
        print(f"[@crawler:android:{mode}] Done. {len(site_map)} screens in {crawl_time_ms}ms")

        return {
            'success': True, 'platform': f'android_{mode}',
            'screens_found': len(site_map) + skipped_count,
            'screens_explored': len(site_map), 'screens_skipped': skipped_count,
            'site_map': site_map, 'tree_view': tree_view, 'crawl_time_ms': crawl_time_ms,
        }
