"""Private portal preview on an existing Fly VM, reached through fly proxy.

Uses the existing encrypted database and Sticky environment in place. Does not
restart the checkout worker or expose payment/catalog mutation routes. Never
copy the live database or credentials to the development laptop.
"""
import os
from urllib.parse import urlsplit
from fastapi import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from app import app

origin = os.environ.get('MEMBER_PREVIEW_ORIGIN', 'http://127.0.0.1:8873')
parsed = urlsplit(origin)
if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path or parsed.query or parsed.fragment or parsed.username:
    raise RuntimeError('The private preview requires a loopback origin')
checkout_origin = app.state.settings.public_url
app.state.settings.public_url = origin
app.state.settings.authorization_verified = False


@app.middleware('http')
async def portal_only(req, next_handler):
    path = req.url.path
    if path == '/admin' and req.method == 'GET':
        return RedirectResponse(checkout_origin + '/admin')
    if path.startswith('/api/admin/sites/') and path.endswith('/checkout-testing'):
        try:
            app.state.admin.authenticated(req)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        if req.method != 'GET':
            return JSONResponse({'detail': 'Publish the checkout update before enabling $1 testing'}, status_code=409)
        return JSONResponse({'enabled': False, 'available': False,
            'terms': 'The $1 checkout update is ready to publish. It is not active on the public checkout yet.'})
    allowed = (path == '/health' or path.startswith(('/portal/', '/portal-admin/', '/portal-assets/', '/api/admin/portal/', '/api/admin/master-refill-rules/'))
               or path in ('/api/admin/auth', '/api/admin/login', '/api/admin/logout')
               or (path.startswith('/api/v1/sites/') and '/portal/' in path)
               or (path.startswith('/api/admin/sites/') and ('/portal/' in path or path.endswith('/checkout-testing'))))
    if not allowed:
        return JSONResponse({'detail': 'This private preview serves only member portal routes'}, status_code=404)
    return await next_handler(req)
