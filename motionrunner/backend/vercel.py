import json
import os
import time
from typing import Dict, List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
GAME_DIR = os.path.join(PROJECT_DIR, "game")
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
SCORES_FILE = os.path.join(PROJECT_DIR, "scores.json")
DEFAULT_SCORES = [
    {"id": "score_1", "name": "MotionRunner", "score": 0, "date": ""},
]


app = FastAPI(title="MotionRunner Web API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_scores() -> List[Dict]:
    try:
        with open(SCORES_FILE, "r", encoding="utf-8") as scores_file:
            return json.load(scores_file)
    except (OSError, ValueError):
        return DEFAULT_SCORES.copy()


def save_scores(scores: List[Dict]) -> None:
    try:
        with open(SCORES_FILE, "w", encoding="utf-8") as scores_file:
            json.dump(scores, scores_file, indent=2)
    except OSError:
        pass


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "camera_active": False,
        "pose_detected": False,
        "calibrated": False,
    }


@app.post("/recalibrate")
def recalibrate():
    return {"status": "ok", "message": "Camera control runs in the local backend."}


@app.get("/state")
def state():
    return {
        "h_state": "none",
        "v_state": "none",
        "is_jumping": False,
        "dx": 0,
        "dy": 0,
        "calibrated": False,
        "calib_progress": 0,
        "calib_total": 0,
        "pose_detected": False,
    }


@app.get("/scores")
def get_scores():
    return load_scores()


@app.post("/scores")
async def add_score(request: Request):
    try:
        body = await request.json()
        name = str(body.get("name", "")).strip()[:20]
        score_value = int(body.get("score", 0))
        if not name or score_value <= 0:
            return JSONResponse(status_code=400, content={"error": "Invalid name or score"})

        scores = load_scores()
        scores.append({
            "id": f"score_{int(time.time() * 1000)}",
            "name": name,
            "score": score_value,
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        scores.sort(key=lambda score: score.get("score", 0), reverse=True)
        scores = scores[:50]
        save_scores(scores)
        return {"status": "ok", "scores": scores}
    except (TypeError, ValueError, AttributeError):
        return JSONResponse(status_code=400, content={"error": "Invalid score payload"})


@app.delete("/scores")
def clear_scores():
    save_scores(DEFAULT_SCORES.copy())
    return {"status": "ok", "scores": DEFAULT_SCORES}


if os.path.exists(GAME_DIR):
    app.mount("/game", StaticFiles(directory=GAME_DIR, html=True), name="game")

if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")