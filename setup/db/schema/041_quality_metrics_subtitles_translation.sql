-- 041_quality_metrics_subtitles_translation.sql
-- Subtitle (OCR), audio transcription (Whisper) and audio translation availability,
-- added to the per-minute quality_metrics row. NULL when those features are disabled.

ALTER TABLE quality_metrics
  ADD COLUMN IF NOT EXISTS subtitle_availability  numeric,   -- 0..1 fraction of frames with on-screen subtitles
  ADD COLUMN IF NOT EXISTS subtitle_language      text,      -- dominant detected subtitle language
  ADD COLUMN IF NOT EXISTS transcript_available   numeric,   -- 0..1 audio transcribed (Whisper)
  ADD COLUMN IF NOT EXISTS transcript_language    text,      -- transcript source language
  ADD COLUMN IF NOT EXISTS translation_languages  text,      -- csv of available translated langs (e.g. 'fr,es')
  ADD COLUMN IF NOT EXISTS dubbed_languages       text;      -- csv of available dubbed-audio langs
