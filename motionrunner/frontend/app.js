/**
 * MotionRunner - Client Application Logic
 * Integrates live WebSocket pose telemetry, camera feed, sensitivity tuning, and High Scores
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

  const tuningToggleBtn = document.getElementById('tuning-toggle-btn');
  const tuningDrawer = document.getElementById('tuning-drawer');
  const tuningChevron = document.getElementById('tuning-chevron');
  const sliderXSens = document.getElementById('slider-x-sens');
  const valXSens = document.getElementById('val-x-sens');
  const sliderYSens = document.getElementById('slider-y-sens');
  const valYSens = document.getElementById('val-y-sens');
  const sliderSmooth = document.getElementById('slider-smooth');
  const valSmooth = document.getElementById('val-smooth');
  const btnResetTuning = document.getElementById('btn-reset-tuning');

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
  let localCameraReady = false;
  let localCameraStream = null;
  let browserPose = null;
  let browserPoseBusy = false;
  let browserTrackingEnabled = true;
  let browserBaselineX = null;
  let browserBaselineY = null;
  let browserCalibrationX = [];
  let browserCalibrationY = [];
  let browserSmoothedX = null;
  let browserSmoothedY = null;
  let browserPreviousY = null;
  let browserHorizontalState = 'none';
  let browserVerticalState = 'none';
  let browserLastJump = 0;
  let browserJumpUntil = 0;
  let lastFrameTime = Date.now();
  let frameCount = 0;
  let fps = 0;

  function getWsUrl() {
    const loc = window.location;
    if (loc.protocol === 'file:') {
      return 'ws://127.0.0.1:8000/ws';
    }
    const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProto}//${loc.host}/ws`;
  }

  function getApiBaseUrl() {
    const loc = window.location;
    if (loc.protocol === 'file:') {
      return 'http://127.0.0.1:8000';
    }
    return loc.origin;
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
      browserTrackingEnabled = false;
      if (serverStatusPill) {
        serverStatusPill.className = 'connection-status-pill connected';
        serverStatusText.textContent = 'Vision Online';
      }
      if (camOverlayPlaceholder) {
        camOverlayPlaceholder.style.display = 'none';
      }
      // Send current sensitivity settings
      syncSensitivity();
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
    browserTrackingEnabled = true;
    if (serverStatusPill) {
      serverStatusPill.className = `connection-status-pill ${localCameraReady ? 'connected' : 'error'}`;
      serverStatusText.textContent = localCameraReady ? 'Camera Ready' : 'Vision Offline';
    }
    if (camOverlayPlaceholder && !localCameraReady) {
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
    updateChips('none', 'none', false, false, 0, 40, 0, 0);

    // Schedule auto reconnect
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectWebSocket();
      }, 2000);
    }
  }

  async function startBrowserCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (camPlaceholderTitle) camPlaceholderTitle.textContent = 'Camera API unavailable';
      return;
    }

    try {
      localCameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user' },
        audio: false,
      });
      localCameraReady = true;
      if (webcamFeed) webcamFeed.srcObject = localCameraStream;
      if (floatingCamImg) floatingCamImg.srcObject = localCameraStream;
      await webcamFeed.play();
      startBrowserPose();
      if (camOverlayPlaceholder) camOverlayPlaceholder.style.display = 'none';
      if (serverStatusPill && !isConnected) {
        serverStatusPill.className = 'connection-status-pill connected';
        serverStatusText.textContent = 'Camera Ready';
      }
    } catch (error) {
      localCameraReady = false;
      if (camPlaceholderTitle) camPlaceholderTitle.textContent = 'Camera access required';
      const placeholderDesc = document.getElementById('cam-placeholder-desc');
      if (placeholderDesc) placeholderDesc.textContent = 'Allow camera permission in your browser and reload this page.';
      console.warn('[MotionRunner] Browser camera access failed:', error);
    }
  }

  function resetBrowserCalibration() {
    browserBaselineX = null;
    browserBaselineY = null;
    browserCalibrationX = [];
    browserCalibrationY = [];
    browserSmoothedX = null;
    browserSmoothedY = null;
    browserPreviousY = null;
    browserHorizontalState = 'none';
    browserVerticalState = 'none';
    browserLastJump = 0;
    browserJumpUntil = 0;
  }

  function startBrowserPose() {
    if (!window.Pose || !webcamFeed) {
      if (camPlaceholderTitle) camPlaceholderTitle.textContent = 'Pose engine unavailable';
      return;
    }

    browserPose = new window.Pose({
      locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/pose/${file}`,
    });
    browserPose.setOptions({
      modelComplexity: 1,
      smoothLandmarks: true,
      enableSegmentation: false,
      minDetectionConfidence: 0.6,
      minTrackingConfidence: 0.6,
    });
    browserPose.onResults(handleBrowserPoseResults);
    resetBrowserCalibration();
    runBrowserPoseFrame();
  }

  async function runBrowserPoseFrame() {
    if (!browserPose || !localCameraReady) return;
    if (!browserPoseBusy && webcamFeed.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      browserPoseBusy = true;
      try {
        await browserPose.send({ image: webcamFeed });
      } catch (error) {
        console.warn('[MotionRunner] Browser pose frame failed:', error);
      } finally {
        browserPoseBusy = false;
      }
    }
    window.requestAnimationFrame(runBrowserPoseFrame);
  }

  function handleBrowserPoseResults(results) {
    if (!browserTrackingEnabled) return;

    const landmarks = results.poseLandmarks;
    const requiredLandmarks = landmarks && [11, 12, 23, 24].every(
      (index) => landmarks[index] && (landmarks[index].visibility || 0) >= 0.45,
    );
    if (!requiredLandmarks) {
      handleTelemetryMessage({ pose_detected: false, calibrated: false });
      return;
    }

    const centerX = (landmarks[11].x + landmarks[12].x + landmarks[23].x + landmarks[24].x) / 4;
    const shoulderY = (landmarks[11].y + landmarks[12].y) / 2;
    const calibrationTotal = 40;

    if (browserBaselineX === null) {
      browserCalibrationX.push(centerX);
      browserCalibrationY.push(shoulderY);
      if (browserCalibrationX.length >= calibrationTotal) {
        browserBaselineX = browserCalibrationX.reduce((sum, value) => sum + value, 0) / calibrationTotal;
        browserBaselineY = browserCalibrationY.reduce((sum, value) => sum + value, 0) / calibrationTotal;
        browserSmoothedX = browserBaselineX;
        browserSmoothedY = browserBaselineY;
        browserPreviousY = browserBaselineY;
      }
      handleTelemetryMessage({
        h_state: 'none',
        v_state: 'none',
        pose_detected: true,
        calibrated: false,
        calib_progress: browserCalibrationX.length,
        calib_total: calibrationTotal,
      });
      return;
    }

    const smoothing = parseFloat(sliderSmooth ? sliderSmooth.value : 0.60);
    browserSmoothedX = smoothing * centerX + (1 - smoothing) * browserSmoothedX;
    browserSmoothedY = smoothing * shoulderY + (1 - smoothing) * browserSmoothedY;
    const dx = browserSmoothedX - browserBaselineX;
    const dy = browserSmoothedY - browserBaselineY;
    const velocityY = browserSmoothedY - browserPreviousY;
    browserPreviousY = browserSmoothedY;

    const xThreshold = parseFloat(sliderXSens ? sliderXSens.value : 0.030);
    const yThreshold = parseFloat(sliderYSens ? sliderYSens.value : 0.025);
    const xReleaseThreshold = xThreshold * 0.5;
    const yReleaseThreshold = yThreshold * 0.5;

    if (browserHorizontalState === 'none') {
      if (dx < -xThreshold) browserHorizontalState = 'left';
      if (dx > xThreshold) browserHorizontalState = 'right';
    } else if (Math.abs(dx) < xReleaseThreshold) {
      browserHorizontalState = 'none';
    }

    if (browserVerticalState === 'none' && dy > yThreshold * 1.2) {
      browserVerticalState = 'down';
    } else if (browserVerticalState === 'down' && dy < yReleaseThreshold * 1.2) {
      browserVerticalState = 'none';
    }

    const now = performance.now();
    if (dy < -yThreshold && velocityY < -0.008 && now - browserLastJump > 400) {
      browserLastJump = now;
      browserJumpUntil = now + 160;
    }

    handleTelemetryMessage({
      h_state: browserHorizontalState,
      v_state: browserVerticalState,
      is_jumping: now < browserJumpUntil,
      pose_detected: true,
      calibrated: true,
      calib_progress: calibrationTotal,
      calib_total: calibrationTotal,
      dx,
      dy,
    });
  }

  // ============================================================================
  // DIRECT IN-BROWSER KEYBOARD DISPATCHER (sendKeyToGame)
  // ============================================================================
  function sendKeyToGame(iframeEl, key, type) {
    const keyMap = {
      ArrowLeft:  { key: "ArrowLeft",  code: "ArrowLeft",  keyCode: 37, char: "a", dir: "left" },
      ArrowRight: { key: "ArrowRight", code: "ArrowRight", keyCode: 39, char: "d", dir: "right" },
      ArrowUp:    { key: "ArrowUp",    code: "ArrowUp",    keyCode: 38, char: "w", dir: "up" },
      ArrowDown:  { key: "ArrowDown",  code: "ArrowDown",  keyCode: 40, char: "s", dir: "down" },
    };
    const k = keyMap[key];
    if (!k || !iframeEl) return;

    try {
      const targetWindow = iframeEl.contentWindow;
      if (targetWindow) {
        // 1. Direct function call if available in same-origin game
        if (typeof targetWindow.handleGameAction === "function" && type === "keydown") {
          targetWindow.handleGameAction(k.dir);
        }

        // 2. PostMessage channel
        targetWindow.postMessage({ type: "MOTION_KEY", key: k.dir, state: type }, "*");

        // 3. Synthetic DOM KeyboardEvent
        const targetDoc = targetWindow.document || iframeEl.contentDocument;
        if (targetDoc) {
          const createEvt = (kName, cName, codeNum) => {
            const evt = new KeyboardEvent(type, {
              key: kName,
              code: cName,
              keyCode: codeNum,
              which: codeNum,
              bubbles: true,
              cancelable: true,
            });
            try {
              Object.defineProperty(evt, 'keyCode', { get: () => codeNum, configurable: true });
              Object.defineProperty(evt, 'which', { get: () => codeNum, configurable: true });
            } catch (err) {}
            return evt;
          };

          const arrowEvt = createEvt(k.key, k.code, k.keyCode);
          targetDoc.dispatchEvent(arrowEvt);
          targetWindow.dispatchEvent(arrowEvt);

          const canvas = targetDoc.querySelector('canvas') || targetDoc.getElementById('glcanvas') || targetDoc.getElementById('canvas');
          if (canvas) canvas.dispatchEvent(arrowEvt);
        }
      }
    } catch (e) {
      // Cross-origin iframe, handled by OS hardware keystrokes from Python backend
    }
  }

  let currentHKey = 'none';
  let currentVKey = 'none';

  // ============================================================================
  // TELEMETRY & FRAME RENDERING
  // ============================================================================
  function handleTelemetryMessage(data) {
    // 1. Render Video Frame
    if (data.frame && webcamFeed && webcamFeed.tagName === 'IMG') {
      webcamFeed.src = data.frame;
      if (floatingCamImg && floatingCamImg.tagName === 'IMG' && floatingWebcam.style.display !== 'none') {
        floatingCamImg.src = data.frame;
      }
      if (camOverlayPlaceholder && camOverlayPlaceholder.style.display !== 'none') {
        camOverlayPlaceholder.style.display = 'none';
      }

      frameCount++;
      const now = Date.now();
      if (now - lastFrameTime >= 1000) {
        fps = frameCount;
        frameCount = 0;
        lastFrameTime = now;
      }
    }

    // 2. Extract Gesture States
    const hState = data.h_state || 'none';
    const vState = data.v_state || 'none';
    const isJumping = data.is_jumping || false;
    const isCalibrated = data.calibrated || false;
    const poseDetected = data.pose_detected !== false;
    const calibProgress = data.calib_progress || 0;
    const calibTotal = data.calib_total || 40;
    const dx = data.dx || 0.0;
    const dy = data.dy || 0.0;

    // Safety: on pose loss, release all held in-browser keys
    if (!poseDetected) {
      if (currentHKey === 'left') sendKeyToGame(gameFrame, 'ArrowLeft', 'keyup');
      if (currentHKey === 'right') sendKeyToGame(gameFrame, 'ArrowRight', 'keyup');
      if (currentVKey === 'up') sendKeyToGame(gameFrame, 'ArrowUp', 'keyup');
      if (currentVKey === 'down') sendKeyToGame(gameFrame, 'ArrowDown', 'keyup');
      currentHKey = 'none';
      currentVKey = 'none';
    } else if (isCalibrated) {
      // Horizontal lane control (LEFT / RIGHT)
      if (hState !== currentHKey) {
        if (currentHKey === 'left') sendKeyToGame(gameFrame, 'ArrowLeft', 'keyup');
        if (currentHKey === 'right') sendKeyToGame(gameFrame, 'ArrowRight', 'keyup');

        if (hState === 'left') sendKeyToGame(gameFrame, 'ArrowLeft', 'keydown');
        if (hState === 'right') sendKeyToGame(gameFrame, 'ArrowRight', 'keydown');
        currentHKey = hState;
      }

      // Vertical control (UP / DOWN / JUMP)
      const effectiveV = isJumping ? 'up' : vState;
      if (effectiveV !== currentVKey) {
        if (currentVKey === 'up') sendKeyToGame(gameFrame, 'ArrowUp', 'keyup');
        if (currentVKey === 'down') sendKeyToGame(gameFrame, 'ArrowDown', 'keyup');

        if (effectiveV === 'up') sendKeyToGame(gameFrame, 'ArrowUp', 'keydown');
        if (effectiveV === 'down') sendKeyToGame(gameFrame, 'ArrowDown', 'keydown');
        currentVKey = effectiveV;
      }
    }

    updateChips(hState, isJumping ? 'up' : vState, isCalibrated, calibProgress, calibTotal, dx, dy, poseDetected, isJumping);
  }

  function updateChips(hState, vState, isCalibrated, calibProgress, calibTotal, dx, dy, poseDetected, isJumping) {
    // Coordinate readout
    if (coordsText) {
      coordsText.textContent = `dx: ${dx >= 0 ? '+' : ''}${dx.toFixed(3)} | dy: ${dy >= 0 ? '+' : ''}${dy.toFixed(3)}`;
    }

    // Horizontal Chip (LEFT / RIGHT)
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

    // Vertical Chip (UP / DOWN / JUMP)
    if (chipVKey && valVKey) {
      const isUp = vState.toLowerCase() === 'up' || isJumping;
      const isDown = vState.toLowerCase() === 'down';
      valVKey.textContent = isJumping ? 'JUMP' : isUp ? 'UP' : isDown ? 'DOWN' : 'NONE';
      chipVKey.className = (isUp || isDown) ? 'telemetry-chip active' : 'telemetry-chip';
      if (miniVChip) {
        miniVChip.textContent = `V: ${valVKey.textContent}`;
        miniVChip.className = (isUp || isDown) ? 'mini-chip active' : 'mini-chip';
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

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ action: 'recalibrate' }));
    }
    resetBrowserCalibration();

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
  // SENSITIVITY & TUNING DRAWER
  // ============================================================================
  function syncSensitivity() {
    const xThresh = parseFloat(sliderXSens ? sliderXSens.value : 0.030);
    const yThresh = parseFloat(sliderYSens ? sliderYSens.value : 0.025);
    const smoothing = parseFloat(sliderSmooth ? sliderSmooth.value : 0.60);

    const payload = {
      action: 'set_sensitivity',
      x_thresh: xThresh,
      y_thresh: yThresh,
      smoothing: smoothing
    };

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }

    fetch(`${getApiBaseUrl()}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).catch(() => {});
  }

  if (tuningToggleBtn && tuningDrawer) {
    tuningToggleBtn.addEventListener('click', () => {
      const isHidden = tuningDrawer.style.display === 'none';
      tuningDrawer.style.display = isHidden ? 'block' : 'none';
      if (tuningChevron) {
        tuningChevron.textContent = isHidden ? 'expand_less' : 'expand_more';
      }
    });
  }

  if (sliderXSens && valXSens) {
    sliderXSens.addEventListener('input', (e) => {
      valXSens.textContent = parseFloat(e.target.value).toFixed(3);
      syncSensitivity();
    });
  }

  if (sliderYSens && valYSens) {
    sliderYSens.addEventListener('input', (e) => {
      valYSens.textContent = parseFloat(e.target.value).toFixed(3);
      syncSensitivity();
    });
  }

  if (sliderSmooth && valSmooth) {
    sliderSmooth.addEventListener('input', (e) => {
      valSmooth.textContent = parseFloat(e.target.value).toFixed(2);
      syncSensitivity();
    });
  }

  if (btnResetTuning) {
    btnResetTuning.addEventListener('click', () => {
      if (sliderXSens) { sliderXSens.value = 0.030; valXSens.textContent = '0.030'; }
      if (sliderYSens) { sliderYSens.value = 0.025; valYSens.textContent = '0.025'; }
      if (sliderSmooth) { sliderSmooth.value = 0.60; valSmooth.textContent = '0.60'; }
      syncSensitivity();
    });
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

  // ============================================================================
  // HIGH SCORES MANAGEMENT (Backend REST + LocalStorage Fallback)
  // ============================================================================
  const STORAGE_KEY = 'motionrunner_scores';

  const defaultScores = [
    { id: '1', name: 'CyberDash', score: 42800, date: new Date(Date.now() - 1000 * 60 * 15).toISOString() },
    { id: '2', name: 'NeonRider', score: 38240, date: new Date(Date.now() - 1000 * 60 * 85).toISOString() },
    { id: '3', name: 'Valkyrie', score: 29500, date: new Date(Date.now() - 1000 * 60 * 360).toISOString() },
    { id: '4', name: 'TrackRunner', score: 21900, date: new Date(Date.now() - 1000 * 60 * 1440).toISOString() },
    { id: '5', name: 'SurferX', score: 16400, date: new Date(Date.now() - 1000 * 60 * 2880).toISOString() },
  ];

  async function loadScores() {
    try {
      const res = await fetch(`${getApiBaseUrl()}/scores`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          saveScoresToLocal(data);
          return data;
        }
      }
    } catch (e) {
      console.log('[MotionRunner] Using localStorage fallback for scores.');
    }

    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed.sort((a, b) => b.score - a.score);
        }
      }
    } catch (e) {}

    saveScoresToLocal(defaultScores);
    return defaultScores;
  }

  function saveScoresToLocal(scores) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(scores));
    } catch (e) {}
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

  async function renderLeaderboard() {
    const scores = await loadScores();
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
    scoreForm.addEventListener('submit', async (e) => {
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
        name: name,
        score: scoreNum,
      };

      try {
        const res = await fetch(`${getApiBaseUrl()}/scores`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newEntry)
        });
        if (res.ok) {
          const data = await res.json();
          if (data.scores) {
            saveScoresToLocal(data.scores);
          }
        }
      } catch (err) {
        // Fallback local save
        const currentScores = await loadScores();
        currentScores.push({
          id: 'run_' + Date.now(),
          name: name,
          score: scoreNum,
          date: new Date().toISOString()
        });
        currentScores.sort((a, b) => b.score - a.score);
        saveScoresToLocal(currentScores.slice(0, 50));
      }

      await renderLeaderboard();
      runnerScoreInput.value = '';
    });
  }

  if (clearScoresBtn) {
    clearScoresBtn.addEventListener('click', async () => {
      if (confirm('Reset high scores leaderboard?')) {
        try {
          await fetch(`${getApiBaseUrl()}/scores`, { method: 'DELETE' });
        } catch (e) {}
        saveScoresToLocal(defaultScores);
        await renderLeaderboard();
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
  startBrowserCamera();
  connectWebSocket();

  if (gameFrame) {
    gameFrame.addEventListener('load', () => {
      console.log('[MotionRunner] Game iframe loaded successfully.');
    });
  }
})();
