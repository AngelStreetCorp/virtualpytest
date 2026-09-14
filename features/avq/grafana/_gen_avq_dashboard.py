import json
DS = {"uid": "supabase-postgres"}
F = "$__timeFilter(timestamp) AND device_name IN (${device:sqlstring}) AND host_name IN (${host:sqlstring})"

def base_ts(title, x, y, w, h, pid, mn=None, mx=None):
    fc = {"defaults": {"custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}}, "overrides": []}
    if mn is not None: fc["defaults"]["min"] = mn
    if mx is not None: fc["defaults"]["max"] = mx
    return {"datasource": DS, "title": title, "type": "timeseries", "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "id": pid, "fieldConfig": fc, "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}, "targets": []}

def tgt(sql): return {"datasource": DS, "format": "time_series", "rawQuery": True, "rawSql": sql}
def axis_right(name): return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "custom.axisPlacement", "value": "right"}, {"id": "unit", "value": "percent"}, {"id": "min", "value": 0}, {"id": "max", "value": 100}, {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 4]}}]}

def table(title, sql, x, y, w, h, pid, overrides=None):
    return {"datasource": DS, "title": title, "type": "table", "gridPos": {"x": x, "y": y, "w": w, "h": h}, "id": pid,
            "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}}, "overrides": overrides or []},
            "targets": [{"datasource": DS, "format": "table", "rawQuery": True, "rawSql": sql}]}

def row(title, y, pid, collapsed=False, panels=None):
    r = {"type": "row", "title": title, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "id": pid, "collapsed": collapsed}
    if panels is not None: r["panels"] = panels
    return r

yesno = [{"type": "value", "options": {"Yes": {"color": "green", "index": 0}, "No": {"color": "red", "index": 1}}}]
def cbg(c): return {"matcher": {"id": "byName", "options": c}, "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background"}}, {"id": "mappings", "value": yesno}]}
def mbg(c): return {"matcher": {"id": "byName", "options": c}, "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background"}}, {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 2.5}, {"color": "green", "value": 4}]}}]}

panels = []
# ---------- Overview ----------
panels.append(row("Overview", 0, 100))
ov_sql = f"""SELECT
  (SELECT count(DISTINCT device_id) FROM quality_metrics WHERE {F}) AS "Devices",
  (SELECT count(*) FROM (SELECT device_id FROM quality_metrics WHERE {F} GROUP BY device_id HAVING avg(video_availability) > 0.5) q) AS "With Video",
  (SELECT count(*) FROM (SELECT device_id FROM quality_metrics WHERE {F} GROUP BY device_id HAVING avg(audio_availability) > 0.5) q) AS "With Audio",
  (SELECT count(*) FROM quality_metrics WHERE {F}) AS "Minutes",
  (SELECT COALESCE(sum((events->'noSound'->>'count')::int),0)+COALESCE(sum((events->'highBlurriness'->>'count')::int),0)+COALESCE(sum((events->'highBlockiness'->>'count')::int),0) FROM quality_metrics WHERE {F}) AS "Quality Events",
  (SELECT round(avg(video_mos),2) FROM quality_metrics WHERE {F}) AS "Avg Video MOS",
  (SELECT round(avg(audio_mos),2) FROM quality_metrics WHERE {F}) AS "Avg Audio MOS\""""
panels.append({"datasource": DS, "title": "Overview", "type": "stat", "gridPos": {"x": 0, "y": 1, "w": 24, "h": 5}, "id": 1,
               "fieldConfig": {"defaults": {"color": {"mode": "fixed", "fixedColor": "text"}}, "overrides": []},
               "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": ""}, "colorMode": "none", "graphMode": "none", "textMode": "value_and_name", "justifyMode": "auto"},
               "targets": [{"datasource": DS, "format": "table", "rawQuery": True, "rawSql": ov_sql}]})
