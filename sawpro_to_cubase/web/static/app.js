document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const folderInput = document.getElementById('folderInput');
  const stagingPanel = document.getElementById('stagingPanel');
  const fileChipGrid = document.getElementById('fileChipGrid');
  const fileCountSpan = document.getElementById('fileCount');
  const clearFilesBtn = document.getElementById('clearFilesBtn');
  const convertBtn = document.getElementById('convertBtn');
  const fpsSelect = document.getElementById('fpsSelect');
  const dropFrameCheckbox = document.getElementById('dropFrameCheckbox');
  const embedAudioCheckbox = document.getElementById('embedAudioCheckbox');

  const heroSection = document.getElementById('heroSection');
  const dropSection = document.getElementById('dropSection');
  const loadingSection = document.getElementById('loadingSection');
  const resultsSection = document.getElementById('resultsSection');
  const convertAnotherBtn = document.getElementById('convertAnotherBtn');

  // Metrics & Results
  const resSessionName = document.getElementById('resSessionName');
  const metricSampleRate = document.getElementById('metricSampleRate');
  const metricMagic = document.getElementById('metricMagic');
  const metricTracks = document.getElementById('metricTracks');
  const metricPlacements = document.getElementById('metricPlacements');
  const metricDuration = document.getElementById('metricDuration');

  const timelineRuler = document.getElementById('timelineRuler');
  const timelineLanes = document.getElementById('timelineLanes');
  const masterZipBtn = document.getElementById('masterZipBtn');
  const downloadBtnAaf = document.getElementById('downloadBtnAaf');
  const downloadBtnXml = document.getElementById('downloadBtnXml');
  const downloadBtnCsv = document.getElementById('downloadBtnCsv');
  const downloadBtnCmx = document.getElementById('downloadBtnCmx');

  const soundfilesTableBody = document.getElementById('soundfilesTableBody');
  const soundfilesCount = document.getElementById('soundfilesCount');
  const regionsTableBody = document.getElementById('regionsTableBody');
  const regionsCount = document.getElementById('regionsCount');

  // Audio Transport Elements
  const audioStatusIndicator = document.getElementById('audioStatusIndicator');
  const audioStatusText = document.getElementById('audioStatusText');
  const loadAudioFilesBtn = document.getElementById('loadAudioFilesBtn');
  const extraAudioInput = document.getElementById('extraAudioInput');
  const playPauseBtn = document.getElementById('playPauseBtn');
  const playPauseIcon = document.getElementById('playPauseIcon');
  const stopBtn = document.getElementById('stopBtn');
  const displayCurrentTime = document.getElementById('displayCurrentTime');
  const displayTotalTime = document.getElementById('displayTotalTime');
  const displayCurrentSmpte = document.getElementById('displayCurrentSmpte');
  const volMuteBtn = document.getElementById('volMuteBtn');
  const volIcon = document.getElementById('volIcon');
  const masterVolume = document.getElementById('masterVolume');
  const timelinePlayhead = document.getElementById('timelinePlayhead');
  const exportMixWavBtn = document.getElementById('exportMixWavBtn');
  const exportMixMp3Btn = document.getElementById('exportMixMp3Btn');
  const downloadGridMixWavBtn = document.getElementById('downloadGridMixWavBtn');
  const downloadGridMixMp3Btn = document.getElementById('downloadGridMixMp3Btn');

  // Staged files list: Array of File objects
  let stagedFiles = [];
  let currentSessionData = null;

  // =========================================================================
  // Filename Encoding & Codepage Transliteration Helper
  // =========================================================================
  function getFilenameVariants(name) {
    if (!name) return [];
    const variants = new Set();
    variants.add(name);
    variants.add(name.toLowerCase());

    // Direct transliterations between Windows ANSI (CP1252) and DOS OEM (CP850/865/437)
    const charPairs = [
      ["æ", "µ"], ["ø", "°"], ["å", "Õ"], ["å", "σ"],
      ["Æ", "ã"], ["Æ", "╞"], ["Ø", "Ï"], ["Ø", "╪"], ["Å", "┼"],
      ["é", "Ú"], ["é", "Θ"], ["ä", "õ"], ["ä", "Σ"], ["ö", "÷"], ["ü", "³"], ["ü", "ⁿ"],
      ["æ", "‘"], ["ø", "›"], ["å", "†"],
      ["Æ", "’"], ["é", "‚"], ["ä", "„"], ["ö", "”"],
    ];

    for (const [a, b] of charPairs) {
      if (name.includes(a)) {
        const v = name.replaceAll(a, b);
        variants.add(v);
        variants.add(v.toLowerCase());
      }
      if (name.includes(b)) {
        const v = name.replaceAll(b, a);
        variants.add(v);
        variants.add(v.toLowerCase());
      }
    }

    try {
      variants.add(name.normalize("NFC"));
      variants.add(name.normalize("NFC").toLowerCase());
      variants.add(name.normalize("NFD"));
      variants.add(name.normalize("NFD").toLowerCase());
    } catch (e) {}

    return Array.from(variants);
  }

  // =========================================================================
  // Multitrack Web Audio Engine
  // =========================================================================
  class MultitrackPlayer {
    constructor() {
      this.audioCtx = null;
      this.masterGain = null;
      this.trackGains = new Map(); // trackNum -> GainNode
      this.trackMutes = new Map(); // trackNum -> boolean
      this.trackSolos = new Map(); // trackNum -> boolean
      this.activeTracks = new Set(); // Set of active track numbers
      this.audioBuffers = new Map(); // filename.toLowerCase() -> AudioBuffer
      this.activeSources = [];
      this.isPlaying = false;
      this.playbackStartCtxTime = 0;
      this.currentPositionSeconds = 0;
      this.sessionDuration = 0;
      this.events = [];
      this.fps = 30.0;
      this.animationFrameId = null;
      this.isMasterMuted = false;
      this.lastVolume = 0.8;
    }

    async initContext() {
      if (!this.audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        this.audioCtx = new AudioContextClass();
        this.masterGain = this.audioCtx.createGain();
        const vol = this.isMasterMuted ? 0.0 : (parseFloat(masterVolume.value) || 0.8);
        this.masterGain.gain.setValueAtTime(vol, this.audioCtx.currentTime);
        this.masterGain.connect(this.audioCtx.destination);
      }
      if (this.audioCtx.state === 'suspended') {
        try {
          await this.audioCtx.resume();
        } catch (e) {
          console.warn('AudioContext resume failed:', e);
        }
      }
    }

    async decodeAudio(filename, arrayBuffer) {
      await this.initContext();
      try {
        const copy = arrayBuffer.slice(0);
        const buffer = await this.audioCtx.decodeAudioData(copy);
        this.audioBuffers.set(filename.toLowerCase(), buffer);
        for (const v of getFilenameVariants(filename)) {
          this.audioBuffers.set(v.toLowerCase(), buffer);
        }
        return buffer;
      } catch (err) {
        console.warn(`Could not decode audio for ${filename}:`, err);
        return null;
      }
    }

    hasAudioFor(filename) {
      if (!filename) return false;
      const lower = filename.toLowerCase();
      if (this.audioBuffers.has(lower)) return true;
      for (const v of getFilenameVariants(filename)) {
        if (this.audioBuffers.has(v.toLowerCase())) return true;
      }
      return false;
    }

    hasActiveSolo() {
      if (!this.activeTracks || this.activeTracks.size === 0) {
        return Array.from(this.trackSolos.values()).some(v => v);
      }
      for (const [trk, isSolo] of this.trackSolos.entries()) {
        if (isSolo && this.activeTracks.has(trk)) {
          return true;
        }
      }
      return false;
    }

    shouldMuteTrack(trackNum) {
      const isMuted = !!this.trackMutes.get(trackNum);
      const isSolo = !!this.trackSolos.get(trackNum);
      const hasSolo = this.hasActiveSolo();
      return isMuted || (hasSolo && !isSolo);
    }

    getTrackGain(trackNum) {
      if (!this.trackGains.has(trackNum)) {
        if (!this.audioCtx) return null;
        const gain = this.audioCtx.createGain();
        const shouldMute = this.shouldMuteTrack(trackNum);
        gain.gain.setValueAtTime(shouldMute ? 0.0 : 1.0, this.audioCtx.currentTime);
        gain.connect(this.masterGain);
        this.trackGains.set(trackNum, gain);
      }
      return this.trackGains.get(trackNum);
    }

    updateTrackGains() {
      const now = this.audioCtx ? this.audioCtx.currentTime : 0;

      // Update Web Audio GainNodes
      if (this.audioCtx) {
        for (const [trackNum, gainNode] of this.trackGains.entries()) {
          const shouldMute = this.shouldMuteTrack(trackNum);
          gainNode.gain.setValueAtTime(shouldMute ? 0.0 : 1.0, now);
        }
      }

      // Update UI lane muted styling
      document.querySelectorAll('.timeline-lane[data-track]').forEach(lane => {
        const trk = parseInt(lane.getAttribute('data-track'), 10);
        const shouldMute = this.shouldMuteTrack(trk);
        lane.classList.toggle('is-muted', shouldMute);
      });
    }

    async play(fromSeconds = null) {
      await this.initContext();
      if (this.isPlaying) {
        this.stopSources();
      }

      if (fromSeconds !== null) {
        this.currentPositionSeconds = Math.max(0, Math.min(fromSeconds, this.sessionDuration));
      }

      if (this.currentPositionSeconds >= this.sessionDuration && this.sessionDuration > 0) {
        this.currentPositionSeconds = 0;
      }

      // Sync track gains with current mute/solo state before playback
      this.updateTrackGains();

      const now = this.audioCtx.currentTime;
      this.playbackStartCtxTime = now - this.currentPositionSeconds;
      this.isPlaying = true;
      this.activeSources = [];

      const pos = this.currentPositionSeconds;

      // Schedule clips across tracks safely
      for (const ev of this.events) {
        const evStart = ev.start_seconds;
        const evEnd = evStart + ev.duration_seconds;

        // Clip already finished before current playhead
        if (evEnd <= pos) continue;

        let buffer = this.audioBuffers.get((ev.soundfile_name || '').toLowerCase());
        if (!buffer && ev.soundfile_name) {
          for (const v of getFilenameVariants(ev.soundfile_name)) {
            buffer = this.audioBuffers.get(v.toLowerCase());
            if (buffer) break;
          }
        }
        if (!buffer) continue;

        const trackGain = this.getTrackGain(ev.track);
        if (!trackGain) continue;

        const source = this.audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(trackGain);

        try {
          const bufferDur = buffer.duration;
          if (pos <= evStart) {
            // Scheduled in future
            const when = now + (evStart - pos);
            const rawOffset = Math.max(0, ev.source_in_seconds || 0);
            if (rawOffset >= bufferDur) continue;
            const safeOffset = rawOffset;
            const maxAvailableDur = Math.max(0, bufferDur - safeOffset);
            const safeDur = Math.min(ev.duration_seconds, maxAvailableDur);
            if (safeDur > 0) {
              source.start(when, safeOffset, safeDur);
              this.activeSources.push(source);
            }
          } else {
            // Playhead is in middle of clip: start immediately with offset
            const elapsedInClip = pos - evStart;
            const rawOffset = Math.max(0, (ev.source_in_seconds || 0) + elapsedInClip);
            if (rawOffset >= bufferDur) continue;
            const safeOffset = rawOffset;
            const rawRemainingDur = ev.duration_seconds - elapsedInClip;
            const maxAvailableDur = Math.max(0, bufferDur - safeOffset);
            const safeDur = Math.min(rawRemainingDur, maxAvailableDur);
            if (safeDur > 0) {
              source.start(now, safeOffset, safeDur);
              this.activeSources.push(source);
            }
          }
        } catch (err) {
          console.warn(`Error scheduling clip for ${ev.soundfile_name}:`, err);
        }
      }

      this.updateTransportUI(true);
      this.startAnimationLoop();
    }

    pause() {
      if (!this.isPlaying) return;
      this.stopSources();
      this.isPlaying = false;
      this.cancelAnimationLoop();
      this.updateTransportUI(false);
    }

    stop() {
      this.stopSources();
      this.isPlaying = false;
      this.currentPositionSeconds = 0;
      this.cancelAnimationLoop();
      this.updateTransportUI(false);
      this.renderPosition(0);
    }

    async seek(seconds) {
      const wasPlaying = this.isPlaying;
      if (this.isPlaying) {
        this.stopSources();
      }
      this.currentPositionSeconds = Math.max(0, Math.min(seconds, this.sessionDuration));
      this.renderPosition(this.currentPositionSeconds);

      if (wasPlaying) {
        await this.play();
      }
    }

    stopSources() {
      for (const src of this.activeSources) {
        try {
          src.stop();
          src.disconnect();
        } catch (e) {}
      }
      this.activeSources = [];
    }

    startAnimationLoop() {
      this.cancelAnimationLoop();
      const loop = () => {
        if (!this.isPlaying) return;

        const elapsed = this.audioCtx.currentTime - this.playbackStartCtxTime;
        this.currentPositionSeconds = elapsed;

        if (elapsed >= this.sessionDuration && this.sessionDuration > 0) {
          this.stop();
          return;
        }

        this.renderPosition(elapsed);
        this.animationFrameId = requestAnimationFrame(loop);
      };
      this.animationFrameId = requestAnimationFrame(loop);
    }

    cancelAnimationLoop() {
      if (this.animationFrameId) {
        cancelAnimationFrame(this.animationFrameId);
        this.animationFrameId = null;
      }
    }

    renderPosition(seconds) {
      displayCurrentTime.textContent = formatTime(seconds);
      displayCurrentSmpte.textContent = formatSmpte(seconds, this.fps);

      if (this.sessionDuration > 0) {
        const percent = Math.max(0, Math.min(100, (seconds / this.sessionDuration) * 100));
        timelinePlayhead.style.left = `${percent}%`;
      }
    }

    updateTransportUI(isPlaying) {
      if (isPlaying) {
        playPauseBtn.classList.add('playing');
        playPauseIcon.innerHTML = '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>';
        playPauseBtn.title = "Pause (Spacebar)";
      } else {
        playPauseBtn.classList.remove('playing');
        playPauseIcon.innerHTML = '<polygon points="6 4 20 12 6 20"/>';
        playPauseBtn.title = "Play (Spacebar)";
      }
    }

    setMasterVolume(val) {
      this.initContext();
      const v = Math.max(0, Math.min(1, val));
      this.masterGain.gain.setValueAtTime(v, this.audioCtx.currentTime);
      this.isMasterMuted = v === 0;
      updateVolumeIcon(this.isMasterMuted);
    }

    toggleMasterMute() {
      this.initContext();
      if (this.isMasterMuted) {
        const v = this.lastVolume > 0 ? this.lastVolume : 0.8;
        masterVolume.value = v;
        this.setMasterVolume(v);
      } else {
        this.lastVolume = parseFloat(masterVolume.value) || 0.8;
        masterVolume.value = 0;
        this.setMasterVolume(0);
      }
    }

    async renderMix(targetSampleRate = 44100) {
      if (this.sessionDuration <= 0) {
        throw new Error("Session duration is 0 seconds.");
      }

      this.initContext();
      const sr = this.audioCtx ? this.audioCtx.sampleRate : targetSampleRate;
      const totalFrames = Math.max(1, Math.ceil(this.sessionDuration * sr));

      const OfflineCtxClass = window.OfflineAudioContext || window.webkitOfflineAudioContext;
      const offlineCtx = new OfflineCtxClass(2, totalFrames, sr);

      const masterGain = offlineCtx.createGain();
      const vol = parseFloat(masterVolume.value) || 0.8;
      masterGain.gain.setValueAtTime(this.isMasterMuted ? 0.0 : vol, 0);
      masterGain.connect(offlineCtx.destination);

      const trackGains = new Map();

      for (const ev of this.events) {
        if (!trackGains.has(ev.track)) {
          const gain = offlineCtx.createGain();
          const shouldMute = this.shouldMuteTrack(ev.track);
          gain.gain.setValueAtTime(shouldMute ? 0.0 : 1.0, 0);
          gain.connect(masterGain);
          trackGains.set(ev.track, gain);
        }
      }

      let scheduledCount = 0;
      for (const ev of this.events) {
        let buffer = this.audioBuffers.get((ev.soundfile_name || '').toLowerCase());
        if (!buffer && ev.soundfile_name) {
          for (const v of getFilenameVariants(ev.soundfile_name)) {
            buffer = this.audioBuffers.get(v.toLowerCase());
            if (buffer) break;
          }
        }
        if (!buffer) continue;

        const gainNode = trackGains.get(ev.track);
        if (!gainNode) continue;

        const source = offlineCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(gainNode);

        const start = Math.max(0, ev.start_seconds);
        const rawOffset = Math.max(0, ev.source_in_seconds || 0);
        if (rawOffset >= buffer.duration) continue;
        const safeOffset = rawOffset;
        const maxAvail = Math.max(0, buffer.duration - safeOffset);
        const safeDur = Math.min(ev.duration_seconds, maxAvail);
        if (safeDur <= 0) continue;

        source.start(start, safeOffset, safeDur);
        scheduledCount++;
      }

      if (scheduledCount === 0) {
        throw new Error("No audio files are loaded to render the mix. Please load your audio WAV files first.");
      }

      return await offlineCtx.startRendering();
    }
  }

  const player = new MultitrackPlayer();

  // =========================================================================
  // Audio Mixdown & WAV Encoding
  // =========================================================================
  function audioBufferToWav(buffer) {
    const numChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const format = 1; // 1 = PCM
    const bitDepth = 16;

    let interleaved;
    if (numChannels === 2) {
      const ch0 = buffer.getChannelData(0);
      const ch1 = buffer.getChannelData(1);
      interleaved = new Float32Array(ch0.length + ch1.length);
      let idx = 0;
      for (let i = 0; i < ch0.length; i++) {
        interleaved[idx++] = ch0[i];
        interleaved[idx++] = ch1[i];
      }
    } else {
      interleaved = buffer.getChannelData(0);
    }

    const bytesPerSample = bitDepth / 8;
    const blockAlign = numChannels * bytesPerSample;
    const dataByteCount = interleaved.length * bytesPerSample;
    const arrayBuffer = new ArrayBuffer(44 + dataByteCount);
    const view = new DataView(arrayBuffer);

    // RIFF header
    writeAscii(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataByteCount, true);
    writeAscii(view, 8, 'WAVE');

    // fmt sub-chunk
    writeAscii(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, format, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitDepth, true);

    // data sub-chunk
    writeAscii(view, 36, 'data');
    view.setUint32(40, dataByteCount, true);

    // 16-bit PCM samples
    let offset = 44;
    for (let i = 0; i < interleaved.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, interleaved[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return new Blob([view], { type: 'audio/wav' });
  }

  function writeAscii(view, offset, str) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  async function exportMix(format = 'wav', triggerBtn = null) {
    if (!currentSessionData) {
      alert('Please convert a session first.');
      return;
    }

    const origHtml = triggerBtn ? triggerBtn.innerHTML : null;
    try {
      if (triggerBtn) {
        triggerBtn.disabled = true;
        triggerBtn.innerHTML = `
          <svg class="spin-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="2" x2="12" y2="6"/>
            <line x1="12" y1="18" x2="12" y2="22"/>
            <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/>
            <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/>
            <line x1="2" y1="12" x2="6" y2="12"/>
            <line x1="18" y1="12" x2="22" y2="12"/>
            <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/>
            <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/>
          </svg>
          Rendering...
        `;
      }

      const renderedBuffer = await player.renderMix();
      const wavBlob = audioBufferToWav(renderedBuffer);
      const sessionBase = (currentSessionData.session_name || 'session').replace(/\.[^/.]+$/, '');
      const outName = `${sessionBase}_mix.${format}`;

      if (format === 'wav') {
        const url = URL.createObjectURL(wavBlob);
        const a = document.createElement('a');
        a.href = url;
        a.download = outName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      } else if (format === 'mp3') {
        const resp = await fetch(`/api/mix/mp3?name=${encodeURIComponent(sessionBase)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'audio/wav' },
          body: wavBlob,
        });

        if (resp.ok) {
          const mp3Blob = await resp.blob();
          const url = URL.createObjectURL(mp3Blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = outName;
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(() => URL.revokeObjectURL(url), 10000);
        } else {
          const err = await resp.json().catch(() => ({ error: resp.statusText }));
          alert(`MP3 encoding not available (${err.error || resp.statusText}).\nDownloading as WAV instead.`);
          const url = URL.createObjectURL(wavBlob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `${sessionBase}_mix.wav`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(() => URL.revokeObjectURL(url), 10000);
        }
      }
    } catch (err) {
      console.error('Export mix failed:', err);
      alert(`Export mix failed: ${err.message}`);
    } finally {
      if (triggerBtn) {
        triggerBtn.disabled = false;
        triggerBtn.innerHTML = origHtml;
      }
    }
  }

  // =========================================================================
  // Drag and Drop Event Listeners
  // =========================================================================
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    window.addEventListener(eventName, preventDefaults, false);
    dropZone.addEventListener(eventName, preventDefaults, false);
  });

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.add('drag-over'), false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.remove('drag-over'), false);
  });

  // Handle Drop on Main Drop Zone
  dropZone.addEventListener('drop', async (e) => {
    const dt = e.dataTransfer;
    if (dt.items) {
      const files = await getAllFilesFromDataTransfer(dt.items);
      handleAddedFiles(files);
    } else if (dt.files) {
      handleAddedFiles(Array.from(dt.files));
    }
  });

  // Handle Drag & Drop directly onto active Results Timeline for instant audio loading
  window.addEventListener('drop', async (e) => {
    if (resultsSection.style.display === 'block') {
      const dt = e.dataTransfer;
      let files = [];
      if (dt.items) {
        files = await getAllFilesFromDataTransfer(dt.items);
      } else if (dt.files) {
        files = Array.from(dt.files);
      }
      if (files.length > 0) {
        loadExtraAudioFiles(files);
      }
    }
  });

  async function getAllFilesFromDataTransfer(items) {
    const files = [];
    const queue = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry ? items[i].webkitGetAsEntry() : null;
      if (entry) {
        queue.push(traverseFileTree(entry));
      } else {
        const file = items[i].getAsFile();
        if (file) files.push(file);
      }
    }
    const results = await Promise.all(queue);
    results.forEach(arr => files.push(...arr));
    return files;
  }

  function traverseFileTree(item) {
    return new Promise((resolve) => {
      if (item.isFile) {
        item.file(f => resolve([f]));
      } else if (item.isDirectory) {
        const dirReader = item.createReader();
        const dirFiles = [];
        const readEntries = () => {
          dirReader.readEntries(async (entries) => {
            if (entries.length === 0) {
              resolve(dirFiles);
            } else {
              for (const entry of entries) {
                const subFiles = await traverseFileTree(entry);
                dirFiles.push(...subFiles);
              }
              readEntries();
            }
          });
        };
        readEntries();
      } else {
        resolve([]);
      }
    });
  }

  // Handle File Input Selection
  fileInput.addEventListener('change', (e) => {
    handleAddedFiles(Array.from(e.target.files));
    fileInput.value = '';
  });

  folderInput.addEventListener('change', (e) => {
    handleAddedFiles(Array.from(e.target.files));
    folderInput.value = '';
  });

  clearFilesBtn.addEventListener('click', () => {
    stagedFiles = [];
    renderStagedFiles();
  });

  function handleAddedFiles(files) {
    if (!files || files.length === 0) return;
    const allowed = ['edl', 'ed0', 'wav', 'aif', 'aiff'];
    files.forEach(f => {
      const ext = f.name.split('.').pop().toLowerCase();
      if (allowed.includes(ext)) {
        if (!stagedFiles.some(sf => sf.name.toLowerCase() === f.name.toLowerCase() && sf.size === f.size)) {
          stagedFiles.push(f);
        }
      }
    });
    renderStagedFiles();
  }

  function renderStagedFiles() {
    fileChipGrid.innerHTML = '';
    fileCountSpan.textContent = stagedFiles.length;

    if (stagedFiles.length === 0) {
      stagingPanel.style.display = 'none';
      return;
    }

    stagingPanel.style.display = 'block';

    stagedFiles.forEach((f, idx) => {
      const ext = f.name.split('.').pop().toLowerCase();
      const isSession = ['edl', 'ed0'].includes(ext);
      const isAudio = ['wav', 'aif', 'aiff'].includes(ext);

      const chip = document.createElement('div');
      chip.className = `file-chip ${isSession ? 'session-chip' : (isAudio ? 'audio-chip' : '')}`;

      const icon = isSession
        ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'
        : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';

      chip.innerHTML = `
        ${icon}
        <span>${escapeHtml(f.name)}</span>
        <span class="chip-remove" title="Remove">&times;</span>
      `;

      chip.querySelector('.chip-remove').addEventListener('click', (e) => {
        e.stopPropagation();
        stagedFiles.splice(idx, 1);
        renderStagedFiles();
      });

      fileChipGrid.appendChild(chip);
    });
  }

  // =========================================================================
  // Conversion Handler
  // =========================================================================
  convertBtn.addEventListener('click', async () => {
    if (stagedFiles.length === 0) {
      alert('Please stage at least one .EDL or .ED0 session file.');
      return;
    }

    const hasSession = stagedFiles.some(f => {
      const ext = f.name.split('.').pop().toLowerCase();
      return ['edl', 'ed0'].includes(ext);
    });

    if (!hasSession) {
      alert('Please include at least one .EDL or .ED0 file.');
      return;
    }

    const formData = new FormData();
    stagedFiles.forEach(file => {
      formData.append('files', file, file.name);
    });
    formData.append('fps', fpsSelect.value);
    formData.append('drop_frame', dropFrameCheckbox.checked ? 'true' : 'false');
    formData.append('embed_audio', embedAudioCheckbox.checked ? 'true' : 'false');

    dropSection.style.display = 'none';
    heroSection.style.display = 'none';
    loadingSection.style.display = 'block';

    try {
      const response = await fetch('/api/convert', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Server conversion failed');
      }

      currentSessionData = data;
      renderResults(data);
    } catch (err) {
      alert(`Conversion Error: ${err.message}`);
      loadingSection.style.display = 'none';
      dropSection.style.display = 'block';
      heroSection.style.display = 'block';
    }
  });

  // =========================================================================
  // Render Results Dashboard
  // =========================================================================
  function renderResults(data) {
    loadingSection.style.display = 'none';
    resultsSection.style.display = 'block';

    // Header & Metrics
    resSessionName.textContent = data.session_name;
    metricSampleRate.textContent = `${Number(data.sample_rate).toLocaleString()} Hz`;
    metricMagic.textContent = data.magic || 'SAW32';
    metricTracks.textContent = `${data.active_tracks} Tracks`;
    metricPlacements.textContent = `${data.total_placements} Events`;

    const durSec = data.total_duration_seconds || 0;
    metricDuration.textContent = formatTime(durSec);
    displayTotalTime.textContent = formatTime(durSec);
    displayCurrentTime.textContent = '00:00.00';
    displayCurrentSmpte.textContent = '00:00:00:00';

    // Setup player state
    player.stop();
    player.sessionDuration = durSec;
    player.events = data.events || [];
    player.fps = parseFloat(fpsSelect.value) || 30.0;
    player.trackGains.clear();
    player.trackMutes.clear();
    if (data.track_mutes) {
      for (const [trk, isMuted] of Object.entries(data.track_mutes)) {
        if (isMuted) {
          player.trackMutes.set(parseInt(trk, 10), true);
        }
      }
    }
    player.trackSolos.clear();
    if (data.track_solos) {
      for (const [trk, isSolo] of Object.entries(data.track_solos)) {
        if (isSolo) {
          player.trackSolos.set(parseInt(trk, 10), true);
        }
      }
    }

    // Downloads
    masterZipBtn.href = data.zip_download;
    masterZipBtn.setAttribute('download', `${data.session_name.replace(/\.[^/.]+$/, "")}_interchange.zip`);

    setDownloadButton(downloadBtnAaf, data.downloads, '.aaf');
    setDownloadButton(downloadBtnXml, data.downloads, '_cubase.xml');
    setDownloadButton(downloadBtnCsv, data.downloads, '.csv');
    setDownloadButton(downloadBtnCmx, data.downloads, '_cmx.edl');

    // Multi-Track Timeline
    renderTimeline(data);

    // Soundfiles Table
    soundfilesTableBody.innerHTML = '';
    soundfilesCount.textContent = data.soundfiles.length;
    data.soundfiles.forEach(sf => {
      const tr = document.createElement('tr');
      const statusBadge = sf.resolved 
        ? '<span class="status-badge status-resolved">RESOLVED</span>'
        : '<span class="status-badge status-missing">MISSING</span>';
      
      tr.innerHTML = `
        <td>#${sf.id}</td>
        <td><strong>${escapeHtml(sf.filename)}</strong></td>
        <td><small>${escapeHtml(sf.original_path || '-')}</small></td>
        <td>${statusBadge}</td>
        <td>${sf.resolved ? `${sf.channels}ch / ${sf.sample_rate}Hz` : '-'}</td>
        <td>${sf.resolved ? `${sf.duration_seconds}s` : '-'}</td>
      `;
      soundfilesTableBody.appendChild(tr);
    });

    // Regions Table
    regionsTableBody.innerHTML = '';
    regionsCount.textContent = data.regions.length;
    data.regions.forEach(reg => {
      const sf = data.soundfiles.find(s => s.id === reg.soundfile_id);
      const sfName = sf ? sf.filename : `SF#${reg.soundfile_id}`;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>#${reg.id}</td>
        <td>${escapeHtml(reg.name)}</td>
        <td>${escapeHtml(sfName)}</td>
        <td>${reg.start_sample.toLocaleString()}</td>
        <td>${reg.end_sample.toLocaleString()}</td>
        <td>${reg.length_samples.toLocaleString()}</td>
      `;
      regionsTableBody.appendChild(tr);
    });

    // Resolve & Load Audio into Web Audio Engine
    resolveAudioBuffers(data);
  }

  async function resolveAudioBuffers(data) {
    const needed = (data.soundfiles || []).map(sf => sf.filename);
    if (needed.length === 0) {
      setAudioStatus('ready', 'No audio tracks');
      return;
    }

    setAudioStatus('loading', `Loading audio files (0/${needed.length})...`);
    let loadedCount = 0;

    for (const filename of needed) {
      const lower = filename.toLowerCase();
      const variants = getFilenameVariants(filename).map(v => v.toLowerCase());

      // 1. Check if already decoded
      if (player.hasAudioFor(filename)) {
        loadedCount++;
        continue;
      }

      // 2. Check staged files in browser memory (instant client decode)
      const staged = stagedFiles.find(f => {
        const fLower = f.name.toLowerCase();
        return fLower === lower || variants.includes(fLower) || getFilenameVariants(f.name).some(v => variants.includes(v.toLowerCase()));
      });
      if (staged) {
        try {
          const ab = await staged.arrayBuffer();
          await player.decodeAudio(filename, ab);
          await player.decodeAudio(staged.name, ab);
          loadedCount++;
          setAudioStatus('loading', `Loading audio files (${loadedCount}/${needed.length})...`);
          continue;
        } catch (e) {
          console.warn('Failed decoding staged file:', staged.name, e);
        }
      }

      // 3. Check if server has it (direct or via transliterated variants)
      let serverUrl = null;
      if (data.audio_urls) {
        for (const v of variants) {
          if (data.audio_urls[v]) {
            serverUrl = data.audio_urls[v];
            break;
          }
        }
        if (!serverUrl) {
          for (const [k, u] of Object.entries(data.audio_urls)) {
            if (variants.includes(k.toLowerCase())) {
              serverUrl = u;
              break;
            }
          }
        }
      }

      if (serverUrl) {
        try {
          const resp = await fetch(serverUrl);
          if (resp.ok) {
            const ab = await resp.arrayBuffer();
            await player.decodeAudio(filename, ab);
            loadedCount++;
            setAudioStatus('loading', `Loading audio files (${loadedCount}/${needed.length})...`);
            continue;
          }
        } catch (e) {
          console.warn('Failed fetching audio from server:', serverUrl, e);
        }
      }
    }

    if (loadedCount === needed.length) {
      setAudioStatus('ready', `Audio Ready (${loadedCount}/${needed.length} tracks loaded)`);
      loadAudioFilesBtn.style.display = 'none';
    } else {
      setAudioStatus('warning', `Missing Audio (${loadedCount}/${needed.length} tracks loaded)`);
      loadAudioFilesBtn.style.display = 'inline-flex';
    }
  }

  function setAudioStatus(type, message) {
    audioStatusIndicator.className = 'status-indicator';
    if (type === 'ready') {
      audioStatusIndicator.classList.add('ready');
    } else if (type === 'warning') {
      audioStatusIndicator.classList.add('warning');
    }
    audioStatusText.textContent = message;
  }

  // Handle Load Audio Files button & Extra File Input
  loadAudioFilesBtn.addEventListener('click', () => {
    extraAudioInput.click();
  });

  extraAudioInput.addEventListener('change', (e) => {
    const files = Array.from(e.target.files);
    extraAudioInput.value = '';
    loadExtraAudioFiles(files);
  });

  async function loadExtraAudioFiles(files) {
    if (!files || files.length === 0 || !currentSessionData) return;
    for (const f of files) {
      const ext = f.name.split('.').pop().toLowerCase();
      if (['wav', 'aif', 'aiff'].includes(ext)) {
        try {
          const ab = await f.arrayBuffer();
          await player.decodeAudio(f.name, ab);
          stagedFiles.push(f);
        } catch (e) {
          console.warn('Error reading extra audio file:', f.name, e);
        }
      }
    }
    resolveAudioBuffers(currentSessionData);
  }

  function setDownloadButton(btn, downloads, extOrSuffix) {
    const key = Object.keys(downloads).find(k => k.endsWith(extOrSuffix));
    if (key && downloads[key]) {
      btn.href = downloads[key];
      btn.style.display = 'inline-flex';
      btn.setAttribute('download', key);
      btn.onclick = async (e) => {
        e.preventDefault();
        const origContent = btn.innerHTML;
        try {
          btn.style.opacity = '0.6';
          const resp = await fetch(btn.href);
          if (!resp.ok) {
            const err = await resp.json().catch(() => ({ error: resp.statusText }));
            alert(`Download failed: ${err.error || resp.statusText}`);
            return;
          }
          const blob = await resp.blob();
          const blobUrl = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = blobUrl;
          a.download = key;
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
        } catch (err) {
          alert(`Download error: ${err.message}`);
        } finally {
          btn.style.opacity = '1.0';
          btn.innerHTML = origContent;
        }
      };
    } else {
      btn.style.display = 'none';
      btn.onclick = null;
    }
  }

  // =========================================================================
  // Timeline Visualization & Interaction
  // =========================================================================
  function renderTimeline(data) {
    timelineRuler.innerHTML = '';
    timelineLanes.innerHTML = '';

    const totalSec = Math.max(data.total_duration_seconds, 1.0);
    const stepSec = totalSec > 120 ? 30 : (totalSec > 60 ? 15 : 10);

    // Ruler Ticks
    for (let t = 0; t <= totalSec + stepSec; t += stepSec) {
      const percent = (t / totalSec) * 100;
      if (percent > 100) break;
      const tick = document.createElement('div');
      tick.className = 'ruler-tick';
      tick.style.left = `${percent}%`;
      const m = Math.floor(t / 60);
      const s = Math.floor(t % 60);
      tick.textContent = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
      timelineRuler.appendChild(tick);
    }

    // Ruler click seeking
    timelineRuler.addEventListener('click', (e) => {
      const rect = timelineRuler.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const ratio = Math.max(0, Math.min(1, clickX / rect.width));
      player.seek(ratio * totalSec);
    });

    // Group events by track
    const tracksMap = {};
    for (let t = 1; t <= Math.max(data.active_tracks, 1); t++) {
      tracksMap[t] = [];
    }
    data.events.forEach(ev => {
      if (!tracksMap[ev.track]) tracksMap[ev.track] = [];
      tracksMap[ev.track].push(ev);
    });

    const activeTrackNumbers = Object.keys(tracksMap).map(Number).filter(t => tracksMap[t].length > 0);
    player.activeTracks = new Set(activeTrackNumbers);

    Object.keys(tracksMap).sort((a, b) => Number(a) - Number(b)).forEach(trackNumStr => {
      const trackNum = Number(trackNumStr);
      const events = tracksMap[trackNumStr];
      if (events.length === 0) return;

      // Pre-create gain node if context already active
      if (player.audioCtx) {
        player.getTrackGain(trackNum);
      }

      const lane = document.createElement('div');
      lane.className = 'timeline-lane';
      lane.setAttribute('data-track', trackNum);

      // Lane Header with Track title, Mute, and Solo
      const header = document.createElement('div');
      header.className = 'lane-header';

      const title = document.createElement('span');
      title.className = 'track-title';
      title.textContent = `Track ${trackNum.toString().padStart(2, '0')}`;
      header.appendChild(title);

      const msGroup = document.createElement('div');
      msGroup.className = 'track-ms-group';

      const muteBtn = document.createElement('button');
      muteBtn.className = 'btn-track-ms';
      muteBtn.textContent = 'M';
      muteBtn.title = 'Mute Track';
      if (player.trackMutes.get(trackNum)) {
        muteBtn.classList.add('mute-active');
      }
      muteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const active = !player.trackMutes.get(trackNum);
        player.trackMutes.set(trackNum, active);
        muteBtn.classList.toggle('mute-active', active);
        player.updateTrackGains();
      });

      const soloBtn = document.createElement('button');
      soloBtn.className = 'btn-track-ms';
      soloBtn.textContent = 'S';
      soloBtn.title = 'Solo Track';
      if (player.trackSolos.get(trackNum)) {
        soloBtn.classList.add('solo-active');
      }
      soloBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const active = !player.trackSolos.get(trackNum);
        player.trackSolos.set(trackNum, active);
        soloBtn.classList.toggle('solo-active', active);
        player.updateTrackGains();
      });

      msGroup.appendChild(muteBtn);
      msGroup.appendChild(soloBtn);
      header.appendChild(msGroup);
      lane.appendChild(header);

      const track = document.createElement('div');
      track.className = 'lane-track';

      // Click on track empty space to seek
      track.addEventListener('click', (e) => {
        if (e.target.closest('.timeline-clip')) return; // clip handled separately
        const rect = track.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, clickX / rect.width));
        player.seek(ratio * totalSec);
      });

      events.forEach(ev => {
        const leftPercent = Math.max(0, Math.min(100, (ev.start_seconds / totalSec) * 100));
        const widthPercent = Math.max(0.5, Math.min(100 - leftPercent, (ev.duration_seconds / totalSec) * 100));

        const clip = document.createElement('div');
        clip.className = 'timeline-clip';
        clip.style.left = `${leftPercent}%`;
        clip.style.width = `${widthPercent}%`;
        clip.title = `${ev.region_name} (${ev.soundfile_name})\nStart: ${ev.start_smpte} (${ev.start_seconds}s)\nDuration: ${ev.duration_seconds}s`;

        clip.innerHTML = `
          <span class="clip-name">${escapeHtml(ev.region_name)}</span>
          <span class="clip-dur">${ev.duration_seconds.toFixed(1)}s</span>
        `;

        // Click on clip to jump to its in-point
        clip.addEventListener('click', (e) => {
          e.stopPropagation();
          player.seek(ev.start_seconds);
        });

        track.appendChild(clip);
      });

      lane.appendChild(track);
      timelineLanes.appendChild(lane);
    });

    // Update track gain nodes and lane muted visual styles for initial project mutes
    player.updateTrackGains();
  }

  // =========================================================================
  // Transport Event Listeners
  // =========================================================================
  playPauseBtn.addEventListener('click', async () => {
    if (player.isPlaying) {
      player.pause();
    } else {
      await player.play();
    }
  });

  stopBtn.addEventListener('click', () => {
    player.stop();
  });

  masterVolume.addEventListener('input', (e) => {
    player.setMasterVolume(parseFloat(e.target.value));
  });

  volMuteBtn.addEventListener('click', () => {
    player.toggleMasterMute();
  });

  if (exportMixWavBtn) {
    exportMixWavBtn.addEventListener('click', (e) => exportMix('wav', e.currentTarget));
  }
  if (exportMixMp3Btn) {
    exportMixMp3Btn.addEventListener('click', (e) => exportMix('mp3', e.currentTarget));
  }
  if (downloadGridMixWavBtn) {
    downloadGridMixWavBtn.addEventListener('click', (e) => exportMix('wav', e.currentTarget));
  }
  if (downloadGridMixMp3Btn) {
    downloadGridMixMp3Btn.addEventListener('click', (e) => exportMix('mp3', e.currentTarget));
  }

  function updateVolumeIcon(muted) {
    if (muted) {
      volIcon.innerHTML = `
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
        <line x1="23" y1="9" x2="17" y2="15"/>
        <line x1="17" y1="9" x2="23" y2="15"/>
      `;
    } else {
      volIcon.innerHTML = `
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
        <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
      `;
    }
  }

  // Global Keyboard shortcut: Spacebar toggles Play/Pause
  window.addEventListener('keydown', async (e) => {
    if (e.code === 'Space') {
      const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
      if (['input', 'select', 'textarea'].includes(activeTag)) return;
      if (resultsSection.style.display === 'block') {
        e.preventDefault();
        if (player.isPlaying) {
          player.pause();
        } else {
          await player.play();
        }
      }
    }
  });

  // Reset to Upload another session
  convertAnotherBtn.addEventListener('click', () => {
    player.stop();
    resultsSection.style.display = 'none';
    heroSection.style.display = 'block';
    dropSection.style.display = 'block';
    stagedFiles = [];
    currentSessionData = null;
    renderStagedFiles();
  });

  // =========================================================================
  // Formatting Utilities
  // =========================================================================
  function formatTime(seconds) {
    if (isNaN(seconds) || seconds < 0) seconds = 0;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(2);
    return `${mins.toString().padStart(2, '0')}:${secs.padStart(5, '0')}`;
  }

  function formatSmpte(seconds, fps = 30.0) {
    if (isNaN(seconds) || seconds < 0) seconds = 0;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const f = Math.floor((seconds % 1) * fps);
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}:${f.toString().padStart(2, '0')}`;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
});
