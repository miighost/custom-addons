from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    app_firebase_project_id = fields.Char(
        string='Firebase Project ID',
        config_parameter='app_api.firebase_project_id',
        help="Firebase console > Project settings > General > Project ID. "
             "Must match the 'aud' claim in the app's tokens.")

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
