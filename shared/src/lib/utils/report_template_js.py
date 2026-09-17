"""
Report Template JavaScript Functions

Contains all JavaScript functionality for the HTML validation reports.
"""

def get_report_javascript() -> str:
    """Get the complete JavaScript for the report template."""
    return """// Theme management system
class ThemeManager {{
    constructor() {{
        this.currentMode = this.getSavedTheme() || 'light';
        this.systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        this.init();
    }}
    
    init() {{
        this.applyTheme();
        this.setupSystemThemeListener();
        this.setupThemeToggle();
    }}
    
    getSavedTheme() {{
        return localStorage.getItem('validation-report-theme');
    }}
    
    saveTheme(mode) {{
        localStorage.setItem('validation-report-theme', mode);
    }}
    
    getActualTheme() {{
        if (this.currentMode === 'system') {{
            return this.systemPrefersDark ? 'dark' : 'light';
        }}
        return this.currentMode;
    }}
    
    applyTheme() {{
        const actualTheme = this.getActualTheme();
        document.documentElement.setAttribute('data-theme', actualTheme);
        this.updateToggleButtons();
        this.updateSlider();
    }}
    
    setTheme(mode) {{
        this.currentMode = mode;
        this.saveTheme(mode);
        this.applyTheme();
    }}
    
    setupSystemThemeListener() {{
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        mediaQuery.addEventListener('change', (e) => {{
            this.systemPrefersDark = e.matches;
            if (this.currentMode === 'system') {{
                this.applyTheme();
            }}
        }});
    }}
    
    setupThemeToggle() {{
        const themeOptions = document.querySelectorAll('.theme-option');
        themeOptions.forEach(option => {{
            option.addEventListener('click', (e) => {{
                // Read from currentTarget (the .theme-option we bound to), not
                // target — a click landing on a child node would otherwise yield
                // an undefined mode and silently no-op the toggle.
                const mode = e.currentTarget.dataset.theme;
                if (mode) {{
                    this.setTheme(mode);
                }}
            }});
        }});
    }}
    
    updateToggleButtons() {{
        const themeOptions = document.querySelectorAll('.theme-option');
        themeOptions.forEach(option => {{
            option.classList.toggle('active', option.dataset.theme === this.currentMode);
        }});
    }}
    
    updateSlider() {{
        const slider = document.querySelector('.theme-slider');
        if (slider) {{
            slider.className = 'theme-slider ' + this.currentMode;
        }}
    }}
}}

// Initialize theme manager when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {{
    window.themeManager = new ThemeManager();
    
    // Handle window resize to recalculate expanded section heights
    let resizeTimeout;
    window.addEventListener('resize', () => {{
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {{
            recalculateExpandedSections();
        }}, 250);
    }});
}});

// Recalculate heights for expanded sections after window resize
function recalculateExpandedSections() {{
    const expandedSections = document.querySelectorAll('.collapsible-content.expanded, .step-details.expanded');
    expandedSections.forEach(section => {{
        if (section.style.maxHeight && section.style.maxHeight !== 'none') {{
            const newHeight = section.scrollHeight;
            section.style.maxHeight = newHeight + 'px';
            
            // Set to none after a brief delay for proper scrolling
            setTimeout(() => {{
                if (section.classList.contains('expanded')) {{
                    section.style.maxHeight = 'none';
                }}
            }}, 100);
        }}
    }});
}}

function toggleSection(sectionId) {{
    const content = document.getElementById(sectionId);
    const sectionElements = document.querySelectorAll('.section-header');
    let button = null;
    for (let element of sectionElements) {{
        if (element.onclick && element.onclick.toString().includes(sectionId)) {{
            button = element.querySelector('.toggle-btn');
            break;
        }}
    }}
    
    if (content && content.classList.contains('expanded')) {{
        // Collapsing: measure current height first, then animate to 0
        const currentHeight = content.scrollHeight;
        content.style.maxHeight = currentHeight + 'px';
        
        // Force reflow
        content.offsetHeight;
        
        // Animate to collapsed
        content.style.maxHeight = '0px';
        content.classList.remove('expanded');
        
        if (button) {{
            button.classList.remove('expanded');
            button.textContent = '▶';
        }}
        
        // Clean up after transition
        setTimeout(() => {{
            if (!content.classList.contains('expanded')) {{
                content.style.maxHeight = '';
            }}
        }}, 400);
        
    }} else if (content) {{
        // Expanding: measure content height and animate to it
        content.classList.add('expanded');
        const targetHeight = content.scrollHeight;
        content.style.maxHeight = '0px';
        
        // Force reflow
        content.offsetHeight;
        
        // Animate to full height
        content.style.maxHeight = targetHeight + 'px';
        
        if (button) {{
            button.classList.add('expanded');
            button.textContent = '▼';
        }}
        
        // Clean up after transition - set to none for proper scrolling
        setTimeout(() => {{
            if (content.classList.contains('expanded')) {{
                content.style.maxHeight = 'none';
            }}
        }}, 400);
    }}
}}

function toggleStep(stepId) {{
    const details = document.getElementById(stepId);
    if (details.classList.contains('expanded')) {{
        // Collapsing: measure current height first, then animate to 0
        const currentHeight = details.scrollHeight;
        details.style.maxHeight = currentHeight + 'px';
        
        // Force reflow
        details.offsetHeight;
        
        // Animate to collapsed
        details.style.maxHeight = '0px';
        details.classList.remove('expanded');
        
        // Clean up after transition
        setTimeout(() => {{
            if (!details.classList.contains('expanded')) {{
                details.style.maxHeight = '';
            }}
        }}, 400);
        
    }} else {{
        // Expanding: measure content height and animate to it
        details.classList.add('expanded');
        const targetHeight = details.scrollHeight;
        details.style.maxHeight = '0px';
        
        // Force reflow
        details.offsetHeight;
        
        // Animate to full height
        details.style.maxHeight = targetHeight + 'px';
        
        // Clean up after transition - set to none for proper scrolling
        setTimeout(() => {{
            if (details.classList.contains('expanded')) {{
                details.style.maxHeight = 'none';
            }}
        }}, 400);
    }}
}}

let currentModalData = null;
let currentScreenshotIndex = 0;

function openScreenshotModal(modalDataJson) {{
    try {{
        // Decode HTML entities properly
        const textarea = document.createElement('textarea');
        textarea.innerHTML = modalDataJson;
        const decodedJson = textarea.value;
        
        currentModalData = JSON.parse(decodedJson);
        currentScreenshotIndex = currentModalData.current_index || 0;
        
        updateModalContent();
        
        const modal = document.getElementById('screenshot-modal');
        modal.classList.add('active');
    }} catch (e) {{
        console.error('Error opening screenshot modal:', e);
    }}
}}

function updateModalContent() {{
    if (!currentModalData || !currentModalData.screenshots) return;
    
    const screenshots = currentModalData.screenshots;
    const current = screenshots[currentScreenshotIndex];
    
    // Update image
    const img = document.getElementById('modal-img');
    img.src = current.url;
    
    // Update step title
    const title = document.getElementById('modal-step-title');
    title.textContent = currentModalData.step_title;
    
    // Update action info
    const actionInfo = document.getElementById('modal-action-info');
    if (current.command) {{
        const cmd = current.command;
        const params = current.params || {{}};
        
        // Format parameters intelligently based on type
        let paramsStr = '';
        if (Object.keys(params).length > 0) {{
            paramsStr = Object.entries(params).map(([k, v]) => {{
                if (typeof v === 'object' && v !== null) {{
                    // For objects (like area), show compact JSON representation
                    return k + '=' + JSON.stringify(v);
                }} else if (typeof v === 'string') {{
                    // For strings, wrap in quotes
                    return k + "='" + v + "'";
                }} else {{
                    // For numbers/booleans, show as-is
                    return k + '=' + v;
                }}
            }}).join(', ');
        }}
        
        actionInfo.textContent = current.label + ': ' + cmd + '(' + paramsStr + ')';
        actionInfo.style.display = 'block';
    }} else {{
        actionInfo.textContent = current.label;
        actionInfo.style.display = 'block';
    }}
    
    // Update counter
    const counter = document.getElementById('modal-counter');
    counter.textContent = (currentScreenshotIndex + 1) + ' / ' + screenshots.length;
    
    // Update navigation buttons
    const prevBtn = document.getElementById('modal-prev');
    const nextBtn = document.getElementById('modal-next');
    
    prevBtn.disabled = currentScreenshotIndex === 0;
    nextBtn.disabled = currentScreenshotIndex === screenshots.length - 1;
    
    // Hide arrows if only one screenshot
    if (screenshots.length <= 1) {{
        prevBtn.style.display = 'none';
        nextBtn.style.display = 'none';
    }} else {{
        prevBtn.style.display = 'flex';
        nextBtn.style.display = 'flex';
    }}
}}

function navigateScreenshot(direction) {{
    if (!currentModalData || !currentModalData.screenshots) return;
    
    const newIndex = currentScreenshotIndex + direction;
    if (newIndex >= 0 && newIndex < currentModalData.screenshots.length) {{
        currentScreenshotIndex = newIndex;
        updateModalContent();
    }}
}}

function closeScreenshot() {{
    const modal = document.getElementById('screenshot-modal');
    modal.classList.remove('active');
    currentModalData = null;
    currentScreenshotIndex = 0;
}}

// Legacy function for backward compatibility
function openScreenshot(src) {{
    const modalData = {{
        step_title: 'Screenshot',
        screenshots: [{{
            label: 'Screenshot',
            url: src,
            command: null,
            params: {{}}
        }}],
        current_index: 0
    }};
    openScreenshotModal(JSON.stringify(modalData));
}}

// Video modal functions - supports both MP4 and HLS
function openVideoModal(videoUrl, label) {{
    let videoModal = document.getElementById('video-modal');
    if (!videoModal) {{
        videoModal = document.createElement('div');
        videoModal.id = 'video-modal';
        videoModal.className = 'modal';
        videoModal.innerHTML = `
            <div class="modal-content video-modal-content">
                <div class="modal-header">
                    <h3 id="video-modal-title">${{label}}</h3>
                    <button class="modal-close" onclick="closeVideoModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <!-- Fit the viewport in BOTH orientations. 'min-width: 800px' with
                         'height: auto' blew a portrait phone recording (1080x2400) up to about
                         1780px tall, which put the player's own controls below the fold with no
                         way to reach them. Bounding height as well as width lets a landscape
                         capture still fill the modal while a portrait one scales down to fit. -->
                    <video id="modal-video" controls style="max-width: 100%; max-height: 78vh; width: auto; height: auto; display: block; margin: 0 auto;">
                        Your browser does not support video playback.
                    </video>
                </div>
            </div>
        `;
        document.body.appendChild(videoModal);
    }} else {{
        document.getElementById('video-modal-title').textContent = label;
    }}
    
    const video = document.getElementById('modal-video');
    
    // Clear any existing HLS instance
    if (window.currentHls) {{
        window.currentHls.destroy();
        window.currentHls = null;
    }}
    
    // Detect video type and setup appropriate playback
    if (videoUrl.includes('.mp4')) {{
        // MP4 video - use native playback
        console.log('Loading MP4 video:', videoUrl);
        video.src = videoUrl;
        video.addEventListener('loadedmetadata', function() {{
            video.play().catch(e => console.log('Autoplay prevented:', e));
        }});
    }} else if (videoUrl.includes('.m3u8') && typeof Hls !== 'undefined' && Hls.isSupported()) {{
        // HLS video - use HLS.js
        console.log('Loading HLS video:', videoUrl);
        const hls = new Hls({{
            debug: false,
            enableWorker: true,
            lowLatencyMode: false,
            backBufferLength: 90
        }});
        
        hls.loadSource(videoUrl);
        hls.attachMedia(video);
        
        hls.on(Hls.Events.MANIFEST_PARSED, function() {{
            video.play().catch(e => console.log('Autoplay prevented:', e));
        }});
        
        hls.on(Hls.Events.ERROR, function(event, data) {{
            console.error('HLS error:', data);
            if (data.fatal) {{
                switch(data.type) {{
                    case Hls.ErrorTypes.NETWORK_ERROR:
                        hls.startLoad();
                        break;
                    case Hls.ErrorTypes.MEDIA_ERROR:
                        hls.recoverMediaError();
                        break;
                    default:
                        hls.destroy();
                        break;
                }}
            }}
        }});
        
        window.currentHls = hls;
    }} else if (videoUrl.includes('.m3u8') && video.canPlayType('application/vnd.apple.mpegurl')) {{
        // Safari native HLS support
        console.log('Loading HLS video with native support:', videoUrl);
        video.src = videoUrl;
        video.addEventListener('loadedmetadata', function() {{
            video.play().catch(e => console.log('Autoplay prevented:', e));
        }});
    }} else {{
        console.error('Unsupported video format or HLS.js not available:', videoUrl);
        video.innerHTML = '<p style="color: red; text-align: center; padding: 20px;">Video format not supported in this browser.</p>';
    }}
    
    videoModal.classList.add('active');
}}

// Legacy function for backward compatibility
function openHLSVideoModal(videoUrl, label) {{
    openVideoModal(videoUrl, label);
}}

function closeVideoModal() {{
    const videoModal = document.getElementById('video-modal');
    if (videoModal) {{
        videoModal.classList.remove('active');
        const video = document.getElementById('modal-video');
        if (video) {{
            video.pause();
        }}
        
        // Clean up HLS instance
        if (window.currentHls) {{
            window.currentHls.destroy();
            window.currentHls = null;
        }}
    }}
}}

// Legacy function for backward compatibility
function closeHLSVideoModal() {{
    closeVideoModal();
}}

// Verification image modal functions
function openVerificationImageModal(modalData) {{
    let verificationModal = document.getElementById('verification-image-modal');
    if (!verificationModal) {{
        verificationModal = document.createElement('div');
        verificationModal.id = 'verification-image-modal';
        verificationModal.className = 'modal';
        verificationModal.innerHTML = `
            <div class="modal-content verification-modal-content" style="width: 90%; max-width: 1200px;">
                <div class="modal-header">
                    <h3 id="verification-modal-title">Image Verification Comparison</h3>
                    <button class="modal-close" onclick="closeVerificationImageModal()">&times;</button>
                </div>
                <div class="modal-body" style="display: flex; flex-wrap: wrap; justify-content: center; gap: 15px; align-items: flex-start;">
                    <div id="verification-images-container" style="display: flex; flex-wrap: wrap; justify-content: center; gap: 15px; width: 100%;"></div>
                </div>
            </div>
        `;
        document.body.appendChild(verificationModal);
    }}
    
    // Populate the modal with images
    const imagesContainer = document.getElementById('verification-images-container');
    imagesContainer.innerHTML = '';
    
    modalData.images.forEach(image => {{
        const imageDiv = document.createElement('div');
        imageDiv.style.textAlign = 'center';
        
        // Dynamic width based on number of images for better layout
        const imageCount = modalData.images.length;
        if (imageCount === 4) {{
            imageDiv.style.width = '23%';  // 4 images in one row (23% * 4 = 92% + gaps)
            imageDiv.style.minWidth = '200px';
        }} else if (imageCount === 3) {{
            imageDiv.style.maxWidth = '32%';
            imageDiv.style.minWidth = '250px';
        }} else {{
            imageDiv.style.maxWidth = '45%';
            imageDiv.style.minWidth = '300px';
        }}
        
        // Extract sequence number from filename (capture_0001.jpg)
        const extractSequenceInfo = (url) => {{
            const match = url.match(/capture_(\\d+)\\.jpg/);
            if (match) {{
                const sequence = match[1];
                return `#${{sequence}}`;
            }}
            return '';
        }};
        
        const sequenceInfo = extractSequenceInfo(image.url);
        
        // Sequence info display (small, gray text)
        if (sequenceInfo) {{
            const timestampDiv = document.createElement('div');
            timestampDiv.textContent = sequenceInfo;
            timestampDiv.style.fontSize = '12px';
            timestampDiv.style.color = '#999';
            timestampDiv.style.marginBottom = '5px';
            timestampDiv.style.fontFamily = 'monospace';
            imageDiv.appendChild(timestampDiv);
        }}
        
        const title = document.createElement('h4');
        title.innerHTML = image.label;  // Use innerHTML to support HTML formatting like <br> and <span> tags
        title.style.marginBottom = '10px';
        title.style.color = 'var(--text-primary)';
        title.style.fontSize = '14px';
        
        const img = document.createElement('img');
        img.src = image.url;
        img.style.maxWidth = '100%';
        img.style.maxHeight = '500px';
        img.style.objectFit = 'contain';
        img.style.border = '1px solid var(--border-color)';
        img.style.borderRadius = '4px';
        img.style.cursor = 'pointer';
        img.title = 'Click to open in new tab';
        img.onclick = () => window.open(image.url, '_blank');
        
        imageDiv.appendChild(title);
        imageDiv.appendChild(img);
        imagesContainer.appendChild(imageDiv);
    }});
    
    // Update modal title
    document.getElementById('verification-modal-title').textContent = modalData.title || 'Image Verification Comparison';
    
    // Show the modal
    verificationModal.classList.add('active');
}}

function closeVerificationImageModal() {{
    const verificationModal = document.getElementById('verification-image-modal');
    if (verificationModal) {{
        verificationModal.classList.remove('active');
    }}
}}

// Zapping analysis modal functions - specialized for failure analysis with detailed logs
function openZappingAnalysisModal(modalData) {{
    let zappingModal = document.getElementById('zapping-analysis-modal');
    if (!zappingModal) {{
        zappingModal = document.createElement('div');
        zappingModal.id = 'zapping-analysis-modal';
        zappingModal.className = 'modal';
        zappingModal.innerHTML = `
            <div class="modal-content zapping-modal-content" style="width: 90%; max-width: 1200px; max-height: 90vh; overflow-y: auto;">
                <div class="modal-header">
                    <h3 id="zapping-modal-title">Zapping Analysis</h3>
                    <button class="modal-close" onclick="closeZappingAnalysisModal()">&times;</button>
                </div>
                <div class="modal-body" style="display: flex; flex-direction: column; gap: 20px;">
                    <!-- Mosaic Image Section - Top Priority -->
                    <div id="zapping-mosaic-container" style="text-align: center; background-color: var(--background-secondary); padding: 15px; border-radius: 8px;">
                        <img id="zapping-mosaic-img" style="max-width: 100%; max-height: 70vh; object-fit: contain; border: 1px solid var(--border-color); border-radius: 4px; cursor: pointer; box-shadow: 0 4px 8px rgba(0,0,0,0.1);" onclick="window.open(this.src, '_blank')" title="Click to open in new tab">
                        <div style="margin-top: 10px; font-size: 12px; color: var(--text-secondary); font-style: italic;">Click image to open in new tab for detailed inspection</div>
                    </div>
                    
                    <!-- Analysis Log Section - Collapsible -->
                    <div id="zapping-analysis-section" style="border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden;">
                        <div class="zapping-log-header" onclick="toggleZappingAnalysisLog()" style="background-color: var(--background-secondary); padding: 12px 15px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none;">
                            <h4 style="margin: 0; color: var(--text-primary); font-family: sans-serif; font-size: 14px;">📋 Detailed Analysis Log</h4>
                            <span id="zapping-log-toggle" style="font-size: 12px; color: var(--text-secondary);">▶ Click to expand</span>
                        </div>
                        <div id="zapping-analysis-log" style="max-height: 0; overflow: hidden; transition: max-height 0.3s ease; background-color: var(--background-primary);">
                            <div style="padding: 15px; font-family: monospace; font-size: 11px; line-height: 1.4; max-height: 400px; overflow-y: auto;">
                                <div id="zapping-log-content" style="white-space: pre-wrap; color: var(--text-secondary);"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(zappingModal);
    }}
    
    // Populate the modal with mosaic and analysis log
    const mosaicImg = document.getElementById('zapping-mosaic-img');
    const logContent = document.getElementById('zapping-log-content');
    
    // Set mosaic image
    if (modalData.images && modalData.images.length > 0) {{
        mosaicImg.src = modalData.images[0].url;
        mosaicImg.alt = modalData.images[0].label || 'Analysis Mosaic';
    }}
    
    // Set analysis log
    if (modalData.analysis_log && modalData.analysis_log.length > 0) {{
        logContent.textContent = modalData.analysis_log.join('\\n');
    }} else {{
        logContent.textContent = 'No detailed analysis log available.';
    }}
    
    // Ensure log section starts collapsed
    const logSection = document.getElementById('zapping-analysis-log');
    const toggleIcon = document.getElementById('zapping-log-toggle');
    if (logSection && toggleIcon) {{
        logSection.style.maxHeight = '0px';
        toggleIcon.textContent = '▶ Click to expand';
    }}
    
    // Update modal title
    document.getElementById('zapping-modal-title').textContent = modalData.title || 'Zapping Analysis';
    
    // Show the modal
    zappingModal.classList.add('active');
}}

function closeZappingAnalysisModal() {{
    const zappingModal = document.getElementById('zapping-analysis-modal');
    if (zappingModal) {{
        zappingModal.classList.remove('active');
    }}
}}

function toggleZappingAnalysisLog() {{
    const logSection = document.getElementById('zapping-analysis-log');
    const toggleIcon = document.getElementById('zapping-log-toggle');
    
    if (!logSection || !toggleIcon) return;
    
    const isExpanded = logSection.style.maxHeight && logSection.style.maxHeight !== '0px';
    
    if (isExpanded) {{
        // Collapse
        logSection.style.maxHeight = '0px';
        toggleIcon.textContent = '▶ Click to expand';
    }} else {{
        // Expand
        const contentHeight = logSection.scrollHeight;
        logSection.style.maxHeight = Math.min(contentHeight, 400) + 'px';
        toggleIcon.textContent = '▼ Click to collapse';
    }}
}}

// Event listeners
document.addEventListener('DOMContentLoaded', function() {{
    const modal = document.getElementById('screenshot-modal');
    if (modal) {{
        modal.addEventListener('click', function(e) {{
            if (e.target === modal) {{
                closeScreenshot();
            }}
        }});
    }}
    
    // Modal click-outside handlers
    document.addEventListener('click', function(e) {{
        const videoModal = document.getElementById('video-modal');
        if (videoModal && e.target === videoModal) {{
            closeVideoModal();
        }}
        
        // Legacy support
        const hlsModal = document.getElementById('hls-video-modal');
        if (hlsModal && e.target === hlsModal) {{
            closeHLSVideoModal();
        }}
        
        const verificationModal = document.getElementById('verification-image-modal');
        if (verificationModal && e.target === verificationModal) {{
            closeVerificationImageModal();
        }}
        
        const zappingModal = document.getElementById('zapping-analysis-modal');
        if (zappingModal && e.target === zappingModal) {{
            closeZappingAnalysisModal();
        }}
    }});
    
    // Keyboard navigation
    document.addEventListener('keydown', function(e) {{
        const videoModal = document.getElementById('video-modal');
        const hlsModal = document.getElementById('hls-video-modal');
        const verificationModal = document.getElementById('verification-image-modal');
        
        if (modal && modal.classList.contains('active')) {{
            switch(e.key) {{
                case 'ArrowLeft':
                    e.preventDefault();
                    navigateScreenshot(-1);
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    navigateScreenshot(1);
                    break;
                case 'Escape':
                    e.preventDefault();
                    closeScreenshot();
                    break;
            }}
        }} else if ((videoModal && videoModal.classList.contains('active')) || (hlsModal && hlsModal.classList.contains('active'))) {{
            if (e.key === 'Escape') {{
                e.preventDefault();
                closeVideoModal();
            }}
        }} else if (verificationModal && verificationModal.classList.contains('active')) {{
            if (e.key === 'Escape') {{
                e.preventDefault();
                closeVerificationImageModal();
            }}
        }} else if (document.getElementById('zapping-analysis-modal') && document.getElementById('zapping-analysis-modal').classList.contains('active')) {{
            if (e.key === 'Escape') {{
                e.preventDefault();
                closeZappingAnalysisModal();
            }}
        }}
    }});
}});"""