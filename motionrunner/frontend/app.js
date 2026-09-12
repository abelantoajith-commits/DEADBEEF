/**
 * MotionRunner - Client Application Logic
 * Integrates live WebSocket pose telemetry, camera feed, and local High Scores
 */

(function () {
  'use strict';

  // ============================================================================
  // DOM ELEMENT REFERENCES
  // ============================================================================
  const serverStatusPill = document.getElementById('server-status-pill');
  const serverStatusText = document.getElementById('server-status-text');

  const webcamFeed = document.getElementById('webcam-feed');
  const camOverlayPlaceholder = document.getElementById('cam-overlay-placeholder');
  const camPlaceholderTitle = document.getElementById('cam-placeholder-title');
  const trackingBanner = document.getElementById('tracking-banner');
  const bannerIcon = document.getElementById('banner-icon');
  const bannerText = document.getElementById('banner-text');

  const calibBarWrap = document.getElementById('calib-bar-wrap');
  const calibPctText = document.getElementById('calib-pct-text');
  const calibFill = document.getElementById('calib-fill');

  const coordsText = document.getElementById('coords-text');
  const chipHKey = document.getElementById('chip-h-key');
  const valHKey = document.getElementById('val-h-key');
  const chipVKey = document.getElementById('chip-v-key');
  const valVKey = document.getElementById('val-v-key');
  const chipStatus = document.getElementById('chip-status');
  const valCalibStatus = document.getElementById('val-calib-status');

  const recalibrateBtn = document.getElementById('recalibrate-btn');
  const recalBtnIcon = document.getElementById('recal-btn-icon');

  const gameFrame = document.getElementById('game-frame');
  const gameViewport = document.getElementById('game-viewport');
  const focusGameBtn = document.getElementById('focus-game-btn');
  const fullscreenBtn = document.getElementById('fullscreen-btn');
  const floatingWebcam = document.getElementById('floating-webcam');
  const floatingCamImg = document.getElementById('floating-cam-img');
  const miniHChip = document.getElementById('mini-h-chip');
  const miniVChip = document.getElementById('mini-v-chip');
  const closeMiniHud = document.getElementById('close-mini-hud');

  const scoreForm = document.getElementById('score-form');
  const runnerNameInput = document.getElementById('runner-name');
  const runnerScoreInput = document.getElementById('runner-score');
  const scoresList = document.getElementById('scores-list');
  const clearScoresBtn = document.getElementById('clear-scores-btn');

  const btnLike = document.getElementById('btn-like');
  const likeCount = document.getElementById('like-count');
  const btnBookmark = document.getElementById('btn-bookmark');
  const bookmarkIcon = document.getElementById('bookmark-icon');

  // ============================================================================
  // WEBSOCKET & CAMERA VISION STREAMING
  // ============================================================================
  let socket = null;
  let reconnectTimer = null;
  let isConnected = false;
  let lastFrameTime = Date.now();
  let frameCount = 0;
  let fps = 0;
  const fpsCounter = document.getElementById('fps-counter');

  function getWsUrl() {
    const loc = window.location;
    if (loc.protocol === 'file:') {
      return 'ws://127.0.0.1:8000/ws';
    }
    const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = loc.host.includes(':') ? loc.host : `${loc.hostname}:8000`;
    return `${wsProto}//${host}/ws`;
  }

  function getApiBaseUrl() {
    const loc = window.location;
    if (loc.protocol === 'file:') {
      return 'http://127.0.0.1:8000';
    }
    return `${loc.protocol}//${loc.host.includes(':') ? loc.host : `${loc.hostname}:8000`}`;
  }

  function connectWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const wsUrl = getWsUrl();
    console.log(`[MotionRunner] Connecting to WebSocket: ${wsUrl}`);

    try {
      socket = new WebSocket(wsUrl);
    } catch (e) {
      console.warn('[MotionRunner] WebSocket connection error:', e);
      handleDisconnect();
      return;
    }

    socket.onopen = function () {
      console.log('[MotionRunner] Connected to backend vision stream.');
      isConnected = true;
      if (serverStatusPill) {
        serverStatusPill.className = 'connection-status-pill connected';
        serverStatusText.textContent = 'Vision Online';
      }
      if (camOverlayPlaceholder) {
        camOverlayPlaceholder.style.display = 'none';
      }
    };

    socket.onmessage = function (event) {
      try {
        const data = JSON.parse(event.data);
        handleTelemetryMessage(data);
      } catch (err) {
        console.error('[MotionRunner] Message parse error:', err);
      }
    };

    socket.onclose = function () {
      console.warn('[MotionRunner] WebSocket connection closed.');
      handleDisconnect();
    };

    socket.onerror = function (err) {
      console.warn('[MotionRunner] WebSocket encountered error:', err);
      handleDisconnect();
    };
  }

  function handleDisconnect() {
    isConnected = false;
    if (serverStatusPill) {
      serverStatusPill.className = 'connection-status-pill error';
      serverStatusText.textContent = 'Vision Offline';
    }
    if (camOverlayPlaceholder) {
      camOverlayPlaceholder.style.display = 'flex';
      camPlaceholderTitle.textContent = 'Vision Engine Disconnected';
    }
    if (trackingBanner) {
      trackingBanner.style.display = 'none';
    }
    if (calibBarWrap) {
      calibBarWrap.style.display = 'none';
    }

    // Reset status chips
    updateChips('none', 'none', false, false, 0, 60, 0, 0);

    // Schedule auto reconnect
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectWebSocket();
      }, 2500);
    }
  }

  // ============================================================================
  // TELEMETRY & FRAME RENDERING
  // ============================================================================
  function handleTelemetryMessage(data) {
    // 1. Render Video Frame
    if (data.frame) {
      webcamFeed.src = data.frame;
      if (floatingCamImg && floatingWebcam.style.display !== 'none') {
        floatingCamImg.src = data.frame;
      }
      if (camOverlayPlaceholder && camOverlayPlaceholder.style.display !== 'none') {
        camOverlayPlaceholder.style.display = 'none';
      }

      // Calculate FPS
      frameCount++;
      const now = Date.now();
      if (now - lastFrameTime >= 1000) {
        fps = frameCount;
        frameCount = 0;
        lastFrameTime = now;
        if (fpsCounter) {
          fpsCounter.textContent = `${fps} FPS`;
        }
      }
    }

    // 2. Extract Gesture States
    const hState = data.h_state || 'none';
    const vState = data.v_state || 'none';
    const isJumping = data.is_jumping || false;
    const isCalibrated = data.calibrated || false;
    const poseDetected = data.pose_detected !== false;
    const calibProgress = data.calib_progress || 0;
    const calibTotal = data.calib_total || 60;
    const dx = data.dx || 0.0;
    const dy = data.dy || 0.0;

    // Bridge synthetic DOM keys to same-origin iframe if active
    if (hState !== lastHState) {
      if (lastHState === 'left') bridgeSyntheticKeyEvent(37, 'ArrowLeft', false);
      if (lastHState === 'right') bridgeSyntheticKeyEvent(39, 'ArrowRight', false);
      if (hState === 'left') bridgeSyntheticKeyEvent(37, 'ArrowLeft', true);
      if (hState === 'right') bridgeSyntheticKeyEvent(39, 'ArrowRight', true);
      lastHState = hState;
    }

    if (isJumping !== lastIsJumping) {
      bridgeSyntheticKeyEvent(38, 'ArrowUp', isJumping);
      lastIsJumping = isJumping;
    }

    if (vState !== lastVState) {
      if (lastVState === 'down') bridgeSyntheticKeyEvent(40, 'ArrowDown', false);
      if (vState === 'down') bridgeSyntheticKeyEvent(40, 'ArrowDown', true);
      lastVState = vState;
    }

    updateChips(hState, vState, isJumping, isCalibrated, calibProgress, calibTotal, dx, dy, poseDetected);
  }

  let lastHState = 'none';
  let lastVState = 'none';
  let lastIsJumping = false;

  function updateChips(hState, vState, isJumping, isCalibrated, calibProgress, calibTotal, dx, dy, poseDetected) {
    // Coordinate readout
    if (coordsText) {
      coordsText.textContent = `dx: ${dx >= 0 ? '+' : ''}${dx.toFixed(2)} | dy: ${dy >= 0 ? '+' : ''}${dy.toFixed(2)}`;
    }

    // Horizontal Chip
    if (chipHKey && valHKey) {
      const isLeft = hState.toLowerCase() === 'left';
      const isRight = hState.toLowerCase() === 'right';
      valHKey.textContent = isLeft ? 'LEFT' : isRight ? 'RIGHT' : 'NONE';
      chipHKey.className = (isLeft || isRight) ? 'telemetry-chip active' : 'telemetry-chip';
      if (miniHChip) {
        miniHChip.textContent = `H: ${valHKey.textContent}`;
        miniHChip.className = (isLeft || isRight) ? 'mini-chip active' : 'mini-chip';
      }
    }

    // Vertical Chip
    if (chipVKey && valVKey) {
      if (isJumping) {
        valVKey.textContent = 'JUMP';
        chipVKey.className = 'telemetry-chip jump-active';
      } else if (vState.toLowerCase() === 'down') {
        valVKey.textContent = 'DUCK';
        chipVKey.className = 'telemetry-chip active';
      } else {
        valVKey.textContent = 'NONE';
        chipVKey.className = 'telemetry-chip';
      }
      if (miniVChip) {
        miniVChip.textContent = `V: ${valVKey.textContent}`;
        miniVChip.className = (isJumping || vState.toLowerCase() === 'down') ? 'mini-chip active' : 'mini-chip';
      }
    }

    // Calibration & Pose Status Banner / Chip
    if (chipStatus && valCalibStatus) {
      if (!poseDetected) {
        valCalibStatus.textContent = 'NO BODY';
        chipStatus.className = 'telemetry-chip';
        if (trackingBanner) {
          trackingBanner.style.display = 'flex';
          trackingBanner.className = 'tracking-hud-banner alert';
          bannerIcon.textContent = 'warning';
          bannerText.textContent = 'No Body Detected';
        }
        if (calibBarWrap) calibBarWrap.style.display = 'none';
      } else if (!isCalibrated) {
        const pct = Math.min(100, Math.round((calibProgress / calibTotal) * 100));
        valCalibStatus.textContent = `CALIB ${pct}%`;
        chipStatus.className = 'telemetry-chip';

        if (trackingBanner) {
          trackingBanner.style.display = 'flex';
          trackingBanner.className = 'tracking-hud-banner';
          bannerIcon.textContent = 'sync';
          bannerText.textContent = `Calibrating (${calibProgress}/${calibTotal})...`;
        }
        if (calibBarWrap) {
          calibBarWrap.style.display = 'flex';
          calibPctText.textContent = `${pct}%`;
          calibFill.style.width = `${pct}%`;
        }
      } else {
        valCalibStatus.textContent = 'CALIBRATED';
        chipStatus.className = 'telemetry-chip active';
        if (trackingBanner) trackingBanner.style.display = 'none';
        if (calibBarWrap) calibBarWrap.style.display = 'none';
      }
    }
  }

  // ============================================================================
  // RECALIBRATE ACTION
  // ============================================================================
  async function triggerRecalibrate() {
    if (recalBtnIcon) {
      recalBtnIcon.style.transform = 'rotate(360deg)';
      recalBtnIcon.style.transition = 'transform 0.6s ease';
      setTimeout(() => {
        recalBtnIcon.style.transform = 'none';
        recalBtnIcon.style.transition = 'none';
      }, 600);
    }

    // Send via WebSocket if open
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ action: 'recalibrate' }));
    }

    // Also trigger via REST endpoint
    try {
      await fetch(`${getApiBaseUrl()}/recalibrate`, { method: 'POST' });
      console.log('[MotionRunner] Recalibration endpoint called.');
    } catch (err) {
      console.warn('[MotionRunner] Recalibrate HTTP request error:', err);
    }
  }

  if (recalibrateBtn) {
    recalibrateBtn.addEventListener('click', triggerRecalibrate);
  }

  // ============================================================================
  // GAME FOCUS, SOURCE SWITCHING & FULLSCREEN
  // ============================================================================
  const clickFocusOverlay = document.getElementById('click-focus-overlay');
  const gameSourceSelect = document.getElementById('game-source-select');

  function focusGame() {
    if (clickFocusOverlay) {
      clickFocusOverlay.classList.add('dismissed');
    }
    if (gameFrame) {
      gameFrame.focus();
      try {
        gameFrame.contentWindow.focus();
      } catch (e) {}
    }
  }

  if (clickFocusOverlay) {
    clickFocusOverlay.addEventListener('click', focusGame);
  }

  if (focusGameBtn) {
    focusGameBtn.addEventListener('click', focusGame);
  }

  if (gameSourceSelect) {
    gameSourceSelect.addEventListener('change', (e) => {
      const newUrl = e.target.value;
      if (gameFrame) {
        gameFrame.src = newUrl;
        if (clickFocusOverlay) {
          clickFocusOverlay.classList.remove('dismissed');
        }
      }
    });
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      if (gameViewport.requestFullscreen) {
        gameViewport.requestFullscreen().then(() => {
          floatingWebcam.style.display = 'flex';
          focusGame();
        }).catch(err => console.error(err));
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen().then(() => {
          floatingWebcam.style.display = 'none';
        }).catch(err => console.error(err));
      }
    }
  }

  if (fullscreenBtn) {
    fullscreenBtn.addEventListener('click', toggleFullscreen);
  }

  const btnActionFullscreen = document.getElementById('btn-action-fullscreen');
  if (btnActionFullscreen) {
    btnActionFullscreen.addEventListener('click', toggleFullscreen);
  }

  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement) {
      floatingWebcam.style.display = 'none';
    }
  });

  if (closeMiniHud) {
    closeMiniHud.addEventListener('click', () => {
      floatingWebcam.style.display = 'none';
    });
  }

  // Same-origin iframe synthetic event bridge for ultra-low latency direct control
  function bridgeSyntheticKeyEvent(keyCode, keyName, isDown) {
    if (!gameFrame || !gameFrame.src.includes('/game/index.html')) return;
    try {
      const doc = gameFrame.contentDocument || gameFrame.contentWindow?.document;
      if (doc) {
        const evt = new KeyboardEvent(isDown ? 'keydown' : 'keyup', {
          keyCode: keyCode,
          which: keyCode,
          key: keyName,
          code: keyName,
          bubbles: true,
          cancelable: true
        });
        doc.dispatchEvent(evt);
      }
    } catch (e) {}
  }

  // ============================================================================
  // HIGH SCORES MANAGEMENT (localStorage + Descending Order + Top 3 Styling)
  // ============================================================================
  const STORAGE_KEY = 'motionrunner_scores';

  const defaultScores = [
    { id: '1', name: 'CyberDash', score: 42800, date: new Date(Date.now() - 1000 * 60 * 15).toISOString() },
    { id: '2', name: 'NeonRider', score: 38240, date: new Date(Date.now() - 1000 * 60 * 85).toISOString() },
    { id: '3', name: 'Valkyrie', score: 29500, date: new Date(Date.now() - 1000 * 60 * 360).toISOString() },
    { id: '4', name: 'TrackRunner', score: 21900, date: new Date(Date.now() - 1000 * 60 * 1440).toISOString() },
    { id: '5', name: 'SurferX', score: 16400, date: new Date(Date.now() - 1000 * 60 * 2880).toISOString() },
  ];

  function loadScores() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        saveScores(defaultScores);
        return defaultScores;
      }
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed.sort((a, b) => b.score - a.score);
      }
      return defaultScores;
    } catch (e) {
      console.warn('[MotionRunner] Error loading scores from localStorage:', e);
      return defaultScores;
    }
  }

  function saveScores(scores) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(scores));
    } catch (e) {
      console.warn('[MotionRunner] Error saving scores to localStorage:', e);
    }
  }

  function formatRelativeDate(isoStr) {
    if (!isoStr) return '1m';
    const date = new Date(isoStr);
    const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diffSec < 60) return 'Just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h`;
    return `${Math.floor(diffSec / 86400)}d`;
  }

  function renderLeaderboard() {
    const scores = loadScores();
    scoresList.innerHTML = '';

    if (!scores || scores.length === 0) {
      scoresList.innerHTML = '<div class="empty-scores">No runs recorded yet. Complete a run and submit!</div>';
      return;
    }

    scores.forEach((entry, idx) => {
      const rank = idx + 1;
      const rankClass = rank === 1 ? 'rank-1' : rank === 2 ? 'rank-2' : rank === 3 ? 'rank-3' : '';
      const formattedScore = Number(entry.score).toLocaleString();
      const timeStr = formatRelativeDate(entry.date);

      const row = document.createElement('div');
      row.className = `score-row ${rankClass}`;
      row.innerHTML = `
        <div class="row-left">
          <div class="rank-badge">${rank}</div>
          <span class="player-name">${escapeHtml(entry.name)}</span>
        </div>
        <div class="row-right">
          <span class="player-score">${formattedScore}</span>
          <span class="score-date">${timeStr}</span>
        </div>
      `;
      scoresList.appendChild(row);
    });
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }

  if (scoreForm) {
    scoreForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const name = runnerNameInput.value.trim();
      const scoreNum = parseInt(runnerScoreInput.value, 10);

      if (!name) {
        alert('Please enter a runner name.');
        return;
      }
      if (isNaN(scoreNum) || scoreNum <= 0) {
        alert('Please enter a valid positive numeric score.');
        return;
      }

      const newEntry = {
        id: 'run_' + Date.now() + '_' + Math.random().toString(36).substring(2, 6),
        name: name,
        score: scoreNum,
        date: new Date().toISOString()
      };

      const currentScores = loadScores();
      currentScores.push(newEntry);
      currentScores.sort((a, b) => b.score - a.score);

      // Keep top 50
      const trimmed = currentScores.slice(0, 50);
      saveScores(trimmed);
      renderLeaderboard();

      // Reset score input
      runnerScoreInput.value = '';
    });
  }

  if (clearScoresBtn) {
    clearScoresBtn.addEventListener('click', () => {
      if (confirm('Reset high scores leaderboard?')) {
        saveScores(defaultScores);
        renderLeaderboard();
      }
    });
  }

  // ============================================================================
  // SOCIAL & INTERACTION BUTTONS
  // ============================================================================
  let liked = false;
  if (btnLike) {
    btnLike.addEventListener('click', () => {
      liked = !liked;
      btnLike.classList.toggle('active', liked);
      if (likeCount) {
        likeCount.textContent = liked ? '1.5K' : '1.4K';
      }
    });
  }

  let bookmarked = false;
  if (btnBookmark) {
    btnBookmark.addEventListener('click', () => {
      bookmarked = !bookmarked;
      btnBookmark.classList.toggle('active', bookmarked);
      if (bookmarkIcon) {
        bookmarkIcon.textContent = bookmarked ? 'bookmark' : 'bookmark_border';
      }
    });
  }

  // ============================================================================
  // INITIALIZATION
  // ============================================================================
  renderLeaderboard();
  connectWebSocket();

  // Focus game iframe once loaded
  if (gameFrame) {
    gameFrame.addEventListener('load', () => {
      console.log('[MotionRunner] Game iframe loaded successfully.');
    });
  }
})();
