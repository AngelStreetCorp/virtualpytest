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
  <div class="video-wrapper">
    <iframe 
      src="https://www.youtube.com/embed/eGC_-t5bpzE" 
      frameborder="0" 
      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
      allowfullscreen>
    </iframe>
  </div>
</div>

---

<div class="video-grid">
  <div class="video-card">
    <h3>Device Control</h3>
    <div class="video-wrapper">
      <iframe 
        src="https://www.youtube.com/embed/BsXrSLI0kJg"  
        frameborder="0" 
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
        allowfullscreen>
      </iframe>
    </div>
  </div>

  <div class="video-card">
    <h3>Navigation Tree</h3>
    <div class="video-wrapper">
      <iframe 
        src="https://www.youtube.com/embed/GmN9vmE8PfE" 
        frameborder="0" 
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
        allowfullscreen>
      </iframe>
    </div>
  </div>

  <div class="video-card">
    <h3>Monitoring</h3>
    <div class="video-wrapper">
      <iframe 
        src="https://www.youtube.com/embed/9S78Zt-PZuY" 
        frameborder="0" 
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
        allowfullscreen>
      </iframe>
    </div>
  </div>
</div>

---