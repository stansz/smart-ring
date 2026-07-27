import { useState, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  SVC, make16, makeBig, encodeTimeBCD, localISO,
  parseTemp, parseSpo2, parseSleep, parseHrv, parseStress,
} from "../components/ble/ringProtocol";
import type { SyncRecordSet } from "../components/ble/ringProtocol";

// ─── Wake lock ──────────────────────────────────────────────────────────────
let wl: any = null;
async function lockScreen() {
  try {
    if ("wakeLock" in navigator) {
      wl = await (navigator as any).wakeLock.request("screen");
    }
  } catch { /* unavailable */ }
}
async function unlockScreen() {
  if (wl) { try { await wl.release(); } catch {} wl = null; }
}

// ─── Write helper ───────────────────────────────────────────────────────────
function writeCh(char: BluetoothRemoteGATTCharacteristic, data: Uint8Array) {
  return (char as any).writeValueWithoutResponse(data);
}

type Phase = string | null;

export function useRingSync() {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<Phase>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);
  const deviceRef = useRef<BluetoothDevice | null>(null);
  // Tracks whether the sync finished successfully so the disconnect listener
  // (which fires after our explicit gatt.disconnect()) doesn't clobber the
  // success message with "Ring disconnected".
  const expectDisconnect = useRef(false);

  const dismiss = useCallback(() => {
    setError(null);
    setResult(null);
    setComplete(false);
  }, []);

  const sync = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.bluetooth) {
      setError("Web Bluetooth requires Android Chrome.");
      return;
    }
    setPhase("Opening device picker…");
    setError(null);
    setResult(null);
    setComplete(false);
    expectDisconnect.current = false;

    try {
      await lockScreen();

      // ── Connect ──────────────────────────────────────────────────────────────
      const dev = await navigator.bluetooth.requestDevice({
        filters: [{ namePrefix: "R09" }],
        optionalServices: [SVC.UART, SVC.BIG],
      });
      deviceRef.current = dev;
      dev.addEventListener("gattserverdisconnected", () => {
        // If we intentionally disconnected after a successful upload, this is
        // expected — don't clobber the success message with an error.
        if (expectDisconnect.current) return;
        setPhase(null);
        setError("Ring disconnected");
      });

      setPhase("Connecting…");
      const srv = await dev.gatt!.connect();
      setPhase("Discovering services…");
      const uart = await srv.getPrimaryService(SVC.UART);
      const rx = await uart.getCharacteristic(SVC.RX);
      const tx = await uart.getCharacteristic(SVC.TX);
      await tx.startNotifications();
      const big = await srv.getPrimaryService(SVC.BIG);
      const cmd = await big.getCharacteristic(SVC.CMD);
      const notify = await big.getCharacteristic(SVC.NOTIFY);
      await notify.startNotifications();

      // ── Handler registry ────────────────────────────────────────────────────
      const handlers: Record<number, (d: Uint8Array) => void> = {};
      const bdBuf: { d: Uint8Array | null } = { d: null };

      tx.addEventListener("characteristicvaluechanged", (e: any) => {
        const d = new Uint8Array(e.target.value.buffer);
        handlers[d[0]]?.(d);
      });
      notify.addEventListener("characteristicvaluechanged", (e: any) => {
        const d = new Uint8Array(e.target.value.buffer);
        bdBuf.d = bdBuf.d ? new Uint8Array([...bdBuf.d, ...d]) : new Uint8Array(d);
        if (bdBuf.d.length < 6) return;
        const len = new DataView(bdBuf.d.buffer).getUint16(2, true);
        if (bdBuf.d.length >= len + 6) {
          const done = bdBuf.d.slice(0, len + 6);
          bdBuf.d = null;
          handlers[done[1]]?.(done);
        }
      });

      function sendCmd(c: number, data: number[] = [], timeout = 8000): Promise<Uint8Array | null> {
        return new Promise((resolve, reject) => {
          const timer = setTimeout(() => { delete handlers[c]; resolve(null); }, timeout);
          handlers[c] = (d) => { clearTimeout(timer); delete handlers[c]; resolve(d); };
          writeCh(rx, make16(c, data)).catch((err: Error) => { clearTimeout(timer); delete handlers[c]; reject(err); });
        });
      }

      function sendCmdMulti(c: number, data: number[], isLast: (collected: Uint8Array[], last: Uint8Array) => boolean, timeout = 15000): Promise<Uint8Array[]> {
        return new Promise((resolve, reject) => {
          const collected: Uint8Array[] = [];
          const timer = setTimeout(() => { delete handlers[c]; resolve(collected); }, timeout);
          handlers[c] = (d) => {
            collected.push(d);
            if (isLast(collected, d)) { clearTimeout(timer); delete handlers[c]; resolve(collected); }
          };
          writeCh(rx, make16(c, data)).catch((err: Error) => { clearTimeout(timer); delete handlers[c]; reject(err); });
        });
      }

      function sendBig(type: number): Promise<Uint8Array | null> {
        return new Promise((resolve, reject) => {
          bdBuf.d = null;
          const timer = setTimeout(() => { delete handlers[type]; resolve(null); }, 20000);
          handlers[type] = (d) => { clearTimeout(timer); delete handlers[type]; resolve(d); };
          writeCh(cmd, makeBig(0xbc, type)).catch((err: Error) => { clearTimeout(timer); delete handlers[type]; reject(err); });
        });
      }

      // ── Set time ────────────────────────────────────────────────────────────
      const now = new Date();
      await sendCmd(0x01, encodeTimeBCD(now));

      // ── Battery ─────────────────────────────────────────────────────────────
      setPhase("Reading battery…");
      let batteryPct: number | null = null;
      const batResp = await sendCmd(0x03);
      if (batResp && batResp.length > 1) batteryPct = batResp[1];

      // ── Temperature ─────────────────────────────────────────────────────────
      setPhase("Fetching temperature…");
      const tempRecs: any[] = [];
      for (let t = 0x22; t <= 0x2c; t++) {
        if (t === 0x2a) continue;
        const d = await sendBig(t);
        if (d) tempRecs.push(...parseTemp(d));
      }

      // ── SpO2 ────────────────────────────────────────────────────────────────
      setPhase("Fetching SpO2…");
      const spo2Data = await sendBig(0x2a);
      const spo2Recs = spo2Data ? parseSpo2(spo2Data) : [];

      // ── Heart Rate ──────────────────────────────────────────────────────────
      const hrRecs: any[] = [];
      for (let da = 7; da >= 0; da--) {
        setPhase(`Heart rate: day ${7 - da}/8…`);
        const td = new Date(); td.setDate(td.getDate() - da); td.setHours(0, 0, 0, 0);
        const ts = Math.floor(td.getTime() / 1000);
        const buf = new ArrayBuffer(4);
        new DataView(buf).setUint32(0, ts, true);
        let size = -1;
        const packets = await sendCmdMulti(0x15, [...new Uint8Array(buf)], (_col, d) => {
          if (d[1] === 0) size = d[2];
          if (d[1] === 0xff) return true;
          return size > 0 && d[1] === size - 1;
        });
        const raw: number[] = [];
        for (const p of packets) {
          const sub = p[1];
          if (sub === 0 || sub === 0xff) continue;
          if (sub === 1) { for (let i = 6; i < 15; i++) raw.push(p[i] & 0xff); }
          else { for (let i = 2; i < 15; i++) raw.push(p[i] & 0xff); }
        }
        for (let i = 0; i < 288; i++) {
          const v = raw[i] || 0;
          if (v > 0) {
            const t = new Date(td.getTime() + i * 5 * 60000);
            hrRecs.push({ ts: localISO(t.getFullYear(), t.getMonth() + 1, t.getDate(), t.getHours(), t.getMinutes()), bpm: v });
          }
        }
      }

      // ── Sleep ───────────────────────────────────────────────────────────────
      setPhase("Fetching sleep…");
      const sleepData = await sendBig(0x27);
      const sleepRecs = sleepData ? parseSleep(sleepData) : [];

      // ── HRV ─────────────────────────────────────────────────────────────────
      const hrvRecs: any[] = [];
      for (let da = 0; da < 7; da++) {
        setPhase(`HRV: day ${da + 1}/7…`);
        const buf2 = new ArrayBuffer(4);
        new DataView(buf2).setUint32(0, da, true);
        const td = new Date(); td.setDate(td.getDate() - da); td.setHours(0, 0, 0, 0);
        const packets = await sendCmdMulti(0x39, [...new Uint8Array(buf2)], (_col, d) => d[1] === 4 || d[1] === 0xff, 12000);
        if (packets.length) hrvRecs.push(...parseHrv(packets, da, td));
      }

      // ── Steps ───────────────────────────────────────────────────────────────
      const stepRecs: any[] = [];
      for (let da = 0; da < 7; da++) {
        setPhase(`Steps: day ${da + 1}/7…`);
        const td = new Date(); td.setDate(td.getDate() - da); td.setHours(0, 0, 0, 0);
        const packets = await sendCmdMulti(0x43, [da, 0x0f, 0x00, 0x5f, 0x01], (_col, d) => {
          if (d[1] === 0xff) return true;
          if (d[1] === 0xf0) return false;
          return d[5] === d[6] - 1;
        }, 10000);
        let newCal = false;
        for (const p of packets) {
          if (p[1] === 0xff) break;
          if (p[1] === 0xf0) { if (p[3] === 1) newCal = true; continue; }
          const ti = p[4];
          let cal = p[7] | (p[8] << 8);
          if (newCal) cal *= 10;
          const st = p[9] | (p[10] << 8);
          const dist = p[11] | (p[12] << 8);
          if (st > 0 || cal > 0) {
            const t = new Date(td.getTime() + ti * 15 * 60000);
            stepRecs.push({ ts: localISO(t.getFullYear(), t.getMonth() + 1, t.getDate(), t.getHours(), t.getMinutes()), steps: st, calories: cal, distance: dist });
          }
        }
      }

      // ── Stress ──────────────────────────────────────────────────────────────
      setPhase("Fetching stress…");
      const td = new Date(); td.setHours(0, 0, 0, 0);
      const stressPkts = await sendCmdMulti(0x37, new Array(14).fill(0), (_col, d) => d[1] === 4 || d[1] === 0xff, 12000);
      const stressRecs = parseStress(stressPkts, td);

      // ── Build payload ───────────────────────────────────────────────────────
      const total = hrRecs.length + spo2Recs.length + tempRecs.length + sleepRecs.length + hrvRecs.length + stepRecs.length + stressRecs.length;
      setPhase(`Uploading ${total} records…`);

      const payload = {
        device_id: "phone",
        synced_at: new Date().toISOString(),
        battery_pct: batteryPct,
        records: {
          heart_rate: hrRecs,
          spo2: spo2Recs,
          temperature: tempRecs,
          sleep: sleepRecs,
          hrv: hrvRecs,
          steps: stepRecs,
          stress: stressRecs,
        } satisfies SyncRecordSet,
      };

      const res = await fetch("/api/mobile/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const resultData = await res.json();
      setResult(`Synced! ${resultData.accepted} new, ${resultData.skipped} skipped.`);
      setComplete(true);
      // Refresh all dashboard data — phone sync changed the DB.
      queryClient.invalidateQueries();
    } catch (e: any) {
      setPhase(null);
      setError(`Sync failed: ${e.message || e}`);
    } finally {
      // Explicitly disconnect so the R09 (single-connection) is freed for the
      // phone app or the next sync. Mark this as expected so the disconnect
      // listener doesn't fire an error.
      expectDisconnect.current = true;
      if (deviceRef.current?.gatt?.connected) {
        try { await deviceRef.current.gatt.disconnect(); } catch { /* already gone */ }
      }
      await unlockScreen();
      setPhase(null);
    }
  }, [queryClient]);

  return { phase, error, result, complete, dismiss, sync } as const;
}
