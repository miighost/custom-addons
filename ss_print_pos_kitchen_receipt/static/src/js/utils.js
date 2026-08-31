/** @odoo-module */

export function getRootCategoryGroup(pos, product) {
    if (!product) {
        return "Food";
    }

    // 1. Check product name directly for common drink names & keywords
    const pName = (product.name || product.display_name || "").toLowerCase();
    const drinkKeywords = [
        "drink", "drinks", "beverage", "beverages", "bar", "soda", "soft",
        "beer", "wine", "cocktail", "juice", "coffee", "tea", "water",
        "fanta", "coca", "coke", "sprite", "pepsi", "7up", "mirinda",
        "redbull", "red bull", "monster", "espresso", "latte", "cappuccino",
        "mojito", "lemonade", "milkshake", "smoothie", "tonic"
    ];

    for (const kw of drinkKeywords) {
        if (pName.includes(kw)) {
            return "Drinks";
        }
    }

    // 2. Resolve Category Name from product or POS database
    let catName = "";
    if (typeof product.pos_categ_id === "string") {
        catName = product.pos_categ_id;
    } else if (Array.isArray(product.pos_categ_id) && typeof product.pos_categ_id[1] === "string") {
        catName = product.pos_categ_id[1];
    }
    if (!catName && product.categ_id && Array.isArray(product.categ_id) && typeof product.categ_id[1] === "string") {
        catName = product.categ_id[1];
    }

    // 3. Resolve Category object from pos.db or pos.models
    let categId = false;
    if (Array.isArray(product.pos_categ_id) && product.pos_categ_id.length > 0) {
        categId = product.pos_categ_id[0];
    } else if (typeof product.pos_categ_id === "number") {
        categId = product.pos_categ_id;
    } else if (product.pos_categ_id && product.pos_categ_id.id) {
        categId = product.pos_categ_id.id;
    }

    if (categId && pos) {
        let cat = false;
        if (pos.db && typeof pos.db.get_category_by_id === "function") {
            cat = pos.db.get_category_by_id(categId);
        } else if (pos.models && pos.models["pos.category"]) {
            cat = pos.models["pos.category"].get(categId);
        }
        if (cat && cat.name) {
            catName = catName ? catName + " " + cat.name : cat.name;
        }
    }

    const lowerCat = catName.toLowerCase();
    for (const kw of drinkKeywords) {
        if (lowerCat.includes(kw)) {
            return "Drinks";
        }
    }

    return "Food";
}

