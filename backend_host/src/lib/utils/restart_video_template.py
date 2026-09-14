"""
Restart Video Report Template

Dedicated HTML template for restart video reports that focuses on video playback
and AI analysis results, similar to the frontend restart video player UI.
"""

def get_restart_video_css() -> str:
    """CSS styling for restart video report"""
    return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #000;
            color: #fff;
            overflow: hidden;
        }

        .video-container {
            position: relative;
            width: 100vw;
            height: 100vh;
            display: flex;
        }

        .video-player {
            flex: 1;
            position: relative;
            background: #000;
        }

        .video-element {
            width: 100%;
            height: 100%;
            object-fit: contain;
        }

        .video-controls {
            position: absolute;
            bottom: 20px;
            left: 20px;
            right: 20px;
            background: rgba(0, 0, 0, 0.7);
            border-radius: 8px;
            padding: 12px;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .play-button {
            background: none;
            border: none;
            color: #fff;
            font-size: 18px;
            cursor: pointer;
            padding: 8px;
            border-radius: 4px;
        }

        .play-button:hover {
            background: rgba(255, 255, 255, 0.1);
        }

        .time-display {
            color: #fff;
            font-size: 14px;
            min-width: 80px;
        }

        .progress-bar {
            flex: 1;
            height: 4px;
            background: rgba(255, 255, 255, 0.3);
            border-radius: 2px;
            cursor: pointer;
            position: relative;
        }

        .progress-fill {
            height: 100%;
            background: #fff;
            border-radius: 2px;
            width: 0%;
            transition: width 0.1s;
        }

        .analysis-panel {
            width: 400px;
            background: rgba(0, 0, 0, 0.95);
            border-left: 1px solid rgba(255, 255, 255, 0.1);
            padding: 20px;
            overflow-y: auto;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }

        .full-analysis-section {
            margin-bottom: 16;
            padding-bottom: 16;
            border-bottom: 2px solid rgba(255, 255, 255, 0.2);
        }

        .analysis-header {
            font-size: 14px;
            font-weight: 600;
            color: #4CAF50;
            margin-bottom: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 4px 0;
        }

        .analysis-header:hover {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 4px;
            padding: 4px 8px;
        }

        .expand-icon {
            font-size: 16px;
            transition: transform 0.3s ease;
        }

        .expand-icon.expanded {
            transform: rotate(180deg);
        }

        .analysis-content {
            background: rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            padding: 12px;
            font-size: 12px;
            line-height: 1.5;
            color: rgba(255, 255, 255, 0.9);
            max-height: 120px;
            overflow-y: auto;
            transition: all 0.3s ease;
        }

        .analysis-content.collapsed {
            display: none;
        }

        .frame-by-frame-section {
            margin-top: 20px;
        }

        .frame-by-frame-title {
            font-size: 16px;
            font-weight: 600;
            color: #fff;
            margin-bottom: 12px;
            text-align: center;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .frame-by-frame-title:hover {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 4px;
            padding: 4px 8px;
        }

        .frame-item {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 12px;
            border-left: 3px solid rgba(255, 255, 255, 0.3);
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .frame-item.active {
            background: rgba(76, 175, 80, 0.15);
            border-left-color: #4CAF50;
            box-shadow: 0 2px 8px rgba(76, 175, 80, 0.2);
        }

        .frame-header {
            font-size: 13px;
            font-weight: 600;
            color: #4CAF50;
            margin-bottom: 4px;
        }

        .frame-content {
            font-size: 11px;
            line-height: 1.4;
        }

        .frame-subtitles {
            color: #2196F3;
            margin-bottom: 4px;
            font-style: italic;
        }

        .frame-summary {
            color: rgba(255, 255, 255, 0.85);
        }

        .no-content {
            color: rgba(255, 255, 255, 0.5);
            font-style: italic;
        }

        .report-header {
            position: absolute;
            top: 20px;
            left: 20px;
            background: rgba(0, 0, 0, 0.7);
            border-radius: 8px;
            padding: 12px 16px;
            z-index: 10;
        }

        .report-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 4px;
        }

        .report-meta {
            font-size: 12px;
            color: rgba(255, 255, 255, 0.7);
        }


        .overlay {
            position: absolute;
            left: 0;
            right: 400px;
            z-index: 5;
            pointer-events: none;
        }


        .subtitle-overlay {
            position: absolute;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            text-align: center;
            padding: 12px 20px;
            background: rgba(0, 0, 0, 0.8);
            border-radius: 6px;
            font-size: 18px;
            font-weight: 500;
            color: #ffff00;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.8);
            max-width: 90%;
            z-index: 15;
            transition: opacity 0.3s ease;
        }

        .subtitle-overlay.hidden {
            opacity: 0;
            pointer-events: none;
        }

        .hidden {
            display: none !important;
        }
    """

def get_restart_video_js() -> str:
    """JavaScript for restart video report functionality"""
    return """
        class RestartVideoReport {
            constructor() {
                this.video = document.getElementById('restart-video');
                this.playButton = document.getElementById('play-button');
                this.timeDisplay = document.getElementById('time-display');
                this.progressBar = document.getElementById('progress-bar');
                this.progressFill = document.getElementById('progress-fill');
                this.subtitleOverlay = document.getElementById('subtitle-overlay');
                
                this.analysisData = window.ANALYSIS_DATA || {};
                this.currentFrameIndex = 0;
                this.frameSubtitles = this.extractFrameSubtitles();
                
                this.init();
            }
            
            init() {
                console.log('RestartVideoReport initialized');
                console.log('Analysis data:', this.analysisData);
                console.log('Frame subtitles:', this.frameSubtitles);
                this.setupVideoControls();
                this.setupFrameAnalysis();
                this.setupSubtitleOverlay();
            }
            
            extractFrameSubtitles() {
                // Extract frame subtitles from analysis data
                const subtitleAnalysis = this.analysisData.subtitle_analysis || {};
                const frameSubtitles = subtitleAnalysis.frame_subtitles || [];
                
                // Process subtitles to remove frame prefixes and filter out empty ones
                const processedSubtitles = {};
                frameSubtitles.forEach((subtitle, index) => {
                    if (subtitle && typeof subtitle === 'string') {
                        // Remove "Frame X: " prefix
                        const cleanSubtitle = subtitle.replace(/^Frame \\d+:\\s*/, '');
                        // Only store if not empty and not "No subtitles detected"
                        if (cleanSubtitle && cleanSubtitle !== 'No subtitles detected') {
                            processedSubtitles[index] = cleanSubtitle;
                        }
                    }
                });
                
                return processedSubtitles;
            }
            
            setupSubtitleOverlay() {
                if (!this.subtitleOverlay) {
                    console.warn('Subtitle overlay element not found');
                    return;
                }
                
                // Initially hide subtitle overlay
                this.subtitleOverlay.classList.add('hidden');
            }
            
            setupVideoControls() {
                this.playButton.addEventListener('click', () => {
                    if (this.video.paused) {
                        this.video.play();
                        this.playButton.textContent = '⏸';
                    } else {
                        this.video.pause();
                        this.playButton.textContent = '▶';
                    }
                });
                
                this.video.addEventListener('timeupdate', () => {
                    const current = this.video.currentTime;
                    const duration = this.video.duration || 0;
                    const progress = duration > 0 ? (current / duration) * 100 : 0;
                    
                    this.progressFill.style.width = progress + '%';
                    this.timeDisplay.textContent = this.formatTime(current) + ' / ' + this.formatTime(duration);
                    
                    // Update active frame based on current time
                    const newFrameIndex = Math.floor(current);
                    if (newFrameIndex !== this.currentFrameIndex) {
                        this.currentFrameIndex = newFrameIndex;
                        this.updateActiveFrame();
                        this.updateSubtitleOverlay();
                    }
                });
                
                this.progressBar.addEventListener('click', (e) => {
                    const rect = this.progressBar.getBoundingClientRect();
                    const pos = (e.clientX - rect.left) / rect.width;
                    this.video.currentTime = pos * this.video.duration;
                });
            }
            
            setupFrameAnalysis() {
                const frameContainer = document.getElementById('frame-analysis-container');
                if (!frameContainer) return;
                
                // Get analysis data
                const frameDescriptions = this.analysisData.video_analysis?.frame_descriptions || [];
                const subtitleAnalysis = this.analysisData.subtitle_analysis || {};
                
                if (frameDescriptions.length === 0) {
                    frameContainer.innerHTML = '<div class="frame-item"><div class="no-content">No frame analysis available</div></div>';
                    return;
                }
                
                // Create comprehensive frame items
                frameDescriptions.forEach((description, index) => {
                    const frameItem = document.createElement('div');
                    frameItem.className = 'frame-item';
                    frameItem.dataset.frameIndex = index;
                    
                    // Get subtitle for this frame (if available)
                    const frameSubtitles = this.getFrameSubtitles(index, subtitleAnalysis);
                    
                    frameItem.innerHTML = `
                        <div class="frame-header">Frame ${index + 1}:</div>
                        <div class="frame-content">
                            <div class="frame-subtitles">
                                Subtitles: ${frameSubtitles || '<span class="no-content">None detected</span>'}
                            </div>
                            <div class="frame-summary">
                                ${description}
                            </div>
                        </div>
                    `;
                    
                    // Add click handler to seek to frame
                    frameItem.addEventListener('click', () => {
                        this.seekToFrame(index);
                    });
                    
                    frameContainer.appendChild(frameItem);
                });
                
                // Set initial active frame
                this.updateActiveFrame();
            }
            
            getFrameSubtitles(frameIndex, subtitleAnalysis) {
                // Get frame-specific subtitles from frame_subtitles array
                const frameSubtitles = subtitleAnalysis.frame_subtitles || [];
                if (frameSubtitles.length > frameIndex) {
                    const frameSubtitle = frameSubtitles[frameIndex];
                    // Extract subtitle text after "Frame X: " prefix
                    if (frameSubtitle && frameSubtitle.includes(': ')) {
                        const subtitleText = frameSubtitle.split(': ').slice(1).join(': ');
                        return subtitleText !== 'No subtitles detected' ? subtitleText : null;
                    }
                }
                return null;
            }
            
            seekToFrame(frameIndex) {
                const targetTime = frameIndex;
                if (this.video.duration && targetTime <= this.video.duration) {
                    this.video.currentTime = targetTime;
                    this.currentFrameIndex = frameIndex;
                    this.updateActiveFrame();
                    this.updateSubtitleOverlay();
                }
            }
            
            updateActiveFrame() {
                // Remove active class from all frames
                document.querySelectorAll('.frame-item').forEach(item => {
                    item.classList.remove('active');
                });
                
                // Add active class to current frame
                const currentFrame = document.querySelector(`[data-frame-index="${this.currentFrameIndex}"]`);
                if (currentFrame) {
                    currentFrame.classList.add('active');
                    
                    // Scroll to active frame
                    const container = document.getElementById('frame-analysis-container');
                    if (container) {
                        currentFrame.scrollIntoView({ 
                            behavior: 'smooth', 
                            block: 'center',
                            inline: 'nearest'
                        });
                    }
                }
            }
            
            updateSubtitleOverlay() {
                if (!this.subtitleOverlay) return;
                
                // Get subtitle for current frame
                const currentSubtitle = this.frameSubtitles[this.currentFrameIndex];
                
                if (currentSubtitle && currentSubtitle.trim()) {
                    // Show subtitle
                    this.subtitleOverlay.textContent = currentSubtitle;
                    this.subtitleOverlay.classList.remove('hidden');
                } else {
                    // Hide subtitle
                    this.subtitleOverlay.classList.add('hidden');
                }
            }
            
            
            formatTime(seconds) {
                const mins = Math.floor(seconds / 60);
                const secs = Math.floor(seconds % 60);
                return `${mins}:${secs.toString().padStart(2, '0')}`;
            }
        }
        
        // Toggle section visibility
        function toggleSection(sectionId) {
            const content = document.getElementById(sectionId + '-content') || document.getElementById(sectionId + '-container');
            const icon = document.getElementById(sectionId + '-icon');
            
            if (content && icon) {
                const isCollapsed = content.classList.contains('collapsed');
                
                if (isCollapsed) {
                    content.classList.remove('collapsed');
                    icon.classList.add('expanded');
                    icon.textContent = '▲';
                } else {
                    content.classList.add('collapsed');
                    icon.classList.remove('expanded');
                    icon.textContent = '▼';
                }
            }
        }
        
        // Initialize when DOM is loaded
        document.addEventListener('DOMContentLoaded', () => {
            new RestartVideoReport();
        });
    """

def create_restart_video_template() -> str:
    """Create the complete HTML template for restart video reports"""
    
    # Escape braces in CSS and JS content to avoid format() conflicts
    css_content = get_restart_video_css().replace('{', '{{').replace('}', '}}')
    js_content = get_restart_video_js().replace('{', '{{').replace('}', '}}')
    
    # Build the template using string replacement instead of format() to avoid brace conflicts
    template_parts = []
    
    template_parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Restart Video Report - {device_name}</title>
    <style>""")
    
    template_parts.append(css_content)
    
    template_parts.append("""    </style>
</head>
<body>
    <div class="video-container">
        <!-- Video Player Section -->
        <div class="video-player">
            <!-- Report Header -->
            <div class="report-header">
                <div class="report-title">Restart Video Analysis</div>
                <div class="report-meta">{host_name} - {device_name} {timestamp}</div>
            </div>
            
            
            <!-- Video Element -->
            <video id="restart-video" class="video-element" preload="metadata">
                <source src="{video_url}" type="video/mp4">
                Your browser does not support the video tag.
            </video>
            
            <!-- Video Controls -->
            <div class="video-controls">
                <button id="play-button" class="play-button">▶</button>
                <div id="time-display" class="time-display">0:00 / 0:00</div>
                <div id="progress-bar" class="progress-bar">
                    <div id="progress-fill" class="progress-fill"></div>
                </div>
            </div>
            
            
            <!-- Subtitle Overlay -->
            <div id="subtitle-overlay" class="subtitle-overlay hidden">
                <!-- Subtitle text will be dynamically updated by JavaScript -->
            </div>
        </div>
        
        <!-- Analysis Panel -->
        <div class="analysis-panel">
            <!-- Full Video Analysis Section -->
            <div class="full-analysis-section">
                <div class="analysis-header" onclick="toggleSection('video-summary')">
                    <span>Video Summary (EN):</span>
                    <span class="expand-icon" id="video-summary-icon">▼</span>
                </div>
                <div class="analysis-content" id="video-summary-content">{video_summary}</div>
            </div>
            
            <div class="full-analysis-section">
                <div class="analysis-header" onclick="toggleSection('audio-transcript')">
                    <span>Audio Transcript (EN):</span>
                    <span class="expand-icon" id="audio-transcript-icon">▼</span>
                </div>
                <div class="analysis-content" id="audio-transcript-content">{audio_transcript}</div>
            </div>
            
            <!-- Frame-by-Frame Analysis Section -->
            <div class="frame-by-frame-section">
                <div class="frame-by-frame-title" onclick="toggleSection('frame-analysis')">
                    <span>Frame Analysis</span>
                    <span class="expand-icon" id="frame-analysis-icon">▼</span>
                </div>
                <div id="frame-analysis-container">
                    <!-- Frame items will be populated by JavaScript -->
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // Analysis data for JavaScript
        window.ANALYSIS_DATA = {analysis_data_json};
    </script>
    <script>""")
    
    template_parts.append(js_content)
    
    template_parts.append("""    </script>
</body>
</html>""")
    
    return ''.join(template_parts)