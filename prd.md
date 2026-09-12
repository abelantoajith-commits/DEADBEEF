# Product Requirements Document (PRD)
## Body-Motion Arcade Hub ("MotionRunner")

**Version:** 1.0
**Author:** [Your Name]
**Date:** September 12, 2026
**Status:** Draft

---

## 1. Overview

MotionRunner is a browser-based gaming hub, visually inspired by CrazyGames, that lets a
player control a Subway-Surfers-style endless runner using **full-body motion** captured
from a webcam instead of a keyboard. The page combines three panels in one screen:

1. **Game Area** (center/left, large) — the embedded Subway Surfers game.
2. **Webcam Preview** (right, top) — a live feed showing the player's skeleton overlay and
   current detected motion state (left/right/jump/duck), sourced from the existing
   `main.py` MediaPipe Pose controller.
3. **High Score Board** (right, bottom) — a form to submit a player name + score, and a
   list of past scores sorted descending.

The core novelty is that `main.py` doesn't just show a debug window locally — its camera
feed and detected pose state are **streamed into the web UI**, and its key-press output
drives the embedded game.

---

## 2. Goals & Non-Goals

### Goals
- Recreate a CrazyGames-like browsing/playing experience for a single game.
- Let a player control the game hands-free via body motion (lean, jump, duck).
- Show a live webcam preview with pose skeleton + current control state inside the browser
  (not in a separate OpenCV window).
- Persist and display a local high score leaderboard.

### Non-Goals (v1)
- No multiplayer / online leaderboard sync.
- No user accounts or authentication.
- No support for games other than the one Subway Surfers clone.
- No mobile / touch fallback controls (webcam + desktop browser only for v1).

---

## 3. Users & Use Case

Single local player, desktop browser, webcam attached, sitting/standing far enough back to
be fully visible. They open the web app, calibrate their neutral pose, then play the
embedded game by leaning left/right, jumping, and ducking. After a run, they enter their
name and see it added to the leaderboard.

---

## 4. System Architecture

This is the most important design decision in the project, because **`main.py` as written
today cannot be embedded directly in a browser** — it uses `cv2.imshow()` (a native desktop
window) and `pynput` (OS-level key events). Both need to be adapted.

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│        Browser (Frontend)    │        │      Local Python Backend    │
│                               │        │        (adapted main.py)     │
│  ┌─────────────┐              │        │                              │
│  │  Game Area   │◄─── keypress simulation (pynput, OS-level) ─────────┤
│  │ (Subway      │              │        │  - OpenCV capture loop      │
│  │  Surfers     │              │        │  - MediaPipe Pose inference │
│  │  iframe/     │              │        │  - Gesture state machine    │
│  │  canvas)     │              │        │    (existing logic reused)  │
│  └─────────────┘              │        │  - pynput presses arrow keys │
│                               │        │    (drives the game, same    │
│  ┌─────────────┐  WebSocket/  │        │    as today)                 │
│  │  Webcam      │◄─ MJPEG ────┼────────┤  - NEW: Flask/FastAPI server │
│  │  Preview     │   stream    │        │    exposing:                 │
│  │  + pose HUD  │              │        │    • /video_feed (MJPEG) or  │
│  └─────────────┘              │        │      WebSocket frame stream  │
│                               │        │    • /state (JSON: dx, dy,   │
│  ┌─────────────┐              │        │      h_state, v_state,       │
│  │ High Score   │              │        │      calibration progress)  │
│  │ Board        │◄─ localStorage/       │                              │
│  │ (form+list)  │   backend DB │        └──────────────────────────────┘
│  └─────────────┘              │
└───────────────────────────────┘
```

### 4.1 Backend changes required to `main.py`
- Remove/guard `cv2.imshow`, `cv2.waitKey` when running in "web mode" (keep them optional
  for a `--debug` CLI flag so local testing still works standalone).
- Wrap the capture loop in a lightweight web server (Flask or FastAPI):
  - `GET /video_feed` — MJPEG stream (`multipart/x-mixed-replace`) of the annotated frame
    (skeleton + HUD overlay), OR push base64 JPEG frames over a WebSocket if lower latency
    is preferred.
  - `GET /state` (or push over the same WebSocket) — JSON with the current `horizontal_state`,
    `vertical_state`, `is_jumping`, calibration progress, and dx/dy offsets, so the frontend
    HUD can render styled status chips instead of `cv2.putText`.
  - `POST /recalibrate` — triggers `reset_calibration()` remotely (replaces the `r` key).
- Keep the existing `pynput` key press/release logic untouched — it keeps driving whatever
  window has OS focus. **Important constraint:** for `pynput` key presses to reach the
  embedded game, the actual game must be receiving real OS keyboard focus. If the Subway
  Surfers clone runs purely inside a browser `<iframe>`/canvas, arrow-key `pynput` events
  sent to the OS will work as long as the browser tab/game canvas has focus — this should
  be validated early as a technical spike.
- Run the backend as a local process (e.g., `python main.py --serve`) that the frontend
  connects to at `http://localhost:8000`.

### 4.2 Frontend
- Single-page app (React or plain HTML/CSS/JS) laid out as a 2-column grid:
  - Left/large column: game iframe or canvas.
  - Right column, stacked: webcam preview card, then high score card.
- Webcam preview `<img>` tag pointed at `/video_feed`, or `<canvas>` fed by WebSocket frames.
- Status chips (H-Key, V-Key, Calibration) rendered from `/state` JSON, styled to match the
  CrazyGames dark theme (not baked into the video frame anymore).
