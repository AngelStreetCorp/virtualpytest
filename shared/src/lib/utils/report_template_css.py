"""
Report Template CSS Styles

Contains all CSS styles for the HTML validation reports.
"""

def get_css_z_index(component: str, offset: int = 0) -> int:
    """
    Get z-index values that align with the frontend centralized z-index system.
    This keeps report CSS z-indexes consistent with the frontend layout.
    """
    # Map CSS components to frontend z-index equivalents (base + offset)
    css_z_index_map = {
        'theme_slider': 20,  # UI_ELEMENTS level (60) scaled down for CSS
        'modal_backdrop': 280,  # MODAL_BACKDROP level
        'modal_content': 290,  # MODAL_CONTENT level  
        'nav_arrow': 291,  # MODAL_CONTENT level + 1
    }
    
    base_z_index = css_z_index_map.get(component, 1)
    return base_z_index + offset

def get_report_css() -> str:
    """Get the complete CSS styles for the report template."""
    # Generate z-index values
    theme_slider_z = get_css_z_index('theme_slider')
    theme_slider_bg_z = get_css_z_index('theme_slider', -1)
    modal_backdrop_z = get_css_z_index('modal_backdrop')
    nav_arrow_z = get_css_z_index('nav_arrow')
    
    return f""":root {{
    /* Light theme — the web app's palette (frontend/src/constants/agentChatTheme.ts, UI_STYLE.md):
       warm grey page under white cards, gold accent, palette status colours. */
    color-scheme: light dark;  /* the page does its own dark theme: browsers must not auto-darken it */
    --bg-primary: #f2f0ec;
    --bg-secondary: #ffffff;
    --bg-tertiary: #ebe7e0;
    --container-bg: #f2f0ec;  /* report body on the page tone… */
    --card-bg: #ffffff;       /* …with white cards on it, like the app */
    --text-primary: #141414;
    --text-secondary: #4a4a4a;
    --text-muted: #6e6e6e;
    --border-color: #d9d4cc;
    --border-light: #ebe7e0;
    --shadow: 0 1px 3px rgba(60,50,30,0.08);
    --shadow-hover: 0 2px 8px rgba(60,50,30,0.12);
    --accent: #d4a574;
    --accent-text: #8f5f2e;
    --series-steel: #3f6f8f;
    --success-color: #16a34a;
    --success-bg: #16a34a1f;
    --success-text: #16a34a;
    --failure-color: #dc2626;
    --failure-bg: #dc26261f;
    --failure-text: #dc2626;
    --skipped-color: #b45309;
    --skipped-bg: #b453091f;
    --skipped-text: #b45309;
    --recovery-color: #3f6f8f;
    --recovery-bg: #3f6f8f1f;
    --recovery-text: #3f6f8f;
    --header-bg: #ffffff;
    --header-text: #141414;
    --step-hover: #ebe7e0;
    --error-bg: #dc26261a;
    --error-border: #dc262666;
    --modal-bg: rgba(0,0,0,0.8);
    --link-color: #8f5f2e;
}}

[data-theme="dark"] {{
    /* Dark theme — the web app's dark palette */
    --bg-primary: #0a0a0a;
    --bg-secondary: #242424;
    --bg-tertiary: #2a2a2a;
    --container-bg: #242424;
    --card-bg: #2a2a2a;
    --text-primary: #f0f0f0;
    --text-secondary: #9a9a9a;
    --text-muted: #666666;
    --border-color: #383838;
    --border-light: #2a2a2a;
    --shadow: 0 4px 6px rgba(0,0,0,0.3);
    --shadow-hover: 0 8px 16px rgba(0,0,0,0.4);
    --accent: #d4a574;
    --accent-text: #d4a574;
    --series-steel: #7aa6c2;
    --success-color: #22c55e;
    --success-bg: #22c55e1f;
    --success-text: #22c55e;
    --failure-color: #ef4444;
    --failure-bg: #ef44441f;
    --failure-text: #ef4444;
    --skipped-color: #f59e0b;
    --skipped-bg: #f59e0b1f;
    --skipped-text: #f59e0b;
    --recovery-color: #7aa6c2;
    --recovery-bg: #7aa6c21f;
    --recovery-text: #7aa6c2;
    --header-bg: #1a1a1a;
    --header-text: #f0f0f0;
    --step-hover: #2a2a2a;
    --error-bg: #ef44441a;
    --error-border: #ef444466;
    --modal-bg: rgba(0,0,0,0.9);
    --link-color: #d4a574;
}}

* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

/* Device/UI screenshots are inherently light-mode artifacts. Force EVERY report
   image onto a white surface with a light color-scheme so transparent or
   letterboxed (object-fit: contain) areas never pick up the dark theme
   background — this applies regardless of the active report theme. */
img {{
    background-color: #ffffff !important;
    color-scheme: light;
    forced-color-adjust: none;
}}

body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.4;
    color: var(--text-primary);
    background: var(--bg-primary);
    padding: 10px;
    font-size: 14px;
    transition: background-color 0.3s ease, color 0.3s ease;
    min-height: 100vh;
    overflow-x: hidden;
    overflow-y: auto;
}}

.container {{
    max-width: 1400px;
    margin: 0 auto;
    background: var(--container-bg);
    border-radius: 6px;
    box-shadow: var(--shadow);
    overflow: hidden;
    transition: background-color 0.3s ease, box-shadow 0.3s ease;
}}

.header {{
    background: var(--header-bg);
    color: var(--header-text);
    border-bottom: 1px solid var(--border-color);
    padding: 8px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    min-height: 40px;
}}

.header-left {{
    display: flex;
    align-items: center;
    gap: 15px;
}}

.header h1 {{
    font-size: 1.4em;
    font-weight: 600;
}}

.header .time-info {{
    font-size: 0.85em;
    opacity: 0.9;
    white-space: nowrap;
}}

.header-controls {{
    display: flex;
    align-items: center;
    gap: 10px;
}}

.lang-switch {{
    display: flex;
    align-items: center;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 2px;
}}

.lang-switch:empty {{
    display: none;
}}

.lang-option {{
    padding: 4px 10px;
    border-radius: 16px;
    font-size: 0.75em;
    font-weight: 500;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border: none;
    background: transparent;
    color: inherit;
    font-family: inherit;
    transition: all 0.2s ease;
}}

.lang-option:hover {{
    background: var(--border-light);
}}

.lang-option.active {{
    background: var(--bg-secondary);
    color: var(--accent-text);
    box-shadow: 0 0 0 1px var(--border-color);
}}

.header-icon-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    padding: 0;
    border-radius: 50%;
    border: 1px solid var(--border-color);
    background: var(--bg-tertiary);
    color: inherit;
    cursor: pointer;
    text-decoration: none;
    transition: all 0.2s ease;
}}

.header-icon-btn:hover {{
    background: var(--border-color);
}}

.theme-toggle {{
    display: flex;
    align-items: center;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 2px;
    cursor: pointer;
    transition: all 0.2s ease;
    position: relative;
}}

.theme-toggle:hover {{
    background: var(--border-light);
}}

/* icon-only options (sun / moon / monitor): same width in every language, no header shift */
.theme-option {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 26px;
    border-radius: 16px;
    transition: all 0.2s ease;
    cursor: pointer;
    position: relative;
    z-index: {theme_slider_z};
}}

.theme-option.active {{
    background: var(--bg-secondary);
    color: var(--accent-text);
    box-shadow: 0 0 0 1px var(--border-color);
}}

.theme-slider {{
    position: absolute;
    top: 2px;
    left: 2px;
    width: calc(33.33% - 2px);
    height: calc(100% - 4px);
    background: var(--bg-secondary);
    box-shadow: 0 0 0 1px var(--border-color);
    border-radius: 16px;
    transition: transform 0.2s ease;
    z-index: {theme_slider_bg_z};
}}

.theme-slider.light {{
    transform: translateX(0);
}}

.theme-slider.dark {{
    transform: translateX(100%);
}}

.theme-slider.system {{
    transform: translateX(200%);
}}

.summary {{
    padding: 12px 20px;
    background: var(--bg-tertiary);
    border-bottom: 1px solid var(--border-color);
    transition: background-color 0.3s ease, border-color 0.3s ease;
}}

.summary-grid {{
    display: grid;
    grid-template-columns: auto auto 1fr 1fr auto auto;
    gap: 8px;
    align-items: center;
}}

.summary-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: var(--bg-secondary);
    border-radius: 4px;
    border: 1px solid var(--border-light);
    font-size: 0.9em;
    transition: all 0.3s ease;
}}

.summary-item .label {{
    color: var(--text-secondary);
    font-weight: 500;
}}

.summary-item .value {{
    font-weight: 600;
}}

.success {{
    color: var(--success-color);
}}

.failure {{
    color: var(--failure-color);
}}

.skipped {{
    color: var(--skipped-color);
}}

.neutral {{
    color: var(--text-secondary);
}}

.content {{
    padding: 15px 20px;
}}

.section {{
    margin-bottom: 20px;
}}

.section-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    cursor: pointer;
    padding: 8px 0;
    border-bottom: 1px solid var(--border-light);
    transition: border-color 0.3s ease;
}}

.section-header h2 {{
    color: var(--text-primary);
    font-size: 1.1em;
    font-weight: 600;
}}

.toggle-btn {{
    background: none;
    border: none;
    font-size: 1.2em;
    cursor: pointer;
    color: var(--text-secondary);
    transition: color 0.3s ease;
}}

.collapsible-content {{
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.4s ease;
}}

.collapsible-content.expanded {{
    max-height: none;
    overflow: visible;
}}

.step-list {{
    background: var(--bg-secondary);
    border: 1px solid var(--border-light);
    border-radius: 4px;
    overflow: hidden;
    transition: border-color 0.3s ease;
}}

.step-item {{
    display: flex;
    align-items: center;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-light);
    cursor: pointer;
    transition: background-color 0.2s, border-color 0.3s ease;
}}

.step-item:last-child {{
    border-bottom: none;
}}

.step-item.success {{
    border-left: 3px solid var(--success-color);
}}

.step-item.failure {{
    border-left: 3px solid var(--failure-color);
}}

.step-item.skipped {{
    border-left: 3px solid var(--skipped-color);
}}

.step-item.recovery {{
    border-left: 3px solid var(--recovery-color);
}}

.step-number {{
    width: 30px;
    font-weight: 600;
    color: var(--text-secondary);
    font-size: 0.9em;
}}

.step-status {{
    min-width: 50px;
    text-align: center;
    white-space: nowrap;  /* "BESTANDEN" / "RÉUSSI" are wider than "PASS" */
}}

.step-status-badge {{
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: 600;
    text-transform: uppercase;
    transition: all 0.3s ease;
}}

.step-status-badge.success {{
    background: var(--success-bg);
    color: var(--success-text);
}}

.step-status-badge.failure {{
    background: var(--failure-bg);
    color: var(--failure-text);
}}

.step-status-badge.skipped {{
    background: var(--skipped-bg);
    color: var(--skipped-text);
}}

.step-status-badge.recovery {{
    background: var(--recovery-bg);
    color: var(--recovery-text);
}}

.step-message {{
    flex: 1;
    padding-left: 12px;
    font-size: 0.9em;
}}

.step-timing-inline {{
    font-size: 0.8em;
    color: var(--text-secondary);
    margin-left: 10px;
    white-space: nowrap;
}}

.step-details {{
    max-height: 0;
    overflow: hidden;
    padding: 0 12px;
    background: var(--bg-tertiary);
    border-top: 1px solid var(--border-light);
    transition: max-height 0.4s ease, padding 0.4s ease;
}}

.step-details.expanded {{
    max-height: none;
    overflow: visible;
    padding: 12px;
}}

.step-details-content {{
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 15px;
    align-items: start;
}}

.step-info {{
    display: flex;
    flex-direction: column;
    gap: 8px;
}}

.step-timing {{
    display: flex;
    gap: 15px;
    font-size: 0.85em;
    color: var(--text-secondary);
}}

.step-actions {{
    font-size: 0.9em;
}}

.step-actions strong {{
    color: var(--text-primary);
}}

.action-item, .verification-item {{
    margin: 4px 0;
    padding: 4px 8px;
    background: var(--bg-secondary);
    border-radius: 4px;
    border-left: 3px solid var(--border-color);
    font-family: 'Courier New', monospace;
    font-size: 0.85em;
}}

.action-item {{
    border-left-color: var(--accent);
}}

.retry-action-item {{
    margin: 4px 0;
    padding: 4px 8px;
    background: var(--bg-secondary);
    border-radius: 4px;
    border-left: 3px solid var(--skipped-color);
    font-family: 'Courier New', monospace;
    font-size: 0.85em;
}}

.retry-action-item.executed {{
    background: var(--skipped-bg);
    border-left-color: var(--skipped-color);
}}

.failure-action-item {{
    margin: 4px 0;
    padding: 4px 8px;
    background: var(--bg-secondary);
    border-radius: 4px;
    border-left: 3px solid var(--border-color);
    font-family: 'Courier New', monospace;
    font-size: 0.85em;
}}

.failure-action-item.executed {{
    background: var(--failure-bg);
    border-left-color: var(--failure-color);
}}

.retry-status, .failure-status {{
    font-size: 0.75em;
    padding: 2px 6px;
    border-radius: 3px;
    font-weight: bold;
    margin-left: 8px;
}}

.retry-status.available, .failure-status.available {{
    background: var(--bg-tertiary);
    color: var(--text-secondary);
}}

.retry-status.executed {{
    background: var(--skipped-color);
    color: white;
}}

.failure-status.executed {{
    background: var(--failure-color);
    color: white;
}}

.action-result-badge {{
    display: inline-block;
    font-size: 0.85em;
    padding: 2px 6px;
    border-radius: 3px;
    font-weight: bold;
    margin-left: 8px;
}}

.action-result-badge.success {{
    background: var(--success-bg);
    color: var(--success-text);
}}

.action-result-badge.failure {{
    background: var(--failure-bg);
    color: var(--failure-text);
}}

.verification-item {{
    border-left-color: var(--series-steel);
}}

.verification-result-badge {{
    display: inline-block;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.75em;
    font-weight: bold;
    margin-left: 8px;
}}

.verification-result-badge.success {{
    background-color: var(--success-bg);
    color: var(--success-color);
}}

.verification-result-badge.failure {{
    background-color: var(--failure-bg);
    color: var(--failure-color);
}}

.verification-error {{
    color: var(--failure-color);
    font-style: italic;
    font-size: 0.8em;
    margin-left: 4px;
}}

/* Neutral secondary metadata next to a verification badge — e.g. OCR
   "required 80% · read 'Settings'". Same dim/italic vibe as
   .verification-error but uses the muted text color, not failure red,
   so it reads as "context" on passing verifications too. */
.verification-meta {{
    color: var(--text-muted);
    font-style: italic;
    font-size: 0.8em;
    margin-left: 4px;
    font-family: 'Courier New', monospace;
}}

.verification-score {{
    font-family: 'Courier New', monospace;
    font-size: 0.8em;
    margin-left: 8px;
    padding: 2px 6px;
    border-radius: 3px;
    font-weight: bold;
}}

.verification-score.success {{
    background-color: var(--success-bg);
    color: var(--success-color);
}}

.verification-score.failure {{
    background-color: var(--failure-bg);
    color: var(--failure-color);
}}

.screenshot-modal, .modal {{
    display: none;
    position: fixed;
    z-index: {modal_backdrop_z};
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    background-color: var(--modal-bg);
    transition: background-color 0.3s ease;
}}

.screenshot-modal.active, .modal.active {{
    display: flex;
    justify-content: center;
    align-items: center;
}}

.modal-content {{
    position: relative;
    width: 900px;
    height: 640px;
    max-width: 98%;
    max-height: 98%;
    background: var(--bg-secondary);
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    display: flex;
    flex-direction: column;
}}

.modal-header {{
    text-align: center;
    margin-bottom: 15px;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 10px;
}}

.modal-header h3 {{
    margin: 0;
    color: var(--text-primary);
    font-size: 1.2em;
}}

.action-info {{
    margin-top: 8px;
    color: var(--text-secondary);
    font-size: 0.9em;
    font-family: monospace;
    background: var(--bg-tertiary);
    padding: 5px 10px;
    border-radius: 4px;
    height: 48px;
    overflow: auto;
    word-break: break-all;
    text-align: left;
    box-sizing: border-box;
}}

.modal-body {{
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    flex: 1 1 auto;
    min-height: 0;
}}

.modal-body img {{
    width: 100%;
    height: 100%;
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    background: #f8f9fa;
}}

.nav-arrow {{
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(0,0,0,0.7);
    color: white;
    border: none;
    font-size: 30px;
    width: 50px;
    height: 50px;
    border-radius: 50%;
    cursor: pointer;
    z-index: {nav_arrow_z};
    display: flex;
    align-items: center;
    justify-content: center;
}}

.nav-arrow:hover {{
    background: rgba(0,0,0,0.9);
}}

.nav-arrow:disabled {{
    opacity: 0.3;
    cursor: not-allowed;
}}

.nav-prev {{
    left: 10px;
}}

.nav-next {{
    right: 10px;
}}

.modal-footer {{
    text-align: center;
    margin-top: 15px;
    padding-top: 10px;
    border-top: 1px solid var(--border-color);
    color: var(--text-secondary);
    font-size: 0.9em;
}}

.screenshot-modal .close {{
    position: absolute;
    top: -10px;
    right: -10px;
    color: var(--text-primary);
    background: var(--bg-secondary);
    border: 2px solid var(--border-color);
    border-radius: 50%;
    width: 30px;
    height: 30px;
    font-size: 20px;
    font-weight: bold;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
}}

.screenshot-modal .close:hover, .modal-close:hover {{
    background: var(--failure-color);
    color: white;
    border-color: var(--failure-color);
}}

.modal-close {{
    position: absolute;
    top: -10px;
    right: -10px;
    color: var(--text-primary);
    background: var(--bg-secondary);
    border: 2px solid var(--border-color);
    border-radius: 50%;
    width: 30px;
    height: 30px;
    font-size: 20px;
    font-weight: bold;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
}}

.screenshot-container {{
    text-align: center;
}}

.screenshot-label {{
    display: none;
}}

.screenshot-thumbnail {{
    width: 100%;
    max-width: 200px;
    height: 120px;
    object-fit: cover;
    border-radius: 4px;
    border: 2px solid var(--border-color);
    cursor: pointer;
    transition: all 0.2s;
    color-scheme: light;
    forced-color-adjust: none;
}}

.screenshot-container {{
    color-scheme: light;
    forced-color-adjust: none;
}}

.screenshot-thumbnail:hover {{
    border-color: var(--accent);
    transform: scale(1.02);
    box-shadow: var(--shadow-hover);
}}

.screenshot-row {{
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: flex-start;
}}

.screenshot-row .screenshot-container {{
    flex: 0 0 auto;
}}

.screenshot-row .screenshot-thumbnail {{
    max-width: 150px;
    height: 90px;
}}

.state-video-grid-container {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 20px;
    margin-top: 15px;
    margin-bottom: 25px;
}}

.state-video-grid-item {{
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border: 1px solid var(--border-light);
    border-radius: 6px;
    padding: 15px;
    transition: all 0.3s ease;
    text-align: center;
}}

.state-video-grid-item h3 {{
    color: var(--text-primary);
    font-size: 1.1em;
    font-weight: 600;
    margin-bottom: 12px;
    border-bottom: 1px solid var(--border-light);
    padding-bottom: 8px;
}}

.execution-summary-section {{
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border: 1px solid var(--border-light);
    border-radius: 6px;
    padding: 15px;
    margin-top: 10px;
}}

.execution-summary-section h3 {{
    color: var(--text-primary);
    font-size: 1.1em;
    font-weight: 600;
    margin-bottom: 12px;
    border-bottom: 1px solid var(--border-light);
    padding-bottom: 8px;
}}

.execution-summary-content {{
    font-size: 0.9em;
    line-height: 1.4;
}}

/* report_icons: line icons sit on the text baseline wherever they are used */
.r-icon {{
    vertical-align: -0.15em;
    flex: none;
}}

/* emoji drawn as icons (report_icons.EMOJI_ICONS): text-sized, on the baseline; neutral ones take
   the text colour, only pass / fail / warning are coloured */
.r-emoji {{
    width: 1.15em;
    height: 1.15em;
    vertical-align: -0.2em;
}}

.r-emoji.tone-ok {{
    color: var(--success-color);
}}

.r-emoji.tone-fail {{
    color: var(--failure-color);
}}

.r-emoji.tone-warn {{
    color: var(--skipped-color);
}}

/* summary text and the links below it: one font, one left edge */
.execution-summary-content .summary-text {{
    white-space: pre-wrap;
    font-family: inherit;
    margin: 0 0 10px 0;
}}

.report-links {{
    display: grid;
    grid-template-columns: 18px max-content 1fr;
    column-gap: 8px;
    row-gap: 5px;
    align-items: center;
    padding-top: 10px;
    border-top: 1px solid var(--border-light);
}}

.report-links .rl-icon {{
    display: inline-flex;
    color: var(--text-primary);
}}

.report-links .rl-label {{
    color: var(--text-primary);
}}

.report-links a {{
    color: var(--link-color);
    text-decoration: none;
    font-weight: 600;
}}

.report-links a:hover {{
    text-decoration: underline;
}}

.report-links code {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.95em;
}}

.test-video-content {{
    text-align: center;
}}

.screenshot-container {{
    display: flex;
    justify-content: center;
    align-items: center;
}}

@media (max-width: 720px) {{
    .summary-grid {{
        grid-template-columns: 1fr 1fr;
    }}
    
    .state-video-grid-container {{
        grid-template-columns: 1fr;
        gap: 15px;
    }}
    
    .header {{
        flex-direction: column;
        gap: 8px;
        text-align: center;
        padding: 12px 20px;
    }}
    
    .header-left {{
        flex-direction: column;
        gap: 8px;
    }}
    
    .header-controls {{
        order: -1;
        margin-bottom: 8px;
    }}
    
    .step-details-content {{
        grid-template-columns: 1fr;
        gap: 10px;
    }}
    
    .step-screenshot-container {{
        text-align: center;
    }}
    
    .step-timing-inline {{
        display: block;
        margin-top: 5px;
        margin-left: 0;
    }}

/* Zap Summary Table Styling */
.zap-summary-container {{
    padding: 15px;
    background: var(--bg-secondary);
    border-radius: 8px;
    margin: 10px 0;
}}

.zap-summary-table {{
    margin-bottom: 20px;
}}

.zap-table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--bg-primary);
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}}

.zap-table th,
.zap-table td {{
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border-light);
    font-size: 13px;
}}

.zap-table th {{
    background: var(--bg-tertiary);
    font-weight: 600;
    color: var(--text-primary);
    position: sticky;
    top: 0;
    z-index: 10;
}}

.zap-table tr:hover {{
    background: var(--bg-secondary);
}}

.zap-table td:first-child {{
    font-weight: 600;
    text-align: center;
    width: 50px;
}}

.zap-table td:nth-child(2) {{
    font-family: monospace;
    font-size: 12px;
    width: 100px;
}}

.zap-table td:nth-child(3),
.zap-table td:nth-child(4) {{
    font-family: monospace;
    font-size: 12px;
    width: 80px;
}}

.zap-table td:nth-child(5) {{
    text-align: center;
    width: 70px;
}}

.zap-table td:nth-child(6),
.zap-table td:nth-child(7),
.zap-table td:nth-child(8),
.zap-table td:nth-child(9) {{
    text-align: center;
    width: 80px;
    font-size: 14px;
}}

.zap-table td:last-child {{
    font-size: 12px;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}

.zap-statistics {{
    background: var(--bg-tertiary);
    padding: 15px;
    border-radius: 6px;
    border: 1px solid var(--border-light);
}}

.zap-statistics h4 {{
    margin: 0 0 12px 0;
    color: var(--text-primary);
    font-size: 14px;
    font-weight: 600;
}}

.stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 10px;
}}

.stat-item {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-primary);
    border-radius: 4px;
    border: 1px solid var(--border-light);
}}

.stat-label {{
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
}}

.stat-value {{
    font-size: 13px;
    color: var(--text-primary);
    font-weight: 600;
    font-family: monospace;
}}
}}

@media print {{
    .header-controls, #snapshot-banner, .toggle-btn {{
        display: none !important;
    }}
    .collapsible-content, .step-details {{
        max-height: none !important;
        overflow: visible !important;
    }}
    body {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }}
}}"""