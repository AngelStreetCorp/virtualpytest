"""
Text Helpers

Simple text processing helpers for 3 core operations:
1. Detect text from image in area
2. Wait for text to appear  
3. Wait for text to disappear

Includes: crop, filter (greyscale/binary), OCR, language detection
"""

import os
import requests
import tempfile
import json
import time
import cv2
import numpy as np
import subprocess
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse


class TextHelpers:
    """Simple text processing helpers for core operations."""
    
    def __init__(self, captures_path: str):
        """Initialize text helpers with captures path."""
        self.captures_path = captures_path

    def _purge_stale_debug_images(self, max_age_s: int = 600) -> None:
        """Delete text_detection_* artifacts older than max_age_s from captures_path.

        These per-call OCR debug/overlay images have no other owner: the archiver's
        rotation only matches capture_*.jpg, so anything left here lives until the
        hot tmpfs (200MB) is full. Callers invoke this before writing new ones.
        """
        cutoff = time.time() - max_age_s
        try:
            with os.scandir(self.captures_path) as it:
                for entry in it:
                    if not entry.name.startswith('text_detection_'):
                        continue
                    try:
                        if entry.is_file(follow_symlinks=False) and \
                                entry.stat(follow_symlinks=False).st_mtime < cutoff:
                            os.remove(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass

    def download_image(self, source_url: str) -> str:
        """Download image from URL only."""
        try:
            response = requests.get(source_url, timeout=30)
            response.raise_for_status()
            
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp.write(response.content)
                return tmp.name
                
        except Exception as e:
            print(f"[@text_helpers] Error downloading image from URL: {e}")
            raise
    
    def save_text_reference(self, text: str, reference_name: str, userinterface_name: str, team_id: str,
                           area: Dict[str, Any] = None, shared: bool = False) -> Dict[str, Any]:
        """Save text reference to database. When `shared=True`, the row is visible+editable
        by every UI in the team whose models[] intersects with userinterface_name's models[]."""
        try:
            print(f"[@text_helpers] Saving text reference to database: {reference_name} for userinterface: {userinterface_name}")
            
            # Round all area coordinates to integers (pixels should always be integers)
            if area:
                area = {k: round(v) if isinstance(v, (int, float)) else v for k, v in area.items()}
                print(f"[@text_helpers] Rounded area coordinates: {area}")
            
            # Save reference to database
            from shared.src.lib.database.verifications_references_db import save_reference, snapshot_reference_version
            from shared.src.lib.utils.reference_utils import reference_storage_key
            # Rename-stable storage folder = userinterface id (falls back to name if unresolved)
            _ui_folder = reference_storage_key(userinterface_name, team_id)

            # Snapshot the previous text reference (area + text) before the DB
            # update overwrites it. No-op on first capture. Best-effort.
            snapshot_reference_version(reference_name, userinterface_name, 'reference_text', team_id)

            # Create text data structure and merge with area
            text_data = {
                'text': text
            }

            # Merge text data with existing area data
            extended_area = {**(area or {}), **text_data}

            db_result = save_reference(
                name=reference_name,
                userinterface_name=userinterface_name,
                reference_type='reference_text',
                team_id=team_id,
                r2_path=f'text-references/{_ui_folder}/{reference_name}',
                r2_url='',  # Empty URL for text references
                area=extended_area,  # Store text data in area field
                shared=shared,
            )
            
            if not db_result.get('success'):
                return {
                    'success': False,
                    'error': f"Database save failed: {db_result.get('error')}"
                }
            
            print(f"[@text_helpers] Successfully saved text reference to database: {reference_name}")
            
            return {
                'success': True,
                'reference_name': reference_name,
                'reference_id': db_result.get('reference_id'),
                'text_data': text_data
            }
            
        except Exception as e:
            print(f"[@text_helpers] Error saving text reference: {e}")
            return {'success': False, 'error': str(e)}
    
    def detect_text_in_area(self, image_path: str, area: dict = None, use_advanced_ocr: bool = False, char_whitelist: str = None) -> Dict[str, Any]:
        """
        Core function: Detect text from image in area.
        1. Crop to area (if specified)
        2. Apply filters (greyscale + binary)
        3. OCR text extraction
        4. Language detection

        Args:
            image_path: Path to the image file
            area: Optional area dict to crop
            use_advanced_ocr: If True, use multi-approach OCR (for getMenuInfo). If False, use simple OCR (for regular text verification)
            char_whitelist: Optional tesseract char whitelist. When set, tesseract is
                forced to emit ONLY these characters (tessedit_char_whitelist), which
                prevents it from inventing stray symbols on noisy menus. Pass e.g.
                alphanumerics + ".-_+ " when extracting version/serial strings.
                Leave None for unconstrained OCR (default).
        """
        # Reused for every tesseract invocation below (advanced + simple paths).
        wl_args = ['-c', f'tessedit_char_whitelist={char_whitelist}'] if char_whitelist else []
        try:
            if not os.path.exists(image_path):
                return {'extracted_text': '', 'error': 'Image not found', 'image_textdetected_path': ''}
            
            # Load image
            img = cv2.imread(image_path)
            if img is None:
                return {'extracted_text': '', 'error': 'Failed to load image', 'image_textdetected_path': ''}
            
            # Step 1: Crop to area if specified
            if area:
                x, y = int(area['x']), int(area['y'])
                w, h = int(area['width']), int(area['height'])
                
                img_height, img_width = img.shape[:2]
                if x < 0 or y < 0 or x + w > img_width or y + h > img_height:
                    return {'extracted_text': '', 'error': 'Area out of bounds', 'image_textdetected_path': ''}
                
                img = img[y:y+h, x:x+w]
            
            # Step 2: Apply filters for better OCR
            # Convert to greyscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            timestamp = int(time.time())

            # The text_detection_* artifacts below land in the hot captures tmpfs and
            # no rotation matches their names (archiver only rotates capture_*.jpg) —
            # purge our own older ones or they accumulate until the 200MB mount is
            # full and ffmpeg stalls (17k files on host1 capture2, 2026-07-21).
            self._purge_stale_debug_images()
            
            # Save processed image path
            processed_filename = f'text_detection_{timestamp}.png'
            processed_path = os.path.join(self.captures_path, processed_filename)
            cv2.imwrite(processed_path, img)
            
            # Step 3: OCR text extraction
            if use_advanced_ocr:
                # ADVANCED OCR: Multi-approach for difficult text (getMenuInfo)
                print(f"[@text_helpers:OCR] Using ADVANCED multi-approach OCR")
                
                # Save grayscale for debugging
                gray_filename = f'text_detection_{timestamp}_gray.png'
                gray_path = os.path.join(self.captures_path, gray_filename)
                cv2.imwrite(gray_path, gray)
                print(f"[@text_helpers:OCR] Saved grayscale image: {gray_filename}")
                
                # Enhance contrast using CLAHE (Contrast Limited Adaptive Histogram Equalization)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(gray)
                
                # Save enhanced image
                enhanced_filename = f'text_detection_{timestamp}_enhanced.png'
                enhanced_path = os.path.join(self.captures_path, enhanced_filename)
                cv2.imwrite(enhanced_path, enhanced)
                print(f"[@text_helpers:OCR] Saved contrast-enhanced image: {enhanced_filename}")
                # Try multiple preprocessing approaches
                binary_adaptive = cv2.adaptiveThreshold(
                    enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
                )
                _, binary_otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                _, binary_otsu_inv = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                
                # Save preprocessed versions
                adaptive_filename = f'text_detection_{timestamp}_adaptive.png'
                otsu_filename = f'text_detection_{timestamp}_otsu.png'
                otsu_inv_filename = f'text_detection_{timestamp}_otsu_inv.png'
                
                cv2.imwrite(os.path.join(self.captures_path, adaptive_filename), binary_adaptive)
                cv2.imwrite(os.path.join(self.captures_path, otsu_filename), binary_otsu)
                cv2.imwrite(os.path.join(self.captures_path, otsu_inv_filename), binary_otsu_inv)
                
                print(f"[@text_helpers:OCR] Saved preprocessed images: {adaptive_filename}, {otsu_filename}, {otsu_inv_filename}")
                
                # Try OCR with multiple approaches and rank by mean tesseract confidence
                ocr_results = []
                for name, binary_img in [
                    ('adaptive', binary_adaptive),
                    ('otsu', binary_otsu),
                    ('otsu_inv', binary_otsu_inv),
                    ('enhanced', enhanced),
                    ('grayscale', gray)
                ]:
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        cv2.imwrite(tmp.name, binary_img)
                        ocr_temp_path = tmp.name

                    text_result = subprocess.run(
                        ['tesseract', ocr_temp_path, 'stdout', *wl_args],
                        capture_output=True, text=True, timeout=30
                    )
                    text = text_result.stdout.strip() if text_result.returncode == 0 else ""

                    tsv_result = subprocess.run(
                        ['tesseract', ocr_temp_path, 'stdout', *wl_args, 'tsv'],
                        capture_output=True, text=True, timeout=30
                    )
                    confidence = self._mean_tesseract_confidence(tsv_result.stdout) if tsv_result.returncode == 0 else 0.0

                    ocr_results.append({
                        'method': name,
                        'text': text,
                        'length': len(text),
                        'word_count': len(text.split()) if text else 0,
                        'confidence': confidence,
                    })

                    try:
                        os.unlink(ocr_temp_path)
                    except:
                        pass

                # Pick the result with the highest mean per-word confidence (length tiebreak)
                best_result = max(ocr_results, key=lambda r: (r['confidence'], r['length']))
                extracted_text = best_result['text']

                print(f"[@text_helpers:OCR] Tried {len(ocr_results)} OCR approaches:")
                for r in ocr_results:
                    status = "✅ BEST" if r['method'] == best_result['method'] else "  "
                    print(f"[@text_helpers:OCR]   {status} {r['method']:12s}: conf={r['confidence']:5.1f}, {r['length']:4d} chars, {r['word_count']:3d} words")

                print(f"[@text_helpers:OCR] Selected best result from '{best_result['method']}' method (confidence {best_result['confidence']:.1f})")
                print(f"[@text_helpers:OCR] >>> {extracted_text[:200]}")
                
            else:
                # SIMPLE OCR: Fast and reliable for regular text verification (waitForTextToAppear/Disappear)
                print(f"[@text_helpers:OCR] Using SIMPLE binary threshold OCR")
                
                # Apply simple binarization (old algorithm - works great for regular text)
                _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
                
                # Use the binary filtered version for OCR
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    cv2.imwrite(tmp.name, binary)
                    ocr_temp_path = tmp.name
                
                result = subprocess.run(
                    ['tesseract', ocr_temp_path, 'stdout', *wl_args],
                    capture_output=True, text=True, timeout=30
                )

                extracted_text = result.stdout.strip() if result.returncode == 0 else ""
                
                try:
                    os.unlink(ocr_temp_path)
                except:
                    pass
                
                print(f"[@text_helpers:OCR] Extracted: '{extracted_text.strip()}'")
            
            # Step 4: Language detection with confidence
            if extracted_text:
                lang_code, lang_confidence = self.detect_language(extracted_text)
            else:
                lang_code, lang_confidence = 'en', 0.0

            return {
                'extracted_text': extracted_text,
                'character_count': len(extracted_text),
                'word_count': len(extracted_text.split()) if extracted_text else 0,
                'detected_language': lang_code,
                'language_confidence': lang_confidence,
                'area': area,
                'image_textdetected_path': processed_path
            }

        except Exception as e:
            return {'extracted_text': '', 'error': str(e), 'image_textdetected_path': ''}

    def _mean_tesseract_confidence(self, tsv_output: str) -> float:
        """Compute the mean per-word confidence from a tesseract tsv stdout dump."""
        lines = tsv_output.strip().split('\n')
        if len(lines) < 2:
            return 0.0
        header = lines[0].split('\t')
        try:
            idx_level = header.index('level')
            idx_conf = header.index('conf')
            idx_text = header.index('text')
        except ValueError:
            return 0.0
        confs = []
        for row in lines[1:]:
            cols = row.split('\t')
            if len(cols) <= idx_text:
                continue
            try:
                level = int(cols[idx_level])
                conf = float(cols[idx_conf])
            except ValueError:
                continue
            if level != 5 or conf < 0:
                continue
            if not cols[idx_text].strip():
                continue
            confs.append(conf)
        return sum(confs) / len(confs) if confs else 0.0

    def ocr_with_whitelist(self, image_path: str, area: dict = None, whitelist: str = None, psm: int = 6, scale: int = 3) -> str:
        """
        Single-pass OCR with optional character whitelist for self-healing specific fields.

        Upscales the (optionally cropped) image, applies inverted Otsu (light-on-dark
        text → black-on-white), and runs tesseract with the given PSM and whitelist.
        Use ONLY when the caller has a strong prior on the value's shape (e.g. a
        regex-validated serial number). A whitelist will mangle anything outside it.
        """
        if not os.path.exists(image_path):
            return ''
        img = cv2.imread(image_path)
        if img is None:
            return ''
        if area:
            x, y = int(area['x']), int(area['y'])
            w, h = int(area['width']), int(area['height'])
            img_h, img_w = img.shape[:2]
            if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
                return ''
            img = img[y:y+h, x:x+w]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if scale and scale > 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            cv2.imwrite(tmp.name, binary)
            tmp_path = tmp.name

        cmd = ['tesseract', tmp_path, 'stdout', '--psm', str(psm), '--dpi', '300']
        if whitelist:
            cmd.extend(['-c', f'tessedit_char_whitelist={whitelist}'])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout.strip() if result.returncode == 0 else ''
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass

    # OCR on STB UIs only ever sees menus/labels in EN/FR/IT/DE.
    SUPPORTED_LANGUAGES = ('en', 'fr', 'it', 'de')

    # Lazily-built langdetect factory loaded with ONLY the four supported
    # language profiles (see _get_restricted_factory). Built once per process.
    _restricted_factory = None

    @classmethod
    def _get_restricted_factory(cls):
        """Build (once) a langdetect DetectorFactory that knows ONLY EN/FR/IT/DE.

        langdetect's default detector scores text against all ~55 bundled
        language profiles and returns the single global best. On a single UI
        word that lands on nonsense — "watching"→Swahili, "Settings"→Swedish,
        "Home"→Danish — which the old code then discarded (none of them in the
        supported set), reporting ('en', 0.0). Loading only the four candidate
        profiles forces the detector to choose among them, so "watching"
        correctly scores en≈1.0. We seed the factory so results are
        deterministic (the default detect_langs() is not seeded and can flip
        between runs on the same word).

        Profiles ship inside the langdetect package, so this adds no new
        dependency and works on the deployed hosts as-is.
        """
        if cls._restricted_factory is not None:
            return cls._restricted_factory
        import langdetect
        from langdetect.detector_factory import DetectorFactory
        from langdetect.utils.lang_profile import LangProfile
        prof_dir = os.path.join(os.path.dirname(langdetect.__file__), 'profiles')
        factory = DetectorFactory()
        factory.seed = 0
        for index, lang in enumerate(cls.SUPPORTED_LANGUAGES):
            with open(os.path.join(prof_dir, lang)) as fh:
                factory.add_profile(LangProfile(**json.load(fh)), index, len(cls.SUPPORTED_LANGUAGES))
        cls._restricted_factory = factory
        return factory

    def detect_language(self, text: str) -> Tuple[str, float]:
        """Detect language with confidence, restricted to EN/FR/IT/DE.

        Returns (code, probability) on a 0..1 scale, choosing the most likely of
        the four supported languages (never a global guess we'd have to throw
        away). Falls back to ('en', 0.0) only for text too short to judge
        (<= 3 chars) or if langdetect errors.
        """
        if not text or len(text.strip()) <= 3:
            return 'en', 0.0
        try:
            detector = self._get_restricted_factory().create()
            detector.append(text)
            probs = detector.get_probabilities()
            if probs:
                return probs[0].lang, float(probs[0].prob)
            return 'en', 0.0
        except Exception:
            return 'en', 0.0
    
    @staticmethod
    def _normalize_for_match(s: str) -> str:
        """Fold diacritics to their base letter, lowercase, drop
        punctuation/symbols (keep letters+digits and spaces), collapse
        whitespace. Shared by score + bool matchers so both see the same input.

        Accent FOLDING (NFKD + strip combining marks), not stripping: "Über"
        becomes "uber", "Paramètres" becomes "parametres". This is what lets an
        accented reference match OCR output that dropped the accent — tesseract
        (default EN model) reads "Über" as "Uber", which previously scored only
        0.750 ("uber" vs "über", one char off) and failed the 0.8 threshold.
        Folding makes it an exact substring → score 1.0.

        Two earlier behaviors this avoids:
        - ASCII-only strip (`[^a-zA-Z0-9\\s]`) DELETED accented letters,
          collapsing "Über" to the fragment "ber", which fuzzy-matched the "er"
          in "Systerr" at exactly 0.800 — a false positive at threshold 0.8.
        - Unicode-aware KEEP (`\\w` with re.UNICODE) preserved "über" but then
          couldn't match OCR's accent-less "uber".
        Folding fixes both: "Über"→"uber" matches "Uber" at 1.0, and the old
        "Systerr" false positive now scores 0.667 (below 0.8)."""
        import re, unicodedata
        # NFKD splits "ü" into "u" + combining diaeresis; drop the combining marks.
        s = ''.join(c for c in unicodedata.normalize('NFKD', s)
                    if not unicodedata.combining(c))
        # `\\w` is Unicode by default for str; it also keeps '_', so strip that too.
        return ' '.join(
            re.sub(r'[^\w\s]', ' ', s, flags=re.UNICODE).replace('_', ' ').split()
        ).lower()

    def text_match_score(self, extracted_text: str, target_text: str) -> float:
        """
        Compute a 0.0-1.0 similarity between `target_text` and `extracted_text`,
        after the same normalization used by `text_matches` (alphanumeric+space
        only, lowercased, whitespace collapsed).

        Semantics — mirrors image-template scoring (score=1.0 means perfect):
        - Empty input on either side → 0.0
        - Normalized target found as a substring of extracted → 1.0
          (this is the existing matcher's positive case; preserved exactly so
          callers that pass threshold=1.0 keep today's behavior)
        - Otherwise, slide a target-length window across extracted and return
          the best `difflib.SequenceMatcher.ratio()` against any window.
          One-character OCR misreads in short strings (e.g. "Anrnelden" vs
          "Anmelden") score ~0.875 — passes default threshold 0.8, fails 0.95.

        difflib is already used in backend_host/src/services/ai/* — no new dep.
        """
        if not extracted_text or not target_text:
            return 0.0

        extracted_clean = self._normalize_for_match(extracted_text)
        target_clean = self._normalize_for_match(target_text)

        if not extracted_clean or not target_clean:
            return 0.0

        # Exact substring → perfect score. Short-circuit before difflib so
        # `score == 1.0` always means "we found the target verbatim (modulo
        # punctuation/case)", which is what threshold=1.0 callers expect.
        if target_clean in extracted_clean:
            return 1.0

        from difflib import SequenceMatcher
        n = len(target_clean)
        m = len(extracted_clean)

        # If extracted is shorter than (or equal to) target, just compare directly.
        if m <= n:
            return SequenceMatcher(None, target_clean, extracted_clean,
                                   autojunk=False).ratio()

        # Sweep window sizes from n-2 to n+2. Fixed-n windows miss the common
        # OCR case where a single letter is misread as two (e.g. 'm' → 'rn',
        # giving "Anrnelden" for "Anmelden") or vice-versa — the target-sized
        # window then always drops either the leading or trailing char and
        # scores ~0.75 even though a 9-char window scores ~0.82. Sweeping ±2
        # closes that gap and matches what rapidfuzz.partial_ratio returns.
        # Bound: ~5 * m SequenceMatcher calls on ~n-sized strings, each O(n²).
        # Fine for OCR text (n≤50, m≤a few thousand) — well under 100ms.
        best = 0.0
        for win_n in range(max(1, n - 2), min(m, n + 2) + 1):
            for i in range(m - win_n + 1):
                r = SequenceMatcher(None, target_clean,
                                    extracted_clean[i:i + win_n],
                                    autojunk=False).ratio()
                if r > best:
                    best = r
                    if best >= 1.0:
                        return best
        return best

    def text_matches(self, extracted_text: str, target_text: str,
                     threshold: float = 0.8) -> bool:
        """
        Threshold-driven text match. Returns True iff
        `text_match_score(...) >= threshold`.

        Default 0.8 mirrors image verification. Pass `threshold=1.0` for the
        legacy strict-substring behavior. Normalization strips punctuation,
        collapses whitespace, and lowercases — so e.g.:
        - "Movies Series" matches "Movies & Series" at score 1.0 ✅
        - "Settings" matches "Settings!" at score 1.0 ✅
        - "Anmelden" matches "Anrnelden" at score ~0.875 — passes 0.8, fails 0.95
        """
        return self.text_match_score(extracted_text, target_text) >= threshold
    
    def parse_menu_info(self, ocr_text: str) -> Dict[str, str]:
        """
        Parse key-value pairs from OCR text (menu format).
        
        Supports both horizontal and vertical layouts:
        
        HORIZONTAL (same line with delimiter):
        - "Serial Number: ABC123"
        - "MAC Address = 00:11:22:33:44:55"
        - "Firmware - 1.2.3"
        
        VERTICAL (consecutive lines):
        - Line 1: "APPLICATION VERSION"
        - Line 2: "67_2025102"
        
        Args:
            ocr_text: Raw OCR text from menu/info screen
            
        Returns:
            Dict with parsed key-value pairs (keys normalized to lowercase with underscores)
        """
        parsed_data = {}
        lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Try horizontal format first (key:value, key=value, key-value)
            found_horizontal = False
            for delimiter in [':', '=', '-']:
                if delimiter in line:
                    parts = line.split(delimiter, 1)
                    if len(parts) == 2:
                        key_raw = parts[0].strip()
                        value = parts[1].strip()
                        
                        # Validate: key should look like a label (contains letters, reasonable length)
                        if key_raw and value and any(c.isalpha() for c in key_raw) and len(key_raw) < 50:
                            key = key_raw.lower().replace(' ', '_').replace('(', '').replace(')', '')
                            parsed_data[key] = value
                            found_horizontal = True
                            break
            
            if found_horizontal:
                i += 1
                continue
            
            # Try vertical format (current line is key, next line is value)
            if i + 1 < len(lines):
                potential_key = line
                potential_value = lines[i + 1]
                
                # Heuristic: Key should contain letters and look like a label (all caps or title case)
                # Value should be different from key (not another label)
                is_key = (
                    any(c.isalpha() for c in potential_key) and
                    len(potential_key) < 50 and
                    (potential_key.isupper() or potential_key.istitle()) and
                    ':' not in potential_key and '=' not in potential_key  # No delimiters
                )
                
                # Value should be different from key
                # Fixed: Don't reject uppercase values - many serial numbers/versions are uppercase
                # Instead, reject if next line looks like another label (ends with VERSION, NUMBER, etc.)
                looks_like_label = (
                    potential_value.isupper() and 
                    any(potential_value.endswith(suffix) for suffix in ['VERSION', 'NUMBER', 'ADDRESS', 'NAME', 'INFO', 'STATUS', 'TYPE', 'MODE'])
                )
                
                is_value = (
                    potential_value and 
                    potential_value != potential_key and
                    not looks_like_label
                )
                
                if is_key and is_value:
                    key = potential_key.lower().replace(' ', '_').replace('(', '').replace(')', '')
                    value = potential_value
                    parsed_data[key] = value
                    i += 2  # Skip both key and value lines
                    continue
            
            # No pattern matched, skip this line
            i += 1
        
        return parsed_data

    def extract_full_ocr_dump(self, image_path: str, confidence_threshold: int = 30) -> list:
        """
        Extract ALL text from image with bounding boxes (like ADB dump for TV).
        
        Uses pytesseract.image_to_data() to get text with coordinates for each word/line.
        This is the TV equivalent of ADB dump - discovers all text elements with their areas.
        
        Results are SORTED BY FONT SIZE (largest first) - titles/headings appear first.
        This prioritizes larger, more prominent text for better verification matching.
        
        Args:
            image_path: Path to screenshot
            confidence_threshold: Minimum OCR confidence (0-100), default 30
            
        Returns:
            List of text elements with areas (sorted by font_size descending):
            [
                {'text': 'Rent', 'area': {...}, 'confidence': 95, 'font_size': 48},  # Title - largest
                {'text': 'Lassie 2 Ein neues Abenteuer', 'area': {...}, 'confidence': 85, 'font_size': 24},
                {'text': 'SD 2 days CHF 3.50', 'area': {...}, 'confidence': 92, 'font_size': 18},
                ...
            ]
        """
        try:
            print(f"[@text_helpers:extract_full_ocr_dump] Extracting OCR dump from: {image_path}")
            
            if not os.path.exists(image_path):
                print(f"[@text_helpers:extract_full_ocr_dump] ERROR: Image not found at {image_path}")
                return []
            
            # Load image
            img = cv2.imread(image_path)
            if img is None:
                print(f"[@text_helpers:extract_full_ocr_dump] ERROR: Failed to load image with cv2.imread")
                return []
            
            # Preprocess: Convert to grayscale and apply binary threshold
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
            
            # Save preprocessed image temporarily for pytesseract
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                cv2.imwrite(tmp.name, binary)
                temp_path = tmp.name
            
            try:
                # Use pytesseract.image_to_data to get bounding boxes
                # This returns a TSV string with columns: level, page_num, block_num, par_num, line_num, word_num, left, top, width, height, conf, text
                result = subprocess.run(
                    ['tesseract', temp_path, 'stdout', '--psm', '11', 'tsv'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode != 0:
                    print(f"[@text_helpers:extract_full_ocr_dump] ERROR: Tesseract failed")
                    return []
                
                # Parse TSV output
                lines = result.stdout.strip().split('\n')
                
                if len(lines) < 2:  # Need header + at least 1 data row
                    print(f"[@text_helpers:extract_full_ocr_dump] No text detected by Tesseract")
                    return []
                
                # Parse header to get column indices
                header = lines[0].split('\t')
                
                elements = []
                total_detected = 0
                filtered_by_empty = 0
                filtered_by_confidence = 0
                filtered_by_invalid_box = 0
                filtered_by_quality = 0  # Layer 1: OCR quality filter
                
                # Process each line (skip header)
                for line in lines[1:]:
                    cols = line.split('\t')
                    if len(cols) < len(header):
                        continue
                    
                    # Extract values by column name
                    data = dict(zip(header, cols))
                    
                    text = data.get('text', '').strip()
                    conf = data.get('conf', '-1')
                    
                    total_detected += 1
                    
                    # Skip empty text or low confidence
                    if not text or conf == '-1':
                        filtered_by_empty += 1
                        continue
                    
                    try:
                        confidence = int(float(conf))
                        if confidence < confidence_threshold:
                            filtered_by_confidence += 1
                            continue
                    except ValueError:
                        filtered_by_confidence += 1
                        continue
                    
                    # Get bounding box
                    try:
                        left = int(data.get('left', 0))
                        top = int(data.get('top', 0))
                        width = int(data.get('width', 0))
                        height = int(data.get('height', 0))
                    except ValueError:
                        continue
                    
                    # Skip invalid boxes
                    if width <= 0 or height <= 0:
                        filtered_by_invalid_box += 1
                        continue
                    
                    # ✅ LAYER 1: Filter garbage OCR text (TV-optimized)
                    if not self._is_valid_ocr_text_for_verification(text):
                        filtered_by_quality += 1
                        continue
                    
                    # Expand area for better verification matching (-5 x/y, +10 width/height)
                    expanded_x = max(0, left - 5)
                    expanded_y = max(0, top - 5)
                    expanded_width = width + 10
                    expanded_height = height + 10
                    
                    elements.append({
                        'text': text,
                        'area': {
                            'x': expanded_x,
                            'y': expanded_y,
                            'width': expanded_width,
                            'height': expanded_height
                        },
                        'confidence': confidence,
                        'font_size': height  # Use original height as font size proxy (larger = title/heading)
                    })
                
                print(f"[@text_helpers:extract_full_ocr_dump] Extracted {len(elements)} text elements (confidence >= {confidence_threshold})")
                
                # Group nearby words into phrases (combine words on same line)
                if elements:
                    grouped_elements = self._group_text_elements(elements)
                    print(f"[@text_helpers:extract_full_ocr_dump] Grouped into {len(grouped_elements)} phrases (sorted by font size)")
                    return grouped_elements
                
                return elements
                
            finally:
                # Cleanup temp file
                try:
                    os.unlink(temp_path)
                except:
                    pass
                    
        except Exception as e:
            print(f"[@text_helpers:extract_full_ocr_dump] ERROR: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _is_valid_ocr_text_for_verification(self, text: str) -> bool:
        """
        Filter garbage OCR text for verification quality (TV-optimized).
        
        Applies strict quality rules to ensure only meaningful text is used:
        - NOT checking min length here (done in Layer 2 after grouping)
        - Not all numeric (filters times like '12:20')
        - Not symbol-only (filters '@)', '®', '-~\\.')
        - Not common UI indicators (filters 'HD', 'SD', 'OK', '4K')
        - Not single letter + punctuation (filters 'E.', 'H!')
        - Not garbage patterns (filters 'eh ity fy', 'of ee', 'res Be ae')
        
        Args:
            text: Text to validate
            
        Returns:
            True if text is valid for verification, False if garbage
        """
        text_clean = text.strip()
        
        # 1. ✅ NO MINIMUM LENGTH CHECK - Let "TV" pass for grouping with "Guide"
        #    Layer 2 will filter standalone short words AFTER grouping
        
        # 2. All numeric (times, channel numbers)
        #    Filters: '12:20', '1:55', '123'
        if text_clean.replace(':', '').replace('.', '').replace(' ', '').isdigit():
            return False
        
        # 3. Symbol-only (UI icons misread as text)
        #    Filters: '@)', '-~\.', '®', '©'
        if not any(c.isalnum() for c in text_clean):
            return False
        
        # 4. Common UI indicators (too generic for verification)
        #    Filters: 'HD', 'SD', 'OK', '4K', 'UHD'
        common_ui = {'hd', 'sd', 'ok', '4k', 'uhd'}
        if text_clean.lower() in common_ui:
            return False
        
        # 5. Single letter + punctuation/symbol (OCR artifacts)
        #    Filters: 'E.', 'H!', 'A?', '@)'
        if len(text_clean) == 2:
            if text_clean[0].isalpha() and not text_clean[1].isalnum():
                return False
            if not text_clean[0].isalnum() and text_clean[1].isalpha():
                return False
        
        # 6. ✅ NEW: Garbage pattern detection (nonsensical OCR results)
        #    Filters: 'eh ity fy', 'of ee', 'res Be ae'
        #    Heuristic: More than 50% of "words" are 1-2 chars each
        words = text_clean.split()
        if len(words) >= 2:  # Only apply to multi-word text
            short_word_count = sum(1 for word in words if len(word) <= 2)
            if short_word_count / len(words) > 0.5:  # More than 50% are tiny words
                return False
        
        # 7. ✅ NEW: Vowel-consonant ratio check (garbage text often lacks vowels)
        #    Filters: 'xyz', 'qwrt', 'bcdfg'
        #    But allows: 'TV', 'BBC', 'CNN' (common acronyms are short anyway)
        if len(text_clean) > 4:  # Only check longer text (acronyms are short)
            alpha_chars = [c for c in text_clean.lower() if c.isalpha()]
            if alpha_chars:
                vowels = sum(1 for c in alpha_chars if c in 'aeiou')
                vowel_ratio = vowels / len(alpha_chars)
                # Require at least 15% vowels (English averages ~40%, allow flexibility)
                if vowel_ratio < 0.15:
                    return False
        
        return True
    
    def _clean_grouped_text(self, text: str) -> str:
        """
        Clean special characters from grouped text.
        
        Removes special characters from start/end of each word:
        - 'Store) FEATURED (New Staging' → 'FEATURED New Staging'
        - '(New' → 'New'
        - 'Store)' → 'Store'
        - 'store"' → 'store'
        
        Args:
            text: Text to clean
            
        Returns:
            Cleaned text with special chars removed, or empty string if nothing remains
        """
        words = text.split()
        cleaned_words = []
        
        for word in words:
            # Strip special chars from start/end: '(New' → 'New', 'Store)' → 'Store'
            cleaned = word.strip('()[]{}"\',.:;!?@#$%^&*_-+=~`|\\/<>')
            
            # Skip if nothing left after cleaning, or single letter
            if cleaned and len(cleaned) > 1:
                cleaned_words.append(cleaned)
        
        return ' '.join(cleaned_words)
    
    def _is_valid_grouped_phrase(self, text: str) -> bool:
        """
        Filter grouped phrases for verification quality (Layer 2).
        
        NOTE: Text should already be cleaned by _clean_grouped_text() before calling this.
        
        Filters:
        - Single letters: 'Q', 'E' → Invalid
        - Too short: 'TV', 'be' → Invalid (but 'TV Guide' → Valid)
        - Orphan letters: 'E Shared', 'Apps De' → Invalid
        
        Args:
            text: Cleaned grouped phrase to validate
            
        Returns:
            True if phrase is valid, False if likely grouping error
        """
        # First apply base quality check (no min length check there now)
        if not self._is_valid_ocr_text_for_verification(text):
            return False
        
        text_clean = text.strip()
        
        # ✅ Single letter (moved from Layer 1)
        # Filters: 'Q', 'E', 'T', 'A' - even with high confidence
        if len(text_clean) == 1:
            return False
        
        # ✅ Minimum 3 characters (moved from Layer 1)
        # Filters standalone short words: 'TV', 'Er', 'It', 'De', 'be'
        # But allows them in grouped phrases: 'TV Guide' ✅, 'Apple TV' ✅
        if len(text_clean) < 3:
            return False
        
        words = text_clean.split()
        
        # Single word: Already validated by min length above
        if len(words) == 1:
            return True
        
        # Multi-word phrase: Check for orphan single letters at start/end
        # Filters: 'E Shared', 'It Now', 'Settings E', 'Apps De'
        first_word = words[0]
        last_word = words[-1]
        
        # Orphan single letter at start
        if len(first_word) == 1 and first_word.isalpha():
            return False
        
        # Orphan single letter at end
        if len(last_word) == 1 and last_word.isalpha():
            return False
        
        return True
    
    def _group_text_elements(self, elements: list) -> list:
        """
        Group nearby text elements into phrases (combine words on same line).
        
        Args:
            elements: List of individual word elements
            
        Returns:
            List of grouped phrase elements
        """
        if not elements:
            return []
        
        # Sort by vertical position (top), then horizontal (left)
        sorted_elements = sorted(elements, key=lambda e: (e['area']['y'], e['area']['x']))
        
        grouped = []
        current_group = None
        
        for elem in sorted_elements:
            if current_group is None:
                # Start new group
                current_group = {
                    'text': elem['text'],
                    'area': elem['area'].copy(),
                    'confidence': elem['confidence'],
                    'font_size': elem.get('font_size', 0),  # Track font size (use max from group)
                    'word_count': 1
                }
            else:
                # Check if this element is on the same line (similar y position)
                y_diff = abs(elem['area']['y'] - current_group['area']['y'])
                height_avg = (elem['area']['height'] + current_group['area']['height']) / 2
                
                # Also check horizontal proximity
                current_right = current_group['area']['x'] + current_group['area']['width']
                elem_left = elem['area']['x']
                x_gap = elem_left - current_right
                
                # Check font size similarity (don't group if font sizes differ by more than 50%)
                current_font_size = current_group.get('font_size', 0)
                elem_font_size = elem.get('font_size', 0)
                max_font = max(current_font_size, elem_font_size)
                min_font = min(current_font_size, elem_font_size)
                font_ratio = min_font / max_font if max_font > 0 else 1.0
                
                # Dynamic x_gap threshold based on font size (TV navigation text has larger spacing)
                # Small font (< 20px): 30px gap max
                # Large font (> 40px): 150px gap max (common for TV navigation menus)
                avg_font_size = (current_font_size + elem_font_size) / 2
                if avg_font_size > 40:
                    max_x_gap = 150  # Large text (TV navigation)
                elif avg_font_size > 25:
                    max_x_gap = 80   # Medium text
                else:
                    max_x_gap = 30   # Small text
                
                # FIX: Reject negative x_gap (element is to the LEFT, not right - wrong spatial order)
                should_group_by_distance = (y_diff < height_avg * 0.5 and 0 <= x_gap < max_x_gap)
                should_group_by_font = (font_ratio > 0.5)  # Allow grouping if fonts within 50% size
                
                # If on same line (y_diff < half height) and close horizontally (gap < 30px max) and similar font size
                if should_group_by_distance and should_group_by_font:
                    # Merge into current group
                    current_group['text'] += ' ' + elem['text']
                    
                    # Expand bounding box to include new element
                    new_right = elem['area']['x'] + elem['area']['width']
                    current_right = current_group['area']['x'] + current_group['area']['width']
                    
                    current_group['area']['width'] = max(new_right, current_right) - current_group['area']['x']
                    current_group['area']['height'] = max(
                        current_group['area']['height'],
                        elem['area']['y'] + elem['area']['height'] - current_group['area']['y']
                    )
                    
                    # Average confidence
                    current_group['confidence'] = int(
                        (current_group['confidence'] * current_group['word_count'] + elem['confidence']) / 
                        (current_group['word_count'] + 1)
                    )
                    
                    # Use MAX font size from all words (important for titles with mixed sizes)
                    current_group['font_size'] = max(
                        current_group.get('font_size', 0),
                        elem.get('font_size', 0)
                    )
                    
                    current_group['word_count'] += 1
                else:
                    # ✅ LAYER 2: Save current group with cleaned text if it passes quality check
                    if current_group:
                        cleaned_text = self._clean_grouped_text(current_group['text'])
                        if cleaned_text and self._is_valid_grouped_phrase(cleaned_text):
                            grouped.append({
                                'text': cleaned_text,
                                'area': current_group['area'],
                                'confidence': current_group['confidence'],
                                'font_size': current_group.get('font_size', 0)
                            })
                    
                    current_group = {
                        'text': elem['text'],
                        'area': elem['area'].copy(),
                        'confidence': elem['confidence'],
                        'font_size': elem.get('font_size', 0),
                        'word_count': 1
                    }
        
        # ✅ LAYER 2: Don't forget the last group (with cleaned text and quality check)
        if current_group:
            cleaned_text = self._clean_grouped_text(current_group['text'])
            if cleaned_text and self._is_valid_grouped_phrase(cleaned_text):
                grouped.append({
                    'text': cleaned_text,
                    'area': current_group['area'],
                    'confidence': current_group['confidence'],
                    'font_size': current_group.get('font_size', 0)
                })
        
        # Sort by font_size (descending) - larger text (titles) comes first
        grouped.sort(key=lambda g: g.get('font_size', 0), reverse=True)
        
        return grouped

 