# Audio Hot/Cold Storage Architecture

## 📋 Overview

Audio chunks are now properly integrated into the hot/cold storage architecture, following the same pattern as all other data types (segments, metadata, transcripts).

---

## 🏗️ Storage Structure

```
/var/www/html/stream/capture1/
├── hot/                          # RAM storage (if RAM mode enabled)
│   ├── segments/                 # Latest 150 TS files (2.5min)
│   ├── captures/                 # Latest 300 captures (60s)
│   ├── metadata/                 # Latest 750 metadata JSONs (150s)
│   ├── transcript/               # Latest transcript chunks
│   └── audio/                    # ← NEW: Latest 6 audio chunks (1h buffer)
│       ├── chunk_10min_0.mp3
│       ├── chunk_10min_1.mp3
│       └── ... (up to 6 files)
│
├── segments/{hour}/              # Cold: 24h video archive
│   ├── chunk_10min_0.mp4
│   ├── chunk_10min_1.mp4
│   └── ... (6 per hour × 24h = 144 total)
│
├── audio/{hour}/                 # ← NEW: Cold: 24h audio archive
│   ├── chunk_10min_0.mp3
│   ├── chunk_10min_1.mp3
│   └── ... (6 per hour × 24h = 144 total)
│
├── metadata/{hour}/              # Cold: Detector metadata
│   └── chunk_10min_X.json
│
└── transcript/{hour}/            # Cold: Audio transcripts
    └── chunk_10min_X.json
```

---

## 🔄 Data Flow

### **1. Audio Extraction (During MP4 Creation)**

When `hot_cold_archiver.py` creates a 10-minute MP4 chunk:

```python
# Step 1: Create 10-min MP4 in cold storage
mp4_path = "/segments/{hour}/chunk_10min_{index}.mp4"
merge_progressive_batch(...)  # Creates MP4

# Step 2: Extract audio to HOT storage
if ram_mode:
    hot_audio_dir = "/hot/audio/"
else:
    hot_audio_dir = "/audio/"

audio_path = hot_audio_dir + f"chunk_10min_{index}.mp3"

# Extract using FFmpeg
ffmpeg -i {mp4_path} -vn -acodec libmp3lame -q:a 4 {audio_path}
```

**Result**: Audio chunk created in HOT storage, ready for archival

---

### **2. Audio Archival (Hot → Cold)**

On next archiver cycle (60s later):

```python
# Archive audio chunks from hot to cold
archived_audio = archive_hot_files(capture_dir, 'audio')

# Process:
# - Count files in /hot/audio/
# - If > 6 files (hot limit)
# - Move oldest to /audio/{hour}/chunk_10min_X.mp3
# - Keep newest 6 in hot storage
```

**Result**: Proper hot/cold flow, 24h rolling archive

---

## ⚙️ Configuration

### **Hot Limits** (`HOT_LIMITS` dict)

```python
HOT_LIMITS = {
    'segments': 150,      # 2.5min buffer
    'captures': 300,      # 60s buffer
    'thumbnails': 100,    # Freeze detection
    'metadata': 750,      # 150s buffer
    'audio': 6,          # 1h buffer (6 × 10-min chunks)
}
```

### **File Patterns** (`FILE_PATTERNS` dict)

```python
FILE_PATTERNS = {
    'segments': 'segment_*.ts',
    'captures': 'capture_*[0-9].jpg',
    'audio': 'chunk_10min_*.mp3',  # ← NEW
}
```

---

## 💾 Storage Impact

### **RAM Usage (Per Device)**

```
Hot Storage:
- Segments:     6 MB   (150 files)
- Captures:    74 MB   (300 files, HD quality)
- Thumbnails:   3 MB   (100 files)
- Metadata:     0.75MB (750 files)
- Transcripts:  1.2MB  (kept in hot)
- Audio:        6 MB   (6 × 1MB chunks)
─────────────────────────────────
Total:        ~91 MB   (45% of 200MB budget) ✅
```

### **Disk Usage (24h Archive)**

```
Cold Storage (per device):
- Segments:   ~500 MB  (144 × 3.5MB MP4 chunks)
- Audio:      ~150 MB  (144 × 1MB MP3 chunks)
- Metadata:    ~20 MB  (144 × 140KB JSON chunks)
- Transcripts: ~10 MB  (144 × 70KB JSON chunks)
─────────────────────────────────
Total:        ~680 MB  per device per 24h
```

---

## 🎯 Benefits

### **1. Clean Architecture**
- ✅ All data types follow same hot/cold pattern
- ✅ Consistent folder structure across system
- ✅ Clear separation of concerns

### **2. Storage Optimization**
- ✅ Audio archived separately from video
- ✅ Independent retention policies possible
- ✅ Efficient hot buffer (only 6 chunks = 1h)

