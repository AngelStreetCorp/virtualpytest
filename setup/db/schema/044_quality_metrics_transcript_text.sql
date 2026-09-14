-- 044_quality_metrics_transcript_text.sql
-- Store the actual recognised text alongside the availability/language columns so the
-- L2 device page can show WHAT was found, not just that something was found.
-- NULL when no text was recognised (or the feature is disabled).

ALTER TABLE quality_metrics
  ADD COLUMN IF NOT EXISTS transcript_text text,   -- latest audio-transcript text (source language)
  ADD COLUMN IF NOT EXISTS subtitle_text   text;   -- latest on-screen subtitle text (OCR)
