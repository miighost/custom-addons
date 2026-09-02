from odoo import api, fields, models


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

    _sql_constraints = [
        ('firebase_uid_uniq', 'unique(firebase_uid)',
         'This Firebase account is already linked to another contact.'),
    ]

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
        email = (claims.get('email') or '').strip().lower()
        phone = (claims.get('phone_number') or '').strip()

        partner = self.search([('firebase_uid', '=', uid)], limit=1)
        if partner:
            return partner

        # Returning customer who already exists in Odoo: claim the record
        # instead of creating a duplicate. Only trust a VERIFIED email.
        domain = []
        if email and claims.get('email_verified'):
            domain = [('email', '=ilike', email)]
        elif phone:
            domain = [('phone', '=', phone)]
        if domain:
            partner = self.search(domain + [('firebase_uid', '=', False)], limit=1)

        vals = {
            'firebase_uid': uid,
            'app_signup_date': fields.Datetime.now(),
        }
        if partner:
            partner.write(vals)
            return partner

        return self.create(dict(vals, **{
            'name': claims.get('name') or email or phone or 'App user',
            'email': email or False,
            'phone': phone or False,
            'customer_rank': 1,
        }))
