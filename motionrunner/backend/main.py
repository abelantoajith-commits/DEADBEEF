"""
MotionRunner - Body Motion Keyboard Controller & WebSocket Server
==================================================================
Control games (like Subway Surfers) and applications using full-body motion 
detected via webcam and MediaPipe Pose.

Features:
  - Lean/Step LEFT   -> Holds Left Arrow
  - Lean/Step RIGHT  -> Holds Right Arrow
  - JUMP             -> Taps Up Arrow (~150ms tap duration, cooldown ~0.6s)
  - DUCK / Crouch    -> Holds Down Arrow
  - WebSocket /ws    -> Streams base64 JPEG annotated skeleton frames + JSON state
  - POST /recalibrate-> Resets baseline neutral pose calibration
  - Embedded Game    -> Serves Subway Surfers at /game/
  - Single-Page UI   -> Serves MotionRunner web app at /
  - Standalone/Debug -> Supports cv2.imshow local window for testing
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
from typing import Set

import cv2
import mediapipe as mp
from pynput.keyboard import Controller, Key

# FastAPI and ASGI server imports
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ==============================================================================
# CONFIGURATION & THRESHOLDS
# ==============================================================================
CALIBRATION_FRAMES = 60          # Number of frames to average for neutral pose baseline

# Horizontal thresholds (normalized 0.0 - 1.0 coordinate delta)
X_THRESHOLD = 0.045              # Lateral displacement needed to trigger Left/Right

# Vertical thresholds (normalized 0.0 - 1.0 coordinate delta, Y increases downward)
Y_DUCK_THRESHOLD = 0.045         # Downward displacement from baseline to trigger Duck (Down Arrow)
Y_JUMP_THRESHOLD = 0.035         # Upward displacement from baseline required for Jump
JUMP_VELOCITY_THRESHOLD = 0.008  # Minimum per-frame upward velocity to distinguish jump from slow standing

# Jump timing parameters
JUMP_TAP_DURATION = 0.18         # Seconds to keep Up Arrow pressed during a jump
JUMP_COOLDOWN = 0.45             # Seconds between consecutive jump triggers

# Webcam and Window configuration
CAMERA_INDEX = 0                 # Default webcam device index
WINDOW_TITLE = "MotionRunner - Controller Preview"

# Directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
GAME_DIR = os.path.join(PROJECT_DIR, "game")
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")


# ==============================================================================
# KEYBOARD CONTROLLER & STATE MACHINE
# ==============================================================================
keyboard = Controller()

# State variables
horizontal_state = "none"        # "left", "right", or "none"
vertical_state = "none"          # "down" or "none"
is_jumping = False               # True while Up Arrow is actively tapped
jump_release_time = 0.0          # Timestamp when Up Arrow should be released
last_jump_time = 0.0             # Timestamp when last jump was triggered

# Baseline calibration variables
baseline_x = None
baseline_y = None
calib_x_samples = []
calib_y_samples = []

# Velocity tracking
prev_shoulder_y = None

# Current tracking state snapshot
current_dx = 0.0
current_dy = 0.0
pose_detected = False
camera_active = False

# WebSocket broadcasting & Async loop
active_websockets: Set[WebSocket] = set()
state_lock = threading.Lock()
running = True
main_event_loop = None


# DirectInput and Keyboard emulation imports
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

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002


def _win_key(vk_code: int, is_press: bool):
    """Direct Windows low-level hardware keyboard event dispatcher."""
    if user32 is None:
        return
    try:
        scan_code = user32.MapVirtualKeyW(vk_code, 0)
        flags = 0
        if vk_code in (VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN):
            flags |= KEYEVENTF_EXTENDEDKEY
        if not is_press:
            flags |= KEYEVENTF_KEYUP
        user32.keybd_event(vk_code, scan_code, flags, 0)
    except Exception:
        pass


def release_all_keys():
    """Safety cleanup: release all potentially held keys (DirectInput + Pynput + WinAPI)."""
    global horizontal_state, vertical_state, is_jumping
    try:
        # DirectInput releases
        for k in ('left', 'right', 'up', 'down', 'a', 'd', 'w', 's'):
            try:
                pydirectinput.keyUp(k)
            except Exception:
                pass

        # Pynput releases
        keyboard.release(Key.left)
        keyboard.release(Key.right)
        keyboard.release(Key.up)
        keyboard.release(Key.down)
        keyboard.release('a')
        keyboard.release('d')
        keyboard.release('w')
        keyboard.release('s')

        # Windows low-level releases
        for vk in (VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN, VK_A, VK_D, VK_W, VK_S):
            _win_key(vk, False)
    except Exception as e:
        print(f"Error releasing keys during cleanup: {e}")
    horizontal_state = "none"
    vertical_state = "none"
    is_jumping = False


def set_horizontal_state(new_state: str):
    """
    State machine for Left/Right controls (Arrow keys + 'A'/'D').
    Fires DirectInput, Pynput, and WinAPI key events.
    """
    global horizontal_state
    if new_state == horizontal_state:
        return

    # Release previous key if active
    if horizontal_state == "left":
        try:
            pydirectinput.keyUp('left')
            pydirectinput.keyUp('a')
        except Exception:
            pass
        keyboard.release(Key.left)
        keyboard.release('a')
        _win_key(VK_LEFT, False)
        _win_key(VK_A, False)
    elif horizontal_state == "right":
        try:
            pydirectinput.keyUp('right')
            pydirectinput.keyUp('d')
        except Exception:
            pass
        keyboard.release(Key.right)
        keyboard.release('d')
        _win_key(VK_RIGHT, False)
        _win_key(VK_D, False)

    # Press new key if entering a directional state
    if new_state == "left":
        try:
            pydirectinput.keyDown('left')
            pydirectinput.keyDown('a')
        except Exception:
            pass
        keyboard.press(Key.left)
        keyboard.press('a')
        _win_key(VK_LEFT, True)
        _win_key(VK_A, True)
    elif new_state == "right":
        try:
            pydirectinput.keyDown('right')
            pydirectinput.keyDown('d')
        except Exception:
            pass
        keyboard.press(Key.right)
        keyboard.press('d')
        _win_key(VK_RIGHT, True)
        _win_key(VK_D, True)

    horizontal_state = new_state


def set_duck_state(is_ducking: bool):
    """
    State machine for Down / Crouch controls (Down Arrow + 'S').
    Holds Down / 'S' while ducking, releases when standing up.
    """
    global vertical_state
    if is_ducking and vertical_state != "down":
        try:
            pydirectinput.keyDown('down')
            pydirectinput.keyDown('s')
        except Exception:
            pass
        keyboard.press(Key.down)
        keyboard.press('s')
        _win_key(VK_DOWN, True)
        _win_key(VK_S, True)
        vertical_state = "down"
    elif not is_ducking and vertical_state == "down":
        try:
            pydirectinput.keyUp('down')
            pydirectinput.keyUp('s')
        except Exception:
            pass
        keyboard.release(Key.down)
        keyboard.release('s')
        _win_key(VK_DOWN, False)
        _win_key(VK_S, False)
        vertical_state = "none"


def trigger_jump(current_time: float):
    """
    Non-blocking jump trigger: presses Up Arrow + 'W' and schedules its release.
    """
    global is_jumping, jump_release_time, last_jump_time
    try:
        pydirectinput.keyDown('up')
        pydirectinput.keyDown('w')
    except Exception:
        pass
    keyboard.press(Key.up)
    keyboard.press('w')
    _win_key(VK_UP, True)
    _win_key(VK_W, True)
    is_jumping = True
    jump_release_time = current_time + JUMP_TAP_DURATION
    last_jump_time = current_time


def update_jump_state(current_time: float):
    """Releases Up Arrow + 'W' once the tap duration has elapsed."""
    global is_jumping, jump_release_time
    if is_jumping and current_time >= jump_release_time:
        try:
            pydirectinput.keyUp('up')
            pydirectinput.keyUp('w')
        except Exception:
            pass
        keyboard.release(Key.up)
        keyboard.release('w')
        _win_key(VK_UP, False)
        _win_key(VK_W, False)
        is_jumping = False


def reset_calibration():
    """Reset baseline so the user can re-calibrate in their current position."""
    global baseline_x, baseline_y, calib_x_samples, calib_y_samples, prev_shoulder_y
    with state_lock:
        baseline_x = None
        baseline_y = None
        calib_x_samples = []
        calib_y_samples = []
        prev_shoulder_y = None
        release_all_keys()
    print("[Backend] Baseline calibration reset requested.")


# ==============================================================================
# CAMERA & POSE PROCESSING LOOP
# ==============================================================================
def process_camera_stream(show_debug_window: bool = False, camera_idx: int = CAMERA_INDEX):
    """
    Main capture and pose detection loop.
    Extracts pose landmarks, runs gesture state machine, simulates pynput keys,
    draws skeleton overlay, and broadcasts frames & state to WebSockets.
    """
    global baseline_x, baseline_y, calib_x_samples, calib_y_samples
    global prev_shoulder_y, last_jump_time, current_dx, current_dy
    global pose_detected, camera_active, running

    mp_pose = mp.solutions.pose
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles

    pose = mp_pose.Pose(
        model_complexity=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.6,
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

            current_time = time.time()

            # Maintain non-blocking jump key release
            with state_lock:
                update_jump_state(current_time)

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
                    l_sh = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
                    r_sh = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]
                    l_hip = landmarks[mp_pose.PoseLandmark.LEFT_HIP]
                    r_hip = landmarks[mp_pose.PoseLandmark.RIGHT_HIP]

                    # Horizontal center: average x of shoulders and hips
                    center_x = (l_sh.x + r_sh.x + l_hip.x + r_hip.x) / 4.0
                    # Vertical height: average y of shoulders
                    shoulder_y = (l_sh.y + r_sh.y) / 2.0

                    # 2. Calibration Phase
                    if baseline_x is None:
                        calib_x_samples.append(center_x)
                        calib_y_samples.append(shoulder_y)
                        progress = len(calib_x_samples)
                        current_dx = 0.0
                        current_dy = 0.0

                        # Draw calibration overlay on video frame
                        cv2.rectangle(frame, (15, 15), (420, 75), (30, 30, 30), -1)
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
                            "Stand still in neutral position",
                            (25, 68),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (200, 200, 200),
                            1,
                        )

                        if progress >= CALIBRATION_FRAMES:
                            baseline_x = sum(calib_x_samples) / len(calib_x_samples)
                            baseline_y = sum(calib_y_samples) / len(calib_y_samples)
                            print(f"[Backend] Calibrated: baseline_x={baseline_x:.3f}, baseline_y={baseline_y:.3f}")

                    # 3. Tracking & Action Phase
                    else:
                        dx = center_x - baseline_x
                        dy = shoulder_y - baseline_y
                        current_dx = dx
                        current_dy = dy

                        # --- Horizontal Tracking (Left / Right) ---
                        # In mirrored view: physical left -> center_x increases (dx > 0)
                        # physical right -> center_x decreases (dx < 0)
                        if dx > X_THRESHOLD:
                            set_horizontal_state("left")
                        elif dx < -X_THRESHOLD:
                            set_horizontal_state("right")
                        else:
                            set_horizontal_state("none")

                        # --- Vertical Tracking: Jump ---
                        velocity_y = (shoulder_y - prev_shoulder_y) if prev_shoulder_y is not None else 0.0

                        if (
                            dy < -Y_JUMP_THRESHOLD
                            and velocity_y < -JUMP_VELOCITY_THRESHOLD
                            and (current_time - last_jump_time) > JUMP_COOLDOWN
                        ):
                            trigger_jump(current_time)

                        # --- Vertical Tracking: Duck (Hold Down Arrow) ---
                        is_ducking = (dy > Y_DUCK_THRESHOLD) and not is_jumping
                        set_duck_state(is_ducking)

                        prev_shoulder_y = shoulder_y

                        # Draw baseline reference guide on preview
                        bx_px = int(baseline_x * w)
                        by_px = int(baseline_y * h)
                        cv2.circle(frame, (bx_px, by_px), 6, (255, 255, 0), -1)

                        if show_debug_window:
                            cv2.rectangle(frame, (15, 15), (410, 115), (20, 20, 20), -1)
                            cv2.rectangle(frame, (15, 15), (410, 115), (70, 70, 70), 1)
                            cv2.putText(
                                frame,
                                f"Offset: dx={dx:+.2f} | dy={dy:+.2f}",
                                (25, 42),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.65,
                                (255, 255, 255),
                                2,
                            )
                            h_color = (0, 255, 0) if horizontal_state != "none" else (180, 180, 180)
                            v_label = "JUMP" if is_jumping else (vertical_state if vertical_state != "none" else "none")
                            v_color = (0, 255, 255) if is_jumping else ((0, 255, 0) if vertical_state != "none" else (180, 180, 180))
                            cv2.putText(
                                frame,
                                f"H-Key: {horizontal_state.upper()}",
                                (25, 75),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.65,
                                h_color,
                                2,
                            )
                            cv2.putText(
                                frame,
                                f"V-Key: {v_label.upper()}",
                                (230, 75),
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
                    set_duck_state(False)
                    prev_shoulder_y = None

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
                v_label = "jump" if is_jumping else vertical_state
                state_data = {
                    "type": "state",
                    "h_state": horizontal_state,
                    "v_state": v_label,
                    "is_jumping": is_jumping,
                    "dx": round(current_dx, 3),
                    "dy": round(current_dy, 3),
                    "calibrated": baseline_x is not None,
                    "calib_progress": len(calib_x_samples),
                    "calib_total": CALIBRATION_FRAMES,
                    "pose_detected": pose_detected,
                }

            # If there are active WebSocket connections, encode frame and broadcast
            if active_websockets and main_event_loop:
                small_frame = cv2.resize(frame, (480, int(480 * h / w)))
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 65]
                _, buffer = cv2.imencode(".jpg", small_frame, encode_param)
                jpg_as_text = base64.b64encode(buffer).decode("utf-8")

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
                if msg.get("action") == "recalibrate":
                    reset_calibration()
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
        print(" Recalibrate endpoint: POST /recalibrate")
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