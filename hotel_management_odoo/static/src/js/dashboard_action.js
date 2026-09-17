/** @odoo-module */
import { registry } from '@web/core/registry';
import { useService } from "@web/core/utils/hooks";
const { Component, onWillStart, onMounted } = owl;
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { session } from "@web/session";

export class CustomDashBoard extends Component {
    _getFormattedToday() {
        const today = new Date();
        const day = String(today.getDate()).padStart(2, '0');
        const month = String(today.getMonth() + 1).padStart(2, '0');
        const year = today.getFullYear();
        return `${year}-${month}-${day}`;
    }

    get currentCompanyId() {
        return (
            (typeof user !== "undefined" && user.currentCompany && user.currentCompany.id) ||
            (typeof user !== "undefined" && user.companyId) ||
            (typeof user !== "undefined" && user.context && user.context.allowed_company_ids && user.context.allowed_company_ids[0]) ||
            (typeof session !== "undefined" && session.user_companies && (session.user_companies.current_company?.id || session.user_companies.current_company)) ||
            (typeof session !== "undefined" && session.company_id) ||
            (typeof session !== "undefined" && session.user_context && session.user_context.allowed_company_ids && session.user_context.allowed_company_ids[0]) ||
            false
        );
    }

    _getContext(extra = {}) {
        const baseCtx = (typeof user !== "undefined" && user.context) ? { ...user.context } : (typeof session !== "undefined" && session.user_context ? { ...session.user_context } : {});
        const cid = this.currentCompanyId;
        if (cid) {
            baseCtx.company_id = cid;
            baseCtx.default_company_id = cid;
        }
        return Object.assign(baseCtx, extra);
    }