export function exportForKitchenPrinting(pos, order, targetCategoryGroup = null) {
    if (!order) {
        return null;
    }

    let lines = order.getOrderlines ? order.getOrderlines() : (order.orderlines || order.lines || []);

    if (targetCategoryGroup) {
        lines = lines.filter((line) => {
            const product = line.getProduct ? line.getProduct() : (line.product || {});
            const group = getRootCategoryGroup(pos, product);
            return group === targetCategoryGroup;
        });
    }

    let hasNewItems = false;
    let hasCancelledItems = false;
    const newLines = [];
    const sentLines = [];
    const cancelledLines = [];

    const orderlines = lines.map((line) => {
        const product = line.getProduct ? line.getProduct() : (line.product || {});
        const productName = product ? (product.name || product.display_name || "") : "";
        const attributeValues =
            line.orderDisplayProductName?.attributeString ||
            (line.getFullProductName ? line.getFullProductName().replace(productName, "").trim() : "");

        let qtyNum = 1;
        let qtyStr = "";
        if (line.get_quantity) {
            qtyNum = line.get_quantity();
            qtyStr = String(qtyNum);
        } else if (line.getQuantityStr) {
            const qObj = line.getQuantityStr();
            qtyStr = qObj ? (qObj.qtyStr || String(qObj)) : "1";
            qtyNum = parseFloat(qtyStr) || 1;
        } else {
            qtyNum = line.quantity || line.qty || 1;
            qtyStr = String(qtyNum);
        }

        let note = "";
        if (pos.getStrNotes) {
            note = pos.getStrNotes(line.getNote ? line.getNote() : line.note);
        } else if (line.getNote) {
            note = line.getNote() || "";
        } else {
            note = line.note || "";
        }

        let printedQty = 0;
        if (typeof line.printed_qty === "number") {
            printedQty = line.printed_qty;
        } else if (typeof line.saved_printed_qty === "number") {
            printedQty = line.saved_printed_qty;
        } else if (typeof line.get_printed_qty === "function") {
            printedQty = line.get_printed_qty();
        } else if (line.was_printed && !line.is_new_line) {
            printedQty = qtyNum;
        }

        const newQty = Math.max(0, qtyNum - printedQty);
        const cancelledQty = Math.max(0, printedQty - qtyNum);


        const lineData = {
            qty: qtyStr,
            qty_num: qtyNum,
            printed_qty: printedQty,
            new_qty: newQty,
            cancelled_qty: cancelledQty,
            product_name: productName,
            attribute_values: attributeValues,
            note: note,
            is_new: newQty > 0,
            is_cancelled: cancelledQty > 0,
        };

        if (printedQty > 0 && newQty > 0) {
            // Added quantity to an existing previously printed line
            hasNewItems = true;
            newLines.push({
                ...lineData,
                qty: String(newQty),
                qty_num: newQty,
            });
            sentLines.push({
                ...lineData,
                qty: String(printedQty),
                qty_num: printedQty,
            });
        } else if (printedQty === 0 && newQty > 0) {
            // Brand new line never printed before
            hasNewItems = true;
            newLines.push({
                ...lineData,
                qty: String(newQty),
                qty_num: newQty,
            });
        } else if (cancelledQty > 0) {
            // Quantity reduced / line removed
            hasCancelledItems = true;
            cancelledLines.push({
                ...lineData,
                qty: String(cancelledQty),
                qty_num: cancelledQty,
            });
            if (qtyNum > 0) {
                sentLines.push({
                    ...lineData,
                    qty: String(qtyNum),
                    qty_num: qtyNum,
                });
            }
        } else {
            // Unchanged previously printed line
            sentLines.push(lineData);
        }

        return lineData;
    });


    let dateFormatted = "";
    let timeFormatted = "";
    const now = new Date();

    const d = String(now.getDate()).padStart(2, '0');
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const y = now.getFullYear();
    dateFormatted = `${d}/${m}/${y}`;

    let hours = now.getHours();
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const ampm = hours >= 12 ? 'PM' : 'AM';
    const hours12 = hours % 12 || 12;
    const hoursStr = String(hours12).padStart(2, '0');
    timeFormatted = `${hoursStr}:${minutes} ${ampm}`;
    const fullDateTime = `${dateFormatted} ${timeFormatted}`;

    const tableName =
        order.table_id && order.table_id.table_number
            ? order.table_id.table_number
            : (order.table_id?.name || "");
    const floorName =
        order.table_id && order.table_id.floor_id
            ? order.table_id.floor_id.name
            : "";

    const cashierName = order.getCashierName
        ? order.getCashierName()
        : (pos.get_cashier ? pos.get_cashier()?.name : "");

    const isAddition = Boolean(order.was_kot_printed && (hasNewItems || hasCancelledItems));

    let printCount = order.kot_print_count;
    if (typeof printCount !== "number" || printCount < 1) {
        printCount = order.was_kot_printed ? 2 : 1;
    }
    function getOrdinal(n) {
        const s = ["th", "st", "nd", "rd"];
        const v = n % 100;
        return n + (s[(v - 20) % 10] || s[v] || s[0]);
    }
    const printCountStr = getOrdinal(printCount);
    const printLabel = printCount === 1 ? "1st Print (Original)" : `${printCountStr} Print (Re-Order / Change)`;

    return {
        name: order.name || order.pos_reference || "N/A",
        date: dateFormatted,
        time: timeFormatted,
        datetime: fullDateTime,
        print_count: printCount,
        print_count_str: printCountStr,
        print_label: printLabel,
        table_name: tableName,
        floor_name: floorName,
        cashier: cashierName,
        general_note: order.general_customer_note || "",
        orderlines: orderlines,
        new_lines: newLines,
        sent_lines: sentLines,
        cancelled_lines: cancelledLines,
        is_addition: isAddition,
        has_new_items: hasNewItems || hasCancelledItems,
    };
}

