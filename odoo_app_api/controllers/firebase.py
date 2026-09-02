"""Firebase ID token verification.

No firebase-admin SDK needed: an ID token is a plain RS256 JWT signed by
Google. We fetch Google's public x509 certs, cache them for the lifetime
the Cache-Control header allows, and verify signature + claims ourselves.
"""
import logging
import re
import time

import requests
from werkzeug.exceptions import Unauthorized

from odoo.http import request

_logger = logging.getLogger(__name__)

CERT_URL = ("https://www.googleapis.com/robot/v1/metadata/x509/"
            "securetoken@system.gserviceaccount.com")

# module-level cache: {kid: public_key}, plus the expiry timestamp
_CERT_CACHE = {'keys': {}, 'expires_at': 0}


def _load_public_keys():
    now = time.time()
    if _CERT_CACHE['keys'] and now < _CERT_CACHE['expires_at']:
        return _CERT_CACHE['keys']

    from cryptography.x509 import load_pem_x509_certificate

    resp = requests.get(CERT_URL, timeout=10)
    resp.raise_for_status()

    keys = {}
    for kid, cert_pem in resp.json().items():
        cert = load_pem_x509_certificate(cert_pem.encode())
        keys[kid] = cert.public_key()

    max_age = 3600
    cache_control = resp.headers.get('Cache-Control', '')
    match = re.search(r'max-age=(\d+)', cache_control)
    if match:
        max_age = int(match.group(1))

    _CERT_CACHE['keys'] = keys
    _CERT_CACHE['expires_at'] = now + max_age
    return keys


def _project_id():
    project_id = request.env['ir.config_parameter'].sudo().get_param(
        'app_api.firebase_project_id')
    if not project_id:
        _logger.error("app_api.firebase_project_id system parameter is not set")
        raise Unauthorized("API not configured")
    return project_id


def verify_id_token(token):
    """Return the decoded claims, or raise Unauthorized."""
    import jwt
    from jwt import PyJWTError

    project_id = _project_id()
    try:
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256':
            raise Unauthorized("Unexpected token algorithm")

        keys = _load_public_keys()
        key = keys.get(header.get('kid'))
        if key is None:
            # Google rotated its keys since we cached them
            _CERT_CACHE['expires_at'] = 0
            key = _load_public_keys().get(header.get('kid'))
        if key is None:
            raise Unauthorized("Unknown signing key")

        claims = jwt.decode(
            token,
            key=key,
            algorithms=['RS256'],
            audience=project_id,
            issuer=f"https://securetoken.google.com/{project_id}",
            options={'require': ['exp', 'iat', 'aud', 'iss', 'sub']},
        )
    except PyJWTError as err:
        _logger.info("Rejected Firebase token: %s", err)
        raise Unauthorized("Invalid token")

    if not claims.get('sub'):
        raise Unauthorized("Invalid token subject")
    if claims.get('auth_time', 0) > time.time() + 60:
        raise Unauthorized("Invalid token auth_time")

    return claims


def current_partner():
    """Resolve the caller's Authorization header to a res.partner."""
    auth = request.httprequest.headers.get('Authorization', '')
    match = re.match(r'^[Bb]earer\s+(.+)$', auth.strip())
    if not match:
        raise Unauthorized("Missing bearer token")

    claims = verify_id_token(match.group(1))
    return request.env['res.partner'].sudo()._resolve_firebase_user(claims)
