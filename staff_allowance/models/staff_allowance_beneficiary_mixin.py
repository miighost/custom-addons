from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AllowanceBeneficiaryMixin(models.AbstractModel):
    """Shared 'who is this for?' behaviour.

    A beneficiary is either an employee or a contact -- exactly one of the two.
    Every model that belongs to somebody (allowance lines, orders, blocked
    attempts) inherits this so the resolution logic is written once.
    """

    _name = "staff.allowance.beneficiary.mixin"
    _description = "Allowance Beneficiary Mixin"
    # These models have no `name` field. Without this, _rec_name falls back to
    # `id` and Odoo cannot build the implicit search field for a search view.
    _rec_name = "beneficiary_name"

    employee_id = fields.Many2one(
        "hr.employee", string="Employee", index=True, ondelete="cascade"
    )
    partner_id = fields.Many2one(
        "res.partner", string="Contact", index=True, ondelete="cascade"
    )
    beneficiary_type = fields.Selection(
        [("employee", "Employee"), ("partner", "Contact")],
        compute="_compute_beneficiary",
        store=True,
        index=True,
    )
    beneficiary_name = fields.Char(compute="_compute_beneficiary", store=True)

    # ------------------------------------------------------------------
    @api.depends("employee_id", "partner_id")
    def _compute_beneficiary(self):
        for record in self:
            if record.employee_id:
                record.beneficiary_type = "employee"
                record.beneficiary_name = record.employee_id.name
            elif record.partner_id:
                record.beneficiary_type = "partner"
                record.beneficiary_name = record.partner_id.display_name
            else:
                record.beneficiary_type = False
                record.beneficiary_name = False

    @api.constrains("employee_id", "partner_id")
    def _check_beneficiary(self):
        for record in self:
            if bool(record.employee_id) == bool(record.partner_id):
                raise ValidationError(
                    _("Set exactly one beneficiary: either an employee or a contact.")
                )

    # ------------------------------------------------------------------
    def _beneficiary(self):
        """Return the hr.employee or res.partner record behind this line."""
        self.ensure_one()
        return self.employee_id or self.partner_id

    @api.model
    def _beneficiary_domain(self, beneficiary):
        """Domain fragment matching a beneficiary record on this model."""
        if not beneficiary:
            return [("id", "=", False)]
        if beneficiary._name == "hr.employee":
            return [("employee_id", "=", beneficiary.id)]
        return [("partner_id", "=", beneficiary.id)]

    @api.model
    def _beneficiary_vals(self, beneficiary):
        """Values dict pointing at a beneficiary, for create()."""
        if beneficiary._name == "hr.employee":
            return {"employee_id": beneficiary.id}
        return {"partner_id": beneficiary.id}

    # ------------------------------------------------------------------
    # Timezone: the allowance day is the beneficiary's local day
    # ------------------------------------------------------------------
    @api.model
    def _beneficiary_tz(self, beneficiary):
        tz_name = (
            getattr(beneficiary, "tz", False)
            or self.env.user.tz
            or "UTC"
        )
        try:
            return pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    @api.model
    def _local_today(self, beneficiary):
        tz = self._beneficiary_tz(beneficiary)
        return pytz.utc.localize(fields.Datetime.now()).astimezone(tz).date()

    @api.model
    def _resets_at(self, beneficiary):
        """Next local midnight, as a naive UTC datetime (Odoo storage format)."""
        tz = self._beneficiary_tz(beneficiary)
        today = self._local_today(beneficiary)
        midnight = datetime.combine(today + timedelta(days=1), time.min)
        return tz.localize(midnight).astimezone(pytz.utc).replace(tzinfo=None)
