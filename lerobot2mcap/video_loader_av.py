"""Video loader using PyAV for better codec support (including AV1).

This module provides a drop-in replacement for tabular2mcap's load_video_data
function, using PyAV instead of OpenCV for video decoding.

PyAV supports more codecs including AV1, which OpenCV's VideoCapture may
struggle with on some platforms.

It also provides video slicing functionality for LeRobot v3.0 datasets
where multiple episodes are merged into single video files.
"""

import logging
from pathlib import Path

import av
import numpy as np

logger = logging.getLogger(__name__)


def load_video_data_av(file_path: Path) -> tuple[list[np.ndarray], dict]:
    """
    Load video using PyAV (supports AV1 and other codecs).

    This is a drop-in replacement for tabular2mcap's load_video_data function.

    Args:
        file_path: Path to the video file

    Returns:
        Tuple of (frames, video_properties) where:
        - frames: List of numpy arrays (BGR format, like OpenCV)
        - video_properties: Dict with fps, frame_count, width, height
    """
    container = av.open(str(file_path))
    video_stream = container.streams.video[0]
    logger.debug(f"Loading video with PyAV from {file_path}")

    # Get video properties
    fps = float(video_stream.average_rate) if video_stream.average_rate else 30.0
    frame_count = video_stream.frames or 0
    width = video_stream.width
    height = video_stream.height

    video_props = {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
    }

    # Decode all frames
    frames = []
    for frame in container.decode(video=0):
        # Convert to numpy array (BGR format like OpenCV)
        img = frame.to_ndarray(format="bgr24")
        frames.append(img)

    container.close()

    logger.debug(
        f"Loaded {len(frames)} frames from {file_path} "
        f"(codec: {video_stream.codec_context.name})"
    )

    return frames, video_props


def load_video_slice_av(
    file_path: Path,
    from_timestamp: float,
    to_timestamp: float,
) -> tuple[list[np.ndarray], dict]:
    """
    Load a slice of video frames between two timestamps.

    This is used for LeRobot v3.0 datasets where multiple episodes
    are merged into single video files.

    Args:
        file_path: Path to the video file
        from_timestamp: Start timestamp in seconds (inclusive)
        to_timestamp: End timestamp in seconds (exclusive)

    Returns:
        Tuple of (frames, video_properties) where:
        - frames: List of numpy arrays (BGR format, like OpenCV)
        - video_properties: Dict with fps, frame_count, width, height
    """
    container = av.open(str(file_path))
    video_stream = container.streams.video[0]

    # Get video properties
    fps = float(video_stream.average_rate) if video_stream.average_rate else 30.0
    width = video_stream.width
    height = video_stream.height
    time_base = float(video_stream.time_base)

    logger.debug(
        f"Loading video slice from {file_path} "
        f"[{from_timestamp:.3f}s - {to_timestamp:.3f}s]"
    )

    # Seek to the start timestamp
    # PyAV seek uses pts (presentation timestamp) in stream time_base units
    start_pts = int(from_timestamp / time_base)
    container.seek(start_pts, stream=video_stream)

    # Decode frames within the time range
    frames = []
    for frame in container.decode(video=0):
        # Get frame timestamp in seconds
        frame_ts = float(frame.pts * time_base)

        # Skip frames before start timestamp (seek might not be exact)
        if frame_ts < from_timestamp:
            continue

        # Stop when we reach the end timestamp
        if frame_ts >= to_timestamp:
            break

        # Convert to numpy array (BGR format like OpenCV)
        img = frame.to_ndarray(format="bgr24")
        frames.append(img)

    container.close()

    video_props = {
        "fps": fps,
        "frame_count": len(frames),
        "width": width,
        "height": height,
    }

    logger.debug(
        f"Loaded {len(frames)} frames from slice "
        f"[{from_timestamp:.3f}s - {to_timestamp:.3f}s]"
    )

    return frames, video_props


def save_video_slice(
    source_path: Path,
    output_path: Path,
    from_timestamp: float,
    to_timestamp: float,
    codec: str = "libx264",
) -> None:
    """
    Extract a slice of video and save it to a new file using ffmpeg.

    Args:
        source_path: Path to the source video file
        output_path: Path to save the output video
        from_timestamp: Start timestamp in seconds
        to_timestamp: End timestamp in seconds
        codec: Output codec (default: libx264 for H.264)
    """
    import subprocess

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Calculate duration
    duration = to_timestamp - from_timestamp

    # Use ffmpeg command line for reliable video slicing
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output file
        "-ss",
        str(from_timestamp),  # Start time (before -i for fast seek)
        "-i",
        str(source_path),  # Input file
        "-t",
        str(duration),  # Duration
        "-c:v",
        codec,  # Video codec
        "-pix_fmt",
        "yuv420p",  # Pixel format
        "-an",  # No audio
        "-loglevel",
        "error",  # Reduce verbosity
        str(output_path),  # Output file
    ]

    logger.debug(f"Running ffmpeg: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed with code {result.returncode}: {result.stderr}"
        )

    logger.debug(
        f"Saved video slice to {output_path} "
        f"({from_timestamp:.3f}s - {to_timestamp:.3f}s)"
    )
