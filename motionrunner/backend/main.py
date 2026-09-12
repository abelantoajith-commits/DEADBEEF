"""
MotionRunner - Body Motion Keyboard Controller & WebSocket Server
==================================================================
Control games (like Subway Surfers) and applications using full-body motion 
detected via webcam and MediaPipe Pose.

Features:
  - Lean/Step LEFT   -> Dispatches Left Arrow (and 'A')
  - Lean/Step RIGHT  -> Dispatches Right Arrow (and 'D')
  - JUMP             -> Taps Up Arrow (~160ms tap, ~400ms cooldown) & 'W'
  - DUCK / Crouch    -> Holds Down Arrow & 'S'
  - WebSocket /ws    -> Streams base64 JPEG annotated skeleton frames + JSON state
  - GET /video_feed  -> MJPEG multipart stream for standard preview
  - GET /state       -> JSON telemetry snapshot
  - POST /recalibrate-> Resets baseline neutral pose calibration
  - GET /scores      -> High scores retrieval (persisted to scores.json)
  - POST /scores     -> High score submission
  - Embedded Game    -> Serves Subway Surfers from external URL or /game/
  - Single-Page UI   -> Serves MotionRunner web app at /
  - Standalone/Debug -> Supports cv2.imshow local window with --debug
"""

import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import os
import sys
import threading
import time
from typing import Dict, List, Optional, Set

import cv2
import mediapipe as mp
from pynput.keyboard import Controller, Key

# FastAPI and ASGI server imports
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# DirectInput and Keyboard emulation
import pydirectinput
pydirectinput.PAUSE = 0.0

# Windows Hardware Virtual Key and Scan Code constants
import ctypes

user32 = None
if sys.platform == "win32":
    try:
        user32 = ctypes.windll.user32
    except Exception as e:
        print(f"[Backend] Note: ctypes user32 unavailable: {e}")

VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_A = 0x41
VK_D = 0x44
VK_W = 0x57
VK_S = 0x53

SCAN_LEFT = 0x4B
SCAN_RIGHT = 0x4D
SCAN_UP = 0x48
SCAN_DOWN = 0x50
SCAN_A = 0x1E
SCAN_D = 0x20
SCAN_W = 0x11
SCAN_S = 0x1F

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

PUL = ctypes.POINTER(ctypes.c_ulong)

class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]

class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]

class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]

class Input_I(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput),
    ]

class Input(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", Input_I),
    ]

INPUT_KEYBOARD = 1


def _send_input_key(vk_code: int, scan_code: int, is_press: bool, is_extended: bool = False):
    """Low-level Windows SendInput event dispatcher with hardware scan codes."""
    if not user32:
        return
    try:
        flags = KEYEVENTF_SCANCODE
        if is_extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        if not is_press:
            flags |= KEYEVENTF_KEYUP

        extra = ctypes.c_ulong(0)
        ii = Input_I()
        ii.ki = KeyBdInput(vk_code, scan_code, flags, 0, ctypes.pointer(extra))
        cmd = Input(INPUT_KEYBOARD, ii)
        user32.SendInput(1, ctypes.pointer(cmd), ctypes.sizeof(cmd))
    except Exception as e:
        pass


def _win_key(vk_code: int, is_press: bool):
    """Fallback via user32.keybd_event."""
    if not user32:
        return
    try:
        flags = 0 if is_press else KEYEVENTF_KEYUP
        user32.keybd_event(vk_code, 0, flags, 0)
    except Exception:
        pass


# ==============================================================================
# CONFIGURATION & THRESHOLDS
# ==============================================================================
CALIBRATION_FRAMES = 40          # Number of frames to average for neutral baseline

# Movement thresholds with Hysteresis (Activation vs Release)
X_THRESHOLD_ON = 0.030           # Enter Left (dx < -0.030) / Right (dx > +0.030)
X_THRESHOLD_OFF = 0.015          # Exit to Neutral (|dx| < 0.015)
Y_UP_THRESHOLD_ON = 0.025        # Jump activation (dy < -0.025)
Y_UP_THRESHOLD_OFF = 0.012       # Jump release (|dy| < 0.012)
Y_DOWN_THRESHOLD_ON = 0.030      # Duck activation (dy > +0.030)
Y_DOWN_THRESHOLD_OFF = 0.015     # Duck release (|dy| < 0.015)

