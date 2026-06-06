"""Hardware integration: live Tapo C211 camera + Arduino serial bridge.

This subpackage is the I/O edge of CatRanger. It is *optional* — the scored
pipeline runs entirely on Go2 files and never imports anything here. All heavy
or device-specific deps (pytapo, pyserial) are lazy-imported inside the methods
that need them, so `import catranger.hw` stays light and only fails (with a clear
install hint) when you actually try to talk to a device.

    from catranger.hw import TapoCamera, open_bridge

    cam = TapoCamera("192.168.1.50", "camuser", "campass")
    bridge = open_bridge("/dev/ttyACM0")     # DummyBridge if port is None
    for idx, frame in cam.frames(stride=2):
        ...                                  # run pipeline -> Command
        bridge.send(command)
        gt_cm = bridge.read_distance_cm()    # ultrasonic ground truth, or None
"""

from __future__ import annotations

from catranger.hw.serial_bridge import ArduinoBridge, DummyBridge, open_bridge
from catranger.hw.tapo import TapoCamera

__all__ = ["TapoCamera", "ArduinoBridge", "DummyBridge", "open_bridge"]
