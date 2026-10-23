"""Bound ID upload request bodies, including chunked requests, before JSON parsing."""
import re
from starlette.responses import JSONResponse
from .id_uploads import MAX_BODY_BYTES


def is_id_upload(path):
    return path == '/api/post-checkout-id-photo' or bool(re.fullmatch(r'/api/v1/sites/[^/]+/(?:portal/orders/[^/]+|sessions/[^/]+)/id-photo', path))


class IDUploadBodyLimit:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'POST' or not is_id_upload(scope.get('path', '')):
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        length = headers.get(b'content-length', b'')
        if length.isdigit() and int(length) > MAX_BODY_BYTES:
            return await JSONResponse({'detail': 'Choose an image smaller than 5 MB.'}, status_code=413)(scope, receive, send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect': return
            total += len(message.get('body', b''))
            if total > MAX_BODY_BYTES:
                return await JSONResponse({'detail': 'Choose an image smaller than 5 MB.'}, status_code=413)(scope, receive, send)
            chunks.append(message)
            if not message.get('more_body', False): break
        async def replay():
            return chunks.pop(0) if chunks else await receive()
        await self.app(scope, replay, send)
