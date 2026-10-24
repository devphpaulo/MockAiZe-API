"""Documentação e recursos Swagger empacotados, sem CDN ou leitura arbitrária."""
from functools import lru_cache
from importlib.resources import files


DOCUMENTATION_ROUTES = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/swagger': ('index.html', 'text/html; charset=utf-8'),
    '/swagger/': ('index.html', 'text/html; charset=utf-8'),
    '/swagger/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/openapi.json': ('openapi.json', 'application/json; charset=utf-8'),
    '/swagger/v1/swagger.json': ('openapi.json', 'application/json; charset=utf-8'),
    '/swagger/swagger-ui-bundle.js': ('swagger-ui-bundle.js', 'application/javascript; charset=utf-8'),
    '/swagger/swagger-ui.css': ('swagger-ui.css', 'text/css; charset=utf-8'),
    '/swagger/initializer.js': ('initializer.js', 'application/javascript; charset=utf-8'),
    '/swagger/favicon.ico': ('mockaize.ico', 'image/x-icon'),
}


@lru_cache(maxsize=8)
def _asset(name):
    assets = files('mockaize_api').joinpath('assets')
    if name == 'mockaize.ico':
        return assets.joinpath('mockaize.ico').read_bytes()
    return assets.joinpath('swagger', name).read_bytes()


def documentation_response(path):
    name, media_type = DOCUMENTATION_ROUTES[path]
    return {
        'status': 200,
        'headers': {
            'Content-Type': media_type,
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': (
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            ),
        },
        'body': _asset(name),
    }
