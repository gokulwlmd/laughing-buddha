"""Restrict a separately run member worker to one public patient site.

This wrapper never proxies a private preview or mounts checkout/admin actions.
It uses the same on-host data store and provider credentials as the checkout
service; deployment must supply a separate process and a durable supervisor.
"""
import re
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse


def public_portal(app, *, site_id, origin):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', site_id or ''):
        raise ValueError('A single explicit portal site ID is required')
    parsed = urlsplit(origin or '')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment
            or parsed.port not in (None, 443)):
        raise ValueError('The public portal requires an HTTPS origin without a path')
    settings = app.state.settings
    settings.checkout_public_url = settings.public_url
    settings.public_url = origin
    settings.authorization_verified = False
    page = '/portal/' + site_id
    api = '/api/v1/sites/' + site_id + '/portal/'
    assets = {'portal.js', 'portal.css', 'red-hat-display-latin-v1.woff2', 'red-hat-display-OFL.txt',
              'fortifyhp/logo.png', 'fortifyhp/code-pro.ttf'}

    @app.middleware('http')
    async def site_only(req, next_handler):
        path = req.url.path
        read = req.method in ('GET', 'HEAD')
        allowed = ((read and path in ('/health', page, page + '/docs', page + '/openapi.json'))
                   or (read and path.removeprefix('/portal-assets/') in assets and path.startswith('/portal-assets/'))
                   or path.startswith(api))
        if not allowed:
            return JSONResponse({'detail': 'Not found'}, status_code=404,
                                headers={'Cache-Control': 'no-store'})
        return await next_handler(req)

    return app
