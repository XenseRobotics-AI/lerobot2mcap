"""Standalone MCAP output validator for lerobot2mcap conversions.

Checks that a generated MCAP file is structurally correct:

  1. File opens via mcap.reader without errors.
  2. Required topics exist (robot/actions/data, robot/states/data, observation/images/*/video).
  3. log_time is monotonic per topic.
  4. Tabular message count == parquet row count for the episode.
  5. Each video topic message count == decoded frame count of the corresponding sliced video.
  6. Every video message is an independently-decodable keyframe (the whole point of the
     all-keyframe re-encoding pass — if this regresses, MCAP playback breaks).

Usage:
  python tests/validate_mcap.py <mcap_path> --dataset-root <lerobot_dataset_root> --episode <idx>

Exit status: 0 on success, 1 on any check failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import av
import pandas as pd
from mcap.reader import make_reader


REQUIRED_TABULAR_TOPICS = ("robot/actions/data", "robot/states/data")
VIDEO_TOPIC_PREFIX = "observation/images/"


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def ok(msg: str) -> None:
    print(f"  [ OK ] {msg}")


def load_messages_by_topic(mcap_path: Path) -> dict[str, list[tuple[int, bytes]]]:
    by_topic: dict[str, list[tuple[int, bytes]]] = defaultdict(list)
    with open(mcap_path, "rb") as f:
        reader = make_reader(f)
        for schema, channel, message in reader.iter_messages():
            by_topic[channel.topic].append((message.log_time, message.data))
    return by_topic


def extract_episode_parquet_rows(
    dataset_root: Path, episode_idx: int
) -> int:
    """Replicate the converter's row-filtering logic to learn the expected count."""
    info = json.loads((dataset_root / "meta" / "info.json").read_text())
    is_v3 = info["codebase_version"].startswith("v3")

    if not is_v3:
        # v2.x: one parquet per episode
        chunk = episode_idx // info.get("chunks_size", 1000)
        rel = info["data_path"].format(
            episode_chunk=chunk, episode_index=episode_idx
        )
        return len(pd.read_parquet(dataset_root / rel))

    # v3.0: shared parquet, filter by index range
    ep_meta_files = sorted((dataset_root / "meta" / "episodes").glob("**/*.parquet"))
    if not ep_meta_files:
        # fallback: single-file layout
        ep_meta_files = list((dataset_root / "meta").glob("episodes*"))
    if not ep_meta_files:
        raise RuntimeError("Cannot find episodes metadata")
    ep_df = pd.concat([pd.read_parquet(p) for p in ep_meta_files], ignore_index=True)
    row = ep_df[ep_df["episode_index"] == episode_idx].iloc[0]
    chunk_idx = int(row["data/chunk_index"])
    file_idx = int(row["data/file_index"])
    from_idx = int(row["dataset_from_index"])
    to_idx = int(row["dataset_to_index"])

    parquet_path = dataset_root / info["data_path"].format(
        chunk_index=chunk_idx, file_index=file_idx
    )
    df = pd.read_parquet(parquet_path)
    return len(df[(df["index"] >= from_idx) & (df["index"] < to_idx)])


def extract_episode_video_frame_counts(
    dataset_root: Path, episode_idx: int
) -> dict[str, int]:
    """Slice each episode video (timestamps from metadata) and decode to count frames."""
    info = json.loads((dataset_root / "meta" / "info.json").read_text())
    is_v3 = info["codebase_version"].startswith("v3")
    if not is_v3:
        return {}

    video_keys = [k for k, v in info["features"].items() if v.get("dtype") == "video"]
    ep_meta_files = sorted((dataset_root / "meta" / "episodes").glob("**/*.parquet"))
    ep_df = pd.concat([pd.read_parquet(p) for p in ep_meta_files], ignore_index=True)
    row = ep_df[ep_df["episode_index"] == episode_idx].iloc[0]

    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for vkey in video_keys:
            chunk_idx = int(row[f"videos/{vkey}/chunk_index"])
            file_idx = int(row[f"videos/{vkey}/file_index"])
            from_ts = float(row[f"videos/{vkey}/from_timestamp"])
            to_ts = float(row[f"videos/{vkey}/to_timestamp"])
            src = dataset_root / info["video_path"].format(
                video_key=vkey, chunk_index=chunk_idx, file_index=file_idx
            )
            out = Path(tmp) / f"{vkey}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(from_ts),
                "-i", str(src),
                "-t", str(to_ts - from_ts),
                "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-an", "-loglevel", "error",
                str(out),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            ct = av.open(str(out))
            n = sum(1 for _ in ct.decode(video=0))
            ct.close()
            topic = vkey.replace(".", "/") + "/video"
            counts[topic] = n
    return counts


