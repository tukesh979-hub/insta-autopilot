"""Instagram Reels and Threads video publishing via the official Graph APIs.

Requirements (see docs/SETUP.md):
  * Instagram Business/Creator account linked to a Facebook Page
  * Meta app with instagram_business_basic + instagram_business_content_publish
    (and instagram_business_manage_comments / insights for the other commands)
  * Graph API cannot read local files: the video must be reachable at a public
    HTTPS URL while Meta processes it. upload_public() handles that with R2/S3.
"""
from __future__ import annotations

import pathlib
import time

from .util import env as _env, http as _http, log

IG_ERROR = {"ERROR", "EXPIRED"}


def _need(name: str) -> str:
    value = _env(name)
    if not value:
        raise SystemExit(f"Missing {name} in .env (see .env.example / docs/SETUP.md)")
    return value


class IGClient:
    def __init__(self, cfg: dict):
        self.base = f"https://graph.facebook.com/{cfg['publish']['graph_version']}"
        self.user = _need("IG_USER_ID")
        self.token = _need("IG_ACCESS_TOKEN")

    def _get(self, path: str, **params):
        return _http("GET", f"{self.base}/{path}", params={**params, "access_token": self.token})

    def _post(self, path: str, **fields):
        return _http("POST", f"{self.base}/{path}", form={**fields, "access_token": self.token})

    def create_reel(self, video_url: str, caption: str) -> str:
        res = self._post(f"{self.user}/media", media_type="REELS", video_url=video_url,
                         caption=caption, share_to_feed="true")
        return res["id"]

    def wait_ready(self, container_id: str, timeout: int = 420) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._get(container_id, fields="status_code").get("status_code")
            if status == "FINISHED":
                return
            if status in IG_ERROR:
                raise RuntimeError(f"Instagram processing {status} for container {container_id}")
            time.sleep(10)
        raise TimeoutError(f"Instagram still processing container {container_id} after {timeout}s")

    def publish(self, container_id: str) -> str:
        return self._post(f"{self.user}/media_publish", creation_id=container_id)["id"]

    def comments(self, media_id: str) -> list[dict]:
        res = self._get(f"{media_id}/comments", fields="id,text,username,timestamp")
        return res.get("data", [])

    def reply(self, comment_id: str, message: str) -> str:
        return self._post(f"{comment_id}/replies", message=message)["id"]

    def insights(self, media_id: str, metrics: list[str]) -> dict:
        res = self._get(f"{media_id}/insights", metric=",".join(metrics))
        return {row["name"]: row.get("values", [{}])[0].get("value", row.get("total_value", {}).get("value"))
                for row in res.get("data", [])}


class ThreadsClient:
    def __init__(self, cfg: dict):
        self.base = "https://graph.threads.net/v1.0"
        self.user = _need("THREADS_USER_ID")
        self.token = _need("THREADS_ACCESS_TOKEN")

    def _get(self, path: str, **params):
        return _http("GET", f"{self.base}/{path}", params={**params, "access_token": self.token})

    def _post(self, path: str, **fields):
        return _http("POST", f"{self.base}/{path}", form={**fields, "access_token": self.token})

    def create_video(self, video_url: str, text: str) -> str:
        return self._post(f"{self.user}/threads", media_type="VIDEO", video_url=video_url,
                          text=text)["id"]

    def wait_ready(self, container_id: str, timeout: int = 420) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._get(container_id, fields="status").get("status")
            if status == "FINISHED":
                return
            if status in IG_ERROR:
                raise RuntimeError(f"Threads processing {status} for container {container_id}")
            time.sleep(10)
        raise TimeoutError(f"Threads still processing container {container_id}")

    def publish(self, container_id: str) -> str:
        return self._post(f"{self.user}/threads_publish", creation_id=container_id)["id"]


def upload_public(video: pathlib.Path, cfg: dict) -> str:
    """Upload to an S3-compatible bucket (Cloudflare R2 by default) and return a public URL."""
    mode = cfg["publish"]["upload"]
    if mode != "r2":
        raise SystemExit(f"Unsupported upload mode '{mode}'. Use 'r2' or add a provider here.")
    try:
        import boto3  # optional dependency: pip install boto3
    except ImportError:
        raise SystemExit("Install boto3 for R2 uploads: pip install -r requirements.txt") from None

    s3 = boto3.client(
        "s3",
        endpoint_url=_need("R2_ENDPOINT"),
        aws_access_key_id=_need("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_need("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )
    bucket = _need("R2_BUCKET")
    key = f"reels/{video.parent.parent.name}-{int(time.time())}.mp4"
    s3.upload_file(str(video), bucket, key, ExtraArgs={"ContentType": "video/mp4"})
    base = cfg["publish"]["public_base_url"].rstrip("/")
    url = f"{base}/{key}"
    log(f"Uploaded {video.name} -> {url}")
    return url
