<style>
.spotlight-video {
  max-width: 700px;
  margin: 10px auto;
  text-align: center;
}

.spotlight-video h2 {
  margin-bottom: 8px;
  color: rgb(255, 255, 255);
  font-size: 24px;
}

.spotlight-video .video-wrapper {
  position: relative;
  padding-bottom: 56.25%; /* 16:9 aspect ratio */
  height: 0;
  overflow: hidden;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

.spotlight-video .video-wrapper iframe {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  padding: 20px 0;
  max-width: 1200px;
  margin: 0 auto;
}

.video-card {
  border: 1px solid #e1e4e8;
  border-radius: 8px;
  padding: 4px;
  text-align: center;
  transition: transform 0.2s, box-shadow 0.2s;
  background: transparent;
}

.video-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.video-card h3 {
  margin: 0 0 8px 0;
  font-size: 14px;
  font-weight: 600;
  color: rgb(255, 255, 255);
  min-height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-card .video-wrapper {
  position: relative;
  padding-bottom: 56.25%; /* 16:9 aspect ratio */
  height: 0;
  overflow: hidden;
  border-radius: 4px;
}

.video-card .video-wrapper iframe {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}

@media (max-width: 768px) {
  .video-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<div class="spotlight-video">
  <h2>VirtualPyTest in 60 seconds</h2>
  <div class="video-wrapper">
    <iframe
      src="https://www.youtube.com/embed/RBgS376Blvo"
      title="VirtualPyTest in 60 seconds"
      frameborder="0"
      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
      allowfullscreen>
    </iframe>
  </div>
  <p>Dashboard, live device control, one-click test runs, reports, KPI measurement, the 24h heatmap and incident evidence, in one minute.</p>
  <p>
    <a href="https://www.youtube.com/watch?v=RBgS376Blvo" target="_blank" rel="noopener">Watch on YouTube</a>
    &nbsp;·&nbsp;
    <a href="https://github.com/AngelStreetCorp/virtualpytest" target="_blank" rel="noopener">Source on GitHub</a>
  </p>
</div>

---

More walkthroughs (device control, navigation trees, monitoring) are being re-recorded and will appear here as they are published.