# EMA (Exponential Moving Average) Smoothing Factor (0.0 to 1.0)
EMA_ALPHA = 0.60                 # 0.60 gives fast response with smooth tracking

# Jump pulse duration & cooldown
JUMP_PULSE_DURATION = 0.160      # Seconds to hold Up Arrow for a jump tap
JUMP_COOLDOWN = 0.400            # Cooldown seconds before next jump can trigger

# Webcam and Window configuration
CAMERA_INDEX = 0                 # Default webcam device index
WINDOW_TITLE = "MotionRunner - Controller Preview"

# Directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
GAME_DIR = os.path.join(PROJECT_DIR, "game")
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
SCORES_FILE = os.path.join(PROJECT_DIR, "scores.json")


# ==============================================================================
# KEYBOARD CONTROLLER & STATE MACHINE
# ==============================================================================
keyboard = Controller()

# Gesture states
horizontal_state = "none"        # "left", "right", or "none"
vertical_state = "none"          # "up", "down", or "none"
is_jumping = False               # True during jump pulse
last_jump_time = 0.0             # Timestamp of last jump trigger

# Smoothed tracking coordinates
smoothed_x: Optional[float] = None
smoothed_y: Optional[float] = None

# Baseline calibration coordinates
baseline_x: Optional[float] = None
baseline_y: Optional[float] = None
calib_x_samples: List[float] = []
calib_y_samples: List[float] = []

# Current tracking snapshot
current_dx: float = 0.0
current_dy: float = 0.0
pose_detected: bool = False
camera_active: bool = False

# Latest encoded frame for MJPEG streaming
latest_jpeg_bytes: Optional[bytes] = None

# WebSocket broadcasting & Async loop
active_websockets: Set[WebSocket] = set()
state_lock = threading.Lock()
running = True
main_event_loop = None


def emit_key(key_name: str, is_press: bool):
    """
    Robust multi-layer key sender (SendInput scan codes + DirectInput + Pynput).
    """
    try:
        pynput_map = {
            'left': Key.left,
            'right': Key.right,
            'up': Key.up,
            'down': Key.down,
            'a': 'a',
            'd': 'd',
            'w': 'w',
            's': 's',
        }
        k = pynput_map.get(key_name.lower())
        if k:
            if is_press:
                keyboard.press(k)
            else:
                keyboard.release(k)
    except Exception:
        pass

    try:
        if is_press:
            pydirectinput.keyDown(key_name.lower())
        else:
            pydirectinput.keyUp(key_name.lower())
    except Exception:
        pass

    key_specs = {
        'left': (VK_LEFT, SCAN_LEFT, True),
        'right': (VK_RIGHT, SCAN_RIGHT, True),
        'up': (VK_UP, SCAN_UP, True),
        'down': (VK_DOWN, SCAN_DOWN, True),
        'a': (VK_A, SCAN_A, False),
        'd': (VK_D, SCAN_D, False),
        'w': (VK_W, SCAN_W, False),
        's': (VK_S, SCAN_S, False),
    }
    spec = key_specs.get(key_name.lower())
    if spec:
        vk, scan, ext = spec
        _send_input_key(vk, scan, is_press, is_extended=ext)
        _win_key(vk, is_press)


def release_all_keys():
    """Safety cleanup: reset all state variables and release any held hardware keys."""
    global horizontal_state, vertical_state, is_jumping
    for k in ('left', 'right', 'up', 'down', 'a', 'd', 'w', 's'):
        emit_key(k, False)
    horizontal_state = "none"
    vertical_state = "none"
    is_jumping = False


