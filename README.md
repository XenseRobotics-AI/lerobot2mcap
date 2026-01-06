# lerobot2mcap

Convert LeRobot datasets to MCAP format with automatic configuration generation from dataset metadata. No manual configuration required – just point it at your dataset and go. **This version is primarily focused on LeRobot v3.0 merged-format datasets** (parquet+video merged, per-episode slicing), while remaining backward compatible with v2.1/v2.x. AV1 is supported via a PyAV monkey‑patch.

## Features (v3.0-first)

- **Automatic configuration**: Reads `meta/info.json` and generates all necessary configuration using Pydantic models for type safety
- **Episode-based conversion**: Converts each episode to a separate MCAP file in its own directory
- **Chunk-aware**: Handles datasets organized in chunks (supports datasets with 1000+ episodes)
- **Multi-video support**: Auto-detects and converts all video streams
- **Terminal log support**: Parses raw `.log` files into `rcl_interfaces/msg/Log` messages with full metadata
- **ROS2 format**: Outputs ROS2-compatible MCAP files (configurable via metadata)
- **v3.0-first**: Handles merged parquet+video with per-episode slicing (rows + timestamp-based video trim)
- **Cross-compatible**: Still supports LeRobot v2.0, v2.1 (per-episode files)
- **AV1-ready**: PyAV monkey-patch replaces OpenCV video loader for AV1/H.264/etc.
- **Metadata-driven**: Reads FPS, video codecs, writer format, and chunk size from dataset metadata

## Installation

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/Vertax42/lerobot2mcap.git
cd lerobot2mcap

# Install dependencies
uv sync

# Open help menu
uv run lerobot2mcap --help
```

### Using pip

```bash
# Clone and install
git clone https://github.com/Vertax42/lerobot2mcap.git
cd lerobot2mcap
pip install -e .
```

## Requirements

Your LeRobot dataset should have the following structure:

```
dataset_root/
├── meta/
│   └── info.json          # Required: Dataset metadata
├── data/                  # Required: Parquet data files
└── videos/                # Optional: Video files (if dataset contains video)
```

### Required `info.json` Fields

The converter reads the following fields from `meta/info.json`:

| Field              | Type   | Description                                                  | Default                      |
| ------------------ | ------ | ------------------------------------------------------------ | ---------------------------- |
| `codebase_version` | string | Dataset format version (e.g., "v2.0", "v3.0")                | _(required)_                 |
| `total_episodes`   | int    | Total number of episodes in the dataset                      | _(required)_                 |
| `fps`              | int    | Frames per second for the dataset                            | _(required)_                 |
| `features`         | dict   | Feature definitions including video streams and their codecs | _(required)_                 |
| `data_path`        | string | Template path for parquet files                              | _(required)_                 |
| `video_path`       | string | Template path for video files                                | _(required if videos exist)_ |
| `chunks_size`      | int    | Maximum episodes per chunk                                   | 1000                         |
| `writer_format`    | string | MCAP writer format ("ros1", "ros2", "json", "protobuf")      | "ros2"                       |

### Video Codec Support

- Default encode: `h264` (configurable via `DEFAULT_CODEC` in `dataset_info.py`)
- Decode: PyAV monkey-patch (supports AV1/H.264/…); replaces OpenCV loader in tabular2mcap

## Architecture

The converter uses an object-oriented, metadata-driven architecture:

```
┌─────────────────┐
│  DatasetInfo    │  Parses meta/info.json to extract:
│                 │  • total_episodes, chunks_size, fps
└────────┬────────┘  • video_keys and codecs from features
         │           • data_path and video_path templates
         │           • codebase_version, writer_format
         ↓
┌─────────────────┐
│ ConfigGenerator │  Generates per-episode Pydantic configs:
│                 │  • TabularMappingConfig (parquet data)
└────────┬────────┘  • CompressedVideoMappingConfig (videos)
         │           • AttachmentConfig (log files)
         │           • Validates all fields at runtime
         ↓
┌─────────────────┐
│ LeRobotConverter│  Orchestrates conversion:
│                 │  • Iterates through episodes
└────────┬────────┘  • Calls tabular2mcap per episode
         │           • Saves config alongside MCAP
         ↓
┌─────────────────┐
│  tabular2mcap   │  Performs actual MCAP writing:
│                 │  • Reads parquet, videos, logs
└─────────────────┘  • Writes MCAP with ROS2 schemas
```

**Key Design Principles (v3.0-first):**

1. **Type Safety**: Uses Pydantic models from `tabular2mcap.loader.models` for validation
2. **Template-Based**: Builds configs from a base template with `.model_copy()`
3. **Metadata-Driven**: Reads all values from `info.json` instead of hardcoding
4. **Episode-Level**: Processes one episode at a time for predictable output structure
5. **v3.0 merging aware**: Splits merged parquet rows and trims merged videos per episode

## Usage

The tool provides two main commands: `download` and `convert`.

### Quick Start

```bash
# Download and convert in one command (downloads from Hugging Face)
uv run lerobot2mcap download lerobot/pusht -o ./data

