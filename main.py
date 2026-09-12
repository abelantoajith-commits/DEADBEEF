"""
Body Motion Keyboard Controller
================================
Control games (like Subway Surfers) and applications using full-body motion 
detected via your webcam and MediaPipe Pose!

Key Mappings:
  - Lean/Step LEFT   -> Holds Left Arrow
  - Lean/Step RIGHT  -> Holds Right Arrow
  - JUMP             -> Taps Up Arrow (~150ms tap duration, cooldown ~0.6s)
  - DUCK / Crouch    -> Holds Down Arrow

Installation:
    pip install mediapipe opencv-python pynput

Usage:
    python main.py

Controls in Preview Window:
    q  -> Quit cleanly (releases any pressed keys)
    r  -> Recalibrate neutral standing baseline

Note for macOS Users:
    pynput requires Accessibility permissions on macOS. 
    Ensure your terminal or IDE (Terminal, iTerm, VS Code, etc.) is enabled under:
    System Settings -> Privacy & Security -> Accessibility
"""

import time
import cv2
import mediapipe as mp
from pynput.keyboard import Controller, Key

# ==============================================================================
# CONFIGURATION & THRESHOLDS (Tune these to your camera setup and body posture)
# ==============================================================================
CALIBRATION_FRAMES = 60          # Number of frames to average for neutral pose baseline

# Horizontal thresholds (normalized 0.0 - 1.0 coordinate delta)
X_THRESHOLD = 0.06               # Lateral displacement needed to trigger Left/Right

# Vertical thresholds (normalized 0.0 - 1.0 coordinate delta, Y increases downward)
Y_DUCK_THRESHOLD = 0.06          # Downward displacement from baseline to trigger Duck (Down Arrow)
Y_JUMP_THRESHOLD = 0.045         # Upward displacement from baseline required for Jump
JUMP_VELOCITY_THRESHOLD = 0.012  # Minimum per-frame upward velocity to distinguish jump from slow standing

# Jump timing parameters
JUMP_TAP_DURATION = 0.15         # Seconds to keep Up Arrow pressed during a jump
JUMP_COOLDOWN = 0.60             # Seconds between consecutive jump triggers

# Webcam and Window configuration
CAMERA_INDEX = 0                 # Default webcam device index
WINDOW_TITLE = "Body Motion Controller (Subway Surfers)"


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


def release_all_keys():
    """Safety cleanup: release all potentially held keys."""
    global horizontal_state, vertical_state, is_jumping
    try:
        if horizontal_state == "left":
            keyboard.release(Key.left)
        elif horizontal_state == "right":
            keyboard.release(Key.right)
        if vertical_state == "down":
            keyboard.release(Key.down)
        if is_jumping:
            keyboard.release(Key.up)
    except Exception as e:
        print(f"Error releasing keys during cleanup: {e}")
    horizontal_state = "none"
    vertical_state = "none"
    is_jumping = False


def set_horizontal_state(new_state):
    """
    State machine for Left/Right arrow keys.
    Prevents rapid key flickering by only firing press/release on state transitions.
    """
    global horizontal_state
    if new_state == horizontal_state:
        return

    # Release previous key if active
    if horizontal_state == "left":
        keyboard.release(Key.left)
    elif horizontal_state == "right":
        keyboard.release(Key.right)

    # Press new key if entering a directional state
    if new_state == "left":
        keyboard.press(Key.left)
    elif new_state == "right":
        keyboard.press(Key.right)

    horizontal_state = new_state


def set_duck_state(is_ducking):
    """
    State machine for Down arrow key (crouch/duck).
    Holds Down Arrow while ducking, releases when standing up.
    """
    global vertical_state
    if is_ducking and vertical_state != "down":
        keyboard.press(Key.down)
        vertical_state = "down"
    elif not is_ducking and vertical_state == "down":
        keyboard.release(Key.down)
        vertical_state = "none"


def trigger_jump(current_time):
    """
    Non-blocking jump trigger: presses Up Arrow and schedules its release.
    Does not block the video processing loop with sleep().
    """
    global is_jumping, jump_release_time, last_jump_time
    keyboard.press(Key.up)
    is_jumping = True
    jump_release_time = current_time + JUMP_TAP_DURATION
    last_jump_time = current_time


def update_jump_state(current_time):
    """Releases the Up Arrow once the tap duration has elapsed."""
    global is_jumping, jump_release_time
    if is_jumping and current_time >= jump_release_time:
        keyboard.release(Key.up)
        is_jumping = False


def reset_calibration():
    """Reset baseline so the user can re-calibrate in their current position."""
    global baseline_x, baseline_y, calib_x_samples, calib_y_samples, prev_shoulder_y
    baseline_x = None
    baseline_y = None
    calib_x_samples = []
    calib_y_samples = []
    prev_shoulder_y = None
    release_all_keys()


