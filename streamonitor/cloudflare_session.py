import html
import re
import time
from threading import Lock
from urllib.parse import urlencode, urlsplit

import requests
from requests.structures import CaseInsensitiveDict

from parameters import (
    FLARESOLVERR_RETRY_INTERVAL,
    FLARESOLVERR_TIMEOUT,
    FLARESOLVERR_URL,
    FLARESOLVERR_DISABLE_MEDIA,
    FLARESOLVERR_RATE_LIMIT_PROXY, FLARESOLVERR_GEO_PROXY,
    FLARESOLVERR_RATE_LIMIT_SESSION, FLARESOLVERR_GEO_SESSION,
)


def create_flaresolverr_sessions(logger):
    """Create/recreate the two persistent browser sessions at application start."""
    if not FLARESOLVERR_URL:
        logger.info("FlareSolverr disabled")
        return False

    sessions = (
        (FLARESOLVERR_RATE_LIMIT_SESSION, FLARESOLVERR_RATE_LIMIT_PROXY),
        (FLARESOLVERR_GEO_SESSION, FLARESOLVERR_GEO_PROXY),
    )
    client = requests.Session()
    client.trust_env = False
    ok = True
    for session_name, proxy_url in sessions:
        try:
            response = client.post(
                FLARESOLVERR_URL,
                json={
                    "cmd": "sessions.create",
                    "session": session_name,
                    "proxy": {"url": proxy_url},
                },
                timeout=FLARESOLVERR_TIMEOUT + 10,
            )
            data = response.json()
            if data.get("status") == "ok" or "already exists" in data.get("message", "").lower():
                logger.info(
                    f"FlareSolverr session '{session_name}' ready via {proxy_url}")
            else:
                ok = False
                logger.warning(
                    f"FlareSolverr session '{session_name}' unavailable: "
                    f"{data.get('message', 'unknown error')}")
        except (requests.RequestException, ValueError) as exc:
            ok = False
            logger.warning(
                f"FlareSolverr session '{session_name}' unavailable: {exc}")
    return ok


