import m3u8
import os
import subprocess
from threading import Thread
from ffmpy import FFmpeg, FFRuntimeError
from time import sleep
from urllib.parse import urljoin
from parameters import DEBUG, CONTAINER, SEGMENT_TIME, FFMPEG_PATH

_http_lib = None
if not _http_lib:
    try:
        import pycurl_requests as requests
        _http_lib = 'pycurl'
    except ImportError:
        pass
if not _http_lib:
    try:
        import requests
        _http_lib = 'requests'
    except ImportError:
        pass
if not _http_lib:
    raise ImportError("Please install requests or pycurl package to proceed")


def getVideoNativeHLS(self, url, filename, m3u_processor=None):
    self.stopDownloadFlag = False
    error = False
    tmpfilename = filename[:-len('.' + CONTAINER)] + '.tmp.ts'
    session = requests.Session()
    session.proxies.update(self.session.proxies)

    def execute():
        nonlocal error
        downloaded_list = []
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return

        with open(tmpfilename, 'wb') as outfile:
            did_download = False
            while not self.stopDownloadFlag:
                playlist_url = url
                r = session.get(playlist_url, headers=self.headers, cookies=self.cookies)
                if r.status_code != 200:
                    return

                raw_content = r.content.decode("utf-8", errors="replace")
                processed = m3u_processor(raw_content) if m3u_processor else raw_content

                try:
                    chunklist = m3u8.loads(processed)
                except Exception as e:
                    return

                # If master playlist, follow selected child playlist URL
                if len(chunklist.segments) == 0 and len(chunklist.playlists) > 0:
                    child_uri = chunklist.playlists[0].uri  # first (already resolution-selected upstream)
                    playlist_url = urljoin(playlist_url, child_uri)
                    r = session.get(playlist_url, headers=self.headers, cookies=self.cookies)
                    if r.status_code != 200:
                        return

                    raw_content = r.content.decode("utf-8", errors="replace")
                    processed = m3u_processor(raw_content) if m3u_processor else raw_content
                    chunklist = m3u8.loads(processed)

                # fallback raw
                if len(chunklist.segments) == 0:
                    chunklist = m3u8.loads(raw_content)
                    if len(chunklist.segments) == 0:
                        return

                for chunk in chunklist.segment_map + chunklist.segments:
                    chunk_uri = (chunk.uri or "").strip()
                    if not chunk_uri:
                        continue

                    chunk_url = urljoin(playlist_url, chunk_uri)

                    if chunk_url in downloaded_list:
                        continue

                    did_download = True
                    downloaded_list.append(chunk_url)
                    self.debug('Downloading ' + chunk_url)

                    m = session.get(chunk_url, headers=self.headers, cookies=self.cookies)
                    if m.status_code != 200:
                        return

                    outfile.write(m.content)
                    if self.stopDownloadFlag:
                        return

                if not did_download:
                    sleep(10)

    def terminate():
        self.stopDownloadFlag = True

    process = Thread(target=execute)
    process.start()
    self.stopDownload = terminate
    process.join()
    self.stopDownload = None

    if error:
        return False

    if not os.path.exists(tmpfilename):
        return False

    if os.path.getsize(tmpfilename) == 0:
        os.remove(tmpfilename)
        return False

    try:
        stdout = open(filename + '.postprocess_stdout.log', 'w+') if DEBUG else subprocess.DEVNULL
        stderr = open(filename + '.postprocess_stderr.log', 'w+') if DEBUG else subprocess.DEVNULL
        # The temporary MPEG-TS file can contain timestamp discontinuities when
        # an HLS playlist stalls or resumes.  FFmpeg normally ignores jumps
        # smaller than 10 seconds, which allows the audio and video timelines
        # to resume at different positions (commonly by about one segment).
        # Lower the shared demuxer discontinuity threshold so both tracks are
        # rebased together, matching the aligned restart-offset behaviour used
        # by the C++ recorder.  make_zero applies one common final shift while
        # preserving the original A/V relationship and codec bitstreams.
        input_str = '-fflags +genpts -dts_delta_threshold 1'
        output_str = '-c:a copy -c:v copy -avoid_negative_ts make_zero'
        suffix = ''
        if SEGMENT_TIME is not None:
            output_str += f' -f segment -reset_timestamps 1 -segment_time {str(SEGMENT_TIME)}'
            if hasattr(self, 'filename_extra_suffix'):
                suffix = self.filename_extra_suffix
            filename = filename[:-len('.' + CONTAINER)] + '_%03d' + suffix + '.' + CONTAINER
        ff = FFmpeg(executable=FFMPEG_PATH, inputs={tmpfilename: input_str}, outputs={filename: output_str})
        ff.run(stdout=stdout, stderr=stderr)
        os.remove(tmpfilename)
    except FFRuntimeError as e:
        if e.exit_code and e.exit_code != 255:
            return False

    return True