# Or convert an existing dataset
uv run lerobot2mcap convert ~/.cache/huggingface/lerobot/pusht -o ./mcap_output
```

### Command: `download`

Download LeRobot datasets from Hugging Face Hub. The dataset will be downloaded and then automatically converted to MCAP.

```bash
# Download full dataset
lerobot2mcap download lerobot/pusht -o ./data

# Download specific episodes only
lerobot2mcap download lerobot/pusht -o ./data -e 0 1 2

# Without output dir (defaults to ./data)
lerobot2mcap download lerobot/pusht
```

**Arguments:**

- `dataset_id`: Hugging Face dataset ID (e.g., `lerobot/pusht`)
- `-o, --output-dir`: Output directory (default: `./data`)
- `-e, --episodes`: Specific episode indices to download (default: all episodes)

**Output:**

- Downloads dataset to `<output-dir>/`
- Creates MCAP files in `<output-dir>/mcap_conversion/`

### Command: `convert`

Convert an existing LeRobot dataset to MCAP format.

```bash
# Convert all episodes (configuration auto-generated)
lerobot2mcap convert ~/.cache/huggingface/lerobot/pusht -o ./mcap_output

# Convert specific episodes only
lerobot2mcap convert /path/to/dataset -o ./mcap_output -e 0 1 2

# Custom converter functions (advanced)
lerobot2mcap convert /path/to/dataset -o ./mcap_output -f ./my_converter_functions.yaml
```

**Arguments:**

- `input_dir`: Path to LeRobot dataset root (must contain `meta/info.json`)
- `-o, --output-dir`: Output directory for MCAP files (default: `<input_dir>/mcap_conversion`)
- `-e, --episodes`: Specific episode indices to convert (default: all episodes)
- `-f, --converter-functions`: Path to custom converter functions YAML (default: built-in `configs/converter_functions.yaml`)

**What Happens During Conversion (v3.0-first):**

1. Reads `meta/info.json` to understand dataset structure (merged files in v3.0)
2. Calculates total chunks (`ceil(total_episodes / chunks_size)`)—ignored for v3.0 merged files
3. For each episode:
   - Slices parquet rows by episode index range (v3.0)
   - Slices video by timestamps per episode (v3.0) using ffmpeg
   - Writes temp files:
     - `robot/actions.parquet` → `/robot/actions/data`
     - `robot/states.parquet` → `/robot/states/data`
     - `observation/images/{cam}.mp4` → `/observation/images/{cam}/video`
   - Generates per-episode config (Pydantic) and calls `tabular2mcap` with `strip_file_suffix=True`
   - Saves MCAP and per-episode config under `output/episode_xxx/`
4. After all episodes finish, copies the last generated config to `configs/config.yaml` as the latest example
5. Skips episodes with missing files (warns in logs)

### Topic layout (v3.0 example)

- `/robot/actions/data` — action vectors
- `/robot/states/data` — observation.state vectors
- `/observation/images/{cam}/video` — compressed video (foxglove_msgs/CompressedVideo)

### Recording Your Own Dataset With Terminal Logs

To capture terminal logs during recording (optional but recommended for debugging):

```bash
# Set log file path
LOG_FILE=~/.cache/huggingface/lerobot/${HF_USER}/my-dataset.log

# Record with lerobot-record and capture terminal output
lerobot-record \
    --robot.type=so101_follower \
    --robot.port=/dev/tty.usbmodem5A680114161 \
    --robot.id=my_follower_arm \
    --robot.cameras="{
        front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30},
        external: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 15}
    }" \
    --teleop.type=so101_leader \
    --teleop.port=/dev/tty.usbmodem5A680123701 \
    --teleop.id=my_leader_arm \
    --display_data=true \
    --dataset.repo_id=${HF_USER}/my-dataset \
    --dataset.episode_time_s=60 \
    --dataset.reset_time_s=0 \
    --dataset.num_episodes=10 \
    --dataset.single_task="Pick and place demo" \
    2>&1 | tee $LOG_FILE

