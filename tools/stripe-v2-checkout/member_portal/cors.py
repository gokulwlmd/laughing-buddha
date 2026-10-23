"""Browser access to patient APIs only, restricted to each site's storefronts."""
import re
from starlette.middleware.cors import CORSMiddleware


class PortalCORS:
    def __init__(self, app, service):
        self.app, self.service = app, service

    async def __call__(self, scope, receive, send):
        match = re.fullmatch(r'/api/v1/sites/([^/]+)/portal(?:/.*)?', scope.get('path', ''))
        if scope['type'] == 'http' and match:
            handler = CORSMiddleware(self.app, allow_origins=self.service.portal_origins(match[1]),
                allow_methods=['GET', 'POST', 'PATCH', 'PUT'], allow_headers=['Authorization', 'Content-Type'])
            await handler(scope, receive, send)
        else:
            await self.app(scope, receive, send)
