"""Firebase ID token verification.

A Firebase ID token is a plain RS256 JWT signed by Google. Rather than pull in
firebase-admin or PyJWT, this verifies it with `cryptography` alone - a library
Odoo already depends on - so the module has no external dependency to install.
"""
import base64
import binascii
import json
import logging
import re
import time

import requests
from werkzeug.exceptions import Unauthorized

from odoo.http import request

_logger = logging.getLogger(__name__)

CERT_URL = ("https://www.googleapis.com/robot/v1/metadata/x509/"
            "securetoken@system.gserviceaccount.com")

CLOCK_SKEW = 60  # seconds of tolerance for clock drift between us and Google

_CERT_CACHE = {'keys': {}, 'expires_at': 0}


# ---------------------------------------------------------------- helpers
def _b64url_decode(segment):
    """Decode a base64url segment, restoring the stripped '=' padding."""
    padding = '=' * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + padding)
    except (binascii.Error, ValueError) as err:
        raise Unauthorized("Malformed token") from err


def _load_public_keys(force=False):
    now = time.time()
    if not force and _CERT_CACHE['keys'] and now < _CERT_CACHE['expires_at']:
        return _CERT_CACHE['keys']

    from cryptography.x509 import load_pem_x509_certificate

    try:
        resp = requests.get(CERT_URL, timeout=10)
        resp.raise_for_status()
        certs = resp.json()
    except Exception as err:                                   # noqa: BLE001
        _logger.error("Could not fetch Google signing certificates: %s", err)
        if _CERT_CACHE['keys']:
            return _CERT_CACHE['keys']       # stale beats dead
        raise Unauthorized("Cannot verify token right now") from err

    keys = {kid: load_pem_x509_certificate(pem.encode()).public_key()
            for kid, pem in certs.items()}

    max_age = 3600
    match = re.search(r'max-age=(\d+)', resp.headers.get('Cache-Control', ''))
    if match:
        max_age = int(match.group(1))

    _CERT_CACHE['keys'] = keys
    _CERT_CACHE['expires_at'] = now + max_age
    return keys


def _project_id():
    project_id = request.env['ir.config_parameter'].sudo().get_param(
        'app_api.firebase_project_id')
    if not project_id or project_id.startswith('CHANGE-ME'):
        _logger.error("System parameter app_api.firebase_project_id is not set")
        raise Unauthorized("API not configured")
    return project_id


def _verify_signature(signing_input, signature, kid):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    keys = _load_public_keys()
    key = keys.get(kid)
    if key is None:
        # Google rotates its certificates; refetch once before giving up
        key = _load_public_keys(force=True).get(kid)
    if key is None:
        raise Unauthorized("Unknown signing key")
    if not isinstance(key, rsa.RSAPublicKey):
        raise Unauthorized("Unexpected key type")

    try:
        key.verify(signature, signing_input,
                   padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as err:
        raise Unauthorized("Bad token signature") from err


# ------------------------------------------------------------------ public
def verify_id_token(token):
    """Return the decoded claims of a valid Firebase ID token, else raise."""
    parts = token.split('.')
    if len(parts) != 3:
        raise Unauthorized("Malformed token")

    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError) as err:
        raise Unauthorized("Malformed token") from err

    if header.get('alg') != 'RS256':
        raise Unauthorized("Unexpected token algorithm")
    if not header.get('kid'):
        raise Unauthorized("Token has no key id")

    project_id = _project_id()
    now = time.time()

    if claims.get('aud') != project_id:
        raise Unauthorized("Token was issued for another project")
    if claims.get('iss') != f"https://securetoken.google.com/{project_id}":
        raise Unauthorized("Unexpected token issuer")
    if not claims.get('sub'):
        raise Unauthorized("Token has no subject")
    if float(claims.get('exp', 0)) < now - CLOCK_SKEW:
        raise Unauthorized("Token has expired")
    if float(claims.get('iat', 0)) > now + CLOCK_SKEW:
        raise Unauthorized("Token issued in the future")
    if float(claims.get('auth_time', 0)) > now + CLOCK_SKEW:
        raise Unauthorized("Invalid token auth_time")

    _verify_signature(
        f"{header_b64}.{payload_b64}".encode(),
        _b64url_decode(signature_b64),
        header['kid'],
    )
    return claims


def current_partner():
    """Resolve the caller's Authorization header to a res.partner."""
    auth = request.httprequest.headers.get('Authorization', '')
    match = re.match(r'^[Bb]earer\s+(\S+)$', auth.strip())
    if not match:
        raise Unauthorized("Missing bearer token")

    claims = verify_id_token(match.group(1))
    return request.env['res.partner'].sudo()._resolve_firebase_user(claims)
