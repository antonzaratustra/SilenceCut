import os
import sys
import subprocess
import re
import argparse
import logging
import json
import tempfile
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("silencecut.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Constants and Presets
PRESETS = {
    "podcast": {"threshold": -35, "padding_start": 200, "padding_end": 300},
    "interview": {"threshold": -30, "padding_start": 150, "padding_end": 200},
    "lecture": {"threshold": -25, "padding_start": 300, "padding_end": 400},
    "stream": {"threshold": -40, "min_segment_duration": 1.0}
}

class SilenceCut:
    def __init__(self, config):
        self.config = config
        self.ffmpeg_path = "ffmpeg"
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        try:
            subprocess.run([self.ffmpeg_path, "-version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("FFmpeg not found. Please install FFmpeg and add it to your PATH.")
            sys.exit(1)

    def detect_silence(self, input_file):
        logger.info(f"Analyzing audio for silence: {input_file}")
        threshold = self.config.get('threshold', -30)
        duration = self.config.get('duration', 0.5)
        
        # Use only audio stream for faster analysis
        cmd = [
            self.ffmpeg_path, "-i", input_file,
            "-af", f"silencedetect=noise={threshold}dB:d={duration}",
            "-f", "null", "-"
        ]
        
        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
        _, stderr = process.communicate()
        
        silence_starts = re.findall(r"silence_start: ([\d\.]+)", stderr)
        silence_ends = re.findall(r"silence_end: ([\d\.]+) \| silence_duration: ([\d\.]+)", stderr)
        
        silence_segments = []
        for start, (end, dur) in zip(silence_starts, silence_ends):
            silence_segments.append({'start': float(start), 'end': float(end), 'duration': float(dur)})
            
        return silence_segments

    def get_video_duration(self, input_file):
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", input_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout.strip()
        try:
            return float(output)
        except (ValueError, TypeError):
            logger.error(f"Could not get duration from ffprobe output: '{output}'")
            return 0.0

    def calculate_speech_segments(self, silence_segments, total_duration):
        padding_start = self.config.get('padding_start', 100) / 1000.0
        padding_end = self.config.get('padding_end', 150) / 1000.0
        min_segment_duration = self.config.get('min_segment_duration', 0.3)
        
        if not silence_segments:
            return [{'start': 0, 'end': total_duration}]
        
        speech_segments = []
        last_end = 0.0
        
        for silence in silence_segments:
            # Segment before silence
            speech_start = last_end
            speech_end = silence['start'] + padding_start
            
            # Adjust speech_start with padding_end from previous segment
            if speech_start > 0:
                speech_start = max(0, speech_start - padding_end)
            
            if speech_end - speech_start >= min_segment_duration:
                speech_segments.append({'start': speech_start, 'end': speech_end})
            
            last_end = silence['end']
            
        # Final segment after last silence
        speech_start = max(0, last_end - padding_end)
        speech_end = total_duration
        if speech_end - speech_start >= min_segment_duration:
            speech_segments.append({'start': speech_start, 'end': speech_end})
            
        # Merge overlapping segments
        if not speech_segments:
            return []
            
        merged = [speech_segments[0]]
        for current in speech_segments[1:]:
            prev = merged[-1]
            if current['start'] <= prev['end']:
                prev['end'] = max(prev['end'], current['end'])
            else:
                merged.append(current)
                
        return merged

    def process_video(self, input_file, output_file, speech_segments):
        if not speech_segments:
            logger.warning("No speech segments found. Output might be empty.")
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            segment_list_path = os.path.join(tmpdir, "segments.txt")
            with open(segment_list_path, "w") as f:
                for i, seg in enumerate(speech_segments):
                    seg_file = os.path.join(tmpdir, f"seg_{i}.ts")
                    duration = seg['end'] - seg['start']
                    cmd = [
                        self.ffmpeg_path, "-ss", str(seg['start']), "-t", str(duration),
                        "-i", input_file, "-c", "copy", "-avoid_negative_ts", "make_non_negative",
                        "-y", seg_file
                    ]
                    subprocess.run(cmd, capture_output=True, check=True)
                    f.write(f"file '{seg_file}'\n")
            
            # Concatenate
            cmd = [
                self.ffmpeg_path, "-f", "concat", "-safe", "0", "-i", segment_list_path,
                "-c", "copy", "-y", output_file
            ]
            subprocess.run(cmd, capture_output=True, check=True)

    def run(self, input_path):
        if os.path.isdir(input_path):
            files = [f for f in Path(input_path).iterdir() if f.suffix.lower() in ['.mp4', '.mov', '.mkv', '.avi', '.webm']]
        else:
            files = [Path(input_path)]

        for file_path in files:
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                continue
            
            logger.info(f"Processing: {file_path.name}")
            
            # Handle sample mode
            work_file = str(file_path)
            is_temp_sample = False
            if self.config.get('sample'):
                is_temp_sample = True
                sample_duration = self.config.get('sample_duration', 300)
                sample_offset = self.config.get('sample_offset', 0)
                temp_sample = f"sample_{file_path.name}"
                cmd = [
                    self.ffmpeg_path, "-ss", str(sample_offset), "-t", str(sample_duration),
                    "-i", str(file_path), "-c", "copy", "-y", temp_sample
                ]
                subprocess.run(cmd, check=True)
                work_file = temp_sample

            total_duration = self.get_video_duration(work_file)
            silence_segments = self.detect_silence(work_file)
            speech_segments = self.calculate_speech_segments(silence_segments, total_duration)
            
            if self.config.get('dry_run'):
                logger.info(f"Dry run for {file_path.name}:")
                logger.info(f"Found {len(silence_segments)} silence segments.")
                logger.info(f"Speech segments to keep: {json.dumps(speech_segments, indent=2)}")
                if is_temp_sample: os.remove(work_file)
                continue

            output_dir = self.config.get('output_dir', '.')
            os.makedirs(output_dir, exist_ok=True)
            output_suffix = self.config.get('output_suffix', '_cut')
            output_file = os.path.join(output_dir, f"{file_path.stem}{output_suffix}{file_path.suffix}")
            
            self.process_video(work_file, output_file, speech_segments)
            
            if is_temp_sample:
                os.remove(work_file)
            
            logger.info(f"Finished processing {file_path.name}. Output: {output_file}")

def main():
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="SilenceCut - Automatic silence removal from video")
    parser.add_argument("path", nargs="?", default=".", help="Path to file or directory")
    parser.add_argument("--threshold", type=float, help="Silence threshold in dB")
    parser.add_argument("--duration", type=float, help="Minimum silence duration in seconds")
    parser.add_argument("--padding-start", type=int, help="Padding before speech in ms")
    parser.add_argument("--padding-end", type=int, help="Padding after speech in ms")
    parser.add_argument("--min-segment", type=float, dest="min_segment_duration", help="Min speech segment duration")
    parser.add_argument("--sample", type=int, help="Create sample of N seconds")
    parser.add_argument("--sample-offset", type=int, help="Sample offset in seconds")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Show segments without processing")
    parser.add_argument("--preset", choices=PRESETS.keys(), help="Use a preset configuration")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Configuration priority: CLI > .env > Default
    config = {
        'threshold': args.threshold or float(os.getenv('SILENCE_THRESHOLD', -30)),
        'duration': args.duration or float(os.getenv('SILENCE_DURATION', 0.5)),
        'padding_start': args.padding_start or int(os.getenv('PADDING_START', 100)),
        'padding_end': args.padding_end or int(os.getenv('PADDING_END', 150)),
        'min_segment_duration': args.min_segment_duration or float(os.getenv('MIN_SEGMENT_DURATION', 0.3)),
        'sample': args.sample,
        'sample_duration': args.sample or int(os.getenv('SAMPLE_DURATION', 300)),
        'sample_offset': args.sample_offset or int(os.getenv('SAMPLE_OFFSET', 0)),
        'output_dir': args.output_dir,
        'dry_run': args.dry_run,
        'output_suffix': os.getenv('OUTPUT_SUFFIX', '_cut'),
        'verbose': args.verbose
    }

    if args.preset:
        config.update(PRESETS[args.preset])

    if config['verbose']:
        logger.setLevel(logging.DEBUG)

    sc = SilenceCut(config)
    sc.run(args.path)

if __name__ == "__main__":
    main()
