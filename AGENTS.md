# SilenceCut AI Agent Instructions

SilenceCut is a CLI and Web tool for automatic silence removal from videos using FFmpeg.

## CLI Usage
Basic command: `python silencecut.py [PATH] [OPTIONS]`

### Parameters
- `--threshold FLOAT`: Silence level in dB (default: -30). Use lower (e.g., -40) for quiet backgrounds, higher (e.g., -20) for noisy ones.
- `--duration FLOAT`: Min silence length in seconds (default: 0.5).
- `--padding-start INT`: ms to keep before speech (default: 100).
- `--padding-end INT`: ms to keep after speech (default: 150).
- `--min-segment FLOAT`: Min speech segment length (default: 0.3).
- `--sample INT`: Process only first N seconds.
- `--dry-run`: Show segments without processing.
- `--preset NAME`: Use `podcast`, `interview`, `lecture`, or `stream`.

### Common Scenarios
1. **Podcast**: `python silencecut.py video.mp4 --preset podcast`
2. **Noisy Interview**: `python silencecut.py video.mp4 --threshold -25 --duration 0.8`
3. **Quick Test**: `python silencecut.py video.mp4 --sample 60`
4. **Analysis**: `python silencecut.py video.mp4 --dry-run`

## Recommendations
- If the output cuts off speech too early, increase `--padding-end`.
- If background noise is being kept, lower `--threshold` (e.g., -35 or -40).
- For fast-paced content, use `--min-segment 0.1` and low padding.
