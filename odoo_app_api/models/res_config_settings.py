from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    app_firebase_project_id = fields.Char(
        string='Firebase Project ID',
        config_parameter='app_api.firebase_project_id',
        help="Firebase console > Project settings > General > Project ID. "
             "Must match the 'aud' claim in the app's tokens.")

    app_barcode_prefix = fields.Char(
        string='Membership Code Prefix',
        config_parameter='app_api.barcode_prefix',
        default='JPH',
        help="Prefix for the scannable membership code generated for each app "
             "customer, e.g. JPH gives JPH000016. Changing it only affects "
             "customers who sign up from now on.")

    app_wallet_journal_id = fields.Many2one(
        'account.journal', string='eWallet Journal',
        domain="[('type', 'in', ('bank', 'cash'))]",
        config_parameter='app_api.wallet_journal_id',
        help="Journal used when a customer clears an invoice from their "
             "eWallet balance. Point it at a journal whose account is your "
             "customer-wallet liability account.")
    app_waafi_journal_id = fields.Many2one(
        'account.journal', string='WaafiPay Journal',
        domain="[('type', 'in', ('bank', 'cash'))]",
        config_parameter='app_api.waafi_journal_id',
        help="Journal used for invoices paid through WaafiPay from the app.")

    app_waafi_url = fields.Char(
        string='WaafiPay API URL',
        config_parameter='app_api.waafi_url',
        help="Sandbox: https://sandbox.waafipay.com/asm  |  "
             "Production: https://api.waafipay.net/asm")
    app_waafi_merchant_uid = fields.Char(
        string='Merchant UID', config_parameter='app_api.waafi_merchant_uid')
    app_waafi_api_user_id = fields.Char(
        string='API User ID', config_parameter='app_api.waafi_api_user_id')
    app_waafi_api_key = fields.Char(
        string='API Key', config_parameter='app_api.waafi_api_key')