status_sql = f"""SELECT DISTINCT ON (device_id)
  host_name AS "Host", device_name AS "Device",
  CASE WHEN video_availability > 0.5 AND audio_availability > 0.5 THEN 'Yes' ELSE 'No' END AS "A/V Available",
  CASE WHEN video_availability > 0.5 THEN 'Yes' ELSE 'No' END AS "Video",
  round(video_mos,2) AS "Video MOS", round(blurriness_score,2) AS "Bluriness",
  round(blockiness_score,2) AS "Blockiness", round(jerkiness_score,3) AS "Jerkiness",
  round(blackscreen_seconds,0) AS "Blackscreen (s)", round(freeze_seconds,0) AS "Freeze (s)",
  round(macroblocks_seconds,0) AS "Macroblocks (s)",
  CASE WHEN audio_availability > 0.5 THEN 'Yes' ELSE 'No' END AS "Audio",
  round(audio_mos,2) AS "Audio MOS", round(audio_level_db,1) AS "Audio Level (dB)",
  round(loudness_lkfs,1) AS "Loudness (LKFS)", round(saturation_score,2) AS "Saturation",
  round(silence_seconds,1) AS "Silence (s)", device_id AS "device_id"
FROM quality_metrics WHERE {F} ORDER BY device_id, timestamp DESC"""
# Clicking a device name opens its L2 page (/monitoring/avq/<host>/<device_id>).
AVQ_BASE = "https://virtualpytest.angelstreet.io"
device_link = {"matcher": {"id": "byName", "options": "Device"}, "properties": [{"id": "links", "value": [
    {"title": "Open AVQ device page", "targetBlank": True,
     "url": AVQ_BASE + "/monitoring/avq/${__data.fields.Host}/${__data.fields.device_id}"}]}]}
hide_devid = {"matcher": {"id": "byName", "options": "device_id"}, "properties": [{"id": "custom.hidden", "value": True}]}
panels.append(table("Device Status (latest)", status_sql, 0, 6, 24, 9, 7,
                    overrides=[cbg("A/V Available"), cbg("Video"), cbg("Audio"), mbg("Video MOS"), mbg("Audio MOS"), device_link, hide_devid]))

# ---------- Main: 2-col — video (left) / audio (right) ----------
panels.append(row("Main", 15, 101))
# Row 1: per-device MOS
p = base_ts("Video MOS — per device", 0, 16, 12, 7, 10, mn=1, mx=5)
p["targets"] = [tgt(f"SELECT $__timeGroupAlias(timestamp,'1m'), device_name AS metric, avg(video_mos) AS value FROM quality_metrics WHERE {F} GROUP BY 1, device_name ORDER BY 1")]
panels.append(p)
p = base_ts("Audio MOS — per device", 12, 16, 12, 7, 11, mn=1, mx=5)
p["targets"] = [tgt(f"SELECT $__timeGroupAlias(timestamp,'1m'), device_name AS metric, avg(audio_mos) AS value FROM quality_metrics WHERE {F} GROUP BY 1, device_name ORDER BY 1")]
panels.append(p)
# Row 2: metric timelines w/ availability on right axis
p = base_ts("Video — Bluriness / Blockiness / Jerkiness", 0, 23, 12, 7, 12)
p["targets"] = [tgt(f'SELECT $__timeGroupAlias(timestamp,\'1m\'), avg(blurriness_score) AS "Bluriness", avg(blockiness_score) AS "Blockiness", avg(jerkiness_score) AS "Jerkiness", round(avg(video_availability)*100,1) AS "Availability %" FROM quality_metrics WHERE {F} GROUP BY 1 ORDER BY 1')]
p["fieldConfig"]["overrides"] = [axis_right("Availability %")]
panels.append(p)
p = base_ts("Audio — Audio Level / Loudness / Saturation / Silence", 12, 23, 12, 7, 13)
p["targets"] = [tgt(f'SELECT $__timeGroupAlias(timestamp,\'1m\'), avg(audio_level_db) AS "Audio Level (dB)", avg(loudness_lkfs) AS "Loudness (LKFS)", avg(saturation_score) AS "Saturation", avg(silence_seconds) AS "Silence (s)", round(avg(audio_availability)*100,1) AS "Availability %" FROM quality_metrics WHERE {F} GROUP BY 1 ORDER BY 1')]
p["fieldConfig"]["overrides"] = [axis_right("Availability %")]
panels.append(p)

