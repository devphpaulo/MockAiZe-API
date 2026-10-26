"""Host HTTP standalone, sem sessão do estúdio ou dependência de navegador."""
from collections import deque
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import queue
import re
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit
import uuid

from . import __version__
from .api_docs import DOCUMENTATION_ROUTES, documentation_response
from .catalog import Catalog
from .config import load_config
from .errors import ApiError
from .policy import Policy, ResolvedPolicy
from .preflight import check_environment, _check_directories, PreflightError
from .publication import metadata, publish, safe_filename
from .request_log import RequestLog
from .security import AuthContext, Authenticator, key_digest
from .state import State

def _engine_child(channel, operation, variation, body, index, policy):
    try:
        from .xml_engine import generate_new, generate_return
        if operation == 'new':
            result = generate_new(variation, body['recordCount'], file_index=index, policy=policy)
        else:
            result = generate_return(variation, body['returnSelection'], body.get('composition', 'apart'),
                                     input_xml=body['inputXml'], file_index=index,
                                     input_records=body.get('inputRecords', 'all'), policy=policy)
        channel.send(('ok', result))
    except ApiError as error:
        channel.send(('error', (error.status, error.code, error.detail, error.extensions)))
    except Exception:
        channel.send(('error', (500, 'INTERNAL_ERROR', 'Falha interna na geração.', {})))
    finally:
        channel.close()


def run_engine(operation, variation, body, index, timeout, stop_event=None, policy=None):
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_engine_child,
                              args=(sender, operation, variation, body, index, policy or ResolvedPolicy()))
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
    response = _json(error.status, {'error': {'code': error.code, 'message': error.detail,
                                            'traceId': request_id}, **error.public_extensions()})
    response['headers']['X-Request-ID'] = request_id
    if error.status == 429:
        response['headers']['Retry-After'] = '1'
    return response


def _response_error(response: dict) -> dict:
    """Read new errors and persisted legacy errors without rewriting replay bytes."""
    if response['status'] < 400 or 'json' not in response['headers'].get('Content-Type', ''):
        return {}
    try:
        payload = json.loads(response['body'])
    except (ValueError, UnicodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get('error'), dict):
        return payload['error']
    if response['headers'].get('X-Idempotent-Replay') == 'true' and 'code' in payload:
        return {'code': payload['code'], 'traceId': payload.get('requestId')}
    return {}


