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


// ---------------------------------------------------------------------------
// Catalogue (11 chansons) — écouter / analyser une chanson depuis la grille
// ---------------------------------------------------------------------------
function playCatalogCard(btn){
  const card = btn.closest('.song-card');
  if(!card) return;
  const id = parseInt(card.dataset.id, 10);
  const title = card.dataset.title;
  const src = card.dataset.src;
  playQueueItem([{ id: `cat-${id}`, title, filename: null, cover: null, _directSrc: src }], 0);
}

// playQueueItem() calls playCurrentQueueItem() -> loadAndPlay(id, audioUrl(filename), ...)
// Les chansons du catalogue ont déjà une URL complète (pas un simple nom de
// fichier dans static/uploads), donc on adapte playCurrentQueueItem pour ce cas.
const _originalPlayCurrentQueueItem = playCurrentQueueItem;
playCurrentQueueItem = function(){
  const t = queue[queueIndex];
  if(!t) return;
  const src = t._directSrc ? t._directSrc : audioUrl(t.filename);
  loadAndPlayDirect(t.id, src, t.title, t.cover);
};

function loadAndPlayDirect(id, src, title, cover){
  ensureAudioGraph();
  if(audioCtx.state === 'suspended') audioCtx.resume();

  const isNewTrack = currentTrackId !== id;
  currentTrackId = id;
  currentTitle = title;
  currentCover = cover || null;

  if(isNewTrack){
    audio.src = src;
    audio.play().catch(()=>{});
    if(typeof id === 'number'){
      fetch(`/track/${id}/play`, { method: 'POST' }).catch(()=>{});
    }
  } else if(audio.paused){
    audio.play().catch(()=>{});
  } else {
    audio.pause();
  }

  localStorage.setItem('imusic_last_track', JSON.stringify({id, src, title, cover: currentCover}));
  updateMiniPlayer();
  updateCoverArt();
}

function playCatalogSong(id, title, src, kind){
  // Les morceaux importés (kind === 'track') utilisent leur vrai id numérique
  // pour que /track/<id>/play soit appelé (compteur d'écoutes) ; les chansons
  // du catalogue utilisent un id préfixé car elles n'ont pas d'entrée en base.
  const queueId = kind === 'track' ? id : `cat-${id}`;
  playQueueItem([{ id: queueId, title, filename: null, cover: null, _directSrc: src }], 0);
  syncListenButton();
}

function syncListenButton(){
  const icon = document.getElementById('listenBtnIcon');
  const label = document.getElementById('listenBtnLabel');
  if(!icon || !label) return;
  const playing = !audio.paused && !audio.ended && audio.src;
  icon.innerHTML = playing
    ? '<path d="M6 4h4v16H6zM14 4h4v16h-4z"/>'
    : '<path d="M8 5v14l11-7z"/>';
  label.textContent = playing ? 'Pause' : 'Écouter';
}
audio.addEventListener('play', syncListenButton);
audio.addEventListener('pause', syncListenButton);

