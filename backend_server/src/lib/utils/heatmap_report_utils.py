"""
Heatmap Report Utilities

Comprehensive HTML generation for heatmap display with timeline navigation.
"""

import json
from datetime import datetime
from typing import Dict, List
from .heatmap_template_utils import create_heatmap_html_template

def generate_comprehensive_heatmap_html(all_heatmap_data: List[Dict]) -> str:
    """Generate ONE comprehensive heatmap HTML report with all mosaics and timeline navigation."""
    try:
        template = create_heatmap_html_template()
        
        if not all_heatmap_data:
            return "<html><body><h1>No heatmap data available</h1></body></html>"
        
        # Calculate summary stats with null checks
        total_timestamps = len(all_heatmap_data)
        
        # Safe access to analysis_data with null checks
        first_data = all_heatmap_data[0] if all_heatmap_data else {}
        analysis_data = first_data.get('analysis_data', []) if first_data else []
        total_devices = len(analysis_data) if analysis_data else 0
        
        # Count incidents with null checks
        incidents_count = 0
        for data in all_heatmap_data:
            if data and isinstance(data, dict):
                incidents = data.get('incidents', [])
                if incidents:
                    incidents_count += len(incidents)
        
        generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Prepare data for JavaScript
        mosaic_data_for_js = []
        timeline_marks = []
        
        for i, heatmap_data in enumerate(all_heatmap_data):
            # Skip if heatmap_data is None or not a dict
            if not heatmap_data or not isinstance(heatmap_data, dict):
                continue
                
            # Process analysis data - only include devices with actual analysis
            analysis_items = []
            has_incidents = False
            
            if heatmap_data and isinstance(heatmap_data, dict):
                analysis_data = heatmap_data.get('analysis_data', [])
                if analysis_data and isinstance(analysis_data, list):
                    for item in analysis_data:
                        if item and isinstance(item, dict):
                            # Host endpoint now guarantees all images have analysis_json
                            analysis_json = item.get('analysis_json')
                            
                            host_name = item.get('host_name', 'Unknown')
                            device_id = item.get('device_id', 'Unknown')
                            has_error = item.get('error') is not None
                            
                            # Safe access to analysis_json (guaranteed to exist from host)
                            if not analysis_json or not isinstance(analysis_json, dict):
                                analysis_json = {}
                            
                            # Check if this device has incidents
                            device_has_incidents = (
                                analysis_json.get('freeze', False) or
                                analysis_json.get('blackscreen', False) or
                                analysis_json.get('audio') is False
                            )

                            if device_has_incidents:
                                has_incidents = True

                            # Generate table row (matching React component exactly)
                            has_video = not analysis_json.get('blackscreen', False) and not analysis_json.get('freeze', False)
                            # Three-state audio: True=Yes, False=No (loss), None/absent=N/A (no audio capture)
                            audio_raw = analysis_json.get('audio')
                            audio_chip_class = 'success' if audio_raw is True else ('error' if audio_raw is False else 'default')
                            audio_chip_label = 'Yes' if audio_raw is True else ('No' if audio_raw is False else 'N/A')
                            volume_raw = analysis_json.get('volume_percentage')
                            mean_volume_raw = analysis_json.get('mean_volume_db')
                            volume_percentage = f"{volume_raw}%" if volume_raw is not None else 'N/A'
                            mean_volume_db = f"{mean_volume_raw} dB" if mean_volume_raw is not None else 'N/A'
                            blackscreen_percentage = analysis_json.get('blackscreen_percentage', 0)
                            freeze_diffs = analysis_json.get('freeze_diffs', [])

                            # Format freeze diffs as comma-separated string
                            freeze_diffs_str = ', '.join(map(str, freeze_diffs)) if freeze_diffs else ''

                            analysis_items.append(f"""
                            <tr>
                                <td>{host_name}-{device_id}</td>
                                <td><span class="chip {audio_chip_class}">{audio_chip_label}</span></td>
                                <td><span class="chip {'success' if has_video else 'error'}">{'Yes' if has_video else 'No'}</span></td>
                                <td>{volume_percentage}</td>
                                <td>{mean_volume_db}</td>
                                <td><span class="{'text-success' if not analysis_json.get('blackscreen', False) else 'text-error'}">{'No' if not analysis_json.get('blackscreen', False) else f'Yes ({blackscreen_percentage}%)'}</span></td>
                                <td><span class="{'text-success' if not analysis_json.get('freeze', False) else 'text-error'}">{'No' if not analysis_json.get('freeze', False) else f'Yes ({freeze_diffs_str})'}</span></td>
                            </tr>
                            """)
            
            # Add to JavaScript data
            mosaic_data_for_js.append({
                'mosaic_url': heatmap_data.get('mosaic_url', ''),
                'analysis_html': ''.join(analysis_items),
                'timestamp': heatmap_data.get('timestamp', ''),
                'has_incidents': has_incidents
            })
            
            # Create timeline mark with time label (like in React MosaicPlayer)
            mark_position = (i / max(1, total_timestamps - 1)) * 100
            timestamp = heatmap_data.get('timestamp', '')
            
            # Latest frame (last in array) is current by default
            current_class = "current" if i == total_timestamps - 1 else ""
            
            timeline_marks.append(f"""
            <div class="timeline-mark {current_class}" style="left: {mark_position}%" onclick="changeFrame({i})">
                <span class="time-label">{timestamp}</span>
                <span class="date-label">Today</span>
            </div>
            """)
        
        # Get latest frame data safely (last item in array is now the latest)
        latest_data = all_heatmap_data[-1] if all_heatmap_data else {}
        first_mosaic_url = latest_data.get('mosaic_url', '') if latest_data else ''
        first_analysis_items = mosaic_data_for_js[-1]['analysis_html'] if mosaic_data_for_js else ''
        first_timestamp = latest_data.get('timestamp', '') if latest_data else ''
        
        # Create timeframe string
        if total_timestamps > 1 and all_heatmap_data:
            last_timestamp = all_heatmap_data[-1].get('timestamp', '') if all_heatmap_data[-1] else ''
            timeframe = f"{first_timestamp} - {last_timestamp}"
        else:
            timeframe = first_timestamp
        
        # Fill template
        html_content = template.format(
            timeframe=timeframe,
            generated_at=generated_at,
            total_devices=total_devices,
            total_timestamps=total_timestamps,
            incidents_count=incidents_count,
            first_mosaic_url=first_mosaic_url,
            first_timestamp=first_timestamp,
            max_frame=max(0, total_timestamps - 1),
            timeline_marks=''.join(timeline_marks),
            first_analysis_items=first_analysis_items,
            mosaic_data_json=json.dumps(mosaic_data_for_js)
        )
        
        return html_content
        
    except Exception as e:
        print(f"[@heatmap_report_utils] Error details: {str(e)}")
        return f"<html><body><h1>Error generating comprehensive heatmap HTML</h1><p>{str(e)}</p></body></html>" 