def set_horizontal_state(new_state: str):
    """
    Update Left/Right horizontal gesture state and dispatch hardware keystrokes.
    """
    global horizontal_state
    if new_state == horizontal_state:
        return

    # Release previous
    if horizontal_state == "left":
        emit_key('left', False)
        emit_key('a', False)
    elif horizontal_state == "right":
        emit_key('right', False)
        emit_key('d', False)

    # Press new
    if new_state == "left":
        emit_key('left', True)
        emit_key('a', True)
    elif new_state == "right":
        emit_key('right', True)
        emit_key('d', True)

    horizontal_state = new_state


def trigger_jump():
    """
    Trigger a single tap of the Jump key (Up Arrow + W) with auto-release after pulse duration.
    """
    global is_jumping, last_jump_time
    is_jumping = True
    last_jump_time = time.time()
    emit_key('up', True)
    emit_key('w', True)

    def _auto_release():
        time.sleep(JUMP_PULSE_DURATION)
        emit_key('up', False)
        emit_key('w', False)
        with state_lock:
            global is_jumping
            is_jumping = False

    threading.Thread(target=_auto_release, daemon=True).start()


def set_vertical_state(new_state: str):
    """
    Update Up/Down vertical gesture state and dispatch hardware keystrokes.
    """
    global vertical_state, last_jump_time
    if new_state == vertical_state:
        return

    now = time.time()

    # Release previous duck if leaving down
    if vertical_state == "down" and new_state != "down":
        emit_key('down', False)
        emit_key('s', False)

    # Entering UP (Jump)
    if new_state == "up":
        if (now - last_jump_time) >= JUMP_COOLDOWN:
            trigger_jump()

    # Entering DOWN (Duck / Roll)
    elif new_state == "down":
        emit_key('down', True)
        emit_key('s', True)

    vertical_state = new_state


def reset_calibration():
    """Reset baseline so the user can re-calibrate in their current position."""
    global baseline_x, baseline_y, calib_x_samples, calib_y_samples
    global smoothed_x, smoothed_y
    with state_lock:
        baseline_x = None
        baseline_y = None
        calib_x_samples = []
        calib_y_samples = []
        smoothed_x = None
        smoothed_y = None
        release_all_keys()
    print("[Backend] Baseline calibration reset requested.")


