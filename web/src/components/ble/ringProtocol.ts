/**
 * Pure protocol constants and helpers for Colmi R09 Web Bluetooth sync.
 * Extracted from the legacy dashboard IIFE — byte-for-byte identical logic,
 * typed for React/TypeScript consumption.
 */

// ─── BLE service / characteristic UUIDs ─────────────────────────────────────
export const SVC = {
  UART:   "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e",
  RX:     "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
  TX:     "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
  BIG:    "de5bf728-d711-4e47-af26-65e3012a5dc7",
  CMD:    "de5bf72a-d711-4e47-af26-65e3012a5dc7",
  NOTIFY: "de5bf729-d711-4e47-af26-65e3012a5dc7",
} as const;

// ─── Timestamp helpers ──────────────────────────────────────────────────────
const pad2 = (n: number) => String(n).padStart(2, "0");
const tzOffset = -new Date().getTimezoneOffset();
const tzSign = tzOffset >= 0 ? "+" : "-";
const tzStr = `${tzSign}${pad2(Math.floor(Math.abs(tzOffset) / 60))}:${pad2(Math.abs(tzOffset) % 60)}`;

export function localISO(y: number, mo: number, d: number, h: number, mi = 0): string {
  return `${y}-${pad2(mo)}-${pad2(d)}T${pad2(h)}:${pad2(mi)}:00${tzStr}`;
}

export function localDateISO(dt: Date, h = 0, mi = 0): string {
  return localISO(dt.getFullYear(), dt.getMonth() + 1, dt.getDate(), h, mi);
}

