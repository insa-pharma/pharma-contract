// Décodeur ChirpStack (v4) de la trame du camion, format v1.
// Même logique que truck_frame.py ; truck_vectors.json est le jeu de test commun.
// Sortie : { data: { ... } } (format decodeUplink compatible ChirpStack / TTN).

var VERSION = 1;
var PORT_BATCH = 10;
var PORT_HEARTBEAT = 11;
var NO_FIX = 0x7fffffff;
var TEMP_INVALID = -0x8000;
var HUM_INVALID = 0xff;

function u8(b, o) { return b[o]; }
function u16(b, o) { return b[o] | (b[o + 1] << 8); }
function i16(b, o) { var v = u16(b, o); return v & 0x8000 ? v - 0x10000 : v; }
function u32(b, o) { return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0; }
function i32(b, o) { return u32(b, o) | 0; }

function decodeUplink(input) {
  var b = input.bytes;
  if (input.fPort === PORT_BATCH) {
    if (b.length < 5 || b[0] !== VERSION) return { errors: ["version ou longueur invalide"] };
    var count = b[4];
    if (b.length !== 5 + count * 16) return { errors: ["longueur incohérente"] };
    var records = [];
    for (var i = 0; i < count; i++) {
      var o = 5 + i * 16;
      var lat = i32(b, o + 4), lon = i32(b, o + 8);
      var temp = i16(b, o + 12), hum = u8(b, o + 14), flags = u8(b, o + 15);
      var fix = !!(flags & 1) && lat !== NO_FIX && lon !== NO_FIX;
      records.push({
        ts_ms: u32(b, o) * 1000,
        temperature_c: temp === TEMP_INVALID ? null : temp / 100,
        humidity_pct: hum === HUM_INVALID ? null : hum / 2,
        gps_fix: fix,
        lat: fix ? lat / 1e5 : null,
        lon: fix ? lon / 1e5 : null,
        gap_before: !!(flags & 2),
        temp_alarm: !!(flags & 4),
      });
    }
    return { data: { batch_id: b[1], frame_idx: b[2], frame_total: b[3], records: records } };
  }
  if (input.fPort === PORT_HEARTBEAT) {
    if (b.length !== 9 || b[0] !== VERSION) return { errors: ["heartbeat invalide"] };
    return { data: { battery_mv: u16(b, 1), pending_records: u16(b, 3), uptime_s: u32(b, 5) } };
  }
  return { errors: ["port inconnu: " + input.fPort] };
}

if (typeof module !== "undefined") module.exports = { decodeUplink: decodeUplink };