### **3. Access Patterns**
- ✅ Easy to find: `/audio/{hour}/chunk_10min_{index}.mp3`
- ✅ Aligned with video chunks (same naming)
- ✅ Aligned with transcripts (same time range)

### **4. Integration Ready**
- ✅ Perfect for restart/monitoring unification
- ✅ Can serve audio chunks directly to frontend
- ✅ Can generate dubbed versions on-demand

---

## 🔌 API Access Patterns

### **Get Audio Chunk by Time**

```typescript
// Calculate chunk from timestamp
const hour = Math.floor(timestampSeconds / 3600) % 24;
const minuteInHour = Math.floor((timestampSeconds % 3600) / 60);
const chunkIndex = Math.floor(minuteInHour / 10); // 0-5

// Build audio URL
const audioUrl = `/host/stream/capture1/audio/${hour}/chunk_10min_${chunkIndex}.mp3`;
```

### **Get Aligned Video + Audio + Transcript**

```typescript
// All three use same hour/chunk_index!
const videoUrl = `/host/stream/capture1/segments/${hour}/chunk_10min_${chunkIndex}.mp4`;
const audioUrl = `/host/stream/capture1/audio/${hour}/chunk_10min_${chunkIndex}.mp3`;
const transcriptUrl = `/host/stream/capture1/transcript/${hour}/chunk_10min_${chunkIndex}.json`;
```

Perfect alignment for unified analysis! 🎯

---

## 🚀 Unified Restart/Monitoring Integration

### **Old Approach (Restart)**
```
1. User clicks "Restart Video"
2. Backend generates NEW 10s video from segments
3. Backend extracts audio from NEW video
4. Backend transcribes audio (again)
5. Display in isolated "restart player"
```
❌ Duplicate generation, duplicate storage, isolated system

### **New Approach (Unified)**
```
1. User selects timestamp (live or archive)
2. Frontend loads EXISTING chunk
   - Video: /segments/{hour}/chunk_10min_X.mp4
   - Audio: /audio/{hour}/chunk_10min_X.mp3 ← NEW
   - Transcript: /transcript/{hour}/chunk_10min_X.json (already exists!)
3. Apply restart features ON-DEMAND:
   - Translation (batch translate transcript)
   - Dubbing (use extracted audio)
   - AI Analysis (use existing captures)
   - PDF Report (from existing data)
```
✅ Zero duplication, instant access, full 24h coverage

---

## 📊 Monitoring Integration

### **Display Real-time Audio Analysis**

```typescript
// In monitoring mode, show current transcript
const currentChunk = getCurrentChunk(videoTime);
const transcript = await fetch(`/transcript/${currentChunk.hour}/chunk_10min_${currentChunk.index}.json`);

// Display scrolling transcript alongside video
<TranscriptPanel>
  {transcript.segments.map(seg => (
    <TranscriptLine time={seg.relative_seconds}>
      {seg.transcript}
    </TranscriptLine>
  ))}
</TranscriptPanel>
```

### **On-Demand Translation/Dubbing**

```typescript
// User selects language in settings
async function translateCurrentChunk(language: string) {
  // 1. Get current transcript chunk
  const transcript = await loadCurrentTranscript();
  
  // 2. Translate (existing restart endpoint)
  const translated = await fetch('/server/translate/restart-batch', {
    body: JSON.stringify({
      content_blocks: { audio_transcript: transcript },
      target_language: language
    })
  });
  
  // 3. Generate dubbed audio (using extracted MP3)
  const audioUrl = `/audio/${hour}/chunk_10min_${index}.mp3`;
  const dubbed = await fetch('/server/restart/createDubbedVideoFast', {
    body: JSON.stringify({
      audio_url: audioUrl,  // Use existing extracted audio!
      target_language: language,
      transcript: translated.audio_transcript
    })
  });
  
  // 4. Play dubbed version
  videoPlayer.src = dubbed.dubbed_video_url;
}
```

---

## ✅ Implementation Complete

The audio hot/cold architecture is now live! All changes in:
- `backend_host/scripts/hot_cold_archiver.py`

**What changed**:
1. ✅ Added `'audio': 'chunk_10min_*.mp3'` to `FILE_PATTERNS`
2. ✅ Added `'audio': 6` to `HOT_LIMITS`
3. ✅ Updated audio extraction to write to `/hot/audio/` instead of `/segments/{hour}/`
4. ✅ Added `archive_hot_files(capture_dir, 'audio')` to processing cycle
5. ✅ Updated logging and documentation

**What's next**:
- Frontend: Add audio chunk access utilities
- Backend: Add nginx routes for `/host/stream/*/audio/` serving
- Integration: Unify restart + monitoring into single player
- Features: Real-time transcript display, on-demand translation/dubbing

---

## 🎉 Summary

Audio is now a **first-class data type** in the hot/cold architecture, perfectly aligned with video chunks and transcripts for seamless unified monitoring + restart analysis! 🚀
