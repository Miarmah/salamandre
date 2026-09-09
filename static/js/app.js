// ---------------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------------
function updateClock(){
  const el = document.getElementById('clock');
  if(!el) return;
  const now = new Date();
  el.textContent = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
}
updateClock();
setInterval(updateClock, 30000);

// ---------------------------------------------------------------------------
// Password visibility toggle
// ---------------------------------------------------------------------------
function togglePwd(id){
  const input = document.getElementById(id);
  input.type = input.type === 'password' ? 'text' : 'password';
}

// ---------------------------------------------------------------------------
// Audio player state
// ---------------------------------------------------------------------------
const audio = document.getElementById('audio-el');
let currentTrackId = null;
let currentTitle = '';
let currentCover = null;
let audioCtx = null, analyser = null, sourceNode = null, dataArray = null;
let vizMode = localStorage.getItem('imusic_viz_mode') || 'bars';
let rafId = null;
let isSeeking = false;

let queue = [];       // [{id, title, filename, cover}]
let queueIndex = -1;
let shuffleOn = localStorage.getItem('imusic_shuffle') === '1';
let repeatMode = localStorage.getItem('imusic_repeat') || 'off'; // off | all | one

function coverUrl(cover){ return cover ? `/covers/${cover}` : null; }
function audioUrl(filename){ return `/uploads/${filename}`; }

function ensureAudioGraph(){
  if(audioCtx) return;
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  sourceNode = audioCtx.createMediaElementSource(audio);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 128;
  dataArray = new Uint8Array(analyser.frequencyBinCount);
  sourceNode.connect(analyser);
  analyser.connect(audioCtx.destination);
}

// Start playback from a given list of tracks at a given index (sets the queue)
function playQueueItem(list, index){
  if(!list || !list.length) return;
  queue = list.slice();
  queueIndex = index;
  playCurrentQueueItem();
}

function playCurrentQueueItem(){
  const t = queue[queueIndex];
  if(!t) return;
  loadAndPlay(t.id, audioUrl(t.filename), t.title, t.cover);
}

function loadAndPlay(id, src, title, cover){
  ensureAudioGraph();
  if(audioCtx.state === 'suspended') audioCtx.resume();

  const isNewTrack = currentTrackId !== id;
  currentTrackId = id;
  currentTitle = title;
  currentCover = cover || null;

  if(isNewTrack){
    audio.src = src;
    audio.play();
    fetch(`/track/${id}/play`, { method: 'POST' }).catch(()=>{});
  } else if(audio.paused){
    audio.play();
  } else {
    audio.pause();
  }

  localStorage.setItem('imusic_last_track', JSON.stringify({id, src, title, cover: currentCover}));
  updateMiniPlayer();
  updateCoverArt();
}

function togglePlay(){
  if(!audio.src){
    const last = localStorage.getItem('imusic_last_track');
    if(last){
      const t = JSON.parse(last);
      loadAndPlay(t.id, t.src, t.title, t.cover);
    }
    return;
  }
  ensureAudioGraph();
  if(audioCtx.state === 'suspended') audioCtx.resume();
  if(audio.paused){ audio.play(); } else { audio.pause(); }
}

// ---------------------------------------------------------------------------
// Queue navigation: shuffle / repeat / next / previous
// ---------------------------------------------------------------------------
function toggleShuffle(){
  shuffleOn = !shuffleOn;
  localStorage.setItem('imusic_shuffle', shuffleOn ? '1' : '0');
  updateQueueControlsUI();
}

function toggleRepeat(){
  repeatMode = repeatMode === 'off' ? 'all' : (repeatMode === 'all' ? 'one' : 'off');
  localStorage.setItem('imusic_repeat', repeatMode);
  updateQueueControlsUI();
}

function updateQueueControlsUI(){
  const sBtn = document.getElementById('shuffle-btn');
  const rBtn = document.getElementById('repeat-btn');
  const badge = document.getElementById('repeat-one-badge');
  const hint = document.getElementById('queue-hint');
  if(sBtn) sBtn.classList.toggle('active', shuffleOn);
  if(rBtn) rBtn.classList.toggle('active', repeatMode !== 'off');
  if(badge) badge.style.display = repeatMode === 'one' ? 'flex' : 'none';
  if(hint){
    if(queue.length > 1){
      hint.textContent = `${queueIndex + 1} / ${queue.length} dans la file`;
    } else {
      hint.textContent = '';
    }
  }
}

