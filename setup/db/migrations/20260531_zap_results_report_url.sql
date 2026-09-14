-- Add per-event zap report URL to zap_results (parity with execution_results.kpi_report_url).
-- Populated by zap_report_generator.generate_and_upload_zap_report via the single
-- detect_and_record_zapping funnel; surfaced in the "All Zapping Events" Grafana dashboard.

ALTER TABLE zap_results ADD COLUMN IF NOT EXISTS report_url text;

CREATE INDEX IF NOT EXISTS idx_zap_results_report_url
    ON zap_results(report_url) WHERE report_url IS NOT NULL;
