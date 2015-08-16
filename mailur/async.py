import asyncio
import json

import aiohttp
import aiohttp.web as web

from . import Env, log


@asyncio.coroutine
def bad_auth(request):
    resp = yield from aiohttp.request(
        'GET', 'http://localhost:8000/check-auth/',
        headers=request.headers,
        cookies=request.cookies.items(),
        allow_redirects=False
    )
    if resp.status == 200:
        resp.close()
        return None
    elif resp.status in (301, 302, 403):
        return web.Response(body=b'403 Forbidden', status=403)

    body = yield from resp.read()
    return web.Response(body=body, status=resp.status)


@asyncio.coroutine
def wshandler(request):
    error = yield from bad_auth(request)
    if error:
        return error

    ws = web.WebSocketResponse()
    ws.start(request)

    request.app['sockets'].append(ws)
    while True:
        msg = yield from ws.receive()
        if msg.tp == web.MsgType.text:
            log.debug(msg.data)
            data = json.loads(msg.data)
            payload = data.get('payload')
            if payload:
                payload = json.dumps(payload)
            resp = yield from aiohttp.request(
                'POST' if payload else 'GET',
                data['url'],
                data=payload,
                cookies=request.cookies.items()
            )
            log.debug('%s %s', resp.status, msg.data)
            if resp.status == 200:
                resp = (yield from resp.read()).decode()
                ws.send_str(json.dumps({'uid': data['uid'], 'payload': resp}))
        elif msg.tp == web.MsgType.close:
            log.debug('ws closed')
            yield from ws.close()
            break
        elif msg.tp == web.MsgType.error:
            log.exception(ws.exception())

    request.app['sockets'].remove(ws)
    return ws


@asyncio.coroutine
def notify(request):
    error = yield from bad_auth(request)
    if error:
        return error

    yield from request.post()
    msg = json.dumps({'updated': request.POST.getall('ids')})
    for ws in request.app['sockets']:
        ws.send_str(msg)
    return web.Response(body=b'OK')


def create_app():
    app = web.Application()
    app.router.add_route('GET', '/', wshandler)
    app.router.add_route('POST', '/notify/', notify)

    app['env'] = Env()
    app['sockets'] = []
    return app