function nextTrack(auto){
  if(!queue.length) return;
  if(repeatMode === 'one' && auto){
    audio.currentTime = 0;
    audio.play();
    return;
  }
  if(shuffleOn && queue.length > 1){
    let idx;
    do { idx = Math.floor(Math.random() * queue.length); } while(idx === queueIndex);
    queueIndex = idx;
  } else {
    queueIndex++;
    if(queueIndex >= queue.length){
      if(repeatMode === 'all'){ queueIndex = 0; }
      else { queueIndex = queue.length - 1; updateQueueControlsUI(); return; }
    }
  }
  playCurrentQueueItem();
  updateQueueControlsUI();
}

function prevTrack(){
  if(!queue.length) return;
  if(audio.currentTime > 3){ audio.currentTime = 0; return; }
  if(shuffleOn && queue.length > 1){
    nextTrack(false);
    return;
  }
  queueIndex--;
  if(queueIndex < 0){ queueIndex = repeatMode === 'all' ? queue.length - 1 : 0; }
  playCurrentQueueItem();
  updateQueueControlsUI();
}

function skip(seconds){
  if(!audio.src) return;
  audio.currentTime = Math.max(0, Math.min(audio.duration || 0, audio.currentTime + seconds));
}

function formatTime(t){
  if(!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

audio.addEventListener('play', () => { updatePlayIcons(true); startViz(); });
audio.addEventListener('pause', () => { updatePlayIcons(false); });
audio.addEventListener('ended', () => { updatePlayIcons(false); nextTrack(true); });

audio.addEventListener('timeupdate', () => {
  if(isSeeking) return;
  const seek = document.getElementById('seek');
  const dur = audio.duration || 0;
  if(seek && dur){
    const pct = (audio.currentTime / dur) * 1000;
    seek.value = pct;
    seek.style.background = `linear-gradient(to right, var(--green-bright) ${pct/10}%, var(--green-bright) ${pct/10}%, #d9d2c0 ${pct/10}%, #d9d2c0 100%)`;
  }
  const cur = document.getElementById('time-current');
  if(cur) cur.textContent = formatTime(audio.currentTime);
});
audio.addEventListener('loadedmetadata', () => {
  const dur = document.getElementById('time-duration');
  if(dur) dur.textContent = formatTime(audio.duration);
  if(currentTrackId && isFinite(audio.duration)){
    const body = new URLSearchParams();
    body.set('duration', audio.duration);
    fetch(`/track/${currentTrackId}/duration`, { method: 'POST', body }).catch(()=>{});
  }
});

function onSeekInput(el){
  isSeeking = true;
  const dur = audio.duration || 0;
  const pct = el.value / 1000;
  el.style.background = `linear-gradient(to right, var(--green-bright) ${pct*100}%, var(--green-bright) ${pct*100}%, #d9d2c0 ${pct*100}%, #d9d2c0 100%)`;
  if(dur){
    audio.currentTime = pct * dur;
  }
  const cur = document.getElementById('time-current');
  if(cur) cur.textContent = formatTime(pct * dur);
  isSeeking = false;
}

function updatePlayIcons(playing){
  const iconPath = playing
    ? '<path d="M6 4h4v16H6zM14 4h4v16h-4z"/>'
    : '<path d="M8 5v14l11-7z"/>';
  const miniIcon = document.getElementById('mini-play-icon');
  const bigIcon = document.getElementById('big-play-icon');
  if(miniIcon) miniIcon.innerHTML = iconPath;
  if(bigIcon) bigIcon.innerHTML = iconPath;
}

function updateMiniPlayer(){
  const mini = document.getElementById('mini-player');
  const title = document.getElementById('mini-title');
  const nowTitle = document.getElementById('now-title');
  const miniCover = document.querySelector('#mini-player .mini-cover');
  if(!mini) return;
  if(currentTrackId){
    mini.style.display = 'flex';
    if(title) title.textContent = currentTitle;
    if(nowTitle) nowTitle.textContent = currentTitle;
    if(miniCover){
      const url = coverUrl(currentCover);
      miniCover.style.backgroundImage = url ? `url('${url}')` : '';
    }
  }
}

function updateCoverArt(){
  const cover = document.getElementById('now-cover');
  if(!cover) return;
  const url = coverUrl(currentCover);
  if(url){
    cover.style.backgroundImage = `url('${url}')`;
    cover.classList.add('visible');
  } else {
    cover.classList.remove('visible');
  }
}

// restore last-known track title into mini player (paused) across page loads
(function restoreLastTrack(){
  const last = localStorage.getItem('imusic_last_track');
  if(last){
    try{
      const t = JSON.parse(last);
      currentTrackId = null; // require explicit play to (re)create media element source
      currentTitle = t.title;
      currentCover = t.cover || null;
      const mini = document.getElementById('mini-player');
      const title = document.getElementById('mini-title');
      const miniCover = document.querySelector('#mini-player .mini-cover');
      if(mini){ mini.style.display = 'flex'; }
      if(title){ title.textContent = t.title; }
      if(miniCover && currentCover){ miniCover.style.backgroundImage = `url('${coverUrl(currentCover)}')`; }
      const nowTitle = document.getElementById('now-title');
      if(nowTitle) nowTitle.textContent = t.title;
    }catch(e){}
  }
})();

function openPlayer(){
  const overlay = document.getElementById('player-overlay');
  if(!overlay) return;
  if(!currentTrackId){
    const last = localStorage.getItem('imusic_last_track');
    if(last){
      const t = JSON.parse(last);
      loadAndPlay(t.id, t.src, t.title, t.cover);
    }
  }
  updateQueueControlsUI();
  updateCoverArt();
  overlay.classList.add('open');
}
function closePlayer(){
  const overlay = document.getElementById('player-overlay');
  if(overlay) overlay.classList.remove('open');
}

// ---------------------------------------------------------------------------
// Visualizer
// ---------------------------------------------------------------------------
function setVizMode(mode){
  vizMode = mode;
  localStorage.setItem('imusic_viz_mode', mode);
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
}

function startViz(){
  const canvas = document.getElementById('viz-canvas');
  if(!canvas) return;
  const ctx = canvas.getContext('2d');

  function resize(){
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = rect.height * devicePixelRatio;
  }
  resize();

  const green = getComputedStyle(document.documentElement).getPropertyValue('--green-bright').trim() || '#43D97D';
  const greenDeep = getComputedStyle(document.documentElement).getPropertyValue('--green').trim() || '#3C5C42';

  function draw(){
    rafId = requestAnimationFrame(draw);
    if(!analyser) return;
    analyser.getByteFrequencyData(dataArray);
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    if(vizMode === 'bars'){
      const barCount = 20;
      const barWidth = w / (barCount * 1.6);
      const gap = barWidth * 0.6;
      let x = gap;
      for(let i=0;i<barCount;i++){
        const idx = Math.floor(i * dataArray.length / barCount);
        const v = dataArray[idx] / 255;
        const barH = Math.max(h*0.04, v * h * 0.85);
        const y = (h - barH) / 2;
        ctx.fillStyle = i % 2 === 0 ? green : greenDeep;
        roundRect(ctx, x, y, barWidth, barH, barWidth/2);
        x += barWidth + gap;
      }
    } else if(vizMode === 'wave'){
      ctx.lineWidth = w * 0.012;
      ctx.strokeStyle = green;
      ctx.beginPath();
      const sliceW = w / dataArray.length;
      let x = 0;
      for(let i=0;i<dataArray.length;i++){
        const v = dataArray[i] / 255;
        const y = h/2 + Math.sin(i*0.5 + Date.now()*0.002) * (v * h * 0.35);
        if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        x += sliceW;
      }
      ctx.stroke();
    } else if(vizMode === 'circle'){
      const cx = w/2, cy = h/2;
      const baseR = Math.min(w,h) * 0.22;
      const bars = 48;
      for(let i=0;i<bars;i++){
        const idx = Math.floor(i * dataArray.length / bars);
        const v = dataArray[idx] / 255;
        const angle = (i / bars) * Math.PI * 2;
        const len = baseR * 0.3 + v * baseR * 0.9;
        const x1 = cx + Math.cos(angle) * baseR;
        const y1 = cy + Math.sin(angle) * baseR;
        const x2 = cx + Math.cos(angle) * (baseR + len);
        const y2 = cy + Math.sin(angle) * (baseR + len);
        ctx.strokeStyle = i % 2 === 0 ? green : greenDeep;
        ctx.lineWidth = w * 0.01;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(x1,y1);
        ctx.lineTo(x2,y2);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(cx, cy, baseR*0.7, 0, Math.PI*2);
      ctx.fillStyle = greenDeep + '22';
      ctx.fill();
    }
  }
  if(rafId) cancelAnimationFrame(rafId);
  draw();
}

function roundRect(ctx, x, y, w, h, r){
  ctx.beginPath();
  ctx.moveTo(x+r, y);
  ctx.arcTo(x+w, y, x+w, y+h, r);
  ctx.arcTo(x+w, y+h, x, y+h, r);
  ctx.arcTo(x, y+h, x, y, r);
  ctx.arcTo(x, y, x+w, y, r);
  ctx.closePath();
  ctx.fill();
}

document.addEventListener('DOMContentLoaded', () => {
  setVizMode(vizMode);
  updateQueueControlsUI();
});

// ---------------------------------------------------------------------------
// Add-to-playlist modal
// ---------------------------------------------------------------------------
let addToPlaylistTrackId = null;
function openAddToPlaylist(trackId){
  addToPlaylistTrackId = trackId;
  const modal = document.getElementById('add-playlist-modal');
  const list = document.getElementById('add-playlist-list');
  if(!modal) return;
  modal.style.display = 'flex';
  list.innerHTML = '<p style="color:var(--muted);">Chargement…</p>';

  fetch('/api/playlists').then(r => r.json()).then(items => {
    if(items.length === 0){
      list.innerHTML = '<p style="color:var(--muted);">Aucune playlist. Créez-en une depuis l\'onglet Playlists.</p>';
      return;
    }
    list.innerHTML = items.map(p => `
      <button class="btn outline" style="justify-content:flex-start;" onclick="addTrackToPlaylist(${p.id}, this)">
        ${p.name}
      </button>
    `).join('');
  });
}
function closeAddToPlaylist(){
  const modal = document.getElementById('add-playlist-modal');
  if(modal) modal.style.display = 'none';
}
function addTrackToPlaylist(playlistId, btn){
  fetch(`/api/playlists/${playlistId}/add/${addToPlaylistTrackId}`, { method: 'POST' })
    .then(r => r.json())
    .then(res => {
      if(res.ok){
        btn.textContent = '✓ Ajouté';
        btn.style.background = 'var(--green-pale)';
        setTimeout(closeAddToPlaylist, 700);
      }
    });
}

// ---------------------------------------------------------------------------
// Rename modal
// ---------------------------------------------------------------------------
function openRename(trackId, title){
  const modal = document.getElementById('rename-modal');
  const form = document.getElementById('rename-form');
  const input = document.getElementById('rename-input');
  if(!modal) return;
  form.action = `/track/${trackId}/rename`;
  input.value = title;
  modal.style.display = 'flex';
  setTimeout(() => input.focus(), 50);
}
function closeRename(){
  const modal = document.getElementById('rename-modal');
  if(modal) modal.style.display = 'none';
}

// ---------------------------------------------------------------------------
// Drag-and-drop playlist reorder
// ---------------------------------------------------------------------------
function initPlaylistReorder(playlistId){
  const list = document.getElementById('playlist-track-list');
  if(!list) return;
  let dragEl = null;

  list.querySelectorAll('.track-card').forEach(card => {
    card.setAttribute('draggable', 'true');

    card.addEventListener('dragstart', () => {
      dragEl = card;
      setTimeout(() => card.classList.add('dragging'), 0);
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      dragEl = null;
      persistOrder(playlistId, list);
    });
    card.addEventListener('dragover', (e) => {
      e.preventDefault();
      const after = getDragAfterElement(list, e.clientY);
      if(!dragEl) return;
      if(after == null){
        list.appendChild(dragEl);
      } else {
        list.insertBefore(dragEl, after);
      }
    });
  });
}

function getDragAfterElement(container, y){
  const cards = [...container.querySelectorAll('.track-card:not(.dragging)')];
  return cards.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if(offset < 0 && offset > closest.offset){
      return { offset, element: child };
    }
    return closest;
  }, { offset: Number.NEGATIVE_INFINITY }).element;
}

function persistOrder(playlistId, list){
  const order = [...list.querySelectorAll('.track-card')].map(c => c.dataset.trackId);
  fetch(`/playlists/${playlistId}/reorder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order }),
  }).catch(()=>{});
}

// Constantes
const API_SONGS = '/api/songs';
const PIXELS_PER_SECOND = 50; // Échelle de la timeline

document.addEventListener('DOMContentLoaded', () => {
    const songGrid = document.getElementById('songGrid');
    const timelineWrapper = document.getElementById('timelineWrapper');

    // Initialisation Catalogue
    if (songGrid) {
        fetchSongs();
    }

    // Initialisation Timeline (si on est sur la page d'analyse)
    if (timelineWrapper) {
        const songId = new URLSearchParams(window.location.search).get('id');
        if (songId) {
            startAnalysis(songId);
        }
    }
});

// --- CATALOGUE ---
async function fetchSongs() {
    try {
        const response = await fetch(API_SONGS);
        const data = await response.json();
        renderCatalog(data.songs);
    } catch (err) {
        console.error("Erreur chargement catalogue", err);
    }
}

function renderCatalog(songs) {
    const grid = document.getElementById('songGrid');
    grid.innerHTML = '';
    songs.forEach(song => {
        const card = document.createElement('div');
        card.className = 'song-card';
        card.innerHTML = `
            <div class="cover-placeholder">♪</div>
            <div class="song-info">
                <h3>${song.title}</h3>
                <button onclick="window.location.href='/timeline?id=${song.id}'">Analyser</button>
            </div>
        `;
        grid.appendChild(card);
    });
}

// --- ANALYSE & TIMELINE ---
async function startAnalysis(songId) {
    // 1. Lancer le job (asynchrone)
    const response = await fetch(`/api/songs/${songId}/analyse/start`);
    const data = await response.json();
    
    if (data.job_id) {
        pollJobStatus(data.job_id);
    }
}

async function pollJobStatus(jobId) {
    const interval = setInterval(async () => {
        const res = await fetch(`/api/jobs/${jobId}`);
        const job = await res.json();
        
        if (job.status === 'finished') {
            clearInterval(interval);
            renderTimeline(job.result);
        } else if (job.status === 'failed') {
            clearInterval(interval);
            alert("Erreur lors de l'analyse");
        }
    }, 1000);
}

function renderTimeline(analysisData) {
    document.getElementById('globalTempo').textContent = `Tempo: ${analysisData.tempo} BPM`;
    
    const keyContent = document.getElementById('keyContent');
    const chordContent = document.getElementById('chordContent');
    
    // Rendu des segments de tonalité (Modulation)
    analysisData.key.forEach(segment => {
        const width = (segment.end - segment.start) * PIXELS_PER_SECOND;
        const left = segment.start * PIXELS_PER_SECOND;
        
        const el = document.createElement('div');
        el.className = 'timeline-segment key-segment';
        el.style.width = `${width}px`;
        el.style.left = `${left}px`;
        el.textContent = segment.key;
        keyContent.appendChild(el);
    });

    // Rendu des accords (Lissage Viterbi)
    analysisData.timeline.forEach(segment => {
        const width = (segment.end - segment.start) * PIXELS_PER_SECOND;
        const left = segment.start * PIXELS_PER_SECOND;
        
        const el = document.createElement('div');
        el.className = 'timeline-segment chord-segment';
        el.style.width = `${width}px`;
        el.style.left = `${left}px`;
        el.textContent = segment.chord;
        chordContent.appendChild(el);
    });

    drawTempoCurve(analysisData.tempo_curve);
}

function drawTempoCurve(curve) {
    const canvas = document.getElementById('tempoCanvas');
    if (!canvas || !curve || curve.length === 0) return;
    const ctx = canvas.getContext('2d');
    
    const maxT = Math.max(...curve);
    const minT = Math.min(...curve);
    const stepX = canvas.width / (curve.length - 1);
    
    ctx.beginPath();
    ctx.strokeStyle = '#4CAF50';
    ctx.lineWidth = 2;
    
    curve.forEach((tempo, i) => {
        const x = i * stepX;
        // Normaliser Y entre 10% et 90% de la hauteur du canvas
        const y = canvas.height - ((tempo - minT) / (maxT - minT || 1) * (canvas.height * 0.8) + canvas.height * 0.1);
        
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
}