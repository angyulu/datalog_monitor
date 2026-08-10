"""JSON-backed persistence: app-level config, per-folder runcard tags, per-folder thresholds."""
import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
APP_CONFIG_PATH = APP_DIR / "config.json"

RUNCARD_TAGS_FILENAME = "runcard_tags.json"
THRESHOLDS_FILENAME = "thresholds.json"

DEFAULT_TOLERANCE_PCT = 5.0


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp_path.replace(path)


# ---- app-level config (lives next to the app, not the data) ----

def load_app_config() -> dict:
    return _read_json(APP_CONFIG_PATH, {})


def get_last_folder() -> str | None:
    return load_app_config().get("last_folder")


def set_last_folder(folder: str) -> None:
    config = load_app_config()
    config["last_folder"] = folder
    _write_json(APP_CONFIG_PATH, config)


# ---- runcard tags (sidecar file inside the selected data folder) ----

def _relative_key(root_folder: str, file_path: str) -> str:
    return Path(file_path).relative_to(Path(root_folder)).as_posix()


def load_runcard_tags(root_folder: str) -> dict:
    return _read_json(Path(root_folder) / RUNCARD_TAGS_FILENAME, {})


def set_runcard_tag(root_folder: str, file_path: str, tag: str) -> None:
    tags = load_runcard_tags(root_folder)
    key = _relative_key(root_folder, file_path)
    if tag:
        tags[key] = tag
    else:
        tags.pop(key, None)
    _write_json(Path(root_folder) / RUNCARD_TAGS_FILENAME, tags)


def get_runcard_tag(root_folder: str, file_path: str, tags: dict | None = None) -> str:
    tags = tags if tags is not None else load_runcard_tags(root_folder)
    return tags.get(_relative_key(root_folder, file_path), "")


def move_runcard_tag(root_folder: str, old_path: str, new_path: str) -> None:
    """Re-key a run's tag entry after its file has been renamed on disk."""
    tags = load_runcard_tags(root_folder)
    old_key = _relative_key(root_folder, old_path)
    if old_key not in tags:
        return
    new_key = _relative_key(root_folder, new_path)
    tags[new_key] = tags.pop(old_key)
    _write_json(Path(root_folder) / RUNCARD_TAGS_FILENAME, tags)


# ---- thresholds (sidecar file inside the selected data folder) ----

def load_thresholds(root_folder: str) -> dict:
    defaults = {"global_default_pct": DEFAULT_TOLERANCE_PCT, "overrides": {}}
    stored = _read_json(Path(root_folder) / THRESHOLDS_FILENAME, {})
    defaults.update(stored)
    return defaults


def save_thresholds(root_folder: str, thresholds: dict) -> None:
    _write_json(Path(root_folder) / THRESHOLDS_FILENAME, thresholds)


def get_tolerance_pct(thresholds: dict, pair_name: str) -> float:
    return thresholds.get("overrides", {}).get(pair_name, thresholds["global_default_pct"])
