import json
from pathlib import Path
import re
import subprocess
import time
from .core import Problem


def run(args, cancel=lambda: None, timeout=300):
    # Log to a temporary file to avoid pipe deadlocks on verbose FFmpeg output.
    import tempfile
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT)
        start = time.monotonic()
        try:
            while proc.poll() is None:
                cancel()
                if time.monotonic()-start > timeout:
                    raise Problem('Media operation timed out', 422)
                time.sleep(0.1)
            out.seek(0)
            text = out.read(2_000_000).decode(errors='replace')
            if proc.returncode:
                raise Problem('Media decoding/encoding failed', 422)
            return text
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_streams', '-show_format', '-of', 'json', str(path)], timeout=30))


def technical_qa(path, spec, settings, cancel=lambda: None):
    data = probe(path)
    if 'mov' not in data.get('format', {}).get('format_name', '').split(','):
        raise Problem('Only real MP4/MOV video containers are accepted', 422)
    streams = data.get('streams', [])
    video = next((s for s in streams if s['codec_type'] == 'video'), None)
    audio = next((s for s in streams if s['codec_type'] == 'audio'), None)
    duration = float(data.get('format', {}).get('duration', 0))
    issues = []
    if not video:
        issues.append('Missing video track')
    else:
        if video.get('width', 0) < 360 or video.get('height', 0) < 360:
            issues.append('Video resolution below 360 pixels')
        target = 16/9 if settings['aspect'] == '16:9' else 9/16
        if abs(video['width']/video['height']-target) > 0.08:
            issues.append('Wrong aspect ratio')
    if abs(duration-spec['duration']) > 1:
        issues.append('Duration differs from planned shot by more than 1 second')
    if (settings['require_audio'] or spec['dialogue']) and not audio:
        issues.append('Required audio track missing')
    if video:
        # Full decoding catches corrupt frames, not just a readable header.
        run(['ffmpeg', '-v', 'error', '-xerror', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-f', 'null', '-'], cancel, 120)
        analysis = run(['ffmpeg', '-hide_banner', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-vf', 'blackdetect=d=1:pix_th=0.02',
                        '-an', '-f', 'null', '-'], cancel, 120)
        if sum(float(x) for x in re.findall(r'black_duration:([\d.]+)', analysis)) > duration*.95:
            issues.append('Clip is almost entirely black')
    if audio and spec['dialogue']:
        analysis = run(['ffmpeg', '-hide_banner', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-af', 'volumedetect', '-vn', '-f', 'null', '-'], cancel, 120)
        values = re.findall(r'max_volume:\s*(-?\d+(?:\.\d+)?) dB', analysis)
        if 'max_volume: -inf' in analysis or (values and float(values[-1]) < -45):
            issues.append('Dialogue track is silent or extremely quiet')
    return {'approved': not issues, 'issues': issues, 'duration': duration,
            'width': video.get('width') if video else None, 'height': video.get('height') if video else None,
            'has_audio': bool(audio), 'method': 'ffprobe, full FFmpeg decode, blackdetect, volumedetect'}


def assemble(paths, destination, aspect, cancel=lambda: None):
    destination = Path(destination)
    destination.parent.mkdir(exist_ok=True, parents=True)
    normalized = []
    width, height = (1280, 720) if aspect == '16:9' else (720, 1280)
    for i, source in enumerate(paths):
        cancel()
        output = destination.parent / f'normalized-{i:04d}.mp4'
        audio = any(s['codec_type'] == 'audio' for s in probe(source)['streams'])
        args = ['ffmpeg', '-y', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-i', str(source)]
        if not audio:
            args += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
        args += ['-map', '0:v:0', '-map', '0:a:0' if audio else '1:a:0',
                 '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24',
                 '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                 '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-af', 'aresample=async=1:first_pts=0',
                 '-shortest', '-movflags', '+faststart', str(output)]
        run(args, cancel, 600)
        normalized.append(output)
    if not normalized:
        raise Problem('Cannot export an empty episode', 422)
    listing = destination.parent / 'concat.txt'
    # Only internally generated basename paths enter the concat manifest.
    listing.write_text(''.join("file '"+p.name+"'\n" for p in normalized))
    temporary = destination.with_suffix('.partial.mp4')
    try:
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', str(listing),
             '-c', 'copy', '-movflags', '+faststart', str(temporary)], cancel, 600)
        check = probe(temporary)
        total = sum(float(probe(p)['format']['duration']) for p in normalized)
        if abs(float(check['format']['duration'])-total) > 0.5:
            raise Problem('Final export duration validation failed', 422)
        cancel()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
        for item in normalized:
            item.unlink(missing_ok=True)
        listing.unlink(missing_ok=True)
    return destination
