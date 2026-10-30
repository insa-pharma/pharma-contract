// Vérifie que le décodeur JS donne exactement les mêmes résultats que le codec Python.
// Usage : node test_codec.js   (après python3 truck_frame.py)
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { decodeUplink } = require("./chirpstack_codec.js");

const v = JSON.parse(fs.readFileSync(path.join(__dirname, "truck_vectors.json"), "utf8"));
let n = 0;
for (const group of [v.batch, v.heartbeat]) {
  for (const t of group) {
    const bytes = Array.from(Buffer.from(t.hex, "hex"));
    const out = decodeUplink({ bytes, fPort: t.port });
    assert.ok(!out.errors, JSON.stringify(out.errors));
    assert.deepStrictEqual(out.data, t.decoded);
    n++;
  }
}
// robustesse : trame tronquée / version inconnue / port inconnu
const first = Array.from(Buffer.from(v.batch[0].hex, "hex"));
assert.ok(decodeUplink({ bytes: first.slice(0, 20), fPort: 10 }).errors);
assert.ok(decodeUplink({ bytes: [2].concat(first.slice(1)), fPort: 10 }).errors);
assert.ok(decodeUplink({ bytes: first, fPort: 99 }).errors);
console.log(`OK: ${n} trames identiques au codec Python, 3 cas d'erreur rejetés`);
