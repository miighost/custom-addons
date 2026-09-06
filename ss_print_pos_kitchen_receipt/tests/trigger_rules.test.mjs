// Run: node tests/trigger_rules.test.mjs
// Pure logic, no Odoo runtime needed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Load the module source directly, stripping the Odoo bundle marker.
const src = readFileSync(
    new URL("../static/src/js/trigger_rules.js", import.meta.url), "utf8"
).replace("/** @odoo-module */", "");
const mod = await import(
    "data:text/javascript;base64," + Buffer.from(src).toString("base64")
);
const { shouldAutoPrint, showManualKotButton, TRIGGER_ON_SEND, TRIGGER_ON_PAYMENT } = mod;

const base = {
    settings: { kitchen_print_auto: true, kitchen_print_trigger: TRIGGER_ON_SEND },
    hasLines: true,
    hasUnsentChanges: true,
    alreadyPrinting: false,
};
let pass = 0;
const check = (label, actual, expected) => {
    assert.equal(actual, expected, `${label}: expected ${expected}, got ${actual}`);
    console.log(`  ok  ${label}`);
    pass++;
};

console.log("on_send trigger");
check("fires when leaving the order screen",
    shouldAutoPrint({ ...base, moment: TRIGGER_ON_SEND }), true);
check("does NOT fire again at payment",
    shouldAutoPrint({ ...base, moment: TRIGGER_ON_PAYMENT }), false);

console.log("on_payment trigger");
const pay = { ...base, settings: { kitchen_print_auto: true, kitchen_print_trigger: TRIGGER_ON_PAYMENT } };
check("fires at payment", shouldAutoPrint({ ...pay, moment: TRIGGER_ON_PAYMENT }), true);
check("does NOT fire on send", shouldAutoPrint({ ...pay, moment: TRIGGER_ON_SEND }), false);

console.log("guards");
check("automatic off -> never fires",
    shouldAutoPrint({ ...base, moment: TRIGGER_ON_SEND, settings: { kitchen_print_auto: false } }), false);
check("empty order -> never fires",
    shouldAutoPrint({ ...base, moment: TRIGGER_ON_SEND, hasLines: false }), false);
check("nothing changed -> never fires",
    shouldAutoPrint({ ...base, moment: TRIGGER_ON_SEND, hasUnsentChanges: false }), false);
check("print already in flight -> never fires (no double ticket)",
    shouldAutoPrint({ ...base, moment: TRIGGER_ON_SEND, alreadyPrinting: true }), false);
check("no settings at all -> never fires",
    shouldAutoPrint({ ...base, moment: TRIGGER_ON_SEND, settings: null }), false);
check("missing trigger defaults to on_send",
    shouldAutoPrint({ ...base, moment: TRIGGER_ON_SEND, settings: { kitchen_print_auto: true } }), true);
check("no arguments at all does not throw", shouldAutoPrint(), false);

console.log("manual button visibility");
check("visible by default", showManualKotButton({}), true);
check("visible when settings never loaded", showManualKotButton(undefined), true);
check("hidden only on an explicit false", showManualKotButton({ kitchen_print: false }), false);
check("visible when explicitly true", showManualKotButton({ kitchen_print: true }), true);

console.log(`\n${pass}/${pass} checks passed`);
