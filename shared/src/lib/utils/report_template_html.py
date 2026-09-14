"""
Report Template HTML Structure

Contains the HTML structure for validation reports.
"""

from .report_template_css import get_report_css
from .report_template_js import get_report_javascript


def create_themed_html_template() -> str:
    """Create the themed HTML template with embedded CSS and theme system."""
    css_content = get_report_css().strip()
    js_content = get_report_javascript().strip()
    
    # Escape CSS content to prevent template conflicts
    css_content = css_content.replace('{', '{{').replace('}', '}}')
    # JavaScript should NOT be escaped - it's already properly formatted
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Validation Report - {{script_name}}</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
{css_content}
    </style>
    <script>
{js_content}
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-left">
                <h1>{{script_name}}</h1>
                <div class="time-info">
                    {{execution_date}} | Start: {{start_time}} | End: {{end_time}}{{testcase_builder_link}}
                </div>
            </div>
            <div class="theme-toggle">
                <div class="theme-slider light"></div>
                <div class="theme-option" data-theme="light">Light</div>
                <div class="theme-option" data-theme="dark">Dark</div>
                <div class="theme-option" data-theme="system">System</div>
            </div>
        </div>
        
        <div class="summary">
            <div class="summary-grid">
                <div class="summary-item">
                    <span class="label">Status:</span>
                    <span class="value {{success_class}}">{{success_status}}</span>
                </div>
                <div class="summary-item">
                    <span class="label">Duration:</span>
                    <span class="value neutral">{{execution_time}}</span>
                </div>
                <div class="summary-item">
                    <span class="label">Device:</span>
                    <span class="value neutral">{{device_name}}</span>
                </div>
                <div class="summary-item">
                    <span class="label">Host:</span>
                    <span class="value neutral">{{host_name}}</span>
                </div>
                <div class="summary-item">
                    <span class="label">Success:</span>
                    <span class="value success">{{passed_steps}}/{{total_steps}}</span>
                </div>
                <div class="summary-item">
                    <span class="label">Failure:</span>
                    <span class="value failure">{{failed_steps}}/{{total_steps}}</span>
                </div>
            </div>
        </div>
        
        <div class="content">
            <div class="section">
                <div class="section-header" onclick="toggleSection('summary-content')">
                    <h2>Execution Summary & State</h2>
                    <button class="toggle-btn expanded">▼</button>
                </div>
                <div id="summary-content" class="collapsible-content expanded">
                    {{overview_section}}
                </div>
            </div>
            
            {{zap_summary_section}}

            {{edge_results_section}}

            {{mosaic_section}}

            <div class="section">
                <div class="section-header" onclick="toggleSection('steps-content')">
                    <h2>{{steps_section_title}}</h2>
                    <button class="toggle-btn expanded">▼</button>
                </div>
                <div id="steps-content" class="collapsible-content expanded">
                    {{step_results_html}}
                </div>
            </div>
            
            {{error_section}}
        </div>
    </div>
    
    <div id="screenshot-modal" class="screenshot-modal">
        <div class="modal-content">
            <span class="close" onclick="closeScreenshot()">&times;</span>
            <div class="modal-header">
                <h3 id="modal-step-title">Screenshot</h3>
                <div id="modal-action-info" class="action-info"></div>
            </div>
            <div class="modal-body">
                <button id="modal-prev" class="nav-arrow nav-prev" onclick="navigateScreenshot(-1)">‹</button>
                <img id="modal-img" src="" alt="Screenshot">
                <button id="modal-next" class="nav-arrow nav-next" onclick="navigateScreenshot(1)">›</button>
            </div>
            <div class="modal-footer">
                <span id="modal-counter">1 / 1</span>
            </div>
        </div>
    </div>
</body>
</html>"""