# ==============================================================================
# CAMERA & POSE PROCESSING LOOP
# ==============================================================================
def process_camera_stream(show_debug_window: bool = False, camera_idx: int = CAMERA_INDEX):
    """
    Main capture and pose detection loop.
    Extracts pose landmarks, runs gesture state machine, simulates keys,
    draws skeleton overlay & HUD, and broadcasts frames & state to WebSockets and MJPEG.
    """
    global baseline_x, baseline_y, calib_x_samples, calib_y_samples
    global smoothed_x, smoothed_y, current_dx, current_dy
    global pose_detected, camera_active, running, latest_jpeg_bytes

    mp_pose = mp.solutions.pose
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles

    pose = mp_pose.Pose(
        model_complexity=1,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    cap = cv2.VideoCapture(camera_idx)
    if not cap.isOpened():
        print(f"[Backend Error] Could not open camera with index {camera_idx}.")
        camera_active = False
        return

    camera_active = True
    print(f"[Backend] Camera {camera_idx} initialized successfully.")

    try:
        while running and cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Mirror frame horizontally for intuitive mirror feedback
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape

            # Convert BGR image to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb_frame)

            with state_lock:
                if results.pose_landmarks:
                    pose_detected = True

                    # 1. Draw skeleton landmarks and connections
                    mp_drawing.draw_landmarks(
                        frame,
                        results.pose_landmarks,
                        mp_pose.POSE_CONNECTIONS,
                        landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style(),
                    )

                    landmarks = results.pose_landmarks.landmark
                    nose = landmarks[mp_pose.PoseLandmark.NOSE]
                    l_eye = landmarks[mp_pose.PoseLandmark.LEFT_EYE]
                    r_eye = landmarks[mp_pose.PoseLandmark.RIGHT_EYE]
                    l_sh = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
                    r_sh = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]

                    # Facial + Head Landmark tracking
                    # Nose + Eyes provide direct, highly responsive head position
                    raw_x = (nose.x * 3.0 + l_eye.x + r_eye.x) / 5.0
                    raw_y = (nose.y * 3.0 + l_eye.y + r_eye.y) / 5.0

                    # Real-time Exponential Moving Average (EMA) smoothing
                    if smoothed_x is None:
                        smoothed_x = raw_x
                        smoothed_y = raw_y
                    else:
                        smoothed_x = EMA_ALPHA * raw_x + (1.0 - EMA_ALPHA) * smoothed_x
                        smoothed_y = EMA_ALPHA * raw_y + (1.0 - EMA_ALPHA) * smoothed_y

                    head_x = smoothed_x
                    head_y = smoothed_y

                    # 2. Calibration Phase
                    if baseline_x is None:
                        calib_x_samples.append(head_x)
                        calib_y_samples.append(head_y)
                        progress = len(calib_x_samples)
                        current_dx = 0.0
                        current_dy = 0.0

                        # Draw calibration overlay on video frame
                        cv2.rectangle(frame, (15, 15), (430, 80), (30, 30, 30), -1)
                        cv2.putText(
                            frame,
                            f"CALIBRATING ({progress}/{CALIBRATION_FRAMES})...",
                            (25, 45),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.7,
                            (0, 255, 255),
                            2,
                        )
                        cv2.putText(
                            frame,
                            "Keep head centered in neutral posture",
                            (25, 70),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (200, 200, 200),
                            1,
                        )

                        if progress >= CALIBRATION_FRAMES:
                            baseline_x = sum(calib_x_samples) / len(calib_x_samples)
                            baseline_y = sum(calib_y_samples) / len(calib_y_samples)
                            print(f"[Backend] Calibrated: baseline_x={baseline_x:.3f}, baseline_y={baseline_y:.3f}")

                    # 3. Tracking & Action Phase with Hysteresis
                    else:
                        dx = head_x - baseline_x
                        dy = head_y - baseline_y
                        current_dx = dx
                        current_dy = dy

                        # --- Horizontal Movement (Left / Right) with Hysteresis ---
                        if horizontal_state == "none":
                            if dx < -X_THRESHOLD_ON:
                                set_horizontal_state("left")
                            elif dx > X_THRESHOLD_ON:
                                set_horizontal_state("right")
                        elif horizontal_state == "left":
                            if dx > -X_THRESHOLD_OFF:
                                set_horizontal_state("none")
                        elif horizontal_state == "right":
                            if dx < X_THRESHOLD_OFF:
                                set_horizontal_state("none")

                        # --- Vertical Movement (Up / Down) with Hysteresis ---
                        if vertical_state == "none":
                            if dy < -Y_UP_THRESHOLD_ON:
                                set_vertical_state("up")
                            elif dy > Y_DOWN_THRESHOLD_ON:
                                set_vertical_state("down")
                        elif vertical_state == "up":
                            if dy > -Y_UP_THRESHOLD_OFF:
                                set_vertical_state("none")
                        elif vertical_state == "down":
                            if dy < Y_DOWN_THRESHOLD_OFF:
                                set_vertical_state("none")

                        # Draw live head tracking reticle & baseline guide on preview
                        cx_px = int(head_x * w)
                        cy_px = int(head_y * h)
                        bx_px = int(baseline_x * w)
                        by_px = int(baseline_y * h)

                        # Threshold deadband box around baseline
                        tx_px = int(X_THRESHOLD_ON * w)
                        ty_up_px = int(Y_UP_THRESHOLD_ON * h)
                        ty_down_px = int(Y_DOWN_THRESHOLD_ON * h)
                        cv2.rectangle(frame, (bx_px - tx_px, by_px - ty_up_px), (bx_px + tx_px, by_px + ty_down_px), (70, 70, 160), 1)

                        # Baseline anchor
                        cv2.circle(frame, (bx_px, by_px), 5, (100, 150, 255), -1)

                        # Current head position reticle
                        active_gesture = (horizontal_state != "none" or vertical_state != "none" or is_jumping)
                        reticle_color = (0, 255, 0) if active_gesture else (0, 220, 255)
                        cv2.circle(frame, (cx_px, cy_px), 8, reticle_color, 2)
                        cv2.line(frame, (bx_px, by_px), (cx_px, cy_px), (255, 255, 0), 1)

                        # HUD overlay box
                        cv2.rectangle(frame, (10, 10), (370, 95), (20, 20, 20), -1)
                        cv2.rectangle(frame, (10, 10), (370, 95), (60, 60, 60), 1)
                        cv2.putText(
                            frame,
                            f"Head dx: {dx:+.3f} | dy: {dy:+.3f}",
                            (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (255, 255, 255),
                            1,
                        )
                        h_color = (0, 255, 0) if horizontal_state != "none" else (160, 160, 160)
                        v_disp = "JUMP" if is_jumping else vertical_state.upper()
                        v_color = (0, 255, 0) if (vertical_state != "none" or is_jumping) else (160, 160, 160)
                        cv2.putText(
                            frame,
                            f"H-KEY: {horizontal_state.upper()}",
                            (20, 70),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            h_color,
                            2,
                        )
                        cv2.putText(
                            frame,
                            f"V-KEY: {v_disp}",
                            (190, 70),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            v_color,
                            2,
                        )

                else:
                    # No body detected - safely release held keys
                    pose_detected = False
                    current_dx = 0.0
                    current_dy = 0.0
                    set_horizontal_state("none")
                    set_vertical_state("none")

                    cv2.rectangle(frame, (15, 15), (320, 60), (0, 0, 180), -1)
                    cv2.putText(
                        frame,
                        "No Body Detected",
                        (25, 45),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (255, 255, 255),
                        2,
                    )

                # Prepare state payload for WebSocket broadcast
                v_state_repr = "jump" if is_jumping else vertical_state
                state_data = {
                    "type": "state",
                    "h_state": horizontal_state,
                    "v_state": v_state_repr,
                    "is_jumping": is_jumping,
                    "dx": round(current_dx, 3),
                    "dy": round(current_dy, 3),
                    "calibrated": baseline_x is not None,
                    "calib_progress": len(calib_x_samples),
                    "calib_total": CALIBRATION_FRAMES,
                    "pose_detected": pose_detected,
                }

            # Encode frame for WebSocket & MJPEG
            small_frame = cv2.resize(frame, (480, int(480 * h / w)))
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 65]
            _, buffer = cv2.imencode(".jpg", small_frame, encode_param)
            jpg_bytes = buffer.tobytes()
            latest_jpeg_bytes = jpg_bytes

            if active_websockets and main_event_loop:
                jpg_as_text = base64.b64encode(jpg_bytes).decode("utf-8")
                payload = {
                    **state_data,
                    "frame": f"data:image/jpeg;base64,{jpg_as_text}",
                }
                msg_str = json.dumps(payload)

                dead_sockets = set()
                for ws in list(active_websockets):
                    try:
                        asyncio.run_coroutine_threadsafe(ws.send_text(msg_str), main_event_loop)
                    except Exception:
                        dead_sockets.add(ws)
                for ds in dead_sockets:
                    active_websockets.discard(ds)

            # Debug window display if enabled
            if show_debug_window:
                cv2.imshow(WINDOW_TITLE, frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    running = False
                    break
                elif key == ord("r"):
                    reset_calibration()

            time.sleep(0.015)

    except Exception as e:
        print(f"[Backend Error] Exception in capture loop: {e}")
    finally:
        print("[Backend] Cleaning up camera and releasing all keys...")
        release_all_keys()
        cap.release()
        cv2.destroyAllWindows()
        pose.close()
        camera_active = False
        print("[Backend] Camera loop exited.")


# ==============================================================================
# HIGH SCORES STORAGE HELPER
# ==============================================================================
DEFAULT_SCORES = [
    {"id": "1", "name": "CyberDash", "score": 42800, "date": "2026-09-12T10:20:00Z"},
    {"id": "2", "name": "NeonRider", "score": 38240, "date": "2026-09-12T09:15:00Z"},
    {"id": "3", "name": "Valkyrie", "score": 29500, "date": "2026-09-11T18:40:00Z"},
    {"id": "4", "name": "TrackRunner", "score": 21900, "date": "2026-09-11T14:30:00Z"},
    {"id": "5", "name": "SurferX", "score": 16400, "date": "2026-09-10T12:00:00Z"},
]

def load_scores_from_disk() -> List[Dict]:
    if os.path.exists(SCORES_FILE):
        try:
            with open(SCORES_FILE, "r", encoding="utf-8") as f:
                scores = json.load(f)
                if isinstance(scores, list):
                    scores.sort(key=lambda s: s.get("score", 0), reverse=True)
                    return scores
        except Exception as e:
            print(f"[Scores] Error reading {SCORES_FILE}: {e}")
    return DEFAULT_SCORES

def save_scores_to_disk(scores: List[Dict]):
    try:
        with open(SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f, indent=2)
    except Exception as e:
        print(f"[Scores] Error writing {SCORES_FILE}: {e}")


# ==============================================================================
# FASTAPI LIFESPAN & APP SETUP
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_event_loop, running
    running = True
    main_event_loop = asyncio.get_running_loop()
    camera_thread = threading.Thread(
        target=process_camera_stream,
        args=(False, CAMERA_INDEX),
        daemon=True,
    )
    camera_thread.start()
    print("[Backend] MotionRunner server started on background camera thread.")
    yield
    print("[Backend] Shutting down server...")
    running = False
    release_all_keys()
    print("[Backend] Server shutdown completed. All keys released.")


app = FastAPI(title="MotionRunner Controller Server", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "camera_active": camera_active,
        "pose_detected": pose_detected,
        "calibrated": baseline_x is not None,
    }


@app.post("/recalibrate")
def recalibrate_endpoint():
    """Trigger recalibration remotely via REST API."""
    reset_calibration()
    return {
        "status": "ok",
        "message": "Calibration reset. Stand still in neutral posture to calibrate.",
    }


@app.get("/state")
def get_state():
    """Get current controller state snapshot."""
    with state_lock:
        return {
            "h_state": horizontal_state,
            "v_state": "jump" if is_jumping else vertical_state,
            "is_jumping": is_jumping,
            "dx": round(current_dx, 3),
            "dy": round(current_dy, 3),
            "calibrated": baseline_x is not None,
            "calib_progress": len(calib_x_samples),
            "calib_total": CALIBRATION_FRAMES,
            "pose_detected": pose_detected,
        }


@app.post("/config")
async def update_config(req: Request):
    """Dynamic sensitivity & threshold tuning."""
    global X_THRESHOLD_ON, X_THRESHOLD_OFF, Y_UP_THRESHOLD_ON, Y_UP_THRESHOLD_OFF
    global Y_DOWN_THRESHOLD_ON, Y_DOWN_THRESHOLD_OFF, EMA_ALPHA
    try:
        body = await req.json()
        if "x_thresh" in body:
            x_val = float(body["x_thresh"])
            X_THRESHOLD_ON = max(0.01, min(0.15, x_val))
            X_THRESHOLD_OFF = X_THRESHOLD_ON * 0.5
        if "y_thresh" in body:
            y_val = float(body["y_thresh"])
            Y_UP_THRESHOLD_ON = max(0.01, min(0.15, y_val))
            Y_UP_THRESHOLD_OFF = Y_UP_THRESHOLD_ON * 0.5
            Y_DOWN_THRESHOLD_ON = Y_UP_THRESHOLD_ON * 1.2
            Y_DOWN_THRESHOLD_OFF = Y_UP_THRESHOLD_OFF * 1.2
        if "smoothing" in body:
            s_val = float(body["smoothing"])
            EMA_ALPHA = max(0.1, min(1.0, s_val))
        return {
            "status": "ok",
            "x_thresh_on": X_THRESHOLD_ON,
            "y_thresh_on": Y_UP_THRESHOLD_ON,
            "ema_alpha": EMA_ALPHA
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/video_feed")
def video_feed():
    """MJPEG streaming endpoint for camera video preview."""
    def frame_generator():
        while running:
            if latest_jpeg_bytes:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + latest_jpeg_bytes + b"\r\n"
                )
            time.sleep(0.033)
    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/scores")
def get_scores():
    """Retrieve high scores list sorted descending."""
    return load_scores_from_disk()


@app.post("/scores")
async def add_score(req: Request):
    """Submit a new high score entry."""
    try:
        body = await req.json()
        name = str(body.get("name", "")).strip()[:20]
        score_val = int(body.get("score", 0))
        if not name or score_val <= 0:
            return JSONResponse(status_code=400, content={"error": "Invalid name or score"})

        scores = load_scores_from_disk()
        entry = {
            "id": f"score_{int(time.time()*1000)}",
            "name": name,
            "score": score_val,
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        scores.append(entry)
        scores.sort(key=lambda s: s.get("score", 0), reverse=True)
        scores = scores[:50]  # Keep top 50
        save_scores_to_disk(scores)
        return {"status": "ok", "entry": entry, "scores": scores}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.delete("/scores")
def clear_scores():
    """Reset high scores to defaults."""
    save_scores_to_disk(DEFAULT_SCORES)
    return {"status": "ok", "scores": DEFAULT_SCORES}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint streaming annotated video frames and state data."""
    await websocket.accept()
    active_websockets.add(websocket)
    print(f"[WebSocket] Client connected. Total clients: {len(active_websockets)}")
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                if action == "recalibrate":
                    reset_calibration()
                elif action == "set_sensitivity":
                    global X_THRESHOLD_ON, X_THRESHOLD_OFF, Y_UP_THRESHOLD_ON, Y_UP_THRESHOLD_OFF
                    global EMA_ALPHA
                    if "x_thresh" in msg:
                        X_THRESHOLD_ON = float(msg["x_thresh"])
                        X_THRESHOLD_OFF = X_THRESHOLD_ON * 0.5
                    if "y_thresh" in msg:
                        Y_UP_THRESHOLD_ON = float(msg["y_thresh"])
                        Y_UP_THRESHOLD_OFF = Y_UP_THRESHOLD_ON * 0.5
                    if "smoothing" in msg:
                        EMA_ALPHA = float(msg["smoothing"])
            except Exception:
                pass
    except WebSocketDisconnect:
        print("[WebSocket] Client disconnected.")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        active_websockets.discard(websocket)
        print(f"[WebSocket] Remaining clients: {len(active_websockets)}")


# ==============================================================================
# STATIC FILE MOUNTS (Subway Surfers Game & Frontend App)
# ==============================================================================
if os.path.exists(GAME_DIR):
    app.mount("/game", StaticFiles(directory=GAME_DIR, html=True), name="game")
    print(f"[Backend] Mounted /game from {GAME_DIR}")

if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    print(f"[Backend] Mounted / from {FRONTEND_DIR}")


# ==============================================================================
# CLI ENTRYPOINT
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="MotionRunner Controller Server & Standalone")
    parser.add_argument("--serve", action="store_true", help="Run FastAPI / WebSocket server")
    parser.add_argument("--debug", action="store_true", help="Show OpenCV debug preview window")
    parser.add_argument("--port", type=int, default=8000, help="Port to run server on (default 8000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (default 0.0.0.0)")
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX, help="Webcam device index")

    args = parser.parse_args()

    if args.serve:
        print("==================================================")
        print(f" MotionRunner Server starting on http://localhost:{args.port}")
        print(f" Web App: http://localhost:{args.port}/")
        print(f" Embedded Game: http://localhost:{args.port}/game/")
        print(" WebSocket endpoint: /ws")
        print(" Video Stream: GET /video_feed")
        print(" Recalibrate endpoint: POST /recalibrate")
        print(" Scores endpoint: GET/POST /scores")
        print("==================================================")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        print("==================================================")
        print(" MotionRunner Controller Running in Standalone Debug Mode")
        print(" Stand in a neutral position to calibrate.")
        print(" Press 'r' to recalibrate at any time.")
        print(" Press 'q' to quit.")
        print("==================================================")
        try:
            process_camera_stream(show_debug_window=True, camera_idx=args.camera)
        except KeyboardInterrupt:
            pass
        finally:
            release_all_keys()


if __name__ == "__main__":
    main()