# TechZoro Silence Cut

Automatic silence removal from video files using FFmpeg.

![First Screen](web/static/images/01%20First%20screen.png)

## Features
- **CLI Mode**: Batch process files in a folder or specific files.
- **Web UI**: User-friendly interface with sliders, presets, and processing progress tracking.
- **Sample Mode**: Test settings on a small fragment before processing the full video.
- **Presets**: Optimized built-in settings for Podcasts, Interviews, Lectures, and Streams.
- **Docker**: Easy deployment as an isolated service.

## Interface Gallery

### 1. Upload & Analyze
Drag and drop your video file into the animated zone. The app will immediately show a thumbnail preview.
![Loading Video](web/static/images/02%20Loading%20video.png)

### 2. Configure Settings
Choose a preset or fine-tune parameters using perfectly aligned sliders.
![Settings and Presets](web/static/images/03%20Settings%20and%20Presets.png)

### 3. Get Results
Download your processed video or sample. You can also proceed to full video processing if you liked the sample.
![Result](web/static/images/04%20Result.png)

## Installation
1. Ensure [FFmpeg](https://ffmpeg.org/) is installed on your system and added to your PATH.
2. Open your terminal in the project directory.
3. To start the web interface, run:
   ```bash
   ./server.sh
   ```
   *(On first run, it will automatically create a virtual environment and install all necessary dependencies like FastAPI).*

## Usage

### Command Line Interface (CLI)
Process a single file using a preset:
```bash
./run.sh video.mp4 --preset podcast
```
Process all supported video files in the current directory:
```bash
./run.sh
```

### Web Interface
Start the local server:
```bash
./server.sh
```
Then open your browser and navigate to: `http://localhost:8765`

### Docker
Run via Docker Compose:
```bash
docker-compose up -d
```

## Storage & Cleanup
The project automatically manages free space to prevent your disk from filling up with large video files:
- **Auto-delete**: Source video files are deleted immediately after a successful "full processing" job.
- **TTL (Time to Live)**: A background task runs every hour, deleting all temporary files, uploads, and outputs older than 24 hours.
- **Samples**: When generating a sample, the original file is kept until you either process the full video or start a new job.
- **Smart Cleanup**: Use the trash bin icon in the header to manually clear temporary files and free up space in one click.

## Configuration
Edit the `.env` file (create one based on `.env.example`) or set environment variables directly to change default parameters such as `SILENCE_THRESHOLD`, `PADDING_START`, and others.
