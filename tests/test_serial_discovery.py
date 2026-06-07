"""Tests for serial port discovery helpers."""

from __future__ import annotations

from unittest.mock import patch

from catranger.hw import serial_discovery as sd


def test_list_serial_ports_merges_pyserial_and_glob() -> None:
    class Port:
        device = "/dev/cu.usbserial-1410"
        description = "USB Serial"
        manufacturer = "WCH"
        vid = 0x1A86
        pid = 0x7523

    with (
        patch.object(sd, "glob") as mock_glob,
        patch("serial.tools.list_ports.comports", return_value=[Port()]),
    ):
        mock_glob.glob.side_effect = lambda pattern: (
            ["/dev/cu.usbserial-1410", "/dev/cu.Bluetooth-Incoming-Port"]
            if pattern == "/dev/cu.*"
            else []
        )
        with patch.object(sd.sys, "platform", "darwin"):
            ports = sd.list_serial_ports()

    assert len(ports) == 1
    assert ports[0]["target"] == "/dev/cu.usbserial-1410"
    assert ports[0]["manufacturer"] == "WCH"


def test_discover_hint_when_empty() -> None:
    hint = sd.discover_hint([])
    assert hint is not None
    assert "HC-05" in hint


def test_discover_hint_usb_like() -> None:
    hint = sd.discover_hint([{"target": "/dev/cu.usbmodem1101", "label": "Mega"}])
    assert hint is not None
    assert "Arduino USB port" in hint


def test_arduino_ports_filters_junk() -> None:
    ports = [
        {"target": "/dev/cu.debug-console", "label": "n/a"},
        {"target": "/dev/cu.usbserial-1410", "label": "CH340"},
    ]
    assert len(sd.arduino_ports(ports)) == 1
    assert sd.arduino_ports(ports)[0]["target"] == "/dev/cu.usbserial-1410"


def test_bluetooth_spp_ports_finds_hc05() -> None:
    ports = [
        {"target": "/dev/cu.Bluetooth-Incoming-Port", "label": "n/a"},
        {"target": "/dev/cu.HC-05-DevB", "label": "HC-05"},
        {"target": "/dev/cu.usbserial-1410", "label": "CH340"},
    ]
    bt = sd.bluetooth_spp_ports(ports)
    assert len(bt) == 1
    assert bt[0]["target"] == "/dev/cu.HC-05-DevB"
    assert bt[0]["kind"] == "bluetooth_spp"


def test_discover_hint_mentions_bluetooth_when_empty() -> None:
    hint = sd.discover_hint([])
    assert hint is not None
    assert "HC-05" in hint


def test_pick_usb_telemetry_port_skips_bt() -> None:
    with patch.object(sd, "list_serial_ports") as mock_list:
        mock_list.return_value = [
            {"target": "/dev/cu.HC-06", "label": "HC-06"},
            {"target": "/dev/cu.usbserial-10", "label": "Mega"},
        ]
        assert sd.pick_usb_telemetry_port() == "/dev/cu.usbserial-10"
        assert sd.pick_usb_telemetry_port(exclude="/dev/cu.usbserial-10") is None
