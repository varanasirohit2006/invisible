"""Suggest scoped destinations from prior moves, without changing any files."""

import re
from collections import Counter
from pathlib import Path

from shared.paths import Scope, ScopeError

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}
GENERIC_WORDS = {
    "image",
    "img",
    "photo",
    "picture",
    "pic",
    "download",
    "file",
    "copy",
    "screenshot",
    "screen",
    "shot",
    "untitled",
    "edited",
    "final",
    "dsc",
    "px",
    "new",
    "next",
    "old",
    "sample",
    "test",
    "lesson",
}


def name_words(value: str) -> set[str]:
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    words = set()
    for word in re.findall(r"[^\W\d_]+", value.casefold()):
        if word == "buses":
            word = "bus"
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        if len(word) >= 3 and word not in GENERIC_WORDS:
            words.add(word)
    return words


def file_family(path: Path) -> str:
    suffix = path.suffix.casefold()
    return "image" if suffix in IMAGE_EXTENSIONS else suffix


def suggest_destination(source: Path, moves: list[dict], scope: Scope) -> dict:
    groups: dict[str, dict] = {}
    seen = set()
    for move in moves:
        try:
            old = scope.check(move.get("old_path") or "")
            new = scope.check(move.get("new_path") or "")
        except (ScopeError, OSError):
            continue
        # Learn routes from the same starting folder and kind of file. Another
        # workflow elsewhere must not silently decide this file's destination.
        if old.parent != source.parent or old.parent == new.parent:
            continue
        if file_family(old) != file_family(source) or file_family(new) != file_family(source):
            continue
        if not new.parent.is_dir() or (old, new) in seen:
            continue
        seen.add((old, new))
        folder = str(new.parent)
        group = groups.setdefault(
            folder,
            {
                "folder": folder,
                "examples": 0,
                "words": set(),
                "folder_words": name_words(new.parent.name),
            },
        )
        group["examples"] += 1
        group["words"].update(name_words(old.stem) | name_words(new.stem))

    source_words = name_words(source.stem)
    word_destinations = Counter(word for group in groups.values() for word in group["words"])
    category_words = {word for group in groups.values() for word in group["folder_words"]}
    source_categories = source_words & category_words
    candidates = []
    for group in groups.values():
        folder_matches = source_words & group["folder_words"]
        distinct_matches = {
            word
            for word in source_words & group["words"]
            if word_destinations[word] == 1 or word in category_words
        }
        matches = folder_matches | distinct_matches
        if source_categories:
            # Category words such as bus/car beat incidental shared words such
            # as red/next, while conflicting examples for that category ask.
            matches = source_categories & (group["folder_words"] | group["words"])
        candidates.append(
            {
                "folder": group["folder"],
                "examples": group["examples"],
                "matched_words": sorted(matches),
                "reason": (
                    f"The name matches {', '.join(sorted(matches))} in your previous filing choices."
                    if matches
                    else "You previously moved this kind of file here."
                ),
            }
        )
    candidates.sort(
        key=lambda item: (-bool(item["matched_words"]), -item["examples"], item["folder"])
    )
    matching = [candidate for candidate in candidates if candidate["matched_words"]]
    selected = matching[0] if len(matching) == 1 else None
    return {
        "source_file": str(source),
        "destination_folder": selected["folder"] if selected else None,
        "status": "suggested" if selected else ("uncertain" if candidates else "no_history"),
        "reason": (
            selected["reason"]
            if selected
            else "More than one destination matches. Choose the right folder for this file."
            if len(matching) > 1
            else "The file name does not identify one destination. Choose a folder below or edit the path."
            if candidates
            else "No previous moves from this folder identify a destination yet. Choose one for this file."
        ),
        "candidates": candidates[:20],
    }
