// Run: node tests/routing.test.mjs
// Exercises category routing and unrouted-line detection without an Odoo runtime.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// escpos_transport imports owl and ./utils; stub both so the pure routing
// helpers can be loaded on their own.
let src = readFileSync(
    new URL("../static/src/js/escpos_transport.js", import.meta.url), "utf8"
)
    .replace("/** @odoo-module */", "")
    .replace('import { reactive } from "@odoo/owl";', "const reactive = (o) => o;")
    .replace('import { exportForKitchenPrinting } from "./utils";',
             "const exportForKitchenPrinting = () => ({ orderlines: [] });");
const mod = await import(
    "data:text/javascript;base64," + Buffer.from(src).toString("base64")
);
const { productCategoryIds, makeLineFilter, findUnroutedLines } = mod;

let pass = 0;
const check = (label, actual, expected) => {
    assert.deepEqual(actual, expected, `${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
    console.log(`  ok  ${label}`);
    pass++;
};

console.log("product category extraction (the shapes Odoo actually uses)");
check("many2many of record objects (Odoo 17+)",
    productCategoryIds({ pos_categ_ids: [{ id: 4 }, { id: 7 }] }), [4, 7]);
check("plain id array", productCategoryIds({ pos_categ_ids: [4, 7] }), [4, 7]);
check("legacy [id, name] pair", productCategoryIds({ pos_categ_id: [4, "Drinks"] }), [4]);
check("bare id", productCategoryIds({ pos_categ_id: 4 }), [4]);
check("record object", productCategoryIds({ pos_categ_id: { id: 9 } }), [9]);
check("falls back to categ_id", productCategoryIds({ categ_id: [3, "All"] }), [3]);
check("no category at all", productCategoryIds({}), []);
check("null product", productCategoryIds(null), []);

console.log("per-printer line filter");
const line = (catIds, name) => ({
    product: { pos_categ_ids: catIds.map((id) => ({ id })), display_name: name },
    getProduct() { return this.product; },
});
const kitchen = { name: "Kitchen", category_ids: [1, 10, 11] }; // 10/11 = children of 1
const bar = { name: "Bar", category_ids: [2] };
const catchAll = { name: "Single", category_ids: [] };

check("kitchen takes a food line", makeLineFilter(kitchen)(line([1], "Suqaar")), true);
check("kitchen takes a CHILD category line", makeLineFilter(kitchen)(line([11], "Grill")), true);
check("kitchen rejects a drink", makeLineFilter(kitchen)(line([2], "Fanta")), false);
check("bar takes the drink", makeLineFilter(bar)(line([2], "Fanta")), true);
check("printer with no categories is a catch-all", makeLineFilter(catchAll), null);

console.log("unrouted-line detection");
const order = (lines) => ({ getOrderlines: () => lines });

check("everything covered -> no orphans",
    findUnroutedLines(null, order([line([1], "Suqaar"), line([2], "Fanta")]), [kitchen, bar]), []);
check("uncategorised product IS flagged",
    findUnroutedLines(null, order([line([], "Mystery Dish")]), [kitchen, bar]), ["Mystery Dish"]);
check("product in an unrouted category IS flagged",
    findUnroutedLines(null, order([line([1], "Suqaar"), line([99], "New Dessert")]), [kitchen, bar]),
    ["New Dessert"]);
check("a catch-all printer means nothing can be orphaned",
    findUnroutedLines(null, order([line([99], "New Dessert")]), [kitchen, catchAll]), []);
check("no printers configured -> handled elsewhere, not flagged here",
    findUnroutedLines(null, order([line([99], "x")]), []), []);
check("empty order -> nothing to flag",
    findUnroutedLines(null, order([]), [kitchen, bar]), []);

console.log(`\n${pass}/${pass} checks passed`);
