# -*- coding: utf-8 -*-
#############################################################################
#
#    MiiG Solution
#
#    Copyright (C) 2026-TODAY MiiG Solution(<https://www.miigsolution.so>)
#    Author: MiiG Solution(<https://www.miigsolution.so>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#############################################################################
from odoo import api, fields, models
from odoo.tools.misc import formatLang


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_banquet = fields.Boolean(
        string='Is Banquet',
        compute='_compute_is_banquet',
        store=False,
    )

    def _compute_is_banquet(self):
        for move in self:
            move.is_banquet = any(so.is_banquet for so in move.invoice_line_ids.sale_line_ids.order_id) or any((l.number_of_days or 1.0) > 1.0 for l in move.invoice_line_ids)

    @api.depends(
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.price_total',
        'invoice_line_ids.number_of_days',
    )
    def _compute_amount(self):
        super()._compute_amount()
        for move in self:
            if move.is_sale_document(include_receipts=True) and (move.is_banquet or any((l.number_of_days or 1.0) > 1.0 for l in move.invoice_line_ids)):
                lines = move.invoice_line_ids.filtered(lambda l: not l.display_type)
                move.amount_untaxed = sum(lines.mapped('price_subtotal'))
                total = sum(lines.mapped('price_total'))
                move.amount_total = total
                move.amount_tax = total - move.amount_untaxed

    @api.depends(
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.price_total',
        'invoice_line_ids.number_of_days',
        'invoice_line_ids.price_unit',
        'invoice_line_ids.quantity'
    )
    def _compute_tax_totals(self):
        """Ensure invoice tax totals widget reflects multi-day banquet calculations."""
        super()._compute_tax_totals()
        for move in self:
            if move.is_sale_document(include_receipts=True) and (move.is_banquet or any((l.number_of_days or 1.0) > 1.0 for l in move.invoice_line_ids)) and move.tax_totals:
                lines = move.invoice_line_ids.filtered(lambda l: not l.display_type)
                untaxed = sum(lines.mapped('price_subtotal'))
                total = sum(lines.mapped('price_total'))
                tax = total - untaxed
                currency = move.currency_id or move.company_id.currency_id

                formatted_untaxed = formatLang(move.env, untaxed, currency_obj=currency)
                formatted_tax = formatLang(move.env, tax, currency_obj=currency)
                formatted_total = formatLang(move.env, total, currency_obj=currency)

                tax_totals = dict(move.tax_totals)
                orig_untaxed = tax_totals.get('amount_untaxed') or 1.0
                ratio = untaxed / orig_untaxed if orig_untaxed else 1.0

                tax_totals['amount_untaxed'] = untaxed
                tax_totals['amount_total'] = total
                tax_totals['formatted_amount_untaxed'] = formatted_untaxed
                tax_totals['formatted_amount_total'] = formatted_total

                if 'subtotals' in tax_totals and tax_totals['subtotals']:
                    for sub in tax_totals['subtotals']:
                        sub['amount'] = untaxed
                        sub['formatted_amount'] = formatted_untaxed

                if 'groups_by_subtotal' in tax_totals and tax_totals['groups_by_subtotal']:
                    for sub_name, groups in tax_totals['groups_by_subtotal'].items():
                        for g in groups:
                            new_group_amount = g.get('tax_group_amount', 0.0) * ratio
                            new_base_amount = g.get('tax_group_base_amount', 0.0) * ratio
                            g['tax_group_amount'] = new_group_amount
                            g['tax_group_base_amount'] = new_base_amount
                            g['formatted_tax_group_amount'] = formatLang(move.env, new_group_amount, currency_obj=currency)
                            g['formatted_tax_group_base_amount'] = formatLang(move.env, new_base_amount, currency_obj=currency)

                move.tax_totals = tax_totals


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    number_of_days = fields.Float(
        string='No of Days',
        default=1.0,
        digits='Product Unit of Measure',
        help="Number of days or sessions for this banquet service."
    )

    @api.onchange('number_of_days')
    def _onchange_number_of_days(self):
        """Trigger instant recomputation when editing No of Days on invoice."""
        if hasattr(self, '_compute_totals'):
            self._compute_totals()

    @api.depends('product_id')
    def _compute_price_unit(self):
        """Preserve user-entered unit price on invoice lines."""
        for line in self:
            if (line.move_id.is_banquet or ((line.number_of_days or 1.0) > 1.0)) and line.price_unit and line.product_id:
                continue
            super(AccountMoveLine, line)._compute_price_unit()

    @api.depends('quantity', 'number_of_days', 'price_unit', 'discount', 'tax_ids')
    def _compute_totals(self):
        """Calculate line amounts including Number of Days: Qty * No of Days * Unit Price."""
        super()._compute_totals()
        for line in self:
            days = line.number_of_days if line.number_of_days and line.number_of_days > 0 else 1.0
            if line.move_id.is_sale_document(include_receipts=True) and days > 1.0:
                effective_qty = (line.quantity or 0.0) * days
                price = (line.price_unit or 0.0) * (1 - (line.discount or 0.0) / 100.0)
                if line.tax_ids:
                    taxes = line.tax_ids.compute_all(
                        price,
                        line.currency_id,
                        effective_qty,
                        product=line.product_id,
                        partner=line.partner_id
                    )
                    line.price_subtotal = taxes['total_excluded']
                    line.price_total = taxes['total_included']
                else:
                    line.price_subtotal = price * effective_qty
                    line.price_total = price * effective_qty

    def _prepare_tax_base_line_dict(self, **kwargs):
        """Pass effective quantity to Odoo native tax computation."""
        res = super()._prepare_tax_base_line_dict(**kwargs) if hasattr(super(), '_prepare_tax_base_line_dict') else {}
        days = self.number_of_days if self.number_of_days and self.number_of_days > 0 else 1.0
        if self.move_id.is_sale_document(include_receipts=True) and days > 1.0:
            res['quantity'] = (self.quantity or 0.0) * days
            if 'price_subtotal' in res:
                res['price_subtotal'] = self.price_subtotal
        return res
