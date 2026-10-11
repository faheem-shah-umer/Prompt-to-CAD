from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = PROJECT_ROOT / "runs"
PROJECTS_DIR = PROJECT_ROOT / "projects"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
