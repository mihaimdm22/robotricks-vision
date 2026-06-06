"""TP-Link Tapo C211 live camera: RTSP frame pull + optional PTZ control.

The C211 is your *demo prop*, NOT the contest camera. Its intrinsics differ from
the Go2 (fx != 554.3), so any metric distance shown on live Tapo frames must be
re-anchored first (see configs/camera/tapo_c211.yaml -> needs_calibration).

CAMERA ACCOUNT REQUIREMENT
--------------------------
RTSP and pytapo do NOT use your TP-Link cloud login. In the Tapo phone app open
    Advanced Settings -> Camera Account
and create a local username + password. Those credentials are what you pass here
(and what go into the rtsp:// URL). Without the Camera Account set, the camera
refuses RTSP and ONVIF/pytapo connections.

Frame pull is just RTSP over FFmpeg, delegated to catranger.io.frame_source so the
rest of the codebase treats a live Tapo identically to a video file or image dir.

    cam = TapoCamera("192.168.1.50", "camuser", "campass")          # main stream
    cam = TapoCamera("192.168.1.50", "camuser", "campass", "stream2")  # ~360p
    for idx, frame_bgr in cam.frames(stride=2, max_frames=300):
        ...

PTZ (the C211 is a pan/tilt cam) uses the `pytapo` library and is optional — only
needed if you want the *camera* to track instead of the *chassis*.
"""

from __future__ import annotations

from typing import Iterator, Optional, Tuple

import numpy as np

from catranger.config import CameraConfig
from catranger.io import frame_source


class TapoCamera:
    """Live Tapo C211: RTSP frames + optional pan/tilt motor control.

    Parameters
    ----------
    ip : str
        Camera IP on the LAN, e.g. "192.168.1.50".
    user, pwd : str
        The Tapo *Camera Account* credentials (NOT the cloud login). See module
        docstring.
    stream : str
        "stream1" = 1080p main stream, "stream2" = ~360p low-latency substream.
    """

    def __init__(self, ip: str, user: str, pwd: str, stream: str = "stream1") -> None:
        self.ip = str(ip)
        self.user = str(user)
        self.pwd = str(pwd)
        self.stream = str(stream)
        self._tapo = None  # lazily built pytapo.Tapo handle for PTZ

    # ------------------------------------------------------------------ frames
    @property
    def rtsp_url(self) -> str:
        """Full RTSP URL: rtsp://<user>:<pass>@<ip>:554/<stream>."""
        return f"rtsp://{self.user}:{self.pwd}@{self.ip}:554/{self.stream}"

    def frames(self, stride: int = 1, max_frames: int = 0) -> Iterator[Tuple[int, np.ndarray]]:
        """Yield (index, frame_bgr) from the live RTSP stream.

        Delegates to catranger.io.frame_source, which opens the stream with the
        FFmpeg backend. `stride` skips frames; `max_frames` caps the count
        (0 = unlimited / run until the stream drops).
        """
        yield from frame_source(self.rtsp_url, stride=stride, max_frames=max_frames)

    # --------------------------------------------------------------------- PTZ
    def _ensure_tapo(self):
        """Lazily build and cache the pytapo handle (raises a clear hint if missing)."""
        if self._tapo is not None:
            return self._tapo
        try:
            from pytapo import Tapo  # lazy: only needed for PTZ, not for frame pull
        except Exception as e:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                "pytapo is required for Tapo pan/tilt control "
                "(pip install pytapo). Frame pulling via .frames() does NOT need it."
            ) from e
        # pytapo authenticates against the same Camera Account used for RTSP.
        self._tapo = Tapo(self.ip, self.user, self.pwd)
        return self._tapo

    def move(self, pan: float, tilt: float) -> None:
        """Continuous relative pan/tilt move, each in [-1, 1] (+pan = right,
        +tilt = up). Maps onto pytapo.moveMotor(x, y) which takes a small signed
        step. No-op for |value| below a deadband to avoid motor chatter."""
        x = int(max(-1.0, min(1.0, float(pan))) * 100)
        y = int(max(-1.0, min(1.0, float(tilt))) * 100)
        if abs(x) < 5 and abs(y) < 5:
            return
        self._ensure_tapo().moveMotor(x, y)

    def preset(self, name: str) -> None:
        """Recall a saved PTZ preset by name (presets are created in the Tapo app
        or via pytapo). Resolves the name to its preset id, then triggers it."""
        tapo = self._ensure_tapo()
        presets = tapo.getPresets()  # {id: name}
        target_id = None
        for pid, pname in presets.items():
            if str(pname) == str(name):
                target_id = pid
                break
        if target_id is None:
            raise ValueError(f"no Tapo preset named {name!r}; have: {list(presets.values())}")
        tapo.setPreset(target_id)

    # ------------------------------------------------------------------ config
    @classmethod
    def from_config(cls, cam_cfg: CameraConfig, user: str, pwd: str) -> "TapoCamera":
        """Build a TapoCamera from a CameraConfig whose `rtsp` field is a template
        like 'rtsp://USER:PASS@CAM_IP:554/stream1'. We parse the host and stream
        out of the template and inject the real credentials.

        Falls back to the config `name` only for labeling; the IP must be present
        in the template (replace CAM_IP in the yaml, or pass a real host there).
        """
        template = cam_cfg.rtsp or ""
        ip = "CAM_IP"
        stream = "stream1"
        # crude but dependency-free parse of rtsp://<auth>@<host>:554/<stream>
        body = template.split("://", 1)[-1]
        if "@" in body:
            body = body.split("@", 1)[1]
        host_part = body.split("/", 1)
        host = host_part[0].split(":", 1)[0]
        if host:
            ip = host
        if len(host_part) > 1 and host_part[1]:
            stream = host_part[1]
        return cls(ip=ip, user=user, pwd=pwd, stream=stream)