    /**
     * Setup method to initialize required services and register event handlers.
     */
    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.on_reverse_breadcrum = this.on_reverse_breadcrum.bind(this);
        onWillStart(async () => {
            await this.fetch_data();
        });
        onMounted(() => {
            // Component mounted
        });
    }

    async on_reverse_breadcrum() {
        await this.fetch_data();
        this.render();
    }

    async fetch_data() {
        var self = this;
        const result = await this.orm.call('room.booking', 'get_details', [[]], {
            context: this._getContext(),
        });

        if (result) {
            self.total_room = result['total_room'] || 0;
            self.lsr_count = result['lsr_count'] || 0;
            self.prr_count = result['prr_count'] || 0;
            self.cr_count = result['cr_count'] || 0;
            self.nr_count = result['nr_count'] || 0;
            self.available_room = result['available_room'] || 0;
            self.staff = result['staff'] || 0;
            self.check_in = result['check_in'] || 0;
            self.reservation = result['reservation'] || 0;
            self.check_out = result['check_out'] || 0;
            self.today_arrival = result['today_arrival'] || 0;
            self.total_vehicle = result['total_vehicle'] || 0;
            self.available_vehicle = result['available_vehicle'] || 0;
            self.total_event = result['total_event'] || 0;
            self.today_events = result['today_events'] || 0;
            self.pending_events = result['pending_events'] || 0;
            self.food_items = result['food_items'] || 0;
            self.night_audit = result['night_audit'] || 0;
            self.food_order = result['food_order'] || 0;

            const sym = result['currency_symbol'] || '$';
            const formatCurr = (val) => {
                const num = Number(val) || 0;
                const formattedNum = num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                return result['currency_position'] === 'after' ? `${formattedNum} ${sym}` : `${sym} ${formattedNum}`;
            };
            self.total_revenue = formatCurr(result['total_revenue']);
            self.today_revenue = formatCurr(result['today_revenue']);
            self.pending_payment = formatCurr(result['pending_payment']);
        }
    }

    total_rooms(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("JPH Rooms"),
            type: 'ir.actions.act_window',
            res_model: 'hotel.room',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: cid ? [['company_id', '=', cid]] : [],
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    check_ins(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['state', '=', 'check_in']];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Occupied Rooms"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // Total Events
    view_total_events(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Total Events"),
            type: 'ir.actions.act_window',
            res_model: 'event.event',
            view_mode: 'kanban,list,form',
            views: [[false, 'kanban'], [false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: cid ? [['company_id', 'in', [cid, false]]] : [],
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // Today's Events
    fetch_today_events(e) {
        e.stopPropagation();
        e.preventDefault();
        const formattedDate = this._getFormattedToday();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['date_end', '>=', formattedDate + ' 00:00:00'], ['date_end', '<=', formattedDate + ' 23:59:59']];
        if (cid) domain.push(['company_id', 'in', [cid, false]]);
        this.action.doAction({
            name: _t("Today's Events"),
            type: 'ir.actions.act_window',
            res_model: 'event.event',
            view_mode: 'kanban,list,form',
            views: [[false, 'kanban'], [false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // Pending Events
    fetch_pending_events(e) {
        e.stopPropagation();
        e.preventDefault();
        const formattedDate = this._getFormattedToday();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['date_end', '>=', formattedDate]];
        if (cid) domain.push(['company_id', 'in', [cid, false]]);
        this.action.doAction({
            name: _t("Pending Events"),
            type: 'ir.actions.act_window',
            res_model: 'event.event',
            view_mode: 'kanban,list,form',
            views: [[false, 'kanban'], [false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // LSR (Long Stay Rooms)
    fetch_lsr_rooms(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['state', '=', 'check_in'], ['is_long_stay', '=', true]];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Long Stay Rooms (LSR)"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // RR (Reserved Rooms)
    fetch_prr_rooms(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['state', '=', 'check_in'], ['is_private_reserved', '=', true]];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Reserved Rooms (RR)"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // CR (Complimentary Rooms)
    fetch_cr_rooms(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['state', '=', 'check_in'], ['is_cr', '=', true]];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Complimentary Rooms (CR)"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // NR (Normal Rooms)
    fetch_nr_rooms(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['state', '=', 'check_in'], ['is_long_stay', '=', false], ['is_private_reserved', '=', false], ['is_cr', '=', false]];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Normal Rooms (NR)"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // Today's Departure
    check_outs(e) {
        const formattedDate = this._getFormattedToday();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [
            ['room_line_ids.checkout_date', '>=', formattedDate + ' 00:00:00'],
            ['room_line_ids.checkout_date', '<=', formattedDate + ' 23:59:59'],
            ['state', 'not in', ['cancel', 'draft']]
        ];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Today's Departure"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // Today's Arrival
    fetch_today_arrivals(e) {
        e.stopPropagation();
        e.preventDefault();
        const formattedDate = this._getFormattedToday();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [
            ['room_line_ids.checkin_date', '>=', formattedDate + ' 00:00:00'],
            ['room_line_ids.checkin_date', '<=', formattedDate + ' 23:59:59'],
            ['state', 'not in', ['cancel', 'draft']]
        ];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Today's Arrival"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // Available rooms
    available_rooms(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['status', '=', 'available']];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Vacant Rooms"),
            type: 'ir.actions.act_window',
            res_model: 'hotel.room',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // Reservations
    reservations(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['state', '=', 'reserved']];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Reserved Rooms"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // Night Audit
    fetch_night_audit(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = cid ? [['company_id', '=', cid]] : [];
        this.action.doAction({
            name: _t("Night Audit"),
            type: 'ir.actions.act_window',
            res_model: 'hotel.night.audit',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }

    // POS Orders (Guest Orders)
    async fetch_food_order(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['booking_id', '!=', false]];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Guest POS Orders"),
            type: 'ir.actions.act_window',
            res_model: 'pos.order',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext({
                'search_default_hotel_orders': 1,
                'group_by': 'date_order:month',
            }),
            target: 'current'
        }, options);
    }

    // total vehicle
    fetch_total_vehicle(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Total Vehicles"),
            type: 'ir.actions.act_window',
            res_model: 'fleet.vehicle.model',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            target: 'current'
        }, options);
    }

    // Available Vehicle
    async fetch_available_vehicle(e) {
        const result = await this.orm.call('fleet.booking.line', 'search_available_vehicle', [{}], {});
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        e.stopPropagation();
        e.preventDefault();
        this.action.doAction({
            name: _t("Available Vehicle"),
            type: 'ir.actions.act_window',
            res_model: 'fleet.vehicle.model',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: [['id', 'not in', result]],
            target: 'current'
        }, options);
    }

    // Total Revenue (Grouped by Stay Category: LSR vs Standard Check-in)
    fetch_total_revenue(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['state', 'in', ['check_in', 'check_out', 'done']]];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Total Hotel Revenue by Stay Category"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext({
                'group_by': 'stay_type',
            }),
            target: 'current'
        }, options);
    }

    // Today's Revenue (Grouped by Stay Category: LSR vs Standard Check-in)
    fetch_today_revenue(e) {
        e.stopPropagation();
        e.preventDefault();
        const formattedDate = this._getFormattedToday();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        let domain = [
            '|',
            ['state', '=', 'check_in'],
            '&', ['state', 'in', ['check_out', 'done']],
            '&', ['checkout_date', '>=', formattedDate + ' 00:00:00'], ['checkout_date', '<=', formattedDate + ' 23:59:59']
        ];
        if (cid) {
            domain = ['&', ['company_id', '=', cid], ...domain];
        }
        this.action.doAction({
            name: _t("Today's Revenue by Stay Category"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext({
                'group_by': 'stay_type',
            }),
            target: 'current'
        }, options);
    }

    // Pending Payment (Bookings with Outstanding Due Balance)
    fetch_pending_payment(e) {
        e.stopPropagation();
        e.preventDefault();
        const cid = this.currentCompanyId;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        const domain = [['state', 'in', ['check_in', 'reserved', 'check_out']], ['today_balance', '>', 0]];
        if (cid) domain.push(['company_id', '=', cid]);
        this.action.doAction({
            name: _t("Bookings with Due Balance"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            search_view_id: [false, 'search'],
            domain: domain,
            context: this._getContext(),
            target: 'current'
        }, options);
    }
}
CustomDashBoard.template = "CustomDashBoard";
registry.category("actions").add("custom_dashboard_tags", CustomDashBoard);