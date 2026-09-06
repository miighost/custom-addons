/** @odoo-module */

/**
 * Pure decision rules for automatic kitchen printing.
 *
 * Deliberately free of Odoo and browser imports so the logic can be tested
 * on its own. Everything here is a function of its arguments.
 */

export const TRIGGER_ON_SEND = "on_send";
export const TRIGGER_ON_PAYMENT = "on_payment";

/**
 * Should the ticket print by itself at this moment?
 *
 * @param {string} moment            the trigger point being evaluated
 * @param {object} settings          kitchenSettings snapshot
 * @param {boolean} hasLines         the order has at least one line
 * @param {boolean} hasUnsentChanges something new or cancelled since last print
 * @param {boolean} alreadyPrinting  a print for this order is in flight
 */
export function shouldAutoPrint({
    moment,
    settings,
    hasLines,
    hasUnsentChanges,
    alreadyPrinting = false,
} = {}) {
    if (alreadyPrinting) {
        // Leaving and re-entering the screen quickly must not double-fire.
        return false;
    }
    if (!settings || !settings.kitchen_print_auto) {
        return false;
    }
    if (!hasLines || !hasUnsentChanges) {
        return false;
    }
    const trigger = settings.kitchen_print_trigger || TRIGGER_ON_SEND;
    return trigger === moment;
}

/** Manual reprint button visibility. Fails open when settings never arrive. */
export function showManualKotButton(settings) {
    return !settings || settings.kitchen_print !== false;
}
