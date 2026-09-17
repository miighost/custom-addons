"""Allowance orders no longer have a chatter.

Remove the follower rows earlier versions attached to every order. Their old
messages are left in place; nothing shows them any more.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("DELETE FROM mail_followers WHERE res_model = 'staff.allowance.order'")
    if cr.rowcount:
        _logger.info("Removed %s followers from allowance orders.", cr.rowcount)