# ---------- Details (collapsed) ----------
vid_ev = f"""SELECT device_name AS "Device",
  COALESCE(sum((events->'blackscreen'->>'count')::int),0) AS "Blackscreen events",
  round(COALESCE(sum(blackscreen_seconds),0),0) AS "Blackscreen (s)",
  round(COALESCE(max((events->'blackscreen'->>'longestMs')::int),0)/1000.0,0) AS "Longest blk (s)",
  COALESCE(sum((events->'freeze'->>'count')::int),0) AS "Freeze events",
  round(COALESCE(sum(freeze_seconds),0),0) AS "Freeze (s)",
  round(COALESCE(max((events->'freeze'->>'longestMs')::int),0)/1000.0,0) AS "Longest frz (s)",
  COALESCE(sum((events->'macroblocks'->>'count')::int),0) AS "Macroblock events",
  round(COALESCE(sum(macroblocks_seconds),0),0) AS "Macroblocks (s)"
FROM quality_metrics WHERE {F} GROUP BY device_name ORDER BY device_name"""
aud_ev = f"""SELECT device_name AS "Device",
  COALESCE(sum((events->'noSound'->>'count')::int),0) AS "No-sound events",
  round(COALESCE(sum((events->'noSound'->>'totalMs')::bigint),0)/1000.0,0) AS "No-sound dur (s)",
  round(COALESCE(max((events->'noSound'->>'longestMs')::int),0)/1000.0,0) AS "Longest silence (s)",
  round(min(loudness_lkfs),1) AS "Min loudness (LKFS)"
FROM quality_metrics WHERE {F} GROUP BY device_name ORDER BY device_name"""
audio_tr = f"""SELECT DISTINCT ON (device_id) device_name AS "Device",
  round(transcript_available*100,0) AS "Transcript %", transcript_language AS "Transcript Lang",
  NULLIF(translation_languages,'') AS "Translations", NULLIF(dubbed_languages,'') AS "Dubbed"
FROM quality_metrics WHERE {F} ORDER BY device_id, timestamp DESC"""
subs = f"""SELECT DISTINCT ON (device_id) device_name AS "Device",
  round(subtitle_availability*100,0) AS "Subtitle %", subtitle_language AS "Subtitle Lang"
FROM quality_metrics WHERE {F} ORDER BY device_id, timestamp DESC"""
panels.append(row("Details", 30, 102, collapsed=True, panels=[
    table("Video Events (count / duration)", vid_ev, 0, 0, 12, 8, 20),
    table("Audio Events (count / duration)", aud_ev, 12, 0, 12, 8, 21),
    table("Audio Translation (latest)", audio_tr, 0, 8, 24, 7, 22),
    table("Subtitles (latest)", subs, 0, 15, 24, 7, 23)]))

def tvar(name, sql):
    return {"name": name, "type": "query", "datasource": DS, "query": sql, "refresh": 2,
            "includeAll": True, "multi": True, "current": {"text": "All", "value": "$__all"}, "label": name.capitalize()}

dash = {"annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True, "name": "Annotations & Alerts", "type": "dashboard"}]},
    "description": "Audio/Video Quality (AVQ) — per-device KPIs from quality_metrics. Filter by host/device.",
    "editable": True, "graphTooltip": 1, "links": [], "panels": panels, "refresh": "1m", "schemaVersion": 39,
    "tags": ["avq", "quality", "monitoring"],
    "templating": {"list": [
        tvar("host", "SELECT DISTINCT host_name FROM quality_metrics WHERE $__timeFilter(timestamp) ORDER BY 1"),
        tvar("device", "SELECT DISTINCT device_name FROM quality_metrics WHERE $__timeFilter(timestamp) AND host_name IN (${host:sqlstring}) ORDER BY 1")]},
    "time": {"from": "now-6h", "to": "now"}, "timepicker": {}, "timezone": "",
    "title": "Audio / Video Quality (AVQ)", "uid": "avq-quality-overview", "version": 11, "weekStart": ""}
import os
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio-video-quality.json")
json.dump(dash, open(out, "w"), indent=2)
print("wrote", out, "panels:", len(panels))
