"""Renaming run CSV files to <timestamp>[~tag].csv, keeping runcard tags in sync."""
from dataclasses import dataclass
from pathlib import Path

from . import storage
from .scanner import RunMetadata, scan_folder

TIMESTAMP_FORMAT = "%Y-%m-%d_%H%M%S"
TAG_DELIMITER = "~"
_ILLEGAL_FILENAME_CHARS = set('\\/:*?"<>|')


def sanitize_tag_for_filename(tag: str) -> str:
    """Make a runcard tag safe to embed in a filename.

    Only the filename derivation is sanitized -- the tag stored in
    runcard_tags.json (used for display/search) is kept exactly as typed.
    """
    cleaned = "".join(
        "-" if ch in _ILLEGAL_FILENAME_CHARS or ch == TAG_DELIMITER else ch
        for ch in tag
    )
    return cleaned.strip(" .")


def target_filename(start_time, tag: str, suffix: str) -> str:
    stamp = start_time.strftime(TIMESTAMP_FORMAT)
    safe_tag = sanitize_tag_for_filename(tag) if tag else ""
    if safe_tag:
        return f"{stamp}{TAG_DELIMITER}{safe_tag}{suffix}"
    return f"{stamp}{suffix}"


@dataclass(frozen=True)
class RenamePlan:
    path: str
    new_path: str
    will_change: bool
    collision: bool


def _plan_for(meta: RunMetadata, tag: str) -> RenamePlan:
    src = Path(meta.path)
    dest = src.with_name(target_filename(meta.start_time, tag, src.suffix))
    will_change = dest != src
    return RenamePlan(
        path=meta.path, new_path=str(dest),
        will_change=will_change, collision=will_change and dest.exists(),
    )


def plan_single_rename(root_folder: str, meta: RunMetadata) -> RenamePlan:
    return _plan_for(meta, storage.get_runcard_tag(root_folder, meta.path))


def plan_renames(root_folder: str) -> list[RenamePlan]:
    """Compute the target name for every run in the folder tree, without touching disk."""
    tags = storage.load_runcard_tags(root_folder)
    return [
        _plan_for(meta, storage.get_runcard_tag(root_folder, meta.path, tags))
        for meta in scan_folder(root_folder)
    ]


class RenameCollision(Exception):
    def __init__(self, target_path: str):
        self.target_path = target_path
        super().__init__(f'A file named "{Path(target_path).name}" already exists.')


def apply_rename(root_folder: str, plan: RenamePlan) -> None:
    """Rename one file on disk and move its tag entry to the new key. Raises on failure."""
    if plan.collision:
        raise RenameCollision(plan.new_path)
    Path(plan.path).rename(plan.new_path)
    storage.move_runcard_tag(root_folder, plan.path, plan.new_path)


@dataclass(frozen=True)
class SweepResult:
    renamed: list[tuple[str, str]]
    skipped: list[tuple[str, str]]


def execute_sweep(root_folder: str, plans: list[RenamePlan]) -> SweepResult:
    """Apply every plan, skipping (not aborting on) individual failures."""
    renamed = []
    skipped = []
    for plan in plans:
        try:
            apply_rename(root_folder, plan)
        except (RenameCollision, OSError) as exc:
            skipped.append((plan.path, str(exc)))
            continue
        renamed.append((plan.path, plan.new_path))
    return SweepResult(renamed=renamed, skipped=skipped)
