/** @odoo-module */
import { registry } from "@web/core/registry";
import { download } from "@web/core/network/download";

// This handler generates and downloads XLSX reports for Venue Booking Management
registry.category("ir.actions.report handlers").add("venue_xlsx_handler", async function (action, options, env) {
    if (action.report_type === 'xlsx' && action.data && typeof action.data.model === 'string' && action.data.model.startsWith('venue.')) {
        if (env && env.services && env.services.ui) {
            env.services.ui.block();
        }
        try {
            await download({
                url: '/venue_xlsx_reports',
                data: action.data,
            });
        } finally {
            if (env && env.services && env.services.ui) {
                env.services.ui.unblock();
            }
        }
        return true;
    }
});
