import io
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from streamonitor.bot import Bot
from streamonitor.cloudflare_session import CloudflareSession
from streamonitor.downloaders.ffmpeg import getVideoFfmpeg
from streamonitor.enums import Status


class ProxyRoutingTests(unittest.TestCase):
    def make_bot(self):
        bot = Bot.__new__(Bot)
        bot.session = CloudflareSession(Mock())
        bot.proxy_url = None
        bot.proxy_name = "direct"
        bot.log = Mock()
        return bot

    def test_rate_limit_selects_india_proxy(self):
        bot = self.make_bot()

        changed = bot._set_proxy_for_status(Status.RATELIMIT)

        self.assertTrue(changed)
        self.assertEqual("http://127.0.0.1:8881", bot.proxy_url)
        self.assertEqual(bot.proxy_url, bot.session.proxies["https"])
        self.assertEqual("India proxy [127.0.0.1:8881]", bot.route_description)

    def test_restricted_selects_us_proxy(self):
        bot = self.make_bot()

        changed = bot._set_proxy_for_status(Status.RESTRICTED)

        self.assertTrue(changed)
        self.assertEqual("http://127.0.0.1:8882", bot.proxy_url)
        self.assertEqual("US proxy [127.0.0.1:8882]", bot.route_description)


class _FinishedProcess:
    last_args = None

    def __init__(self, args, **_kwargs):
        type(self).last_args = args
        self.args = args
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, _timeout=None):
        return self.returncode


class _StalledInput:
    def __init__(self, process):
        self.process = process

    def write(self, _data):
        self.process.returncode = 0

    def flush(self):
        pass


class _StalledProcess:
    def __init__(self, args, **_kwargs):
        self.args = args
        self.returncode = None
        self.stdin = _StalledInput(self)
        self.stdout = io.BytesIO()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class FfmpegProxyTests(unittest.TestCase):
    def test_proxy_and_reconnect_options_are_applied_to_input(self):
        downloader = SimpleNamespace(
            headers={"User-Agent": "test-agent"},
            cookies=None,
            proxy_url="http://127.0.0.1:8882",
            logger=Mock(),
            stopDownload=None,
        )

        with patch.object(subprocess, "Popen", _FinishedProcess):
            result = getVideoFfmpeg(
                downloader,
                "https://example.test/live.m3u8",
                "/tmp/streamonitor-proxy-test.mp4",
            )

        self.assertTrue(result)
        command = _FinishedProcess.last_args
        input_index = command.index("-i")
        self.assertEqual("http://127.0.0.1:8882", command[command.index("-http_proxy") + 1])
        self.assertLess(command.index("-http_proxy"), input_index)
        self.assertEqual("1", command[command.index("-reconnect_at_eof") + 1])
        self.assertIn("pipe:1", command)

    def test_stalled_ffmpeg_is_stopped_and_reported_as_error(self):
        downloader = SimpleNamespace(
            headers={"User-Agent": "test-agent"},
            cookies=None,
            proxy_url=None,
            logger=Mock(),
            stopDownload=None,
        )

        with patch.object(subprocess, "Popen", _StalledProcess), patch(
            "streamonitor.downloaders.ffmpeg.time.monotonic", side_effect=[0, 61]
        ):
            result = getVideoFfmpeg(
                downloader,
                "https://example.test/live.m3u8",
                "/tmp/streamonitor-stall-test.mp4",
            )

        self.assertFalse(result)
        downloader.logger.error.assert_any_call(
            "FFmpeg made no media progress for 60s; restarting recording"
        )


def make_response(status, url, headers=None, body=""):
    request = requests.Request("GET", url).prepare()
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.request = request
    response.headers.update(headers or {})
    response._content = body.encode()
    return response


class CloudflareSessionTests(unittest.TestCase):
    def test_cf_mitigated_challenge_uses_solver_proxy_and_imports_session(self):
        logger = Mock()
        solved_callback = Mock()
        session = CloudflareSession(logger, solved_callback)
        session.set_route(
            "India proxy",
            "http://127.0.0.1:8881",
            "http://proton-india:8888",
        )
        challenge = make_response(
            403,
            "https://chaturbate.com/get_edge_hls_url_ajax/",
            {"cf-mitigated": "challenge", "cf-ray": "test-SIN"},
        )
        solver_result = Mock()
        solver_result.raise_for_status.return_value = None
        solver_result.json.return_value = {
            "status": "ok",
            "solution": {
                "status": 200,
                "url": challenge.url,
                "headers": {"content-type": "application/json"},
                "response": '<html><body><pre>{"room_status":"public"}</pre></body></html>',
                "cookies": [{
                    "name": "cf_clearance",
                    "value": "clear",
                    "domain": ".chaturbate.com",
                    "path": "/",
                    "secure": True,
                }],
                "userAgent": "FlareSolverr Chrome",
            },
        }
        session._solver_session.post = Mock(return_value=solver_result)

        with patch.object(requests.Session, "request", return_value=challenge):
            response = session.post(
                challenge.url,
                data={"room_slug": "example", "bandwidth": "high"},
            )

        payload = session._solver_session.post.call_args.kwargs["json"]
        self.assertEqual("request.post", payload["cmd"])
        self.assertEqual({"url": "http://proton-india:8888"}, payload["proxy"])
        self.assertIn("room_slug=example", payload["postData"])
        self.assertEqual({"room_status": "public"}, response.json())
        self.assertEqual("clear", session.cookies.get("cf_clearance"))
        self.assertEqual("FlareSolverr Chrome", session.headers["User-Agent"])
        solved_callback.assert_called_once_with("FlareSolverr Chrome")

    def test_ordinary_403_does_not_use_flaresolverr(self):
        session = CloudflareSession(Mock())
        forbidden = make_response(403, "https://example.test/api")
        session._solver_session.post = Mock()

        with patch.object(requests.Session, "request", return_value=forbidden):
            response = session.get(forbidden.url)

        self.assertIs(forbidden, response)
        session._solver_session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
