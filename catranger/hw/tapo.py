"""TP-Link Tapo C211 live camera: RTSP frame pull + optional PTZ control.

The C211 is your *demo prop*, NOT the contest camera. Its intrinsics differ from
the Go2 (fx != 554.3), so any metric distance shown on live Tapo frames must be
re-anchored first (see configs/camera/tapo_c211.yaml -> needs_calibration).

CAMERA ACCOUNT REQUIREMENT
--------------------------
RTSP and ONVIF do NOT use your TP-Link cloud login. In the Tapo phone app open
    Advanced Settings -> Camera Account
and create a local username + password. Those credentials are what you pass here
(and what go into the rtsp:// URL). Without the Camera Account set, the camera
refuses RTSP and ONVIF connections.

Also enable **Me -> Tapo Lab -> Third-Party Compatibility** in the Tapo app if
ONVIF/PTZ commands fail.

Frame pull is RTSP over FFmpeg (catranger.io.frame_source). Pan/tilt uses ONVIF
(port 2020) with the same Camera Account — more reliable than pytapo on recent
Tapo firmware, which often rejects Camera Account auth even when RTSP works.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from catranger.config import CameraConfig
from catranger.io import frame_source

_ONVIF_PORT = 2020
# Console nudges are ±0.25; map to a small ONVIF RelativeMove step.
_PTZ_STEP_SCALE = 0.2


class _OnvifPtz:
    """Tapo pan/tilt via ONVIF RelativeMove (Camera Account on port 2020)."""

    def __init__(self, ip: str, user: str, pwd: str) -> None:
        self._ip = str(ip)
        self._user = str(user)
        self._pwd = str(pwd)
        self._profile_token: str | None = None
        self._ptz = None

    def _connect(self) -> None:
        if self._ptz is not None:
            return
        try:
            from onvif import ONVIFCamera  # type: ignore[import-untyped]
        except Exception as e:  # pragma: no cover - optional dep
            raise RuntimeError(
                "onvif-zeep is required for Tapo pan/tilt "
                "(uv sync --extra hw). Frame pulling via RTSP does NOT need it."
            ) from e
        cam = ONVIFCamera(self._ip, _ONVIF_PORT, self._user, self._pwd)
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            raise RuntimeError("ONVIF: no media profiles on Tapo camera")
        self._profile_token = profiles[0].token
        self._ptz = cam.create_ptz_service()

    def move(self, pan: float, tilt: float) -> None:
        pan = max(-1.0, min(1.0, float(pan)))
        tilt = max(-1.0, min(1.0, float(tilt)))
        if abs(pan) < 0.05 and abs(tilt) < 0.05:
            return
        self._connect()
        assert self._ptz is not None and self._profile_token is not None
        req = self._ptz.create_type("RelativeMove")
        req.ProfileToken = self._profile_token
        req.Translation = {"PanTilt": {"x": pan * _PTZ_STEP_SCALE, "y": tilt * _PTZ_STEP_SCALE}}
        self._ptz.RelativeMove(req)

    def preset(self, name: str) -> None:
        self._connect()
        assert self._ptz is not None and self._profile_token is not None
        presets = self._ptz.GetPresets({"ProfileToken": self._profile_token}) or []
        for preset in presets:
            if str(getattr(preset, "Name", "")) == str(name):
                self._ptz.GotoPreset(
                    {"ProfileToken": self._profile_token, "PresetToken": preset.token}
                )
                return
        names = [getattr(p, "Name", p.token) for p in presets]
        raise ValueError(f"no Tapo preset named {name!r}; have: {names}")


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
        self._ptz: _OnvifPtz | None = None

    # ------------------------------------------------------------------ frames
    @property
    def rtsp_url(self) -> str:
        """Full RTSP URL: rtsp://<user>:<pass>@<ip>:554/<stream>."""
        return f"rtsp://{self.user}:{self.pwd}@{self.ip}:554/{self.stream}"

    def frames(self, stride: int = 1, max_frames: int = 0) -> Iterator[tuple[int, np.ndarray]]:
        """Yield (index, frame_bgr) from the live RTSP stream."""
        yield from frame_source(self.rtsp_url, stride=stride, max_frames=max_frames)

    # --------------------------------------------------------------------- PTZ
    def _ensure_ptz(self) -> _OnvifPtz:
        if self._ptz is None:
            self._ptz = _OnvifPtz(self.ip, self.user, self.pwd)
        return self._ptz

    def move(self, pan: float, tilt: float) -> None:
        """Relative pan/tilt nudge, each in [-1, 1] (+pan = right, +tilt = up)."""
        self._ensure_ptz().move(pan, tilt)

    def preset(self, name: str) -> None:
        """Recall a saved PTZ preset by name (created in the Tapo app)."""
        self._ensure_ptz().preset(name)

    # ------------------------------------------------------------------ config
    @classmethod
    def from_config(cls, cam_cfg: CameraConfig, user: str, pwd: str) -> TapoCamera:
        """Build a TapoCamera from a CameraConfig whose `rtsp` field is a template
        like 'rtsp://USER:PASS@CAM_IP:554/stream1'. We parse the host and stream
        out of the template and inject the real credentials."""
        template = cam_cfg.rtsp or ""
        ip = "CAM_IP"
        stream = "stream1"
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
