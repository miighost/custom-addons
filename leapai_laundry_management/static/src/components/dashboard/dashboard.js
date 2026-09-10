/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class LaundryDashboard extends Component {
    static template = "leapai_laundry_management.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, data: {} });
        onWillStart(async () => { await this._loadData(); });
    }

    async _loadData() {
        this.state.loading = true;
        this.state.data = await this.orm.call('laundry.dashboard', 'get_dashboard_data', []);
        this.state.loading = false;
    }

    openOrders(domain) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('Laundry Orders'),
            res_model: 'laundry.order',
            view_mode: 'list,form',
            domain: domain || [],
        });
    }

    openTasks(domain) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('Laundry Tasks'),
            res_model: 'laundry.task',
            view_mode: 'list,form,kanban',
            domain: domain || [],
        });
    }

    openOrder(id) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'laundry.order',
            view_mode: 'form',
            res_id: id,
        });
    }

    openTask(id) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'laundry.task',
            view_mode: 'form',
            res_id: id,
        });
    }

    stateLabel(state) {
        const map = {
            draft: _t('Draft'),
            collected: _t('Collected'),
            in_process: _t('In Process'),
            ready: _t('Ready'),
            picked_up: _t('Picked Up'),
            done: _t('Complete'),
            cancel: _t('Cancelled'),
        };
        return map[state] || state;
    }

    taskStateLabel(state) {
        const map = { new: _t('New'), in_process: _t('In Process'), done: _t('Done') };
        return map[state] || state;
    }

    typeLabel(type) {
        return type === 'delivery' ? _t('Home Delivery') : _t('Pick Up');
    }

    get refresh() {
        return () => this._loadData();
    }
}

registry.category("actions").add("laundry_dashboard", LaundryDashboard);