# ==============================================================================
# MAIN APPLICATION LOOP
# ==============================================================================
def main():
    global baseline_x, baseline_y, calib_x_samples, calib_y_samples
    global prev_shoulder_y, last_jump_time

    # Initialize MediaPipe Pose
    mp_pose = mp.solutions.pose
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles

    pose = mp_pose.Pose(
        model_complexity=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.6,
    )

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"Error: Could not open camera with index {CAMERA_INDEX}.")
        return

    print("==================================================")
    print(" Body Motion Controller Running!")
    print(" Stand in a neutral position to calibrate.")
    print(" Press 'r' to recalibrate at any time.")
    print(" Press 'q' to quit.")
    print("==================================================")

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                print("Warning: Failed to grab camera frame.")
                break

            current_time = time.time()

            # Maintain non-blocking jump key release
            update_jump_state(current_time)

            # Mirror frame horizontally for intuitive mirror-like feedback
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape

            # Convert BGR image to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb_frame)

            if results.pose_landmarks:
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
                # Vertical height: average y of shoulders (more responsive for jump/duck)
                shoulder_y = (l_sh.y + r_sh.y) / 2.0

                # 2. Calibration Phase
                if baseline_x is None:
                    calib_x_samples.append(center_x)
                    calib_y_samples.append(shoulder_y)
                    progress = len(calib_x_samples)

                    # Draw Calibration overlay
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
                        print(f"Calibrated: baseline_x={baseline_x:.3f}, baseline_y={baseline_y:.3f}")

                # 3. Tracking & Action Phase
                else:
                    # Offsets from neutral baseline
                    # dx < 0: moved Left | dx > 0: moved Right
                    # dy < 0: moved UP (jump) | dy > 0: moved DOWN (duck)
                    dx = center_x - baseline_x
                    dy = shoulder_y - baseline_y

                    # --- Horizontal Tracking (Left / Right) ---
                    if dx < -X_THRESHOLD:
                        set_horizontal_state("left")
                    elif dx > X_THRESHOLD:
                        set_horizontal_state("right")
                    else:
                        set_horizontal_state("none")

                    # --- Vertical Tracking: Jump ---
                    # Velocity: negative when rising fast
                    velocity_y = (shoulder_y - prev_shoulder_y) if prev_shoulder_y is not None else 0.0

                    if (
                        dy < -Y_JUMP_THRESHOLD
                        and velocity_y < -JUMP_VELOCITY_THRESHOLD
                        and (current_time - last_jump_time) > JUMP_COOLDOWN
                    ):
                        trigger_jump(current_time)

                    # --- Vertical Tracking: Duck (Hold Down Arrow) ---
                    # Only duck if not actively jumping
                    is_ducking = (dy > Y_DUCK_THRESHOLD) and not is_jumping
                    set_duck_state(is_ducking)

                    prev_shoulder_y = shoulder_y

                    # 4. HUD / Debug Overlay
                    # Draw baseline reference guide on preview
                    bx_px = int(baseline_x * w)
                    by_px = int(baseline_y * h)
                    cv2.circle(frame, (bx_px, by_px), 6, (255, 255, 0), -1)

                    # Status Box
                    cv2.rectangle(frame, (15, 15), (410, 115), (20, 20, 20), -1)
                    cv2.rectangle(frame, (15, 15), (410, 115), (70, 70, 70), 1)

                    # Offsets text
                    cv2.putText(
                        frame,
                        f"Offset: dx={dx:+.2f} | dy={dy:+.2f}",
                        (25, 42),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (255, 255, 255),
                        2,
                    )

                    # Horizontal & Vertical Key State text
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

                    # Calibration indicator
                    cv2.putText(
                        frame,
                        "Status: CALIBRATED (Active)",
                        (25, 102),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.50,
                        (0, 255, 128),
                        1,
                    )

            else:
                # No body detected - safely release held keys
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

            # Footer Controls Help Text
            cv2.putText(
                frame,
                "[Q] Quit   [R] Recalibrate Neutral Baseline",
                (20, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (220, 220, 220),
                1,
                cv2.LINE_AA,
            )

            # Display frame
            cv2.imshow(WINDOW_TITLE, frame)

            # Handle key events
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:  # 'q' or Esc
                break
            elif key == ord("r"):
                reset_calibration()
                print("Recalibrating baseline...")

    finally:
        # Cleanup: ensure no keyboard key remains held down
        print("Cleaning up and releasing keys...")
        release_all_keys()
        cap.release()
        cv2.destroyAllWindows()
        pose.close()
        print("Application exited cleanly.")


if __name__ == "__main__":
    main()