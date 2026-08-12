import errno
import os
import subprocess
import sys
import time

import requests.cookies
from threading import Thread
from parameters import DEBUG, SEGMENT_TIME, CONTAINER, FFMPEG_PATH, FFMPEG_READRATE, FFMPEG_STALL_TIMEOUT


def getVideoFfmpeg(self, url, filename):
    cmd = [
        FFMPEG_PATH,
        '-user_agent', self.headers['User-Agent'],
        '-progress', 'pipe:1',
        '-nostats',
    ]

    if type(self.cookies) is requests.cookies.RequestsCookieJar:
        cookies_text = ''
        for cookie in self.cookies:
            cookies_text += cookie.name + "=" + cookie.value + "; path=" + cookie.path + '; domain=' + cookie.domain + '\n'
        if len(cookies_text) > 10:
            cookies_text = cookies_text[:-1]
        cmd.extend([
            '-cookies', cookies_text
        ])

    if FFMPEG_READRATE:
        cmd.extend(['-readrate', f'{FFMPEG_READRATE!s}'])

    cmd.extend([
        '-max_reload', '20',
        '-seg_max_retry', '20',
        '-m3u8_hold_counters', '20',
    ])

    def add_input(input_url):
        cmd.extend([
            '-reconnect', '1',
            '-reconnect_at_eof', '1',
            '-reconnect_streamed', '1',
            '-reconnect_on_network_error', '1',
            '-reconnect_on_http_error', '4xx,5xx',
            '-reconnect_delay_max', '10',
        ])
        if self.proxy_url:
            cmd.extend(['-http_proxy', self.proxy_url])
        cmd.extend(['-i', input_url])

    # Handle CMAF with separate audio/video URLs (tuple: (video_url, audio_url))
    if isinstance(url, tuple):
        video_url, audio_url = url
        if audio_url:
            # The two live playlists can open on adjacent CMAF segments. Keep
            # their media timestamps and align the audio input to the video
            # input instead of independently rebasing both inputs to zero.
            cmd.extend(['-copyts', '-start_at_zero'])
            add_input(video_url)
            cmd.extend(['-isync', '0'])
            add_input(audio_url)
            cmd.extend([
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-map', '0:v:0',
                '-map', '1:a:0',
            ])
        else:
            add_input(video_url)
            cmd.extend(['-c:a', 'copy', '-c:v', 'copy'])
    else:
        add_input(url)
        cmd.extend(['-c:a', 'copy', '-c:v', 'copy'])

    suffix = ''
    if hasattr(self, 'filename_extra_suffix'):
        suffix = self.filename_extra_suffix

    if SEGMENT_TIME is not None:
        username = filename.rsplit('-', maxsplit=2)[0]
        cmd.extend([
            '-f', 'segment',
            '-reset_timestamps', '1',
            '-segment_time', str(SEGMENT_TIME),
            '-strftime', '1',
            f'{username}-%Y%m%d-%H%M%S{suffix}.{CONTAINER}'
        ])
    else:
        cmd.extend([
            os.path.splitext(filename)[0] + suffix + '.' + CONTAINER
        ])

    class _Stopper:
        def __init__(self):
            self.stop = False

        def pls_stop(self):
            self.stop = True

    stopping = _Stopper()
    error = False

    def execute():
        nonlocal error
        stderr = None
        try:
            stderr = open(filename + '.stderr.log', 'w+') if DEBUG else subprocess.DEVNULL
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.Popen(
                args=cmd, stdin=subprocess.PIPE, stderr=stderr, stdout=subprocess.PIPE, startupinfo=startupinfo)
        except OSError as e:
            if e.errno == errno.ENOENT:
                self.logger.error('FFMpeg executable not found!')
                error = True
                return
            else:
                self.logger.error("Got OSError, errno: " + str(e.errno))
                error = True
                return

        progress = {'value': None, 'updated': time.monotonic()}

        def read_progress():
            for raw_line in iter(process.stdout.readline, b''):
                line = raw_line.decode('utf-8', errors='replace').strip()
                if not line.startswith('out_time_us='):
                    continue
                value = line.partition('=')[2]
                if value != progress['value']:
                    progress['value'] = value
                    progress['updated'] = time.monotonic()

        progress_thread = Thread(target=read_progress, daemon=True)
        progress_thread.start()

        def terminate_process():
            try:
                process.stdin.write(b'q\n')
                process.stdin.flush()
                process.wait(10)
                return
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                pass
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        while process.poll() is None:
            if stopping.stop:
                terminate_process()
                break
            if FFMPEG_STALL_TIMEOUT > 0 and time.monotonic() - progress['updated'] > FFMPEG_STALL_TIMEOUT:
                self.logger.error(
                    f'FFmpeg made no media progress for {FFMPEG_STALL_TIMEOUT}s; restarting recording')
                error = True
                terminate_process()
                break
            try:
                process.wait(1)
            except subprocess.TimeoutExpired:
                pass

        progress_thread.join(timeout=1)
        if stderr != subprocess.DEVNULL:
            stderr.close()

        if not stopping.stop and process.returncode and process.returncode != 0 and process.returncode != 255:
            self.logger.error('The process exited with an error. Return code: ' + str(process.returncode))
            error = True
            return

    thread = Thread(target=execute)
    thread.start()
    self.stopDownload = lambda: stopping.pls_stop()
    thread.join()
    self.stopDownload = None
    return not error
