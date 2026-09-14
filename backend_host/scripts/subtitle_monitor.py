#!/usr/bin/env python3
"""
Subtitle OCR Monitor - processes subtitle detection in dedicated process

OPTIMIZATIONS:
- Skip if freeze/blackscreen/no audio → ~70% fewer OCR calls
- Configurable downscale (default 33% = 89% fewer pixels)
- Optional binarization (black/white) before OCR → ~20% faster  
- Language caching per device (2min) → 2x faster after first detection
- Round-robin processing (1s delay per device)
- LIFO queue (newest frames first, max 10 per device)

DISABLED (too slow for real-time):
- Spell checking (adds 200-500ms per OCR)

PERFORMANCE TUNING:
- Edit DOWNSCALE_FACTOR (line 28) to test different resize percentages
- Edit ENABLE_BINARIZATION (line 29) to toggle black/white conversion
- Edit ENABLE_SPELLCHECK (line 30) to enable/disable spell correction

EXPECTED PERFORMANCE (without spellcheck):
- OCR time: 50-100ms (was 200-300ms)
- Total per frame: 80-150ms (was 300-500ms)

WITH SPELLCHECK ENABLED (adds 200-500ms):
- Corrects misspelled words (e.g., "helo" → "hello")
- Filters garbage text (replaces unknown words)
- Shows corrections in logs with timing
"""

# ============================================================================
# PERFORMANCE TUNING FLAGS
# ============================================================================
DOWNSCALE_FACTOR = 0.5      # Resize factor (0.33 = 33% = 89% fewer pixels, 0.5 = 50% = 75% fewer pixels)
ENABLE_BINARIZATION = False  # Set to False to disable binarization for speed comparison
ENABLE_SPELLCHECK = False    # Set to True to enable spell checking (SLOW: adds 200-500ms per OCR)
ENABLE_DYNAMIC_ROI = True    # Set to True to auto-detect subtitle ROI per device and reuse it

# Garbage filters (cheap — no extra OCR pass, no localize dependency):
# 1) Per-word OCR confidence: image_to_data gives a confidence per word at the
#    SAME cost as image_to_string. We drop words below MIN_WORD_CONFIDENCE,
#    which removes most OCR noise tokens ('"2S', 'Gf', 'rn', ...) at the source.
# 2) Dictionary ratio: kept words must be mostly real words for the active
#    language. pyspellchecker membership is O(1) (only .correction() is slow),
#    so this is effectively free after a one-time per-language dictionary load.
ENABLE_WORD_CONFIDENCE = True  # Drop low-confidence OCR words before assembling text
MIN_WORD_CONFIDENCE = 60       # Tesseract per-word conf (0-100); below this = noise
ENABLE_DICTIONARY_FILTER = True  # Reject text that isn't mostly real dictionary words
MIN_KNOWN_WORD_RATIO = 0.6     # >= this fraction of candidate words must be real
MIN_REAL_WORDS = 2             # Need at least this many >=3-letter words to consider
# ============================================================================

import os
os.environ['OMP_NUM_THREADS'] = '4'
os.environ['MKL_NUM_THREADS'] = '4'
os.environ['OPENBLAS_NUM_THREADS'] = '4'

import sys
import json
import logging
import queue
import threading
import time
import cv2
import numpy as np
import re
import platform

# Cross-platform file monitoring: inotify on Linux, watchdog on macOS
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

if IS_LINUX:
    import inotify.adapters
else:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

# Setup project root BEFORE importing from shared
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# Now import from shared (after path is set up)
from shared.src.lib.utils.audio_transcription_utils import clean_transcript_text

# Spell checker import (only used if ENABLE_SPELLCHECK=True)
try:
    from spellchecker import SpellChecker
    SPELLCHECKER_AVAILABLE = True
except ImportError:
    SPELLCHECKER_AVAILABLE = False

