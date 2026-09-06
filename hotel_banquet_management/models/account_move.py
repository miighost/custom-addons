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


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.depends('invoice_line_ids.price_subtotal', 'invoice_line_ids.number_of_days')
    def _compute_tax_totals(self):
        """Ensure invoice tax totals widget reflects multi-day banquet calculations."""
        super()._compute_tax_totals()
        for move in self:
            if move.is_sale_document(include_receipts=True) and any((l.number_of_days or 1.0) > 1.0 for l in move.invoice_line_ids):
                lines = move.invoice_line_ids.filtered(lambda l: not l.display_type)
                untaxed = sum(lines.mapped('price_subtotal'))
                total = sum(lines.mapped('price_total'))
                if move.tax_totals:
                    tax_totals = dict(move.tax_totals)
                    tax_totals['amount_untaxed'] = untaxed
                    tax_totals['amount_total'] = total
                    if 'subtotals' in tax_totals and tax_totals['subtotals']:
                        for sub in tax_totals['subtotals']:
                            sub['amount'] = untaxed
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

    @api.depends('quantity', 'number_of_days', 'price_unit', 'discount', 'tax_ids')
    def _compute_totals(self):
        """Calculate line amounts including Number of Days: Qty * No of Days * Unit Price."""
        super()._compute_totals()
        for line in self:
            days = line.number_of_days if line.number_of_days and line.number_of_days > 0 else 1.0
            if line.move_id.is_sale_document(include_receipts=True) and days > 1.0:
                effective_qty = line.quantity * days
                price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
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

    def _convert_to_tax_base_line_dict(self, **kwargs):
        """Pass effective quantity to Odoo invoice tax computation."""
        res = super()._convert_to_tax_base_line_dict(**kwargs)
        days = self.number_of_days if self.number_of_days and self.number_of_days > 0 else 1.0
        if self.move_id.is_sale_document(include_receipts=True) and days > 1.0:
            res['quantity'] = self.quantity * days
            if 'price_subtotal' in res:
                res['price_subtotal'] = self.price_subtotal
        return res
