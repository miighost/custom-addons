import re

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    available_in_app = fields.Boolean(
        string='Show in Mobile App',
        default=True,
        help="On by default for every product. Untick it only to HIDE this "
             "product from the mobile app - it stays available everywhere "
             "else in Odoo. Products that are not saleable never appear in "
             "the app regardless of this setting.",
    )

    cover_image_url = fields.Char(
        string='Cover Image URL',
        help="External cover / banner image URL (e.g. Google Drive link or web image URL) for mobile app."
    )

    app_section_ids = fields.Many2many(
        'app.section',
        string='App Sections / Ads',
        compute='_compute_app_section_ids',
        inverse='_inverse_app_section_ids',
        search='_search_app_section_ids',
        help="Select which mobile app sections/carousels (e.g. Today's Best, Featured, Special Offers) this product appears in.",
    )

    def _app_cover_url(self):
        """Format cover image URL, converting Google Drive sharing links to direct image stream URLs."""
        url = (self.cover_image_url or '').strip()
        if not url:
            return ''
        # Convert Google Drive file sharing URL /file/d/<id>/view to direct image CDN URL
        m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if m:
            file_id = m.group(1)
            return f"https://lh3.googleusercontent.com/d/{file_id}"
        m2 = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
        if 'drive.google.com' in url and m2:
            file_id = m2.group(1)
            return f"https://lh3.googleusercontent.com/d/{file_id}"
        return url

    def _compute_app_section_ids(self):
        for template in self:
            variants = template.product_variant_ids
            if variants:
                sections = self.env['app.section'].search([('product_ids', 'in', variants.ids)])
                template.app_section_ids = sections
            else:
                template.app_section_ids = False

    def _inverse_app_section_ids(self):
        for template in self:
            variants = template.product_variant_ids
            if not variants:
                continue
            primary_variant = variants[0]
            primary_variant.app_section_ids = template.app_section_ids
            if template.app_section_ids and not template.available_in_app:
                template.available_in_app = True

    def _search_app_section_ids(self, operator, value):
        sections = self.env['app.section'].search(
            [('id', operator, value)] if isinstance(value, int) else [('name', operator, value)]
        )
        variants = sections.mapped('product_ids')
        return [('product_variant_ids', 'in', variants.ids)]


class ProductProduct(models.Model):
    _inherit = 'product.product'

    cover_image_url = fields.Char(
        related='product_tmpl_id.cover_image_url',
        readonly=False,
        string='Cover Image URL',
    )

    app_section_ids = fields.Many2many(
        'app.section',
        'app_section_product_rel',
        'product_id', 'section_id',
        string='App Sections / Ads',
        help="App sections / promotion carousels that include this product.",
    )

    def _app_cover_url(self):
        return self.product_tmpl_id._app_cover_url()


