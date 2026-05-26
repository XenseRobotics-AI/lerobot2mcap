"""Video utilities for LeRobot v3.0 dataset conversion.

Provides video slicing functionality for LeRobot v3.0 datasets where multiple
episodes are merged into single video files.
"""

import subprocess
from pathlib import Path

from .logger import get_logger

logger = get_logger("video_loader")


def save_video_slice_h264(
    source_path: Path,
    output_path: Path,
    from_timestamp: float,
    to_timestamp: float,
    preset: str = "ultrafast",
    crf: int = 23,
) -> None:
    """Extract a slice and re-encode it as an all-keyframe H.264 Annex-B bitstream.

    Single ffmpeg call does both jobs (slice + reencode with ``-g 1``) and writes
    the raw bitstream directly. Downstream we just read the bytes and split on
    SPS boundaries — no PyAV decode, no second ffmpeg pass, no Python-side
    frame feeding loop. This avoids the GIL bottleneck the previous
    decode-then-re-encode pipeline hit.

    Args:
        source_path: Path to the source merged-episode video file.
        output_path: Path to write the .h264 bitstream to.
        from_timestamp: Slice start in seconds.
        to_timestamp: Slice end in seconds.
        preset: libx264 preset (encoding speed/efficiency knob).
        crf: libx264 CRF quality (0-51, lower = better, 23 is default).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = to_timestamp - from_timestamp

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(from_timestamp),
        "-i",
        str(source_path),
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-g",
        "1",  # every frame a keyframe
        "-keyint_min",
        "1",
        "-bf",
        "0",  # no B frames
        "-tune",
        "zerolatency",
        "-flags",
        "+global_header",
        "-bsf:v",
        "dump_extra",  # ensure each frame carries SPS/PPS
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-f",
        "h264",
        "-loglevel",
        "error",
        str(output_path),
    ]

    logger.debug(f"Running ffmpeg: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed with code {result.returncode}: {result.stderr}"
        )

    logger.debug(
        f"Saved h264 slice to {output_path} "
        f"({from_timestamp:.3f}s - {to_timestamp:.3f}s)"
    )