from shared.src.lib.utils.storage_path_utils import (
    get_capture_base_directories,
    get_capture_folder,
    get_metadata_path,
    get_captures_path
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None
    PYTESSERACT_AVAILABLE = False

try:
    from langdetect import detect_langs, DetectorFactory
    # Deterministic results: without a fixed seed langdetect can flip the label
    # of the same text between runs.
    DetectorFactory.seed = 0
    LANGDETECT_AVAILABLE = True
except ImportError:
    detect_langs = None
    LANGDETECT_AVAILABLE = False

try:
    from crop_subtitles import find_subtitle_bbox
    DYNAMIC_ROI_AVAILABLE = True
except ImportError:
    find_subtitle_bbox = None
    DYNAMIC_ROI_AVAILABLE = False

# Language mapping: langdetect (2-letter) -> Tesseract (3-letter)
LANG_MAP = {
    'en': 'eng',
    'fr': 'fra',
    'de': 'deu',
    'es': 'spa',
    'it': 'ita'
}

# Tesseract 3-letter code -> pyspellchecker 2-letter dictionary code.
# Only these langs have a bundled pyspellchecker dictionary.
TESS_TO_DICT = {
    'eng': 'en',
    'fra': 'fr',
    'deu': 'de',
    'spa': 'es',
    'ita': 'it',
}

# Only ever report a language we actually support (the OCR languages above).
# OCR noise otherwise gets mislabelled as random langs like 'af'/'tl'.
SUPPORTED_LANGS = set(LANG_MAP.keys())
# Minimum langdetect probability before we trust a label; below this -> 'unknown'.
LANG_MIN_CONFIDENCE = 0.90


def detect_supported_language(text):
    """Return the best-matching SUPPORTED language for `text`, or 'unknown'.

    Guards against OCR garbage: only a high-confidence match within the
    supported set is accepted; anything else (low confidence, or a language
    we don't OCR) becomes 'unknown' instead of a random label like 'af'/'tl'.
    """
    if not LANGDETECT_AVAILABLE:
        raise RuntimeError("langdetect not available")
    for cand in detect_langs(text):  # sorted by probability, descending
        if cand.lang in SUPPORTED_LANGS:
            return cand.lang if cand.prob >= LANG_MIN_CONFIDENCE else 'unknown'
    return 'unknown'

class SubtitleMonitor:
    """Subtitle OCR monitor - cross-platform (inotify on Linux, watchdog on macOS)"""
    
    def __init__(self, capture_dirs):
        # Platform-specific file watcher initialization
        if IS_LINUX:
            self.inotify = inotify.adapters.Inotify()
            self._watcher_type = 'inotify'
        else:
            self.observer = Observer()
            self._watcher_type = 'watchdog'
        
        self.path_to_folder = {}
        self.capture_dirs_map = {}
        self.queues = {}
        self.ocr_worker = None
        self.worker_running = False
        
        # Language cache per device: {capture_folder: (timestamp, detected_language)}
        # Reuse language for 2 minutes before detecting again
        self.language_cache = {}
        self.dynamic_roi_cache = {}
        self.dynamic_roi_state = {}
        # Lazily-loaded pyspellchecker dictionaries, keyed by 2-letter code.
        # Loaded once (~0.4s each) then reused; membership lookups are O(1).
        self._dictionaries = {}
        
        for capture_dir in capture_dirs:
            capture_folder = get_capture_folder(capture_dir)
            metadata_dir = get_metadata_path(capture_folder)
            os.makedirs(metadata_dir, mode=0o777, exist_ok=True)
            
            if os.path.exists(metadata_dir):
                if IS_LINUX:
                    self.inotify.add_watch(metadata_dir)
                # macOS watchdog scheduling happens in run()
                self.path_to_folder[metadata_dir] = {
                    'capture_folder': capture_folder,
                    'captures_dir': capture_dir
                }
                self.capture_dirs_map[capture_folder] = capture_dir
                logger.info(f"Watching: {metadata_dir} -> {capture_folder}")
            
            self.queues[capture_folder] = queue.LifoQueue(maxsize=10)
        
        self._start_ocr_worker()
    
    def _start_ocr_worker(self):
        self.worker_running = True
        self.ocr_worker = threading.Thread(
            target=self._round_robin_worker,
            daemon=True,
            name="ocr-worker"
        )
        self.ocr_worker.start()
        binarize_status = "ON" if ENABLE_BINARIZATION else "OFF"
        spellcheck_status = "ON" if ENABLE_SPELLCHECK else "OFF"
        dynamic_roi_status = "ON" if (ENABLE_DYNAMIC_ROI and DYNAMIC_ROI_AVAILABLE) else "OFF"
        downscale_pct = int(DOWNSCALE_FACTOR * 100)
        logger.info(f"OCR worker started (resize={downscale_pct}% + binarization={binarize_status} + spellcheck={spellcheck_status} + dynamic_roi={dynamic_roi_status} + language caching)")
    
    def _round_robin_worker(self):
        devices = list(self.queues.keys())
        if not devices:
            return
        
        device_index = 0
        
        while self.worker_running:
            capture_folder = devices[device_index]
            work_queue = self.queues[capture_folder]
            captures_dir = self.capture_dirs_map[capture_folder]
            processed_item = False
            
            try:
                json_path = work_queue.get_nowait()
                
                try:
                    self.process_ocr(json_path, captures_dir, capture_folder)
                except Exception as e:
                    logger.error(f"[{capture_folder}] OCR error: {e}")
                
                work_queue.task_done()
                processed_item = True
                
            except queue.Empty:
                pass
            
            device_index = (device_index + 1) % len(devices)
            # Keep latency low under load while avoiding busy-spinning when queues are empty.
            time.sleep(0.01 if processed_item else 0.05)

    def _static_roi(self, img_width, img_height):
        return (
            int(img_width * 0.10),
            int(img_height * 0.60),
            int(img_width * 0.80),
            int(img_height * 0.35),
            'static'
        )

    def _get_subtitle_roi(self, capture_folder, img):
        img_height, img_width = img.shape
        static_roi = self._static_roi(img_width, img_height)

        if not ENABLE_DYNAMIC_ROI or not DYNAMIC_ROI_AVAILABLE:
            return static_roi

        cached = self.dynamic_roi_cache.get(capture_folder)
        if cached:
            return cached

        state = self.dynamic_roi_state.setdefault(capture_folder, {
            'attempts': 0,
            'last_attempt_ts': 0.0
        })
        now_ts = time.time()
        # Avoid retrying expensive ROI detection too frequently when it fails.
        if state['attempts'] > 0 and (now_ts - state['last_attempt_ts']) < 15.0:
            return static_roi

        state['attempts'] += 1
        state['last_attempt_ts'] = now_ts

        try:
            bbox = find_subtitle_bbox(img)
            x, y, w, h = bbox.as_tuple()
            x = max(0, min(x, img_width - 1))
            y = max(0, min(y, img_height - 1))
            w = max(1, min(w, img_width - x))
            h = max(1, min(h, img_height - y))
            roi = (x, y, w, h, 'dynamic')
            self.dynamic_roi_cache[capture_folder] = roi
            logger.info(f"[{capture_folder}] ✅ Dynamic subtitle ROI calibrated: x={x}, y={y}, w={w}, h={h}")
            return roi
        except Exception as e:
            if state['attempts'] <= 3:
                logger.info(f"[{capture_folder}] Dynamic ROI calibration pending (attempt {state['attempts']}): {e}")
            return static_roi
    
    def _get_dictionaries(self, lang_config):
        """Return pyspellchecker dictionaries for the active OCR languages.

        `lang_config` is a Tesseract spec like 'deu' or 'eng+deu+fra'. We load
        each corresponding dictionary once and cache it. Membership lookups are
        O(1), so the only cost is the one-time per-language load.
        """
        if not SPELLCHECKER_AVAILABLE:
            return []
        dicts = []
        for tess_code in lang_config.split('+'):
            dict_code = TESS_TO_DICT.get(tess_code.strip())
            if not dict_code:
                continue
            spell = self._dictionaries.get(dict_code)
            if spell is None:
                try:
                    spell = SpellChecker(language=dict_code)
                    self._dictionaries[dict_code] = spell
                    logger.info(f"Loaded '{dict_code}' dictionary ({len(spell.word_frequency.dictionary)} words)")
                except Exception as e:
                    logger.warning(f"Failed to load '{dict_code}' dictionary: {e}")
                    self._dictionaries[dict_code] = False  # cache the failure
                    continue
            if spell:
                dicts.append(spell)
        return dicts

    def _dictionary_ratio(self, text, dicts):
        """Fraction of candidate (>=3-letter) words that are real words.

        Returns (ratio, real_word_count). A word counts as known if it is in
        ANY of the active-language dictionaries. Returns (1.0, n) when no
        dictionaries are available so the filter fails open.
        """
        candidates = [w for w in re.findall(r"[A-Za-zÀ-ÿ']+", text) if len(w) >= 3]
        if not candidates:
            return 0.0, 0
        if not dicts:
            return 1.0, len(candidates)
        known = 0
        for w in candidates:
            wl = w.lower()
            if any(wl in d for d in dicts):
                known += 1
        return known / len(candidates), len(candidates)

    def process_ocr(self, json_path, captures_dir, capture_folder):
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        # Skip OCR if no audio detected (no content = no subtitles)
        if not data.get('audio', True):
            logger.info(f"[{capture_folder}] ⊗ SKIP: No audio (no content to subtitle)")
            data['subtitle_analysis'] = {
                'has_subtitles': False,
                'extracted_text': '',
                'skipped': True,
                'skip_reason': 'no_audio'
            }
            data['subtitle_ocr_pending'] = False
            
            with open(json_path + '.tmp', 'w') as f:
                json.dump(data, f, indent=2)
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(json_path + '.tmp', json_path)
            return
        
        frame_file = os.path.basename(json_path).replace('.json', '.jpg')
        frame_path = os.path.join(captures_dir, frame_file)
        
        # Log detection state with full paths
        audio = "🔇" if not data.get('audio', True) else "🔊"
        freeze = "❄️" if data.get('freeze', False) else ""
        black = "⬛" if data.get('blackscreen', False) else ""
        logger.info(f"[{capture_folder}] Processing frame: {frame_path} {audio}{freeze}{black}")
        logger.info(f"[{capture_folder}]    └─ JSON: {json_path}")
        
        if not data.get('subtitle_ocr_pending', False):
            logger.info(f"[{capture_folder}] ⊗ Skip: no OCR pending")
            return
        
        # Skip OCR if freeze detected (frozen frame = no new subtitles)
        if data.get('freeze', False):
            logger.info(f"[{capture_folder}] ⊗ SKIP: Freeze detected (no new content)")
            data['subtitle_analysis'] = {
                'has_subtitles': False,
                'extracted_text': '',
                'skipped': True,
                'skip_reason': 'freeze'
            }
            data['subtitle_ocr_pending'] = False
            with open(json_path + '.tmp', 'w') as f:
                json.dump(data, f, indent=2)
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(json_path + '.tmp', json_path)
            return
        
        # Skip OCR if blackscreen detected (no content = no subtitles)
        if data.get('blackscreen', False):
            logger.info(f"[{capture_folder}] ⊗ SKIP: Blackscreen (no content)")
            data['subtitle_analysis'] = {
                'has_subtitles': False,
                'extracted_text': '',
                'skipped': True,
                'skip_reason': 'blackscreen'
            }
            data['subtitle_ocr_pending'] = False
            with open(json_path + '.tmp', 'w') as f:
                json.dump(data, f, indent=2)
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(json_path + '.tmp', json_path)
            return
        
        if not os.path.exists(frame_path):
            logger.error(f"[{capture_folder}] ⊗ Skip: image deleted")
            return
        
        try:
            start_total = time.perf_counter()
            img = cv2.imread(frame_path, cv2.IMREAD_GRAYSCALE)
            
            if img is None:
                return
            
            img_height, img_width = img.shape
            
            # Crop early so edge detection runs only in subtitle-prone region.
            start_crop = time.perf_counter()
            x, y, w, h, roi_mode = self._get_subtitle_roi(capture_folder, img)
            crop = img[y:y+h, x:x+w]
            crop_time = (time.perf_counter() - start_crop) * 1000

            # Edge detection in the lower portion of the crop for quick subtitle presence gating.
            start_edge = time.perf_counter()
            probe_start = int(crop.shape[0] * 0.70)
            edge_probe = crop[probe_start:, :]
            edges_subtitle = cv2.Canny(edge_probe, 50, 150)
            subtitle_edge_density = np.sum(edges_subtitle > 0) / edges_subtitle.size * 100
            edge_time = (time.perf_counter() - start_edge) * 1000
            
            if not (0.9 < subtitle_edge_density < 8):
                logger.info(f"[{capture_folder}] ⊗ SKIP: No subtitle edges detected")
                logger.info(f"[{capture_folder}]    └─ Edge density: {subtitle_edge_density:.1f}% (need 0.9-8%)")
                data['subtitle_analysis'] = {
                    'has_subtitles': False,
                    'extracted_text': '',
                    'subtitle_edge_density': round(subtitle_edge_density, 1),
                    'box': {'x': x, 'y': y, 'width': w, 'height': h},
                    'roi_mode': roi_mode,
                    'skipped': True,
                    'skip_reason': 'no_edges'
                }
            else:
                # Downscale - reduces pixels for faster OCR
                start_down = time.perf_counter()
                crop = cv2.resize(crop, None, fx=DOWNSCALE_FACTOR, fy=DOWNSCALE_FACTOR, interpolation=cv2.INTER_AREA)
                down_h, down_w = crop.shape
                down_time = (time.perf_counter() - start_down) * 1000
                
                # Calculate actual pixel reduction
                original_pixels = w * h
                downscaled_pixels = down_w * down_h
                pixel_reduction_pct = ((original_pixels - downscaled_pixels) / original_pixels) * 100
                
                # Binarization (black/white only) - 20% faster OCR (OPTIONAL)
                start_binarize = time.perf_counter()
                if ENABLE_BINARIZATION:
                    _, crop = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                binarize_time = (time.perf_counter() - start_binarize) * 1000
                
                # Get cached language or use default (reuse language for 2 minutes)
                current_time = time.time()
                cached_lang = None
                lang_config = 'eng+deu+fra'  # Default
                lang_cached = False
                
                if capture_folder in self.language_cache:
                    cache_time, cached_lang = self.language_cache[capture_folder]
                    cache_age = current_time - cache_time
                    if cache_age < 120:  # 2 minutes
                        # Map detected language (en/fr/de) to Tesseract code (eng/fra/deu)
                        tesseract_lang = LANG_MAP.get(cached_lang, 'eng')
                        lang_config = tesseract_lang
                        lang_cached = True
                        logger.info(f"[{capture_folder}] 🔄 Using cached language: {cached_lang} → {tesseract_lang} (age={cache_age:.0f}s)")
                
                # OCR
                start_ocr = time.perf_counter()
                if not PYTESSERACT_AVAILABLE:
                    raise RuntimeError("pytesseract not available")
                if ENABLE_WORD_CONFIDENCE:
                    # image_to_data is the SAME single OCR pass as image_to_string,
                    # but also yields a per-word confidence we use to drop noise.
                    ocr_data = pytesseract.image_to_data(
                        crop,
                        config=f'--psm 6 --oem 1 -l {lang_config}',
                        timeout=2,
                        output_type=pytesseract.Output.DICT
                    )
                    lines_by_id = {}
                    dropped_low_conf = 0
                    for i, word in enumerate(ocr_data['text']):
                        word = word.strip()
                        if not word:
                            continue
                        try:
                            conf = float(ocr_data['conf'][i])
                        except (ValueError, TypeError):
                            conf = -1
                        if conf < MIN_WORD_CONFIDENCE:
                            dropped_low_conf += 1
                            continue
                        line_id = (ocr_data['block_num'][i], ocr_data['par_num'][i], ocr_data['line_num'][i])
                        lines_by_id.setdefault(line_id, []).append(word)
                    text = '\n'.join(' '.join(lines_by_id[k]) for k in sorted(lines_by_id)).strip()
                else:
                    text = pytesseract.image_to_string(
                        crop,
                        config=f'--psm 6 --oem 1 -l {lang_config}',
                        timeout=2
                    ).strip()
                    dropped_low_conf = 0
                ocr_time = (time.perf_counter() - start_ocr) * 1000

                # Clean OCR noise
                if text:
                    lines = text.split('\n')
                    cleaned = []
                    for line in lines:
                        words = line.split()
                        real = [w for w in words if len(re.sub(r'[^a-zA-Z]', '', w)) >= 3]
                        if real:
                            cleaned.append(line.strip())
                    text = '\n'.join(cleaned).strip()
                
                # Apply shared regex-based filter
                text_before_spellcheck = text
                text = clean_transcript_text(text)

                # Dictionary gate: real subtitles are mostly real words. OCR
                # noise ('"2S Gf LES rn', 'Kai E El Fr', ...) has a low ratio of
                # known words and gets rejected here. Cheap: O(1) lookups after a
                # one-time per-language dictionary load.
                dict_ratio = None
                if ENABLE_DICTIONARY_FILTER and text:
                    dicts = self._get_dictionaries(lang_config)
                    dict_ratio, real_word_count = self._dictionary_ratio(text, dicts)
                    if real_word_count < MIN_REAL_WORDS or dict_ratio < MIN_KNOWN_WORD_RATIO:
                        logger.info(f"[{capture_folder}] ⊗ REJECT: not real words (ratio={dict_ratio:.2f}, words={real_word_count}) '{text[:50]}'")
                        text = ''
                
                # Spell checking (optional - measures time and shows corrections)
                spell_time = 0
                spell_corrections = 0
                spell_status = "disabled"
                
                if ENABLE_SPELLCHECK and SPELLCHECKER_AVAILABLE and text:
                    start_spell = time.perf_counter()
                    try:
                        # Initialize spell checker (cached after first use)
                        if not hasattr(self, '_spell_checker'):
                            self._spell_checker = SpellChecker()
                        
                        spell = self._spell_checker
                        words = text.split()
                        corrected_words = []
                        corrections_made = []
                        
                        for word in words:
                            # Only check words with letters (skip numbers, punctuation)
                            if any(c.isalpha() for c in word):
                                # Get correction
                                corrected = spell.correction(word.lower())
                                if corrected and corrected != word.lower():
                                    # Word was corrected
                                    corrected_words.append(corrected)
                                    corrections_made.append(f"{word}→{corrected}")
                                    spell_corrections += 1
                                else:
                                    corrected_words.append(word)
                            else:
                                corrected_words.append(word)
                        
                        text = ' '.join(corrected_words)
                        spell_time = (time.perf_counter() - start_spell) * 1000
                        spell_status = f"corrected {spell_corrections} words" if spell_corrections > 0 else "no corrections"
                        
                        if corrections_made:
                            logger.info(f"[{capture_folder}] ✏️  Spell corrections: {', '.join(corrections_made[:5])}")
                            
                    except Exception as e:
                        spell_time = (time.perf_counter() - start_spell) * 1000
                        spell_status = f"error: {str(e)[:30]}"
                        logger.warning(f"[{capture_folder}] Spell check error: {e}")
                elif ENABLE_SPELLCHECK and not SPELLCHECKER_AVAILABLE:
                    spell_status = "unavailable (install pyspellchecker)"
                
                # Detect language if text found and not cached (or cache expired)
                detected_language = None
                if text and len(text) > 10:  # Only detect if meaningful text
                    # Check if we should detect language (no cache or cache expired)
                    should_detect_language = True
                    if capture_folder in self.language_cache:
                        cache_time, cached_lang = self.language_cache[capture_folder]
                        if current_time - cache_time < 120:  # 2 minutes
                            should_detect_language = False
                            detected_language = cached_lang
                    
                    if should_detect_language:
                        # Detect language and cache for 2 minutes
                        start_lang = time.perf_counter()
                        try:
                            detected_language = detect_supported_language(text)
                            # Update cache
                            self.language_cache[capture_folder] = (current_time, detected_language)
                            lang_time = (time.perf_counter() - start_lang) * 1000
                            logger.info(f"[{capture_folder}] 🌐 Detected language: {detected_language} ({lang_time:.0f}ms) - cached for 2min")
                        except Exception as e:
                            detected_language = 'unknown'
                            logger.debug(f"[{capture_folder}] Language detection failed: {e}")
                
                total_time = (time.perf_counter() - start_total) * 1000
                
                # Calculate preprocessing time (everything except OCR)
                preprocess_time = crop_time + down_time + binarize_time
                
                data['subtitle_analysis'] = {
                    'has_subtitles': bool(text),
                    'extracted_text': text,
                    'detected_language': detected_language,
                    'subtitle_edge_density': round(subtitle_edge_density, 1),
                    'box': {'x': x, 'y': y, 'width': w, 'height': h},
                    'roi_mode': roi_mode,
                    'skipped': False,
                    'ocr_time_ms': round(ocr_time, 2),
                    'downscale_factor': DOWNSCALE_FACTOR,
                    'pixel_reduction_pct': round(pixel_reduction_pct, 1),
                    'binarized': ENABLE_BINARIZATION,
                    'dict_ratio': round(dict_ratio, 2) if dict_ratio is not None else None,
                    'words_dropped_low_conf': dropped_low_conf
                }
                
                # Clear, readable logging showing what happened
                binarize_status = "ON" if ENABLE_BINARIZATION else "OFF"
                downscale_pct = int(DOWNSCALE_FACTOR * 100)
                
                if text:
                    lang_str = f" [{detected_language}]" if detected_language else ""
                    if lang_cached:
                        lang_method = f" (cached, single lang)"
                        lang_info = f"lang={lang_config} ⚡"
                    else:
                        lang_method = f" (3 languages)"
                        lang_info = f"lang={lang_config}"
                    
                    logger.info(f"[{capture_folder}] 📝 TEXT FOUND{lang_str}:")
                    logger.info(f"[{capture_folder}]    └─ '{text[:70]}'")
                    logger.info(f"[{capture_folder}]    └─ Image: {w}x{h} → {down_w}x{down_h} (resize={downscale_pct}%, {pixel_reduction_pct:.0f}% fewer pixels)")
                    logger.info(f"[{capture_folder}]    └─ Preprocessing: crop={crop_time:.0f}ms + resize={down_time:.0f}ms + binarize={binarize_time:.0f}ms [bin={binarize_status}] = {preprocess_time:.0f}ms")
                    logger.info(f"[{capture_folder}]    └─ OCR{lang_method}: {ocr_time:.0f}ms (Tesseract {lang_info})")
                    if ENABLE_SPELLCHECK:
                        logger.info(f"[{capture_folder}]    └─ Spellcheck: {spell_time:.0f}ms ({spell_status})")
                    logger.info(f"[{capture_folder}]    └─ TOTAL: {total_time:.0f}ms ({len(text)} chars)")
                else:
                    if lang_cached:
                        lang_info = f" (cached {lang_config})"
                    else:
                        lang_info = f" ({lang_config})"
                    logger.info(f"[{capture_folder}] ⊗ NO TEXT")
                    logger.info(f"[{capture_folder}]    └─ Resize: {downscale_pct}% ({pixel_reduction_pct:.0f}% fewer pixels) | Preprocess: {preprocess_time:.0f}ms [bin={binarize_status}] | OCR{lang_info}: {ocr_time:.0f}ms | Total: {total_time:.0f}ms")
        
        except Exception as e:
            data['subtitle_analysis'] = {
                'has_subtitles': False,
                'extracted_text': '',
                'error': str(e)
            }
        
        data['subtitle_ocr_pending'] = False
        
        with open(json_path + '.tmp', 'w') as f:
            json.dump(data, f, indent=2)
        # Windows-safe atomic overwrite (os.rename fails if destination exists)
        os.replace(json_path + '.tmp', json_path)
    
    def _handle_json_event(self, path, filename):
        """Handle JSON file event from either inotify or watchdog"""
        if not filename.endswith('.json'):
            return
        
        if path in self.path_to_folder:
            capture_folder = self.path_to_folder[path]['capture_folder']
            json_path = os.path.join(path, filename)
            work_queue = self.queues[capture_folder]
            
            try:
                work_queue.put_nowait(json_path)
            except queue.Full:
                try:
                    work_queue.get_nowait()
                    work_queue.put_nowait(json_path)
                except:
                    pass
    
    def run(self):
        """Main event loop - cross-platform"""
        if IS_LINUX:
            self._run_inotify()
        else:
            self._run_watchdog()
    
    def _run_inotify(self):
        """Linux inotify event loop"""
        try:
            for event in self.inotify.event_gen(yield_nones=False):
                (_, type_names, path, filename) = event
                
                if 'IN_CLOSE_WRITE' not in type_names and 'IN_MOVED_TO' not in type_names:
                    continue
                
                self._handle_json_event(path, filename)
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            for path in self.path_to_folder.keys():
                try:
                    self.inotify.remove_watch(path)
                except:
                    pass
    
    def _run_watchdog(self):
        """macOS/cross-platform watchdog event loop"""
        monitor = self
        
        class JSONEventHandler(FileSystemEventHandler):
            def on_moved(self, event):
                if event.is_directory:
                    return
                path = os.path.dirname(event.dest_path)
                filename = os.path.basename(event.dest_path)
                monitor._handle_json_event(path, filename)
            
            def on_created(self, event):
                if event.is_directory:
                    return
                path = os.path.dirname(event.src_path)
                filename = os.path.basename(event.src_path)
                if not filename.startswith('.'):
                    time.sleep(0.05)
                    monitor._handle_json_event(path, filename)
            
            def on_modified(self, event):
                if event.is_directory:
                    return
                path = os.path.dirname(event.src_path)
                filename = os.path.basename(event.src_path)
                if not filename.startswith('.'):
                    monitor._handle_json_event(path, filename)
        
        event_handler = JSONEventHandler()
        
        for path in self.path_to_folder.keys():
            if os.path.exists(path):
                self.observer.schedule(event_handler, path, recursive=False)
                logger.info(f"Watchdog watching: {path}")
        
        try:
            self.observer.start()
            logger.info("Watchdog observer started")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.observer.stop()
            self.observer.join()

def main():
    from shared.src.lib.utils.system_utils import kill_existing_script_instances
    
    killed = kill_existing_script_instances('subtitle_monitor.py')
    if killed:
        logger.info(f"Killed existing instances: {killed}")
        time.sleep(1)
    
    base_dirs = get_capture_base_directories()
    capture_dirs = []
    
    for base_dir in base_dirs:
        device_folder = os.path.basename(base_dir)
        capture_path = get_captures_path(device_folder)
        capture_dirs.append(capture_path)
    
    binarize_status = "ENABLED" if ENABLE_BINARIZATION else "DISABLED"
    spellcheck_status = "ENABLED" if ENABLE_SPELLCHECK else "DISABLED"
    dynamic_roi_status = "ENABLED" if (ENABLE_DYNAMIC_ROI and DYNAMIC_ROI_AVAILABLE) else "DISABLED"
    downscale_pct = int(DOWNSCALE_FACTOR * 100)
    pixel_reduction = int((1 - DOWNSCALE_FACTOR**2) * 100)
    
    logger.info("=" * 80)
    logger.info("Subtitle OCR Monitor - OPTIMIZED")
    logger.info(f"- Downscale: {downscale_pct}% ({pixel_reduction}% fewer pixels)")
    logger.info(f"- Binarization: {binarize_status} (black/white for faster OCR)")
    logger.info(f"- Spellcheck: {spellcheck_status} (corrects misspelled words)")
    logger.info(f"- Dynamic ROI: {dynamic_roi_status} (auto-calibrates subtitle area per device)")
    logger.info("- Language caching (2min per device)")
    logger.info("=" * 80)
    logger.info(f"Monitoring {len(capture_dirs)} devices (queue: 10 most recent per device)")
    
    monitor = SubtitleMonitor(capture_dirs)
    monitor.run()

if __name__ == '__main__':
    main()