export function localDayStr(dt: Date): string {
  return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}`;
}

// ─── Packet framing ─────────────────────────────────────────────────────────
export function make16(cmd: number, data: number[] = []): Uint8Array {
  const p = new Uint8Array(16);
  p[0] = cmd;
  p.set(data, 1);
  let c = cmd;
  for (const b of data) c = (c + b) & 0xff;
  p[15] = c;
  return p;
}

export function makeBig(_cmd: number, type: number): Uint8Array {
  return new Uint8Array([0xbc, type, 0x01, 0x00, 0xff, 0x00, 0xff]);
}

/** BCD-encode a datetime into the 6-byte ring set_time payload. */
export function encodeTimeBCD(d: Date): number[] {
  const y = d.getFullYear() % 2000;
  return [
    ((y / 10) << 4) | (y % 10),
    ((d.getMonth() + 1) / 10 << 4) | ((d.getMonth() + 1) % 10),
    ((d.getDate() / 10) << 4) | (d.getDate() % 10),
    ((d.getHours() / 10) << 4) | (d.getHours() % 10),
    ((d.getMinutes() / 10) << 4) | (d.getMinutes() % 10),
    ((d.getSeconds() / 10) << 4) | (d.getSeconds() % 10),
  ];
}

// ─── Record types for the sync payload ──────────────────────────────────────
export interface SyncRecordSet {
  heart_rate: { ts: string; bpm: number }[];
  spo2: { ts: string; spo2_pct: number }[];
  temperature: { ts: string; temp_c: number }[];
  sleep: { day: string; stage: string; start_ts: string; end_ts: string; duration_minutes: number }[];
  hrv: { ts: string; hrv_value: number; hrv_type: string }[];
  steps: { ts: string; steps: number; calories: number; distance: number }[];
  stress: { ts: string; stress_value: number }[];
}

// ─── sync data parsers ──────────────────────────────────────────────────────
function viewU16(buf: ArrayBufferLike, offset: number): number {
  return new DataView(buf as ArrayBuffer).getUint16(offset, true);
}

export function parseTemp(d: Uint8Array): { ts: string; temp_c: number }[] {
  const recs: { ts: string; temp_c: number }[] = [];
  if (!d || d.length < 6 || d[1] !== 0x25) return recs;
  const len = viewU16(d.buffer, 2);
  let i = 6;
  while (i + 50 <= 6 + len && i + 50 <= d.length) {
    const da = d[i++]; i++; // days_ago + skip
    const td = new Date(); td.setDate(td.getDate() - da);
    for (let h = 0; h < 24; h++) {
      const t00 = d[i] & 0xff; i++;
      const t30 = d[i] & 0xff; i++;
      if (t00 > 0) recs.push({ ts: localDateISO(td, h, 0), temp_c: +(t00 / 10 + 20).toFixed(1) });
      if (t30 > 0) recs.push({ ts: localDateISO(td, h, 30), temp_c: +(t30 / 10 + 20).toFixed(1) });
    }
  }
  return recs;
}

export function parseSpo2(d: Uint8Array): { ts: string; spo2_pct: number }[] {
  const recs: { ts: string; spo2_pct: number }[] = [];
  if (!d || d.length < 6) return recs;
  const len = viewU16(d.buffer, 2);
  let i = 6;
  while (i + 49 <= 6 + len && i + 49 <= d.length) {
    const da = d[i++];
    const td = new Date(); td.setDate(td.getDate() - da);
    for (let h = 0; h < 24; h++) {
      const mn = d[i++] & 0xff;
      const mx = d[i++] & 0xff;
      if (mn > 0 && mx > 0) recs.push({ ts: localDateISO(td, h), spo2_pct: Math.round((mn + mx) / 2) });
    }
  }
  return recs;
}

export function parseSleep(d: Uint8Array): { day: string; stage: string; start_ts: string; end_ts: string; duration_minutes: number }[] {
  const recs: { day: string; stage: string; start_ts: string; end_ts: string; duration_minutes: number }[] = [];
  if (!d || d.length < 6) return recs;
  let i = 7;
  const days = d[6];
  for (let di = 0; di < days; di++) {
    const da = d[i++];
    const dayBytes = d[i++];
    const sleepStart = viewU16(d.buffer, i); i += 2;
    const sleepEnd = viewU16(d.buffer, i); i += 2;
    const td = new Date(); td.setDate(td.getDate() - da);
    const dt = localDayStr(td);
    let ss = new Date(td); ss.setHours(0, 0, 0, 0);
    if (sleepStart > sleepEnd) ss.setMinutes(sleepStart - 1440);
    else ss.setMinutes(sleepStart);
    for (let j = 4; j < dayBytes; j += 2) {
      const stageMap: Record<number, string> = { 2: "light", 3: "deep", 4: "rem", 5: "awake" };
      const st = stageMap[d[i]] || "unknown";
      const dur = d[i + 1];
      i += 2;
      if (dur > 0) {
        const se = new Date(ss.getTime() + dur * 60000);
        recs.push({
          day: dt,
          stage: st,
          start_ts: localISO(ss.getFullYear(), ss.getMonth() + 1, ss.getDate(), ss.getHours(), ss.getMinutes()),
          end_ts: localISO(se.getFullYear(), se.getMonth() + 1, se.getDate(), se.getHours(), se.getMinutes()),
          duration_minutes: dur,
        });
        ss = new Date(se);
      }
    }
  }
  return recs;
}

export function parseHrv(packets: Uint8Array[], _dayOffset: number, td: Date): { ts: string; hrv_value: number; hrv_type: string }[] {
  const recs: { ts: string; hrv_value: number; hrv_type: string }[] = [];
  for (const p of packets) {
    const sub = p[1];
    if (sub === 0 || sub === 0xff) continue;
    const start = sub === 1 ? 3 : 2;
    const minPrev = sub === 1 ? 0 : (12 * 30 + (sub - 2) * 13 * 30);
    for (let i = start; i < 15; i++) {
      const v = p[i] & 0xff;
      if (v > 0) {
        const t = new Date(td.getTime() + (minPrev + (i - start) * 30) * 60000);
        recs.push({ ts: localISO(t.getFullYear(), t.getMonth() + 1, t.getDate(), t.getHours(), t.getMinutes()), hrv_value: v, hrv_type: "composite" });
      }
    }
  }
  return recs;
}

export function parseStress(packets: Uint8Array[], td: Date): { ts: string; stress_value: number }[] {
  const recs: { ts: string; stress_value: number }[] = [];
  for (const p of packets) {
    const sub = p[1];
    if (sub === 0 || sub === 0xff) continue;
    const start = sub === 1 ? 3 : 2;
    const minPrev = sub === 1 ? 0 : (12 * 30 + (sub - 2) * 13 * 30);
    for (let i = start; i < 15; i++) {
      const v = p[i] & 0xff;
      if (v > 0) {
        const t = new Date(td.getTime() + (minPrev + (i - start) * 30) * 60000);
        recs.push({ ts: localISO(t.getFullYear(), t.getMonth() + 1, t.getDate(), t.getHours(), t.getMinutes()), stress_value: v });
      }
    }
  }
  return recs;
}