- "Recalibrate" button in the UI calls `POST /recalibrate` instead of requiring focus on the
  old OpenCV window and pressing `r`.
- High scores stored client-side (localStorage) for v1 simplicity, with a note that a small
  backend endpoint (`/scores` GET/POST, backed by SQLite or a JSON file) is the natural v1.1
  upgrade if scores need to persist across browser resets or machines.

---

## 5. Feature Requirements

### 5.1 Game Area
- Embeds the Subway-Surfers clone (from the referenced repo) full-height in the main
  content column.
- Displays game title, like/dislike icons, fullscreen toggle, and report/bookmark icons in
  a header bar directly under the game — matching the reference CrazyGames layout supplied.
- Fullscreen control expands the game area only (webcam + scoreboard remain visible in a
  side rail, or collapse based on space).

### 5.2 Webcam Preview Panel
- Live annotated video feed (skeleton overlay, "CALIBRATING (n/60)" banner during setup,
  "No Body Detected" banner when pose is lost).
- Status readout showing: current H-Key state (LEFT/RIGHT/NONE), current V-Key state
  (JUMP/DOWN/NONE), and a "Calibrated" indicator — mirroring the current on-frame HUD in
  `main.py`, but rendered as HTML/CSS elements so they match the app's visual theme.
- "Recalibrate" button (replaces pressing `r`).
- Camera permission / connection error states (e.g., backend not running, no camera found).

### 5.3 High Score Board
- Form: Player Name (text input) + Score (number input) + "Submit" button.
- List: sorted descending by score, showing rank, name, score, and timestamp.
- Highlight the top 1–3 entries (gold/silver/bronze styling) similar to arcade leaderboards.
- Optional (v1.1): "Clear leaderboard" action, edit/delete a single entry.

### 5.4 Global Shell
- CrazyGames-style dark header: logo/title, search bar (non-functional placeholder is fine
  for v1), profile/notification icons, "Log in" button (can be a no-op for v1).
- Responsive down to a reasonable minimum desktop width; mobile is out of scope for v1.

---

## 6. Data Model (v1, local)

```jsonc
// localStorage key: "motionrunner_scores"
[
  { "id": "uuid", "name": "Alex", "score": 4820, "date": "2026-09-12T10:22:00Z" },
  { "id": "uuid", "name": "Sam",  "score": 3610, "date": "2026-09-11T18:04:00Z" }
]
```

---

## 7. Non-Functional Requirements
- **Latency:** webcam preview + state should feel real-time (<150ms end-to-end) so the
  player can react while playing; prefer WebSocket streaming over polling `/state`.
- **Reliability:** if MediaPipe loses tracking, all held keys must release immediately
  (already handled by the existing "No Body Detected" branch — preserve this behavior).
- **Safety:** on browser tab close or backend crash, all keys must be released
  (`release_all_keys()` already covers process exit; ensure it's also called on any
  unhandled exception in the new server loop).
- **Portability:** backend runs on the same machine as the browser (localhost) for v1;
  no cloud hosting requirement.

---

## 8. Tech Stack (proposed)
- **Backend:** Python, OpenCV, MediaPipe, pynput (existing), + Flask or FastAPI +
  `flask-sock`/`websockets` for streaming.
- **Frontend:** React (or plain HTML/CSS/JS) + Tailwind or hand-rolled CSS matching the
  CrazyGames dark theme; a `<canvas>`/`<img>` for the video stream; `localStorage` for
  scores in v1.
- **Game:** the referenced Subway-Surfers clone, embedded via `<iframe>` if it's a
  standalone web build, or run as a separate window if it's a native/pygame app (see Risks).

---

## 9. Risks & Open Questions
1. **Game embeddability:** confirm whether the linked Subway-Surfers repo is a web
   (HTML5/JS) build that can sit in an `<iframe>`, or a native Python/Pygame app that would
   need to run in its own OS window alongside the browser. This materially changes the
   layout (true embed vs. "launch game" button that opens a separate window next to the
   dashboard).
2. **OS-level key focus:** `pynput` sends OS-level key events; the embedded/launched game
   window must have keyboard focus for these to register. Needs an early spike/test.
3. **Camera streaming approach:** MJPEG (simpler, slightly higher latency) vs. WebSocket
   base64 frames (more code, lower latency, easier to also push JSON state on the same
   socket). Recommend WebSocket for a single low-latency channel carrying both frame +
   state.
4. **Score persistence:** v1 uses localStorage (single browser/machine only). If scores
   need to survive a browser reset or be shared, add a small `/scores` backend endpoint
   backed by SQLite.

---

## 10. Milestones
1. **M1 — Backend adaptation:** convert `main.py` to serve `/video_feed` + `/state` +
   `/recalibrate`; verify pose detection and key control still work identically.
2. **M2 — Static UI shell:** build the CrazyGames-style layout (header, game area, webcam
   panel, score panel) with placeholder/mock data.
3. **M3 — Integration:** wire webcam panel to the live backend stream and state; wire
   recalibrate button.
4. **M4 — Game embed:** embed/launch the Subway Surfers clone and validate keyboard control
   end-to-end.
5. **M5 — High scores:** implement submit form + sorted list + localStorage persistence.
6. **M6 — Polish:** error states (no camera, backend down), fullscreen mode, responsive
   tweaks.
