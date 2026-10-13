"""
Heatmap Template Utilities

Minimal HTML template for heatmap display with embedded CSS.
"""
from shared.src.lib.utils.report_theme import report_theme_head


def create_heatmap_html_template() -> str:
    """Create comprehensive heatmap HTML template that looks like the heatmap page."""
    # The caller runs .format() on this template: escape the head's CSS braces.
    theme_head = report_theme_head().replace('{', '{{').replace('}', '}}')
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    """ + theme_head + """
    <title>Heatmap Report - {timeframe}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--vpt-page); color: var(--vpt-text); padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; background: var(--vpt-surface); border-radius: 8px; box-shadow: var(--vpt-shadow); border: 1px solid var(--vpt-border); }}
        .header {{ background: var(--vpt-surface); color: var(--vpt-text); padding: 10px 20px; border-bottom: 1px solid var(--vpt-border); }}
        .header h1 {{ font-size: 1.4em; margin: 0; line-height: 1.2; }}

        .mosaic-player {{ padding: 20px; margin-bottom: 0; }}
        .mosaic-container {{
            width: 90%; height: 50vh; margin: 0 auto 20px auto; position: relative;
            background: black; border-radius: 8px; overflow: hidden;
            display: flex; align-items: center; justify-content: center;
        }}
        .mosaic-img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}

        .timeline-controls {{
            margin-top: 10px; padding: 10px; background: var(--vpt-subtle);
            border-radius: 8px; display: flex; align-items: center; gap: 15px;
        }}
        .timeline {{ flex: 1; position: relative; }}
        .timeline-slider {{ width: 100%; -webkit-appearance: none; height: 6px; background: var(--vpt-border); border-radius: 3px; }}
        .timeline-slider::-webkit-slider-thumb {{
            -webkit-appearance: none; width: 16px; height: 16px; background: var(--vpt-accent);
            border-radius: 50%; cursor: pointer;
        }}
        .timeline-marks {{ position: absolute; top: -25px; left: 0; right: 0; height: 25px; }}
        .timeline-mark {{
            position: absolute; transform: translateX(-50%); cursor: pointer;
            font-size: 10px; text-align: center; line-height: 1.2;
        }}
        .timeline-mark:hover {{ font-weight: bold; }}
        .timeline-mark .time-label {{ font-size: 10px; display: inline; }}
        .timeline-mark .date-label {{ font-size: 8px; color: var(--vpt-muted); display: inline; margin-left: 4px; }}
        .timeline-mark.current {{
            border: 2px solid var(--vpt-accent); border-radius: 4px; padding: 2px;
            font-weight: bold; color: var(--vpt-accent-text);
        }}
        .frame-counter {{ font-size: 0.9em; min-width: 60px; text-align: right; }}

        .analysis-section {{ padding: 5px 20px 10px; }}
        .analysis-section h2 {{ margin: 0 0 8px 0; font-size: 1.1em; }}
        .analysis-table {{ width: 100%; border-collapse: collapse; margin-top: 0; background: var(--vpt-surface); }}
        .analysis-table th {{ background: var(--vpt-subtle); padding: 12px 8px; text-align: left; font-weight: bold; border-bottom: 1px solid var(--vpt-border); }}
        .analysis-table td {{ padding: 8px; border-bottom: 1px solid var(--vpt-border); }}
        .analysis-table tr:hover {{ background-color: var(--vpt-subtle); }}
        .chip {{ display: inline-block; padding: 4px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 500; }}
        .chip.success {{ background-color: var(--vpt-success-tint); color: var(--vpt-success); border: 1px solid var(--vpt-success); }}
        .chip.error {{ background-color: var(--vpt-error-tint); color: var(--vpt-error); border: 1px solid var(--vpt-error); }}
        .chip.default {{ background-color: var(--vpt-subtle); color: var(--vpt-text-2); }}
        .text-success {{ color: var(--vpt-success); }}
        .text-error {{ color: var(--vpt-error); }}

        .modal {{ display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); }}
        .modal.active {{ display: flex; justify-content: center; align-items: center; }}
        .modal img {{ max-width: 95%; max-height: 95%; }}
        .modal .close {{ position: absolute; top: 20px; right: 30px; color: white; font-size: 40px; cursor: pointer; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Heatmap Report - {generated_at} - {total_devices} Devices - {total_timestamps} Timestamps - {incidents_count} Incidents</h1>
        </div>

        <div class="mosaic-player">
            <div class="mosaic-container">
                <img id="currentMosaic" src="{first_mosaic_url}" alt="Heatmap Mosaic" class="mosaic-img" onclick="openModal()">
            </div>

            <div class="timeline-controls">
                <div class="timeline">
                    <input type="range" id="timelineSlider" class="timeline-slider" min="0" max="{max_frame}" value="{max_frame}" oninput="changeFrame(this.value)">
                    <div class="timeline-marks">
                        {timeline_marks}
                    </div>
                </div>
                <div id="frameCounter" class="frame-counter">{total_timestamps} / {total_timestamps}</div>
            </div>
        </div>

        <div class="analysis-section">
            <h2>Device Analysis</h2>
            <table id="currentAnalysis" class="analysis-table">
                <thead>
                    <tr>
                        <th>Device</th>
                        <th>Audio</th>
                        <th>Video</th>
                        <th>Volume %</th>
                        <th>Mean dB</th>
                        <th>Blackscreen</th>
                        <th>Freeze</th>
                    </tr>
                </thead>
                <tbody>
                    {first_analysis_items}
                </tbody>
            </table>
        </div>
    </div>

    <div id="modal" class="modal" onclick="closeModal()">
        <span class="close">&times;</span>
        <img id="modalImg" src="{first_mosaic_url}" alt="Heatmap Mosaic">
    </div>

    <script>
        // Data for all timestamps
        const mosaicData = {mosaic_data_json};
        let currentFrame = mosaicData.length - 1; // Start at latest frame (far right)
        
        function changeFrame(frameIndex) {{
            currentFrame = parseInt(frameIndex);
            const data = mosaicData[currentFrame];
            
            // Update mosaic image
            document.getElementById('currentMosaic').src = data.mosaic_url;
            document.getElementById('modalImg').src = data.mosaic_url;
            
            // Update frame counter
            document.getElementById('frameCounter').textContent = `${{currentFrame + 1}} / ${{mosaicData.length}}`;
            
            // Update timeline marks - highlight current
            const marks = document.querySelectorAll('.timeline-mark');
            marks.forEach((mark, index) => {{
                if (index === currentFrame) {{
                    mark.classList.add('current');
                }} else {{
                    mark.classList.remove('current');
                }}
            }});
            
            // Update analysis
            document.getElementById('currentAnalysis').getElementsByTagName('tbody')[0].innerHTML = data.analysis_html;
        }}
        
        // Initialize to latest frame on page load
        window.addEventListener('load', function() {{
            changeFrame(currentFrame);
        }});
        
        function openModal() {{ document.getElementById('modal').classList.add('active'); }}
        function closeModal() {{ document.getElementById('modal').classList.remove('active'); }}
    </script>
</body>
</html>""" 