def _response_trace(response: dict, request_id: str) -> str:
    trace_id = _response_error(response).get('traceId')
    if isinstance(trace_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', trace_id):
        return trace_id
    return request_id


def _invalid():
    return ApiError(400, 'INVALID_REQUEST', 'Verifique os campos, tipos e limites da requisição.')


def _nonempty_string(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 128


def validate_generation(operation: str, body: object, policy: ResolvedPolicy | None = None) -> dict:
    policy = policy or ResolvedPolicy()
    common = {'fileId', 'delivery', 'expectedRevision'}
    extra = {'recordCount'} if operation == 'new' else {'returnSelection', 'composition', 'inputXml', 'inputRecords'}
    if not isinstance(body, dict) or set(body) - common - extra or not _nonempty_string(body.get('fileId')):
        raise _invalid()
    if body.get('delivery', 'directory') not in ('directory', 'content', 'inline'):
        raise _invalid()
    if 'expectedRevision' in body and (type(body['expectedRevision']) is not int or body['expectedRevision'] < 1):
        raise _invalid()
    if operation == 'new':
        count = body.get('recordCount')
        if type(count) is not int or count < 1 or (policy.record_count is not None and count > policy.record_count):
            raise _invalid()
        return body
    if body.get('composition', 'apart') not in ('apart', 'mixed'):
        raise _invalid()
    if body.get('inputRecords', 'all') not in ('all', 'first'):
        raise _invalid()
    if not isinstance(body.get('inputXml'), str) or not body['inputXml'].strip():
        raise _invalid()
    try:
        input_size = len(body['inputXml'].encode('utf-8'))
    except UnicodeError:
        raise ApiError(422, 'INPUT_XML_INVALID', 'XML contém caracteres Unicode inválidos.') from None
    if policy.input_xml_bytes is not None and input_size > policy.input_xml_bytes:
        raise ApiError(413, 'INPUT_TOO_LARGE', 'O XML de entrada excede o limite configurado.')
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
        self.policy = Policy.load(config_path).resolve(
            self.config, config_path=config_path,
            protected_paths=(Path(sys.executable).resolve().parent, Path(__file__).resolve().parent))
        key_digest(config_path)
        self.auth = Authenticator(config_path)
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
        body = validate_generation(operation, body, self.policy)
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
            if (operation == 'return' and body.get('delivery', 'directory') == 'inline'
                    and body.get('composition', 'apart') == 'apart'):
                selection = body['returnSelection']
                count = len(selection['ids']) if selection['type'] == 'ids' else len(variation['config'].get('returnModels', []))
                if count != 1:
                    raise ApiError(422, 'DELIVERY_INCOMPATIBLE', 'Entrega inline exige exatamente um XML final.')
            index = self.state.next_index(body['fileId'])
            documents = run_engine(operation, variation, body, index, self.policy.generation_timeout_seconds,
                                   self.stop_event, self.policy)
            if not documents:
                raise ApiError(500, 'INTERNAL_ERROR', 'A geração não produziu documentos.')
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
        self.rejection_events = queue.Queue(maxsize=application.policy.maximum_connections)
        self.rejection_stop = threading.Event()
        self.rejection_worker = None
        super().__init__(address, Handler)
        self.rejection_worker = threading.Thread(target=self._write_rejection_events,
                                                 name='mockaize-rejection-log', daemon=True)
        self.rejection_worker.start()

    def _write_rejection_events(self):
        while True:
            entry = self.rejection_events.get()
            try:
                if entry is None or self.rejection_stop.is_set():
                    return
                try:
                    self.application.log.write(**entry)
                except ApiError:
                    # Log dependency failures must not block the accept loop or
                    # terminate the service. The HTTP response was already sent.
                    pass
            finally:
                self.rejection_events.task_done()

    def _queue_rejection(self, request_id):
        if self.rejection_stop.is_set():
            return False
        try:
            self.rejection_events.put_nowait({'requestId': request_id, 'method': 'UNPARSED',
                                             'route': 'unmatched', 'status': 429, 'code': 'RATE_LIMITED',
                                             'responseTraceId': request_id})
            return True
        except queue.Full:
            return False

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            request_id = str(uuid.uuid4())
            response = _problem(ApiError(429, 'RATE_LIMITED', 'Limite de conexões excedido.'), request_id)
            try:
                # A bounded discard avoids Windows resetting the connection when
                # an ordinary request arrives while its rejection is being sent.
                # Never parse/log these bytes or wait for a slow client's body.
                request.settimeout(0.05)
                try:
                    request.recv(65536)
                except (OSError, TimeoutError):
                    pass
                if not self._queue_rejection(request_id):
                    response = _problem(ApiError(503, 'DEPENDENCY_UNAVAILABLE',
                                                 'Log operacional temporariamente indisponível.'), request_id)
                headers = {**response['headers'], 'Content-Length': str(len(response['body'])),
                           'Cache-Control': 'no-store', 'Connection': 'close'}
                head = f"HTTP/1.0 {response['status']} {HTTPStatus(response['status']).phrase}\r\n" + ''.join(
                    f'{key}: {value}\r\n' for key, value in headers.items()) + '\r\n'
                request.sendall(head.encode('ascii') + response['body'])
            except OSError:
                pass
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
        self.rejection_stop.set()
        try:
            self.rejection_events.put_nowait(None)
        except queue.Full:
            pass
        # A filesystem/network write cannot be interrupted safely. One daemon
        # worker and a finite queue bound its resources without delaying stop.
        if self.rejection_worker is not None:
            self.rejection_worker.join(0.1)
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

    def send_error(self, code, message=None, explain=None):
        # BaseHTTPHandler diagnostics can contain request targets and credentials.
        # Keep the original HTTP status and supply only fixed public messages.
        codes = {414: 'REQUEST_URI_TOO_LONG', 431: 'REQUEST_HEADERS_TOO_LARGE',
                 501: 'METHOD_NOT_ALLOWED', 505: 'HTTP_VERSION_UNSUPPORTED'}
        request_id = str(uuid.uuid4())
        self.route = 'unmatched'
        command = getattr(self, 'command', None)
        self.command = command if command in {
            'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS', 'TRACE', 'CONNECT'} else 'UNPARSED'
        if getattr(self, 'request_version', '') in ('HTTP/0.9', ''):
            self.request_version = 'HTTP/1.0'
        response = _problem(ApiError(code, codes.get(code, 'INVALID_REQUEST'),
                                     'Não foi possível processar a requisição HTTP.'), request_id)
        self._respond(response, request_id, time.monotonic())

    def _body(self, maximum_bytes=None):
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
        if maximum_bytes is not None and size > maximum_bytes:
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
        if path == '/api/v1/auth/token':
            self.route = path
            keys = self.headers.get_all('X-API-Key', [])
            authorizations = self.headers.get_all('Authorization', [])
            self.auth_context = app.auth.authenticate(keys, authorizations, key_only=True)
            app.rate_check()
            if self.command != 'POST':
                return self._method('POST', request_id)
            if url.query or self._body(maximum_bytes=4096) != {}:
                raise _invalid()
            result = app.auth.issue(keys, authorizations)
            self.login_success = True
            return _json(200, result)
        route = re.fullmatch(
            r'/api/v1/files/xml(?:/([A-Za-z0-9_-]{1,128})(?:/(modes|returns|new|return))?)?', path)
        if not route:
            raise ApiError(404, 'ROUTE_NOT_FOUND', 'Rota não encontrada.')
        file_id, action = route.groups()
        self.route = '/api/v1/files/xml' + ('/{fileId}' if file_id else '') + ('/' + action if action else '')
        self.auth_context = app.auth.authenticate(self.headers.get_all('X-API-Key', []),
                                                  self.headers.get_all('Authorization', []),
                                                  required=app.config.authentication.required)
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
        self.auth_context = AuthContext()
        self.login_success = False
        try:
            response = self._dispatch(request_id)
        except ApiError as error:
            response = _problem(error, request_id)
        except (socket.timeout, TimeoutError):
            response = _problem(ApiError(408, 'REQUEST_TIMEOUT', 'Tempo limite de leitura excedido.'), request_id)
        except Exception:
            response = _problem(ApiError(500, 'INTERNAL_ERROR', 'Falha interna na operação.'), request_id)
        self._respond(response, request_id, started)

    def _respond(self, response, request_id, started):
        response_trace = _response_trace(response, request_id)
        try:
            entry = {'requestId': request_id, 'method': self.command, 'route': self.route,
                     'status': response['status'], 'durationMs': round((time.monotonic() - started) * 1000, 2)}
            context = getattr(self, 'auth_context', AuthContext())
            entry.update(authenticated=context.authenticated, authMethod=context.method)
            if getattr(self, 'login_success', False) and response['status'] == 200:
                entry['event'] = 'LOGIN_SUCCESS'
            if response['headers'].get('Content-Type', '').startswith('application/json'):
                payload = json.loads(response['body'])
                entry.update({key: payload[key] for key in ['fileId', 'sourceRevision', 'composition', 'files'] if key in payload})
            error = _response_error(response)
            if error:
                entry.update(code=error['code'], responseTraceId=response_trace)
                if response['headers'].get('X-Idempotent-Replay') == 'true':
                    entry['replayOfTraceId'] = response_trace
            if 'X-Mockaize-SHA256' in response['headers']:
                entry['files'] = [{'sha256': response['headers']['X-Mockaize-SHA256'],
                                   'sizeBytes': int(response['headers']['X-Mockaize-Size-Bytes'])}]
            self.server.application.log.write(**entry)
        except ApiError as error:
            response = (_json(503, {'status': 'unavailable', 'version': __version__})
                        if self.route == '/health' else _problem(error, request_id))
            response_trace = request_id
        try:
            self.send_response(response['status'])
            for key, value in response['headers'].items():
                if key.lower() != 'x-request-id':
                    self.send_header(key, str(value))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Request-ID', response_trace)
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
