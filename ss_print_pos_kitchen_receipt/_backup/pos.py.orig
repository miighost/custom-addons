# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PosConfig(models.Model):
    _inherit = 'pos.config'

    kitchen_print = fields.Boolean(string='Enable kitchen receipt Printing Button', default=True)
    kitchen_print_auto = fields.Boolean(string='Automatic kitchen receipt Printing', default=False)

    @api.onchange('module_pos_restaurant')
    def _onchange_module_pos_restaurant(self):
        if not getattr(self, 'module_pos_restaurant', False):
            self.kitchen_print_auto = False
            self.kitchen_print = False

    @api.onchange('is_order_printer')
    def _onchange_is_order_printer(self):
        if hasattr(self, 'is_order_printer') and not getattr(self, 'is_order_printer', False):
            self.kitchen_print = False






class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kitchen_print = fields.Boolean(related='pos_config_id.kitchen_print', readonly=False)
    kitchen_print_auto = fields.Boolean(related='pos_config_id.kitchen_print_auto', readonly=False)

    @api.onchange('pos_module_pos_restaurant')
    def _onchange_pos_module_pos_restaurant(self):
        if hasattr(self, 'pos_module_pos_restaurant') and not getattr(self, 'pos_module_pos_restaurant', False):
            self.kitchen_print_auto = False
            self.kitchen_print = False

    @api.onchange('pos_is_order_printer')
    def _onchange_pos_is_order_printer(self):
        if hasattr(self, 'pos_is_order_printer') and not getattr(self, 'pos_is_order_printer', False):
            self.kitchen_print = False


