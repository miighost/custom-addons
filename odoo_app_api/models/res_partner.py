from psycopg2 import IntegrityError

from odoo import api, fields, models
from odoo.exceptions import ConcurrencyError
from odoo.tools import email_normalize


class ResPartner(models.Model):
    _inherit = 'res.partner'

    firebase_uid = fields.Char(
        string='Firebase UID',
        index=True,
        copy=False,
        help="Identifier of this contact in Firebase Authentication. "
             "Set the first time the app user calls the API.",
    )
    app_signup_date = fields.Datetime(string='App Signup', readonly=True, copy=False)
    is_app_user = fields.Boolean(compute='_compute_is_app_user', store=True)
    membership_code = fields.Char(
        string='Membership Code', compute='_compute_membership_code',
        help="Display copy of the contact's barcode. The barcode field itself "
             "is company-dependent, so it cannot be listed or sorted on.")

    # Odoo 19 no longer reads `_sql_constraints`: a constraint declared that
    # way is silently never created.
    _firebase_uid_uniq = models.Constraint(
        'unique(firebase_uid)',
        'This Firebase account is already linked to another contact.',
    )

    @api.depends('barcode')
    def _compute_membership_code(self):
        for partner in self:
            partner.membership_code = partner.barcode or ''

    @api.depends('firebase_uid')
    def _compute_is_app_user(self):
        for partner in self:
            partner.is_app_user = bool(partner.firebase_uid)

    # ------------------------------------------------------------------
    # Called from the API layer with sudo(). Resolves the Firebase claims
    # to exactly one res.partner, creating it on first sight.
    # ------------------------------------------------------------------
    @api.model
    def _resolve_firebase_user(self, claims):
        uid = claims.get('user_id') or claims.get('sub')
        email = email_normalize(claims.get('email') or '') or ''
        phone = (claims.get('phone_number') or '').strip()

        partner = self.search([('firebase_uid', '=', uid)], limit=1)
        if partner:
            return partner

        # Returning customer who already exists in Odoo: claim the record
        # instead of creating a duplicate. Only trust a VERIFIED email, only
        # ever claim a contact that is not already linked to someone else,
        # and compare exactly: an `=ilike` pattern treats `_` as a wildcard,
        # so a verified john_smith@ address would claim john.smith@.
        unlinked = [('firebase_uid', '=', False)]
        if email and claims.get('email_verified'):
            partner = self.search(
                unlinked + [('email_normalized', '=', email)], limit=1)
        if not partner and phone:
            if 'mobile' in self._fields:
                phone_domain = ['|', ('phone', '=', phone), ('mobile', '=', phone)]
            else:
                phone_domain = [('phone', '=', phone)]
            partner = self.search(unlinked + phone_domain, limit=1)

        vals = {
            'firebase_uid': uid,
            'app_signup_date': fields.Datetime.now(),
        }
        try:
            with self.env.cr.savepoint():
                if partner:
                    partner.write(vals)
                else:
                    partner = self.create(dict(vals, **{
                        'name': claims.get('name') or email or phone or 'App user',
                        'email': email or False,
                        'phone': phone or False,
                        'customer_rank': 1,
                    }))
        except IntegrityError as err:
            # Two first sign-ins for the same account raced and the other one
            # linked it first. This transaction's snapshot cannot see that
            # contact, so have Odoo retry the request, which will.
            raise ConcurrencyError("Firebase account linked concurrently") from err
        partner._ensure_app_barcode()
        return partner

    def _ensure_app_barcode(self):
        """Give every app customer a membership number they can be scanned by.

        Kept short and numeric-friendly so it encodes cleanly as Code128 and
        is still readable out loud over the phone.
        """
        prefix = self.env['ir.config_parameter'].sudo().get_param(
            'app_api.barcode_prefix', 'JPH')
        for partner in self:
            if not partner.barcode:
                partner.barcode = '%s%06d' % (prefix, partner.id)
        return True
