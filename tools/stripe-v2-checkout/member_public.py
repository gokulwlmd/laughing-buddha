"""Separate public patient worker; never run inside the checkout worker.

Required env: MEMBER_PORTAL_SITE_ID and MEMBER_PORTAL_PUBLIC_ORIGIN. Run from
the existing VM with its existing encrypted store/environment, on a separate
private IPv6 listener behind the site's public API proxy.
"""
import os

from app import app as checkout_app
from member_portal.public import public_portal

app = public_portal(checkout_app,
                    site_id=os.environ.get('MEMBER_PORTAL_SITE_ID'),
                    origin=os.environ.get('MEMBER_PORTAL_PUBLIC_ORIGIN'))