class CloudflareSession(requests.Session):
    def __init__(self, logger, on_solved=None):
        super().__init__()
        self.trust_env = False
        self.logger = logger
        self.on_solved = on_solved
        self.route_name = "direct"
        self.flaresolverr_proxy_url = None
        self.flaresolverr_session = None
        self._solved_user_agent = None
        self._last_solve_attempt = {}
        self._solve_lock = Lock()
        self._solver_session = requests.Session()
        self._solver_session.trust_env = False

    def set_route(self, name, proxy_url, flaresolverr_proxy_url=None, flaresolverr_session=None):
        self.proxies.clear()
        if proxy_url:
            self.proxies.update({"http": proxy_url, "https": proxy_url})
        self.route_name = name
        self.flaresolverr_proxy_url = flaresolverr_proxy_url
        self.flaresolverr_session = flaresolverr_session

    @staticmethod
    def is_cloudflare_challenge(response):
        if response.headers.get("cf-mitigated", "").lower() == "challenge":
            return True
        if response.status_code != 403 or "cf-ray" not in response.headers:
            return False
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type:
            return False
        body = response.text.lower()
        return "challenges.cloudflare.com" in body or "challenge-platform" in body

    def request(self, method, url, **kwargs):
        kwargs = self._with_solved_user_agent(kwargs)
        response = super().request(method, url, **kwargs)
        if not FLARESOLVERR_URL or not self.is_cloudflare_challenge(response):
            return response

        solved_response = self._solve(response, method, url, kwargs)
        return solved_response or response

    def _with_solved_user_agent(self, kwargs):
        if not self._solved_user_agent or "headers" not in kwargs:
            return kwargs
        updated = dict(kwargs)
        updated["headers"] = dict(updated["headers"] or {})
        updated["headers"]["User-Agent"] = self._solved_user_agent
        return updated

    def _solve(self, challenged_response, method, original_url, request_kwargs):
        target_url = challenged_response.url
        origin = urlsplit(target_url).netloc
        attempt_key = (origin, self.flaresolverr_proxy_url)

        with self._solve_lock:
            now = time.monotonic()
            last_attempt = self._last_solve_attempt.get(attempt_key, 0)
            if now - last_attempt < FLARESOLVERR_RETRY_INTERVAL:
                return None
            self._last_solve_attempt[attempt_key] = now

            self.logger.info(
                f"Cloudflare challenge detected for {origin} via {self.route_name}; "
                "using FlareSolverr")

            payload, can_use_solution = self._solver_payload(
                method, target_url, request_kwargs)
            try:
                solver_response = self._solver_session.post(
                    FLARESOLVERR_URL,
                    json=payload,
                    timeout=FLARESOLVERR_TIMEOUT + 10,
                )
                solver_response.raise_for_status()
                data = solver_response.json()
            except (requests.RequestException, ValueError) as exc:
                self.logger.error(f"FlareSolverr request failed: {exc}")
                return None

            if data.get("status") != "ok" or not data.get("solution"):
                self.logger.error(
                    f"FlareSolverr failed for {origin}: "
                    f"{data.get('message', 'missing solution')}")
                return None

            solution = data["solution"]
            if self._solution_is_challenge(solution):
                self.logger.error(f"FlareSolverr did not clear the challenge for {origin}")
                return None

            self._apply_solution(solution)
            self.logger.info(f"FlareSolverr solved the challenge for {origin}")

            if can_use_solution:
                return self._response_from_solution(solution, challenged_response)

            retry_kwargs = self._with_solved_user_agent(request_kwargs)
            return super().request(method, original_url, **retry_kwargs)

    def _solver_payload(self, method, url, request_kwargs):
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": FLARESOLVERR_TIMEOUT * 1000,
        }
        if self.flaresolverr_session:
            payload["session"] = self.flaresolverr_session
        if FLARESOLVERR_DISABLE_MEDIA:
            payload["disableMedia"] = True
        if self.flaresolverr_proxy_url:
            payload["proxy"] = {"url": self.flaresolverr_proxy_url}

        if method.upper() != "POST" or request_kwargs.get("json") is not None:
            return payload, method.upper() == "GET"

        post_data = request_kwargs.get("data", "")
        if isinstance(post_data, (dict, list, tuple)):
            post_data = urlencode(post_data, doseq=True)
        elif isinstance(post_data, bytes):
            post_data = post_data.decode("utf-8")
        elif not isinstance(post_data, str):
            return payload, False

        payload["cmd"] = "request.post"
        payload["postData"] = post_data
        return payload, True

    def _apply_solution(self, solution):
        for cookie in solution.get("cookies", []):
            options = {}
            if cookie.get("domain"):
                options["domain"] = cookie["domain"]
            if cookie.get("path"):
                options["path"] = cookie["path"]
            if cookie.get("expires"):
                options["expires"] = int(cookie["expires"])
            options["secure"] = bool(cookie.get("secure", False))
            self.cookies.set(cookie["name"], cookie["value"], **options)

        user_agent = solution.get("userAgent")
        if user_agent:
            self._solved_user_agent = user_agent
            self.headers["User-Agent"] = user_agent
        if self.on_solved:
            self.on_solved(user_agent)

    @staticmethod
    def _solution_is_challenge(solution):
        headers = CaseInsensitiveDict(solution.get("headers") or {})
        if headers.get("cf-mitigated", "").lower() == "challenge":
            return True
        body = (solution.get("response") or "").lower()
        return int(solution.get("status", 0)) == 403 and (
            "challenges.cloudflare.com" in body or "challenge-platform" in body)

    @staticmethod
    def _response_from_solution(solution, challenged_response):
        body = solution.get("response") or ""
        match = re.search(r"<pre[^>]*>(.*?)</pre>", body, re.IGNORECASE | re.DOTALL)
        if match:
            body = html.unescape(match.group(1))

        response = requests.Response()
        response.status_code = int(solution.get("status", 200))
        response.headers = CaseInsensitiveDict(solution.get("headers") or {})
        response.url = solution.get("url") or challenged_response.url
        response.request = challenged_response.request
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
        response._content = body.encode(response.encoding or "utf-8")
        return response
