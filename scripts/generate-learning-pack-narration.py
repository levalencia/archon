#!/usr/bin/env python3
"""Generate measured Kokoro narration for one structured learning pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

VOICE = "af_nova"
VIDEO_SCENE_SECONDS = 16.0
AUDIO_GAP_SECONDS = 0.35


def _run(*args: str) -> None:
    subprocess.run(args, check=True)


def _probe(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(result.stdout.strip())
    if duration <= 0.5:
        raise ValueError(f"narration is too short: {path}")
    return duration


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spoken(text: str) -> str:
    replacements = (
        (r"\bCI/CD\b", "C I slash C D"),
        (r"\bOIDC\b", "O I D C"),
        (r"\bUAMI\b", "user assigned managed identity"),
        (r"\bACR\b", "A C R"),
        (r"\bOTLP\b", "O T L P"),
        (r"\bVM\b", "V M"),
        (r"dev\.cogentrex\.com", "dev dot cogentrex dot com"),
        (r"network=none", "network equals none"),
    )
    for pattern, value in replacements:
        text = re.sub(pattern, value, text)
    return text


def _tts(text: str, output: Path) -> None:
    text_path = output.with_suffix(".txt")
    raw_path = output.with_name(output.stem + "-raw.wav")
    text_path.write_text(_spoken(text), encoding="utf-8")
    _run(
        "npx",
        "--yes",
        "hyperframes@0.8.27",
        "tts",
        str(text_path),
        "--voice",
        VOICE,
        "--speed",
        "1.0",
        "--output",
        str(raw_path),
    )
    _run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(raw_path),
        "-ac",
        "1",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(output),
    )
    raw_path.unlink()
    if output.stat().st_size == 0:
        raise ValueError(f"empty narration: {output}")


def _silence(path: Path, seconds: float) -> None:
    _run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-t",
        f"{seconds:.3f}",
        "-c:a",
        "pcm_s16le",
        str(path),
    )


def _concat(parts: list[Path], output: Path) -> None:
    list_path = output.with_suffix(".concat.txt")
    list_path.write_text("".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8")
    _run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac",
        "1",
        "-ar",
        "44100",
        "-b:a",
        "128k",
        str(output),
    )


def _timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _write_vtt(path: Path, segments: list[dict[str, Any]]) -> None:
    rows = ["WEBVTT", ""]
    for index, segment in enumerate(segments, 1):
        rows.extend(
            [
                str(index),
                f"{_timestamp(segment['start_seconds'])} --> {_timestamp(segment['end_seconds'])}",
                segment["text"],
                "",
            ]
        )
    path.write_text("\n".join(rows), encoding="utf-8")


def _audio_lesson(script_path: Path, work: Path, output: Path) -> dict[str, Any]:
    payload = json.loads(script_path.read_text())
    gap = work / "gap.wav"
    _silence(gap, AUDIO_GAP_SECONDS)
    parts: list[Path] = []
    cursor = 0.0
    for index, segment in enumerate(payload["segments"], 1):
        wav = work / f"audio-{index:02d}.wav"
        _tts(segment["text"], wav)
        duration = _probe(wav)
        segment["start_seconds"] = round(cursor, 3)
        segment["end_seconds"] = round(cursor + duration, 3)
        cursor += duration
        parts.append(wav)
        if index < len(payload["segments"]):
            parts.append(gap)
            cursor += AUDIO_GAP_SECONDS
    _concat(parts, output)
    final_duration = _probe(output)
    payload["duration_seconds"] = round(final_duration, 3)
    script_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_vtt(script_path.with_name("captions.vtt"), payload["segments"])
    return {"duration_seconds": final_duration, "segments": len(payload["segments"])}


def _fit_video_segment(source: Path, output: Path) -> None:
    duration = _probe(source)
    target_voice = VIDEO_SCENE_SECONDS - 0.6
    speed = max(1.0, duration / target_voice)
    if speed > 2.0:
        raise ValueError(f"video narration cannot fit one scene: {source} ({duration:.2f}s)")
    _run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-af",
        f"atempo={speed:.6f},apad,atrim=duration={VIDEO_SCENE_SECONDS:.3f}",
        "-ac",
        "1",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(output),
    )
    actual = _probe(output)
    if abs(actual - VIDEO_SCENE_SECONDS) > 0.05:
        raise ValueError(f"video scene duration mismatch: {actual}")


def _video_narration(
    script_path: Path, storyboard_path: Path, work: Path, output: Path
) -> dict[str, Any]:
    payload = json.loads(script_path.read_text())
    parts: list[Path] = []
    for index, segment in enumerate(payload["segments"], 1):
        raw = work / f"video-{index:02d}-voice.wav"
        fitted = work / f"video-{index:02d}.wav"
        _tts(segment["text"], raw)
        _fit_video_segment(raw, fitted)
        start = (index - 1) * VIDEO_SCENE_SECONDS
        segment["start_seconds"] = round(start, 3)
        segment["end_seconds"] = round(start + VIDEO_SCENE_SECONDS, 3)
        parts.append(fitted)
    _concat(parts, output)
    final_duration = _probe(output)
    expected = len(parts) * VIDEO_SCENE_SECONDS
    if abs(final_duration - expected) > 0.1:
        raise ValueError(f"video narration duration mismatch: {final_duration} != {expected}")
    payload["duration_seconds"] = round(final_duration, 3)
    script_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_vtt(script_path.with_name("captions.vtt"), payload["segments"])
    storyboard = json.loads(storyboard_path.read_text())
    for scene, segment in zip(storyboard["scenes"], payload["segments"], strict=True):
        scene["duration_seconds"] = VIDEO_SCENE_SECONDS
        scene["start_seconds"] = segment["start_seconds"]
        scene["end_seconds"] = segment["end_seconds"]
    storyboard_path.write_text(json.dumps(storyboard, indent=2) + "\n", encoding="utf-8")
    return {"duration_seconds": final_duration, "segments": len(payload["segments"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--media-output", type=Path, required=True)
    parser.add_argument("--pack-id", required=True)
    args = parser.parse_args()

    pack = args.pack_id
    published = args.library / "published" / pack
    media_dir = args.media_output / pack
    work = media_dir / "segments"
    work.mkdir(parents=True, exist_ok=True)
    audio_output = media_dir / f"{pack}.mp3"
    video_output = media_dir / f"{pack}.video-narration.mp3"

    audio = _audio_lesson(published / f"{pack}-audio" / "audio-script.json", work, audio_output)
    video = _video_narration(
        published / f"{pack}-video" / "video-script.json",
        published / f"{pack}-video" / "storyboard.json",
        work,
        video_output,
    )
    shutil.copyfile(
        published / f"{pack}-audio" / "audio-script.json",
        media_dir / f"{pack}.audio-script.json",
    )
    shutil.copyfile(
        published / f"{pack}-audio" / "captions.vtt",
        media_dir / f"{pack}.audio-captions.vtt",
    )
    shutil.copyfile(
        published / f"{pack}-video" / "video-script.json",
        media_dir / f"{pack}.video-script.json",
    )
    shutil.copyfile(
        published / f"{pack}-video" / "storyboard.json",
        media_dir / f"{pack}.video-storyboard.json",
    )
    shutil.copyfile(
        published / f"{pack}-video" / "captions.vtt",
        media_dir / f"{pack}.video-captions.vtt",
    )
    manifest = {
        "schema": "cogentrex.learning-narration/v1",
        "pack_id": pack,
        "voice": VOICE,
        "audio": {**audio, "file": audio_output.name, "sha256": _sha(audio_output)},
        "video": {**video, "file": video_output.name, "sha256": _sha(video_output)},
    }
    (media_dir / "narration-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
