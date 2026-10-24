"""Host HTTP standalone, sem sessão do estúdio ou dependência de navegador."""
from collections import deque
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit
import uuid

from . import __version__
from .api_docs import DOCUMENTATION_ROUTES, documentation_response
from .catalog import Catalog
from .config import load_config
from .errors import ApiError
from .inputs import read_input_file
from .policy import Policy
from .preflight import check_environment, _check_directories, PreflightError
from .publication import metadata, publish, safe_filename
from .request_log import RequestLog
from .security import key_digest, verify_key
from .state import State

MAX_BODY = 12 * 1024 * 1024
MAX_OUTPUT = 100_000_000


def _engine_child(channel, operation, variation, body, index):
    try:
        from .xml_engine import generate_new, generate_return
        if operation == 'new':
            result = generate_new(variation, body['recordCount'], file_index=index)
        else:
            result = generate_return(variation, body['returnSelection'], body.get('composition', 'apart'),
                                     input_xml=body.get('inputXml'), file_index=index,
                                     input_records=body.get('inputRecords', 'all'))
        channel.send(('ok', result))
    except ApiError as error:
        channel.send(('error', (error.status, error.code, error.detail, error.extensions)))
    except Exception:
        channel.send(('error', (500, 'INTERNAL_ERROR', 'Falha interna na geração.', {})))
    finally:
        channel.close()


def run_engine(operation, variation, body, index, timeout, stop_event=None):
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_engine_child, args=(sender, operation, variation, body, index))
    try:
        process.start()
        sender.close()
        deadline = time.monotonic() + timeout
        while not receiver.poll(min(0.2, max(0, deadline - time.monotonic()))):
            if stop_event is not None and stop_event.is_set():
                raise ApiError(503, 'SERVICE_STOPPING', 'O serviço está encerrando. Repita após reiniciar.')
            if time.monotonic() >= deadline:
                raise ApiError(503, 'GENERATION_TIMEOUT', 'Tempo limite de geração excedido.')
        kind, payload = receiver.recv()
        if kind == 'error':
            status, code, detail, extensions = payload
            raise ApiError(status, code, detail, **extensions)
        return payload
    except (OSError, EOFError):
        raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Processador de XML indisponível.') from None
    finally:
        receiver.close()
        sender.close()
        if process.pid:
            process.join(1)
            if process.is_alive():
                process.terminate()
                process.join(5)
            process.close()


