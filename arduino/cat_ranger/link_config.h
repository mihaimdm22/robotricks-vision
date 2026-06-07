/*
 * link_config.h — Bluetooth / USB serial wiring for cat_ranger.ino
 *
 * Default (documented rig): HC-05/HC-06 on Mega Serial1 (TX1=pin 18, RX1=pin 19).
 * If your module is wired to D0/D1 instead, uncomment the Serial option below and
 * NEVER keep the USB cable plugged into a laptop while driving over Bluetooth
 * (USB and the module would both drive the same UART).
 *
 * After changing this file, re-flash over USB, then run the robot on battery/barrel
 * power with the USB cable unplugged from the laptop.
 */
#ifndef CATRANGER_LINK_CONFIG_H
#define CATRANGER_LINK_CONFIG_H

// Exactly one of these must be active:
#define CATRANGER_BT_LINK Serial1  // pins 18 (TX1) / 19 (RX1) — default
// #define CATRANGER_BT_LINK Serial  // pins 0/1 — only if module wired there

#define LINK_BAUD 9600

// One-line banner on the BT link at boot (ignored by host; safe for D-line parser).
#define CATRANGER_BT_BOOT_BANNER 1

// Poll USB Serial for commands while bench-testing with a cable. Set 0 for BT-only builds.
#define CATRANGER_POLL_USB 1

#endif
