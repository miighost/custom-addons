// Simulates the real shop: Kitchen + Bar 1 + Bar 2 (LAN) + Bill (USB).
// Run: node tests/four_printer_setup.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(
    new URL("../static/src/js/escpos_transport.js", import.meta.url), "utf8"
)
    .replace("/** @odoo-module */", "")
    .replace('import { reactive } from "@odoo/owl";', "const reactive = (o) => o;")
    .replace('import { exportForKitchenPrinting } from "./utils";',
             "const exportForKitchenPrinting = () => ({ orderlines: [] });");
const { kitchenPrinters, receiptPrinter, makeLineFilter, findUnroutedLines } =
    await import("data:text/javascript;base64," + Buffer.from(src).toString("base64"));

let pass = 0;
const check = (label, actual, expected) => {
    assert.deepEqual(actual, expected, `${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
    console.log(`  ok  ${label}`);
    pass++;
};

// Categories: 1 Food, 10 Grills, 11 Rice  |  2 Soft drinks  |  3 Cocktails
const KITCHEN = { name: "Kitchen", role: "kitchen", category_ids: [] };       // catch-all
const BAR1 = { name: "Bar 1", role: "kitchen", category_ids: [2] };
const BAR2 = { name: "Bar 2", role: "kitchen", category_ids: [3] };
const BILL = { name: "Bill", role: "receipt", connection: "local",
               local_printer_name: "XP-58", category_ids: [] };
const ALL = [KITCHEN, BAR1, BAR2, BILL];

const line = (catIds, name) => ({
    product: { pos_categ_ids: catIds.map((id) => ({ id })), display_name: name },
    getProduct() { return this.product; },
});
const order = (lines) => ({ getOrderlines: () => lines });

console.log("role separation");
check("kitchen dispatch sees exactly the three stations",
    kitchenPrinters(ALL).map((p) => p.name), ["Kitchen", "Bar 1", "Bar 2"]);
check("the bill printer is never sent a kitchen ticket",
    kitchenPrinters(ALL).some((p) => p.role === "receipt"), false);
check("the bill printer is found for receipts", receiptPrinter(ALL).name, "Bill");
check("no receipt printer configured -> null", receiptPrinter([KITCHEN, BAR1]), null);

console.log("routing a mixed order");
const mixed = [
    line([11], "Chicken Suqaar"),   // Rice -> child of Food
    line([2], "Fanta"),             // soft drink -> Bar 1
    line([3], "Mojito"),            // cocktail -> Bar 2
];
const routed = (printer) =>
    mixed.filter(makeLineFilter(printer) || (() => true))
         .map((l) => l.getProduct().display_name);

check("Kitchen (catch-all) receives everything", routed(KITCHEN),
    ["Chicken Suqaar", "Fanta", "Mojito"]);
check("Bar 1 receives only the soft drink", routed(BAR1), ["Fanta"]);
check("Bar 2 receives only the cocktail", routed(BAR2), ["Mojito"]);

console.log("coverage");
check("catch-all kitchen means nothing is ever orphaned",
    findUnroutedLines(null, order(mixed), kitchenPrinters(ALL)), []);

console.log("the risky config: no catch-all");
const strictKitchen = { name: "Kitchen", role: "kitchen", category_ids: [1, 10, 11] };
const strict = [strictKitchen, BAR1, BAR2, BILL];
check("a new uncategorised dish IS caught before service",
    findUnroutedLines(null, order([...mixed, line([], "New Dessert")]),
        kitchenPrinters(strict)),
    ["New Dessert"]);
check("with the catch-all kitchen the same dish is safely cooked",
    findUnroutedLines(null, order([...mixed, line([], "New Dessert")]),
        kitchenPrinters(ALL)),
    []);

console.log(`\n${pass}/${pass} checks passed`);