def _json(status: int, value: dict) -> dict:
    return {'status': status, 'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps(value, ensure_ascii=False).encode('utf-8')}


def _problem(error: ApiError, request_id: str) -> dict:
    extensions = {key: value for key, value in error.extensions.items() if key in {'xmlPath', 'reason'}}
    response = _json(error.status, {'type': 'about:blank', 'title': error.code, 'status': error.status,
                                   'detail': error.detail, 'code': error.code, 'requestId': request_id,
                                   **extensions})
    response['headers']['Content-Type'] = 'application/problem+json; charset=utf-8'
    if error.status == 429:
        response['headers']['Retry-After'] = '1'
    return response


def _invalid():
    return ApiError(400, 'INVALID_REQUEST', 'Verifique os campos, tipos e limites da requisição.')


def _nonempty_string(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 128


def validate_generation(operation: str, body: object) -> dict:
    common = {'fileId', 'delivery', 'expectedRevision'}
    extra = {'recordCount'} if operation == 'new' else {'returnSelection', 'composition', 'inputXml', 'inputFilePath', 'inputRecords'}
    if not isinstance(body, dict) or set(body) - common - extra or not _nonempty_string(body.get('fileId')):
        raise _invalid()
    if body.get('delivery', 'directory') not in ('directory', 'content', 'inline'):
        raise _invalid()
    if 'expectedRevision' in body and (type(body['expectedRevision']) is not int or body['expectedRevision'] < 1):
        raise _invalid()
    if operation == 'new':
        count = body.get('recordCount')
        if type(count) is not int or not 1 <= count <= 500:
            raise _invalid()
        return body
    if body.get('composition', 'apart') not in ('apart', 'mixed'):
        raise _invalid()
    if body.get('inputRecords', 'all') not in ('all', 'first'):
        raise _invalid()
    if 'inputXml' in body and 'inputFilePath' in body:
        raise _invalid()
    for key in ['inputXml', 'inputFilePath']:
        if key in body and (not isinstance(body[key], str) or not body[key].strip()):
            raise _invalid()
    selection = body.get('returnSelection')
    if not isinstance(selection, dict):
        raise _invalid()
    if selection == {'type': 'all'}:
        return body
    ids = selection.get('ids')
    if (set(selection) != {'type', 'ids'} or selection.get('type') != 'ids'
            or not isinstance(ids, list) or not 1 <= len(ids) <= 20
            or any(not _nonempty_string(value) for value in ids) or len(set(ids)) != len(ids)):
        raise _invalid()
    return body


class Application:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.policy = Policy.load(config_path)
        key_digest(config_path)
        self.catalog = Catalog(self.config.database_path)
        self.catalog.check()
        self.state = State(config_path.parent / 'api-state.sqlite3', self.policy.idempotency_retention_seconds)
        self.log = RequestLog(self.config.logs_directory, self.policy.logs_retention_days)
        self.generation_slots = threading.BoundedSemaphore(self.policy.generation_concurrency)
        self.rate_lock = threading.Lock()
        self.rate = deque()
        self.stop_event = threading.Event()

    def rate_check(self):
        now = time.monotonic()
        with self.rate_lock:
            while self.rate and self.rate[0] < now - 1:
                self.rate.popleft()
            if len(self.rate) >= self.policy.requests_per_second:
                raise ApiError(429, 'RATE_LIMITED', 'Limite de chamadas excedido.')
            self.rate.append(now)

    def health(self):
        try:
            self.catalog.check()
            key_digest(self.config_path)
            if self.stop_event.is_set():
                raise OSError
            # Cada chamada será registrada: falha de log converte esta resposta para 503.
            if not all(path.is_dir() for path in [self.config.input_directory, self.config.output_directory, self.config.logs_directory]):
                raise OSError
            _check_directories(self.config)
            with self.state.connect() as connection:
                connection.execute('SELECT 1').fetchone()
            return _json(200, {'status': 'ok', 'version': __version__})
        except (ApiError, OSError, PreflightError):
            return _json(503, {'status': 'unavailable', 'version': __version__})

    def generate(self, operation: str, body: dict, request_id: str, idempotency_key: str | None):
        body = validate_generation(operation, body)
        if self.stop_event.is_set():
            raise ApiError(503, 'SERVICE_STOPPING', 'O serviço está encerrando.')
        if idempotency_key is not None and (not _nonempty_string(idempotency_key) or any(ord(c) < 33 or ord(c) > 126 for c in idempotency_key)):
            raise _invalid()
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        if idempotency_key:
            replay = self.state.begin(operation, idempotency_key, fingerprint)
            if replay:
                replay['headers']['X-Idempotent-Replay'] = 'true'
                return replay
        if not self.generation_slots.acquire(blocking=False):
            error = ApiError(429, 'RATE_LIMITED', 'Há gerações em andamento. Tente novamente.')
            response = _problem(error, request_id)
            if idempotency_key:
                self.state.cancel(operation, idempotency_key)
            return response
        try:
            variation = self.catalog.snapshot(body['fileId'])
            if 'expectedRevision' in body and body['expectedRevision'] != variation['revision']:
                raise ApiError(409, 'REVISION_MISMATCH', 'A revisão salva difere da revisão solicitada.')
            execution_body = dict(body)
            if 'inputFilePath' in body:
                execution_body['inputXml'] = read_input_file(self.config.input_directory, body['inputFilePath'])
            if operation == 'return' and 'inputXml' in execution_body and len(execution_body['inputXml'].encode('utf-8')) > 2_000_000:
                raise ApiError(413, 'INPUT_TOO_LARGE', 'O XML de entrada excede 2 MB.')
            if (operation == 'return' and body.get('delivery', 'directory') == 'inline'
                    and body.get('composition', 'apart') == 'apart'):
                selection = body['returnSelection']
                count = len(selection['ids']) if selection['type'] == 'ids' else len(variation['config'].get('returnModels', []))
                if count != 1:
                    raise ApiError(422, 'DELIVERY_INCOMPATIBLE', 'Entrega inline exige exatamente um XML final.')
            index = self.state.next_index(body['fileId'])
            documents = run_engine(operation, variation, execution_body, index, self.policy.generation_timeout_seconds, self.stop_event)
            if not documents or sum(len(item['content']) for item in documents) > MAX_OUTPUT:
                raise ApiError(413, 'OUTPUT_LIMIT_EXCEEDED', 'O resultado excede 100 MB.')
            if body.get('delivery', 'directory') == 'inline':
                if len(documents) != 1:
                    raise ApiError(422, 'DELIVERY_INCOMPATIBLE', 'Entrega inline exige exatamente um XML final.')
                document = documents[0]
                name = safe_filename(document['fileName'])
                meta = metadata(document['content'])
                response = {'status': 200, 'body': document['content'], 'headers': {
                    'Content-Type': 'application/xml; charset=utf-8',
                    'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name, safe=''),
                    'X-Mockaize-SHA256': meta['sha256'], 'X-Mockaize-Size-Bytes': str(meta['sizeBytes']),
                    'X-Mockaize-Size-Display': meta['sizeDisplay']}}
            else:
                delivery = body.get('delivery', 'directory')
                if delivery == 'content':
                    files = [
                        {**{key: value for key, value in document.items() if key != 'content'},
                         'fileName': safe_filename(document['fileName']),
                         **metadata(document['content']),
                         'content': document['content'].decode('utf-8')}
                        for document in documents
                    ]
                else:
                    files = publish(self.config.output_directory, documents)
                value = {'requestId': request_id, 'fileId': body['fileId'], 'sourceRevision': variation['revision'],
                         'operation': operation, 'delivery': delivery, 'files': files}
                if operation == 'return':
                    value['composition'] = body.get('composition', 'apart')
                    value['inputRecords'] = body.get('inputRecords', 'all')
                    selection = body['returnSelection']
                    ids = (selection['ids'] if selection['type'] == 'ids' else
                           [model['id'] for model in variation['config'].get('returnModels', [])])
                    value['returnIds'] = ids
                    if value['composition'] == 'mixed':
                        value['totalRecords'] = documents[0]['records']
                        value['recordsPerReturn'] = value['totalRecords'] // len(ids)
                response = _json(200, value)
                if delivery == 'content' and len(response['body']) > MAX_OUTPUT:
                    raise ApiError(413, 'OUTPUT_LIMIT_EXCEEDED', 'A resposta JSON excede 100 MB. Reduza a geração ou use delivery=directory.')
        except ApiError as error:
            response = _problem(error, request_id)
            if error.extensions.get('residue'):
                self.log.write(requestId=request_id, code=error.code, residue=error.extensions['residue'])
        except Exception:
            response = _problem(ApiError(500, 'INTERNAL_ERROR', 'Falha interna na operação.'), request_id)
        finally:
            self.generation_slots.release()
        if idempotency_key:
            self.state.complete(operation, idempotency_key, response)
        return response


class ApiServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, address, application):
        self.application = application
        self.connections = threading.BoundedSemaphore(application.policy.maximum_connections)
        self.active_sockets = set()
        self.active_lock = threading.Lock()
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 429 Too Many Requests\r\nContent-Length: 0\r\nRetry-After: 1\r\nCache-Control: no-store\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            with self.active_lock:
                self.active_sockets.add(request)
            super().process_request(request, client_address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.active_lock:
                self.active_sockets.discard(request)
            self.connections.release()

    def close_clients(self):
        self.application.stop_event.set()
        with self.active_lock:
            sockets = list(self.active_sockets)
        for connection in sockets:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def server_close(self):
        self.close_clients()
        super().server_close()

    def handle_error(self, request, client_address):
        # Não escrever tracebacks/payloads em stderr do serviço.
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = 'MockAiZeAPI'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass

    def _body(self):
        if self.headers.get_content_type() != 'application/json':
            raise ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Envie application/json.')
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
            raise _invalid()
        try:
            size = int(lengths[0])
        except ValueError:
            raise _invalid() from None
        if size < 0:
            raise _invalid()
        if size > MAX_BODY:
            raise ApiError(413, 'INPUT_TOO_LARGE', 'Corpo da requisição excede o limite.')
        content = self.rfile.read(size)
        if len(content) != size:
            raise _invalid()
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise _invalid()
                value[key] = item
            return value
        try:
            return json.loads(content.decode('utf-8'), object_pairs_hook=unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(_invalid()))
        except (ValueError, UnicodeError, RecursionError):
            raise _invalid() from None

    def _dispatch(self, request_id):
        app = self.server.application
        url = urlsplit(self.path)
        path = url.path
        if path in DOCUMENTATION_ROUTES:
            self.route = path
            if self.command not in ('GET', 'HEAD'):
                return self._method('GET, HEAD', request_id)
            if url.query:
                raise _invalid()
            return documentation_response(path)
        if path == '/health':
            self.route = '/health'
            if self.command != 'GET':
                return self._method('GET', request_id)
            if url.query:
                raise _invalid()
            return app.health()
        route = re.fullmatch(
            r'/api/v1/files/xml(?:/([A-Za-z0-9_-]{1,128})(?:/(modes|returns|new|return))?)?', path)
        if not route:
            raise ApiError(404, 'ROUTE_NOT_FOUND', 'Rota não encontrada.')
        file_id, action = route.groups()
        self.route = '/api/v1/files/xml' + ('/{fileId}' if file_id else '') + ('/' + action if action else '')
        keys = self.headers.get_all('X-API-Key', [])
        if len(keys) != 1 or not verify_key(app.config_path, keys[0]):
            raise ApiError(401, 'UNAUTHORIZED', 'Chave da API ausente ou inválida.')
        app.rate_check()
        expected = 'POST' if action in ('new', 'return') else 'GET'
        if self.command != expected:
            return self._method(expected, request_id)
        if expected == 'POST':
            if url.query:
                raise _invalid()
            idem = self.headers.get_all('Idempotency-Key', [])
            if len(idem) > 1:
                raise _invalid()
            body = self._body()
            if not isinstance(body, dict) or 'fileId' in body:
                raise _invalid()
            return app.generate(action, {**body, 'fileId': file_id}, request_id, idem[0] if idem else None)
        query = parse_qs(url.query, keep_blank_values=True)
        if file_id:
            if query:
                raise _invalid()
            if action == 'modes':
                result = app.catalog.modes(file_id)
            elif action == 'returns':
                result = app.catalog.returns(file_id)
            else:
                result = app.catalog.file(file_id)
            return _json(200, result)
        if set(query) - {'q', 'limit', 'cursor'} or any(len(values) != 1 for values in query.values()):
            raise _invalid()
        try:
            limit = int(query.get('limit', ['100'])[0])
        except ValueError:
            raise _invalid() from None
        return _json(200, app.catalog.files(query.get('q', [''])[0], limit, query.get('cursor', [None])[0]))

    def _method(self, allowed, request_id):
        response = _problem(ApiError(405, 'METHOD_NOT_ALLOWED', 'Método não permitido nesta rota.'), request_id)
        response['headers']['Allow'] = allowed
        return response

    def _handle(self):
        request_id, started = str(uuid.uuid4()), time.monotonic()
        self.route = 'unmatched'
        try:
            response = self._dispatch(request_id)
        except ApiError as error:
            response = _problem(error, request_id)
        except (socket.timeout, TimeoutError):
            response = _problem(ApiError(408, 'REQUEST_TIMEOUT', 'Tempo limite de leitura excedido.'), request_id)
        except Exception:
            response = _problem(ApiError(500, 'INTERNAL_ERROR', 'Falha interna na operação.'), request_id)
        try:
            entry = {'requestId': request_id, 'method': self.command, 'route': self.route,
                     'status': response['status'], 'durationMs': round((time.monotonic() - started) * 1000, 2)}
            if response['headers'].get('Content-Type', '').startswith('application/json'):
                payload = json.loads(response['body'])
                entry.update({key: payload[key] for key in ['fileId', 'sourceRevision', 'composition', 'files'] if key in payload})
            if response['status'] >= 400 and 'problem+json' in response['headers'].get('Content-Type', ''):
                entry['code'] = json.loads(response['body'])['code']
            if 'X-Mockaize-SHA256' in response['headers']:
                entry['files'] = [{'sha256': response['headers']['X-Mockaize-SHA256'],
                                   'sizeBytes': int(response['headers']['X-Mockaize-Size-Bytes'])}]
            self.server.application.log.write(**entry)
        except ApiError as error:
            response = (_json(503, {'status': 'unavailable', 'version': __version__})
                        if self.route == '/health' else _problem(error, request_id))
        try:
            self.send_response(response['status'])
            for key, value in response['headers'].items():
                self.send_header(key, str(value))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Request-ID', request_id)
            self.send_header('Content-Length', str(len(response['body'])))
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(response['body'])
        except (OSError, BrokenPipeError):
            pass
        self.close_connection = True

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _handle


def serve(config_path: Path, stop_event: threading.Event | None = None) -> None:
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    check_environment(config)
    app = Application(config_path)
    app.log.write(method='START', route='service', status=200)
    stop = stop_event or threading.Event()
    app.stop_event = stop
    with ApiServer((config.host, config.port), app) as server:
        server.timeout = 0.25
        try:
            while not stop.is_set():
                server.handle_request()
        except KeyboardInterrupt:
            stop.set()
        finally:
            server.close_clients()
    app.log.write(method='STOP', route='service', status=200)
