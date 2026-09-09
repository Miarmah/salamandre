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