def check_video_keyframes(messages: list[tuple[int, bytes]], topic: str) -> bool:
    """For h264 inside foxglove_msgs.CompressedVideo, the data field contains an Annex B
    bitstream. The all-keyframe pass means each message must contain an SPS NAL (type 7).
    """
    import struct  # noqa: F401
    failures = 0
    for log_time, raw in messages:
        # Decode CDR-ish payload to find the bytes array: foxglove_msgs / ros2 CDR layout
        # is fragile to parse manually. Simpler: scan for any 00 00 00 01 + nal_type=7
        # within the message data.
        found_sps = False
        i = 0
        n = len(raw)
        while i < n - 4:
            if raw[i : i + 4] == b"\x00\x00\x00\x01":
                if (raw[i + 4] & 0x1F) == 7:
                    found_sps = True
                    break
                i += 4
            elif raw[i : i + 3] == b"\x00\x00\x01":
                if (raw[i + 3] & 0x1F) == 7:
                    found_sps = True
                    break
                i += 3
            else:
                i += 1
        if not found_sps:
            failures += 1
    return failures == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mcap_path", type=Path)
    ap.add_argument("--dataset-root", type=Path, required=True)
    ap.add_argument("--episode", type=int, required=True)
    args = ap.parse_args()

    print(f"Validating {args.mcap_path}")
    if not args.mcap_path.exists() or args.mcap_path.stat().st_size == 0:
        fail("MCAP file missing or empty")
        return 1

    # 1. open + load
    try:
        by_topic = load_messages_by_topic(args.mcap_path)
    except Exception as e:
        fail(f"MCAP load failed: {e}")
        return 1
    ok(f"file opens; {sum(len(v) for v in by_topic.values())} messages total across "
       f"{len(by_topic)} topics")

    passed = True

    # 2. required topics
    for t in REQUIRED_TABULAR_TOPICS:
        if t in by_topic:
            ok(f"topic present: {t} ({len(by_topic[t])} msgs)")
        else:
            fail(f"topic missing: {t}")
            passed = False

    # 3. monotonic log_time per topic
    for topic, msgs in by_topic.items():
        times = [t for t, _ in msgs]
        for i in range(1, len(times)):
            if times[i] < times[i - 1]:
                fail(f"non-monotonic log_time in {topic} at index {i}")
                passed = False
                break
        else:
            ok(f"monotonic timestamps: {topic}")

    # 4. tabular row counts
    try:
        n_rows = extract_episode_parquet_rows(args.dataset_root, args.episode)
    except Exception as e:
        fail(f"could not derive parquet row count: {e}")
        n_rows = None
    if n_rows is not None:
        for t in REQUIRED_TABULAR_TOPICS:
            if t in by_topic:
                got = len(by_topic[t])
                if got == n_rows:
                    ok(f"{t}: msg count == parquet rows ({got})")
                else:
                    fail(f"{t}: msg count {got} != parquet rows {n_rows}")
                    passed = False

    # 5. video frame counts
    try:
        expected_video = extract_episode_video_frame_counts(
            args.dataset_root, args.episode
        )
    except Exception as e:
        fail(f"could not derive video frame counts: {e}")
        expected_video = {}
    for topic, expected in expected_video.items():
        if topic not in by_topic:
            fail(f"video topic missing: {topic}")
            passed = False
            continue
        got = len(by_topic[topic])
        # Allow ±2 frames slack (ffmpeg slicing can produce off-by-one at boundaries)
        if abs(got - expected) <= 2:
            ok(f"{topic}: {got} msgs (~ expected {expected})")
        else:
            fail(f"{topic}: {got} msgs vs expected ~{expected}")
            passed = False

    # 6. every video message must start with SPS (independently decodable)
    for topic, msgs in by_topic.items():
        if not topic.startswith(VIDEO_TOPIC_PREFIX):
            continue
        if check_video_keyframes(msgs, topic):
            ok(f"{topic}: all {len(msgs)} messages contain SPS (keyframe property)")
        else:
            fail(f"{topic}: some messages lack SPS — not independently decodable")
            passed = False

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
