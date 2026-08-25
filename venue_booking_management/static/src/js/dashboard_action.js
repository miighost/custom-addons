/** @odoo-module **/

import { Component, onWillStart, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const actionRegistry = registry.category("actions");

/* Custom Dashboard for Venue Booking Management */
class CustomDashBoard extends Component {
    static template = "CustomDashBoard";

    setup() {
        this.orm = useService('orm');
        this.bookingCanvasRef = useRef('booking');
        this.venueCanvasRef = useRef('venue');
        this.stockSelectionRef = useRef('stock_selection');

        this.totalBookingRef = useRef('total_booking');
        this.totalVenueRef = useRef('total_venue');
        this.totalAmountRef = useRef('total_amount');
        this.totalInvoiceRef = useRef('total_invoice');
        this.bookingThisYearRef = useRef('booking_this_year');
        this.venueThisYearRef = useRef('venue_this_year');
        this.amountThisYearRef = useRef('amount_this_year');
        this.invoiceThisYearRef = useRef('invoice_this_year');
        this.bookingThisDayRef = useRef('booking_this_day');
        this.venueThisDayRef = useRef('venue_this_day');
        this.amountThisDayRef = useRef('amount_this_day');
        this.invoiceThisDayRef = useRef('invoice_this_day');
        this.bookingThisWeekRef = useRef('booking_this_week');
        this.venueThisWeekRef = useRef('venue_this_week');
        this.amountThisWeekRef = useRef('amount_this_week');
        this.invoiceThisWeekRef = useRef('invoice_this_week');
        this.bookingThisMonthRef = useRef('booking_this_month');
        this.venueThisMonthRef = useRef('venue_this_month');
        this.amountThisMonthRef = useRef('amount_this_month');
        this.invoiceThisMonthRef = useRef('invoice_this_month');

        onWillStart(async () => {
            const totalCount = this.orm.call('venue.booking', 'get_total_booking').then(result => {
                if (result) {
                    this.props.booking_count = result.total_booking || 0;
                    this.props.total_venue = result.total_venue || 0;
                    this.props.total_amount = result.total_amount || 0;
                    this.props.total_invoice = result.total_invoice || 0;
                }
            }).catch(err => console.warn(err));

            const tableContent = this.orm.call('venue.booking', 'get_top_venue').then(result => {
                if (result) {
                    this.props.upcoming = result.upcoming || [];
                    this.props.venue = result.venue || [];
                    this.props.customer = result.customer || [];
                }
            }).catch(err => console.warn(err));

            await Promise.all([totalCount, tableContent]);
        });

        onMounted(() => {
            this.render_booking();
            this.render_venue();
        });
    }

    get_filter_value() {
        if (this.stockSelectionRef && this.stockSelectionRef.el) {
            return this.stockSelectionRef.el.value || 'month';
        }
        return 'month';
    }

    render_booking() {
        const ctx = this.bookingCanvasRef ? this.bookingCanvasRef.el : null;
        if (!ctx) return;
        const filterVal = this.get_filter_value();
        this.orm.call('venue.booking', 'get_select_filter', [filterVal]).then(result => {
            if (!result || !ctx) return;
            const data = {
                labels: result.cust_invoice_name || [],
                datasets: [{
                    label: _t('Count'),
                    data: result.cust_invoice_count || [],
                    backgroundColor: [
                        "#003f5c", "#2f4b7c", "#f95d6a", "#665191",
                        "#d45087", "#ff7c43", "#ffa600", "#a05195", "#6d5c16"
                    ],
                    borderColor: [
                        "#003f5c", "#2f4b7c", "#f95d6a", "#665191",
                        "#d45087", "#ff7c43", "#ffa600", "#a05195", "#6d5c16"
                    ],
                    barPercentage: 0.5,
                    barThickness: 6,
                    maxBarThickness: 8,
                    minBarLength: 0,
                    borderWidth: 1,
                    fill: false
                }]
            };

            const options = {
                responsive: true,
                scales: {
                    y: { beginAtZero: true }
                }
            };

            if (typeof Chart !== 'undefined') {
                new Chart(ctx, {
                    type: "bar",
                    data: data,
                    options: options
                });
            }
        }).catch(err => console.warn('render_booking error:', err));
    }

    render_venue() {
        const ctx = this.venueCanvasRef ? this.venueCanvasRef.el : null;
        if (!ctx) return;
        const filterVal = this.get_filter_value();
        this.orm.call('venue.booking', 'get_select_filter', [filterVal]).then(result => {
            if (!result || !ctx) return;
            const data = {
                labels: result.truck_invoice_name || [],
                datasets: [{
                    label: _t('Count'),
                    data: result.truck_invoice_sum || [],
                    backgroundColor: [
                        "#665191", "#ff7c43", "#ffa600", "#d45087",
                        "#a05195", "#6d5c16", "#CCCCFF", "#003f5c",
                        "#2f4b7c", "#f95d6a"
                    ],
                    borderColor: [
                        "#003f5c", "#2f4b7c", "#f95d6a", "#665191",
                        "#d45087", "#ff7c43", "#ffa600", "#a05195",
                        "#6d5c16", "#CCCCFF"
                    ],
                    barPercentage: 0.5,
                    barThickness: 6,
                    maxBarThickness: 8,
                    minBarLength: 0,
                    borderWidth: 1,
                    fill: false
                }]
            };

            const options = {
                responsive: true,
                scales: {
                    y: { beginAtZero: true }
                }
            };

            if (typeof Chart !== 'undefined') {
                new Chart(ctx, {
                    type: "pie",
                    data: data,
                    options: options
                });
            }
        }).catch(err => console.warn('render_venue error:', err));
    }

    on_change_booking_values(e) {
        if (e) e.stopPropagation();
        const value = this.get_filter_value();
        if (value === "year") {
            this.onclick_this_year(value);
        } else if (value === "quarter") {
            this.onclick_this_quarter(value);
        } else if (value === "month") {
            this.onclick_this_month(value);
        } else if (value === "week") {
            this.onclick_this_week(value);
        } else if (value === "day") {
            this.onclick_this_day(value);
        }
    }

    set_display(ref, display) {
        if (ref && ref.el) {
            ref.el.style.display = display;
        }
    }

    set_html(ref, html) {
        if (ref && ref.el) {
            ref.el.innerHTML = html;
        }
    }

    hide_all_filter_refs() {
        const refs = [
            this.totalBookingRef, this.totalVenueRef, this.totalAmountRef, this.totalInvoiceRef,
            this.bookingThisYearRef, this.venueThisYearRef, this.amountThisYearRef, this.invoiceThisYearRef,
            this.bookingThisDayRef, this.venueThisDayRef, this.amountThisDayRef, this.invoiceThisDayRef,
            this.bookingThisWeekRef, this.venueThisWeekRef, this.amountThisWeekRef, this.invoiceThisWeekRef,
            this.bookingThisMonthRef, this.venueThisMonthRef, this.amountThisMonthRef, this.invoiceThisMonthRef,
        ];
        refs.forEach(r => this.set_display(r, 'none'));
    }

    onclick_this_month(value) {
        this.orm.call('venue.booking', 'get_select_filter', [value]).then(result => {
            if (!result) return;
            this.hide_all_filter_refs();

            this.set_display(this.bookingThisMonthRef, 'block');
            this.set_display(this.venueThisMonthRef, 'block');
            this.set_display(this.amountThisMonthRef, 'block');
            this.set_display(this.invoiceThisMonthRef, 'block');

            const bookingCount = result.booking && result.booking[0] ? result.booking[0].count : 0;
            const venueCount = result.venue_count && result.venue_count[0] ? result.venue_count[0].count : 0;
            const amountSum = result.amount && result.amount[0] ? (result.amount[0].sum || 0) : 0;
            const invoiceSum = result.invoice && result.invoice[0] ? (result.invoice[0].sum || 0) : 0;

            this.set_html(this.bookingThisMonthRef, `<span>${bookingCount}</span>`);
            this.set_html(this.venueThisMonthRef, `<span>${venueCount}</span>`);
            this.set_html(this.amountThisMonthRef, `<span>${amountSum}</span>`);
            this.set_html(this.invoiceThisMonthRef, `<span>${invoiceSum}</span>`);
        }).catch(err => console.warn(err));
    }

    onclick_this_year(value) {
        this.orm.call('venue.booking', 'get_select_filter', [value]).then(result => {
            if (!result) return;
            this.hide_all_filter_refs();

            this.set_display(this.bookingThisYearRef, 'block');
            this.set_display(this.venueThisYearRef, 'block');
            this.set_display(this.amountThisYearRef, 'block');
            this.set_display(this.invoiceThisYearRef, 'block');

            const bookingCount = result.booking && result.booking[0] ? result.booking[0].count : 0;
            const venueCount = result.venue_count && result.venue_count[0] ? result.venue_count[0].count : 0;
            const amountSum = result.amount && result.amount[0] ? (result.amount[0].sum || 0) : 0;
            const invoiceSum = result.invoice && result.invoice[0] ? (result.invoice[0].sum || 0) : 0;

            this.set_html(this.bookingThisYearRef, `<span>${bookingCount}</span>`);
            this.set_html(this.venueThisYearRef, `<span>${venueCount}</span>`);
            this.set_html(this.amountThisYearRef, `<span>${amountSum}</span>`);
            this.set_html(this.invoiceThisYearRef, `<span>${invoiceSum}</span>`);
        }).catch(err => console.warn(err));
    }

    onclick_this_day(value) {
        this.orm.call('venue.booking', 'get_select_filter', [value]).then(result => {
            if (!result) return;
            this.hide_all_filter_refs();

            this.set_display(this.bookingThisDayRef, 'block');
            this.set_display(this.venueThisDayRef, 'block');
            this.set_display(this.amountThisDayRef, 'block');
            this.set_display(this.invoiceThisDayRef, 'block');

            const bookingCount = result.booking && result.booking[0] ? result.booking[0].count : 0;
            const venueCount = result.venue_count && result.venue_count[0] ? result.venue_count[0].count : 0;
            const amountSum = result.amount && result.amount[0] ? (result.amount[0].sum || 0) : 0;
            const invoiceSum = result.invoice && result.invoice[0] ? (result.invoice[0].sum || 0) : 0;

            this.set_html(this.bookingThisDayRef, `<span>${bookingCount}</span>`);
            this.set_html(this.venueThisDayRef, `<span>${venueCount}</span>`);
            this.set_html(this.amountThisDayRef, `<span>${amountSum}</span>`);
            this.set_html(this.invoiceThisDayRef, `<span>${invoiceSum}</span>`);
        }).catch(err => console.warn(err));
    }

    onclick_this_week(value) {
        this.orm.call('venue.booking', 'get_select_filter', [value]).then(result => {
            if (!result) return;
            this.hide_all_filter_refs();

            this.set_display(this.bookingThisWeekRef, 'block');
            this.set_display(this.venueThisWeekRef, 'block');
            this.set_display(this.amountThisWeekRef, 'block');
            this.set_display(this.invoiceThisWeekRef, 'block');

            const bookingCount = result.booking && result.booking[0] ? result.booking[0].count : 0;
            const venueCount = result.venue_count && result.venue_count[0] ? result.venue_count[0].count : 0;
            const amountSum = result.amount && result.amount[0] ? (result.amount[0].sum || 0) : 0;
            const invoiceSum = result.invoice && result.invoice[0] ? (result.invoice[0].sum || 0) : 0;

            this.set_html(this.bookingThisWeekRef, `<span>${bookingCount}</span>`);
            this.set_html(this.venueThisWeekRef, `<span>${venueCount}</span>`);
            this.set_html(this.amountThisWeekRef, `<span>${amountSum}</span>`);
            this.set_html(this.invoiceThisWeekRef, `<span>${invoiceSum}</span>`);
        }).catch(err => console.warn(err));
    }

    onclick_this_quarter(value) {
        console.log(`Quarter filter for value: ${value}`);
    }
}

actionRegistry.add('dashboard_tags', CustomDashBoard);