# Move log file to dataset root for automatic inclusion
mv $LOG_FILE ~/.cache/huggingface/lerobot/${HF_USER}/my-dataset/recording.log
```

**Note:** Place the `.log` file in the dataset root directory. The converter will automatically:

- Detect it using `**/*.log` pattern
- Parse it into `rcl_interfaces/msg/Log` messages
- Include it as an attachment in the MCAP file

### Expected Dataset Structure

The converter automatically detects and supports both LeRobot v2.0, v2.1 dataset formats, and has partial support for the v3 dataset format. Example input file structures are given below for v3 and v2.1 (very similar to v2).

#### LeRobot v3 Format

Im Lerobot dataset v3.0 multiple episodes are concatenated into the same files, based on episode and MP4 file size limits defined in the lerobot codebase. The following file structure is an example only; the method and conditions, and recording parameters that data is collected with will dicate how many episodes are merged per file. It should be noted that the seperation of these files back into seperate episodes is not yet supported.

```
dataset_root/
├── meta/
│   ├── info.json           # Dataset metadata (includes total_episodes)
│   ├── episodes.jsonl
│   └── tasks.jsonl
├── data/
│   └── chunk-000/
│       ├── file-000.parquet  # Episode 0-3
│       ├── file-001.parquet  # Episode 4-5
│       └── file-002.parquet  # Episode 6-9
├── videos/
│   ├── observation.images.front/
│   │   └── chunk-000/
│   │       ├── file-000.mp4  # Episode 0-3
│   │       ├── file-001.mp4  # Episode 4-5
│   │       └── file-002.mp4  # Episode 6-9
│   └── observation.images.external/
│       └── chunk-000/
│           ├── file-000.mp4  # Episode 0-3
│           ├── file-001.mp4  # Episode 4-5
│           └── file-002.mp4  # Episode 6-9
└── recording.log           # Optional terminal log
```

#### LeRobot v2.1 Format

Episodes use 6-digit indices (episode_000000, episode_000001, etc.).

```
dataset_root/
├── meta/
│   ├── info.json           # Dataset metadata (includes total_episodes)
│   ├── episodes.jsonl
│   └── tasks.jsonl
├── data/
│   └── chunk-000/
│       ├── episode_000000.parquet  # Episode 0
│       ├── episode_000001.parquet  # Episode 1
│       └── episode_000002.parquet  # Episode 2
└── videos/
    └── chunk-000/
        ├── observation.images.phone/
        │   ├── episode_000000.mp4  # Episode 0
        │   ├── episode_000001.mp4  # Episode 1
        │   └── episode_000002.mp4  # Episode 2
        └── observation.images.external/
            ├── episode_000000.mp4  # Episode 0
            ├── episode_000001.mp4  # Episode 1
            └── episode_000002.mp4  # Episode 2
```

**Note**: The converter automatically detects which format your dataset uses from `meta/info.json` and handles it appropriately.

## Output

Each episode produces a separate directory containing an MCAP file and its configuration:

```
mcap_output/
├── episode_000/
│   ├── episode_000.mcap
│   └── config_000.yaml
├── episode_001/
│   ├── episode_001.mcap
│   └── config_001.yaml
└── episode_002/
    ├── episode_002.mcap
    └── config_002.yaml
```

Each MCAP file contains:

- **Robot data** from the episode's parquet file (topic: `robot_data`)
- **Video streams** for each camera (topics: `observation/images/front`, `observation/images/external`, etc.)
- **Terminal logs** as `rcl_interfaces/msg/Log` if `.log` files present (topic: `terminal_log`)
  - Includes full metadata: log level, timestamp, source file, line number, and message
  - Supports multi-line log entries (e.g., stack traces)

## How Configuration Works

**You don't need to create any configuration files** - everything is automatic:

1. **DatasetInfo** reads your `meta/info.json` to discover:

   - Total number of episodes
   - Video streams and their codecs
   - Dataset FPS and structure
   - Data file patterns

2. **ConfigGenerator** creates a config for each episode:

   - Tabular mappings pointing to the specific episode's parquet file
   - Video mappings pointing to the specific episode's video files
   - Log mappings if `.log` files are present
   - Each config is saved alongside its MCAP file for transparency

3. **tabular2mcap** uses each generated config to convert the episode to MCAP

### Advanced: Custom Converter Functions (Optional)

By default, the converter uses [`configs/converter_functions.yaml`](configs/converter_functions.yaml) for data transformation. You can customize this with the `-f` flag:

```yaml
# Custom converter_functions.yaml
functions:
  row_to_message_with_timestamp:
    schema_name: null
    template: |
      {
        "timestamp": {
          "sec": {{ (timestamp) | int }},
          "nsec": {{ ((timestamp % 1) * 1_000_000_000) | int }}
        }
      }
```

**Note**: Log parsing is handled automatically by tabular2mcap's `LogConverter` - no converter function needed.

## Future Work

Lerobot dataset v3.0 file splitting into individual episodes is yet to be added to this repository.

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Build package
uv build
```

## Browse Datasets

https://huggingface.co/lerobot
