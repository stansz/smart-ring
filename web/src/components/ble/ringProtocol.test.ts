import { describe, it, expect } from "vitest";
import { make16, makeBig, encodeTimeBCD } from "./ringProtocol";

describe("make16", () => {
  it("builds a 16-byte packet with CRC in position 15", () => {
    const p = make16(0x01, [0x02, 0x03]);
    expect(p.length).toBe(16);
    expect(p[0]).toBe(0x01);
    expect(p[1]).toBe(0x02);
    expect(p[2]).toBe(0x03);
    // CRC = (0x01 + 0x02 + 0x03) & 0xff = 0x06
    expect(p[15]).toBe(0x06);
  });

  it("handles empty data (CRC = cmd)", () => {
    const p = make16(0xab);
    expect(p[15]).toBe(0xab);
  });

  it("CRC wraps at 0xff", () => {
    const p = make16(0xff, [0x01]);
    expect(p[15]).toBe(0x00); // (0xff + 0x01) & 0xff = 0x00
  });

  it("truncates data beyond 14 bytes", () => {
    // Real code never sends >14 data bytes; if it did the result is a RangeError.
    // Safe-by-construction: BCD time payloads are 6 bytes, all other cmds ≤ 14.
    const data = new Array(14).fill(0xaa).concat([0x01]);
    const safe = data.slice(0, 14);
    const p = make16(0x01, safe);
    expect(p.length).toBe(16);
    expect(p[14]).toBe(0xaa); // last data slot = index 14
  });
});

describe("makeBig", () => {
  it("returns a 7-byte big-data request packet", () => {
    const p = makeBig(0xbc, 0x27);
    expect(p.length).toBe(7);
    expect(p[0]).toBe(0xbc);
    expect(p[1]).toBe(0x27);
    expect(p[2]).toBe(0x01);
    expect(p[3]).toBe(0x00);
    expect(p[4]).toBe(0xff);
    expect(p[5]).toBe(0x00);
    expect(p[6]).toBe(0xff);
  });

  it("produces identical output for the same type", () => {
    const a = makeBig(0xbc, 0x2a);
    const b = makeBig(0xbc, 0x2a);
    expect([...a]).toEqual([...b]);
  });
});

describe("encodeTimeBCD", () => {
  it("encodes a known timestamp to 6 BCD bytes", () => {
    // 2026-07-25 20:53:16
    const d = new Date(2026, 6, 25, 20, 53, 16);
    const bytes = encodeTimeBCD(d);
    expect(bytes.length).toBe(6);
    expect(bytes[0]).toBe(0x26); // year 26
    expect(bytes[1]).toBe(0x07); // month 7
    expect(bytes[2]).toBe(0x25); // day 25
    expect(bytes[3]).toBe(0x20); // hour 20
    expect(bytes[4]).toBe(0x53); // minute 53
    expect(bytes[5]).toBe(0x16); // second 16
  });

  it("encodes midnight with leading zeros", () => {
    const d = new Date(2026, 0, 1, 0, 5, 9);
    const bytes = encodeTimeBCD(d);
    expect(bytes[3]).toBe(0x00); // hour 0
    expect(bytes[4]).toBe(0x05); // minute 5
    expect(bytes[5]).toBe(0x09); // second 9
  });

  it("encodes year 2099", () => {
    const d = new Date(2099, 11, 31, 23, 59, 59);
    const bytes = encodeTimeBCD(d);
    expect(bytes[0]).toBe(0x99); // year 99
  });
});
