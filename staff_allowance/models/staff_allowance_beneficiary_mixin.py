from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models


class AllowanceBeneficiaryMixin(models.AbstractModel):
    """Shared 'who is this for?' behaviour.

    An allowance belongs to a contact. An employee is handled through their
    work contact -- the contact the POS sells to and the one Odoo links to
    their user -- so a person has one set of limits and one counter, however
    they order.
    """

    _name = "staff.allowance.beneficiary.mixin"
    _description = "Allowance Beneficiary Mixin"
    # These models have no `name` field. Without this, _rec_name falls back to
    # `id` and Odoo cannot build the implicit search field for a search view.
    _rec_name = "beneficiary_name"

    partner_id = fields.Many2one(
        "res.partner", string="Contact", required=True, index=True,
        ondelete="cascade",
    )
    beneficiary_name = fields.Char(compute="_compute_beneficiary_name", store=True)

    # ------------------------------------------------------------------
    @api.depends("partner_id")
    def _compute_beneficiary_name(self):
        for record in self:
            record.beneficiary_name = record.partner_id.display_name or False

    # ------------------------------------------------------------------
    def _beneficiary(self):
        """Return the contact behind this line."""
        self.ensure_one()
        return self.partner_id

    @api.model
    def _allowance_contact(self, person):
        """The contact whose allowance applies to `person`.

        Accepts a contact, an employee (their work contact) or a user (their
        contact, which Odoo keeps equal to their employee's work contact).
        """
        if not person:
            return self.env["res.partner"]
        if person._name == "hr.employee":
            return person.work_contact_id
        if person._name == "res.users":
            return person.partner_id
        return person

    @api.model
    def _beneficiary_domain(self, partner):
        """Domain fragment matching a contact on this model."""
        if not partner:
            return [("id", "=", False)]
        return [("partner_id", "=", partner.id)]

    @api.model
    def _beneficiary_vals(self, partner):
        """Values dict pointing at a contact, for create()."""
        return {"partner_id": partner.id}

    # ------------------------------------------------------------------
    # Timezone: the allowance day is the beneficiary's local day
    # ------------------------------------------------------------------
    @api.model
    def _beneficiary_tz(self, beneficiary):
        """The person's own timezone, else their company's.

        Never the current user's: the same order would otherwise land on a
        different day depending on who recorded it (cashier, app, cron).
        """
        company = (beneficiary.company_id if beneficiary else False) \
            or self.env.company
        tz_name = (
            getattr(beneficiary, "tz", False)
            or company.resource_calendar_id.tz
            or company.partner_id.tz
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