// ---------------------------------------------------------------------------
// Timeline d'analyse — lancement asynchrone + rendu synchronisé à la lecture
// ---------------------------------------------------------------------------
const CHORD_COLORS = {
  '': '#43D97D', 'm': '#3C5C42', '7': '#E2A83C', 'maj7': '#5B8DEF',
  'm7': '#2C4531', 'dim': '#9C4C4C', 'aug': '#B25CE2', 'sus2': '#3FB6C9', 'sus4': '#3F8FC9',
};
function chordColor(label){
  if(!label || label === '...' ) return '#9C9484';
  const m = label.match(/^[A-G]#?(.*)$/);
  const quality = m ? m[1] : '';
  return CHORD_COLORS[quality] || '#43D97D';
}

let currentAnalysis = null; // { tempo, tempo_curve, key: [...], timeline: [...] }
let currentSongDuration = 0;
let timelineSyncRaf = null;

async function startAnalysis(songId){
  const analyseBtn = document.getElementById('analyseBtn');
  const progressBox = document.getElementById('analysisProgress');
  const progressFill = document.getElementById('progressFill');
  const progressStep = document.getElementById('progressStep');
  const results = document.getElementById('resultsSection');

  if(analyseBtn) { analyseBtn.disabled = true; analyseBtn.style.opacity = '0.6'; }
  if(progressBox) progressBox.style.display = 'block';
  if(results) results.style.display = 'none';
  if(progressFill) progressFill.style.width = '4%';
  if(progressStep) progressStep.textContent = "Envoi de la demande d'analyse…";

  try{
    const startRes = await fetch(`/api/songs/${songId}/analyse/start`);
    const startData = await startRes.json();
    if(!startRes.ok || !startData.job_id){
      throw new Error(startData.error || "Impossible de démarrer l'analyse.");
    }
    pollJobStatus(startData.job_id);
  }catch(err){
    if(progressStep) progressStep.textContent = '❌ ' + err.message;
    if(analyseBtn) { analyseBtn.disabled = false; analyseBtn.style.opacity = '1'; }
  }
}

function pollJobStatus(jobId){
  const progressFill = document.getElementById('progressFill');
  const progressStep = document.getElementById('progressStep');
  const analyseBtn = document.getElementById('analyseBtn');

  const interval = setInterval(async () => {
    try{
      const res = await fetch(`/api/jobs/${jobId}`);
      const job = await res.json();

      if(job.error && !job.status){
        clearInterval(interval);
        if(progressStep) progressStep.textContent = '❌ ' + job.error;
        if(analyseBtn) { analyseBtn.disabled = false; analyseBtn.style.opacity = '1'; }
        return;
      }

      const pct = Math.round((job.progress || 0) * 100);
      if(progressFill) progressFill.style.width = pct + '%';
      if(progressStep) progressStep.textContent = job.step || 'Analyse en cours…';

      if(job.status === 'done'){
        clearInterval(interval);
        if(job.result && job.result.error){
          if(progressStep) progressStep.textContent = '❌ ' + job.result.error;
          if(analyseBtn) { analyseBtn.disabled = false; analyseBtn.style.opacity = '1'; }
          return;
        }
        if(progressFill) progressFill.style.width = '100%';
        if(progressStep) progressStep.textContent = 'Terminé ✓';
        renderTimeline(job.result);
      } else if(job.status === 'failed'){
        clearInterval(interval);
        if(progressStep) progressStep.textContent = '❌ ' + (job.error || 'Erreur lors de l\'analyse.');
        if(analyseBtn) { analyseBtn.disabled = false; analyseBtn.style.opacity = '1'; }
      }
    }catch(err){
      clearInterval(interval);
      if(progressStep) progressStep.textContent = '❌ Erreur réseau pendant le suivi de la tâche.';
      if(analyseBtn) { analyseBtn.disabled = false; analyseBtn.style.opacity = '1'; }
    }
  }, 900);
}

function renderTimeline(analysisData){
  currentAnalysis = analysisData;
  const results = document.getElementById('resultsSection');
  const progressBox = document.getElementById('analysisProgress');
  const globalTempo = document.getElementById('globalTempo');
  const keyContent = document.getElementById('keyContent');
  const chordContent = document.getElementById('chordContent');

  if(globalTempo) globalTempo.textContent = `Tempo : ${Math.round(analysisData.tempo)} BPM`;
  // On vide le contenu mais on conserve le repère de lecture (.playhead).
  if(keyContent) keyContent.querySelectorAll('.timeline-segment').forEach(el => el.remove());
  if(chordContent) chordContent.querySelectorAll('.timeline-segment').forEach(el => el.remove());

  const totalDuration = Math.max(
    ...(analysisData.key || []).map(s => s.end),
    ...(analysisData.timeline || []).map(s => s.end),
    currentSongDuration || 0,
    1
  );
  currentSongDuration = totalDuration;

  (analysisData.key || []).forEach((segment, i) => {
    const el = document.createElement('div');
    el.className = 'timeline-segment key-segment';
    el.style.left = `${(segment.start / totalDuration) * 100}%`;
    el.style.width = `${Math.max(((segment.end - segment.start) / totalDuration) * 100, 2)}%`;
    el.style.background = i % 2 === 0 ? '#3f51b5' : '#5b6fd6';
    el.textContent = segment.key;
    el.title = `${segment.key} — ${formatTime(segment.start)} → ${formatTime(segment.end)}`;
    el.dataset.start = segment.start;
    el.onclick = () => seekAudioTo(segment.start);
    keyContent.appendChild(el);
  });

  (analysisData.timeline || []).forEach(segment => {
    const el = document.createElement('div');
    el.className = 'timeline-segment chord-segment';
    el.style.left = `${(segment.start / totalDuration) * 100}%`;
    el.style.width = `${Math.max(((segment.end - segment.start) / totalDuration) * 100, 1.2)}%`;
    el.style.background = chordColor(segment.chord);
    el.textContent = segment.chord;
    el.title = `${segment.chord} — ${formatTime(segment.start)} → ${formatTime(segment.end)}`;
    el.dataset.start = segment.start;
    el.dataset.end = segment.end;
    el.onclick = () => seekAudioTo(segment.start);
    chordContent.appendChild(el);
  });

  drawTempoCurve(analysisData.tempo_curve);

  if(progressBox) progressBox.style.display = 'none';
  if(results) results.style.display = 'block';

  startTimelineSync();
}

function seekAudioTo(t){
  if(!audio.src){
    const page = document.getElementById('timelinePage');
    if(page) playCatalogSong(parseInt(page.dataset.songId, 10), page.dataset.songTitle, page.dataset.songSrc);
  }
  if(isFinite(audio.duration) && audio.duration > 0){
    audio.currentTime = Math.min(t, audio.duration);
  } else {
    audio.currentTime = t;
  }
  if(audio.paused) audio.play().catch(()=>{});
}

function drawTempoCurve(curve){
  const canvas = document.getElementById('tempoCanvas');
  if(!canvas || !curve || curve.length === 0) return;
  const ctx = canvas.getContext('2d');
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * devicePixelRatio;
  canvas.height = rect.height * devicePixelRatio;
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const maxT = Math.max(...curve);
  const minT = Math.min(...curve);
  const stepX = w / Math.max(curve.length - 1, 1);

  // Zone remplie sous la courbe
  ctx.beginPath();
  ctx.moveTo(0, h);
  curve.forEach((tempo, i) => {
    const x = i * stepX;
    const y = h - (((tempo - minT) / (maxT - minT || 1)) * (h * 0.75) + h * 0.12);
    ctx.lineTo(x, y);
  });
  ctx.lineTo(w, h);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, 'rgba(67,217,125,0.35)');
  grad.addColorStop(1, 'rgba(67,217,125,0.02)');
  ctx.fillStyle = grad;
  ctx.fill();

  // Ligne de la courbe
  ctx.beginPath();
  ctx.lineWidth = Math.max(2, w * 0.004);
  ctx.strokeStyle = '#43D97D';
  ctx.lineJoin = 'round';
  curve.forEach((tempo, i) => {
    const x = i * stepX;
    const y = h - (((tempo - minT) / (maxT - minT || 1)) * (h * 0.75) + h * 0.12);
    if(i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function startTimelineSync(){
  if(timelineSyncRaf) cancelAnimationFrame(timelineSyncRaf);

  function tick(){
    timelineSyncRaf = requestAnimationFrame(tick);
    if(!currentAnalysis) return;
    const t = audio.currentTime || 0;
    const duration = currentSongDuration || audio.duration || 1;
    const pct = Math.min(100, (t / duration) * 100);

    const phKey = document.getElementById('playheadKey');
    const phChord = document.getElementById('playheadChord');
    if(phKey) phKey.style.left = pct + '%';
    if(phChord) phChord.style.left = pct + '%';

    document.querySelectorAll('#keyContent .timeline-segment').forEach(el => {
      el.classList.toggle('active-segment', parseFloat(el.dataset.start) <= t &&
        (parseFloat(el.nextElementSibling?.dataset.start ?? Infinity) > t));
    });
    document.querySelectorAll('#chordContent .timeline-segment').forEach(el => {
      const start = parseFloat(el.dataset.start), end = parseFloat(el.dataset.end);
      el.classList.toggle('active-segment', t >= start && t < end);
    });

    const hint = document.getElementById('syncHint');
    if(hint && !audio.paused){
      hint.textContent = `Lecture en cours — ${formatTime(t)} / ${formatTime(duration)}`;
    }
  }
  tick();
}

// Auto-restauration si l'analyse est déjà en cache côté serveur (voir
// window.__CACHED_ANALYSIS__ injecté par timeline.html).
document.addEventListener('DOMContentLoaded', () => {
  const page = document.getElementById('timelinePage');
  if(page && window.__CACHED_ANALYSIS__){
    renderTimeline(window.__CACHED_ANALYSIS__);
    const analyseBtn = document.getElementById('analyseBtn');
    if(analyseBtn){ analyseBtn.textContent = "Relancer l'analyse"; }
  }

  // Grille catalogue : fetch dynamique optionnel (les cartes sont déjà
  // rendues côté serveur par Jinja ; ce fetch ne sert qu'au champ de recherche).
  const catalogSearch = document.getElementById('catalogSearch');
  if(catalogSearch){
    catalogSearch.addEventListener('input', () => {
      const q = catalogSearch.value.trim().toLowerCase();
      document.querySelectorAll('.song-card').forEach(card => {
        const hay = (card.dataset.title + ' ' + card.dataset.artist).toLowerCase();
        card.style.display = hay.includes(q) ? '' : 'none';
      });
    });
  }
});
