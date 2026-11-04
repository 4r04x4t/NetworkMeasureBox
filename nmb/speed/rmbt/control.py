import http.client
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

from . import connection


@dataclass
class TestParams:
    token:          str
    test_uuid:      Optional[str]
    open_test_uuid: Optional[str]
    server_addr:    str
    server_port:    int
    encryption:     bool
    duration:       int
    num_threads:    int
    wait:           int
    server_type:    str


class _BoundHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, source_ip=None, interface=None, **kwargs):
        super().__init__(**kwargs)
        self.source_ip = source_ip
        self.interface = interface

    def http_open(self, req):
        return self.do_open(self._build_conn, req)

    def _build_conn(self, host, **kwargs):
        if self.source_ip:
            kwargs['source_address'] = (self.source_ip, 0)
        return http.client.HTTPConnection(host, **kwargs)


class _BoundHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, source_ip=None, interface=None, **kwargs):
        super().__init__(**kwargs)
        self.source_ip = source_ip
        self.interface = interface

    def https_open(self, req):
        return self.do_open(self._build_conn, req)

    def _build_conn(self, host, **kwargs):
        if self.source_ip:
            kwargs['source_address'] = (self.source_ip, 0)
        return http.client.HTTPSConnection(host, **kwargs)


def _post(url, body, debug):
    data = json.dumps(body).encode()
    if debug:
        print(f'[debug] POST {url}', flush=True)
        print(f'[debug] request body:\n{json.dumps(body, indent=2)}', flush=True)
    req = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'})

    bound_ip = connection._bound_source_ip
    bound_iface = connection._bound_interface
    if bound_ip:
        opener = urllib.request.build_opener(
            _BoundHTTPHandler(source_ip=bound_ip, interface=bound_iface),
            _BoundHTTPSHandler(source_ip=bound_ip, interface=bound_iface),
        )
    else:
        opener = urllib.request.build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code}: {e.read().decode().strip()}')
    except Exception as e:
        if bound_ip:
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode()
            except Exception:
                raise e
        else:
            raise e
    if debug:
        try:
            pretty = json.dumps(json.loads(raw), indent=2)
        except Exception:
            pretty = raw
        print(f'[debug] response:\n{pretty}', flush=True)
    return json.loads(raw)


def request_settings(host, uuid, version, debug):
    url = host.rstrip('/') + '/RMBTControlServer/settings'
    body = {
        'name':                          'RMBT',
        'type':                          'DESKTOP',
        'language':                      'en',
        'timezone':                      'UTC',
        'softwareRevision':              version,
        'softwareVersionName':           version,
        'terms_and_conditions_accepted': True,
    }
    if uuid:
        body['uuid'] = uuid
    resp = _post(url, body, debug)
    settings = resp.get('settings', [])
    if not settings:
        raise RuntimeError('settings response contained no UUID')
    # json.loads gives proper nested dicts — safe to access settings[0]['uuid'] directly;
    # no risk of picking up a nested server UUID like in the C hand-rolled JSON parser.
    client_uuid = settings[0].get('uuid', '')
    if len(client_uuid) < 36:
        raise RuntimeError('settings response contained no valid UUID')
    return client_uuid


def request_test(host, uuid, version, use_ws, debug):
    url = host.rstrip('/') + '/RMBTControlServer/testRequest'
    body = {
        'uuid':             uuid,
        'client':           'RMBTws' if use_ws else 'RMBT',
        'version':          '0.9',
        'type':             'DESKTOP',
        'softwareVersion':  version,
        'softwareRevision': version,
        'language':         'en',
        'timezone':         'UTC',
        'time':             int(time.time() * 1000),
    }
    if not use_ws:
        body['capabilities'] = {'RMBThttp': True}
    resp = _post(url, body, debug)
    errors = resp.get('error', [])
    if errors:
        raise RuntimeError(f'control server error: {"; ".join(errors)}')
    port = resp.get('test_server_port', 443)
    if isinstance(port, str):
        port = int(port)
    return TestParams(
        token=          resp['test_token'],
        test_uuid=      resp.get('test_uuid'),
        open_test_uuid= resp.get('open_test_uuid'),
        server_addr=    resp['test_server_address'],
        server_port=    int(port),
        encryption=     resp.get('test_server_encryption', True),
        duration=       int(resp.get('test_duration',   10)),
        num_threads=    int(resp.get('test_numthreads',  4)),
        wait=           int(resp.get('test_wait',        0)),
        server_type=    resp.get('test_server_type', ''),
    )


def submit_result(host, result, debug):
    url = host.rstrip('/') + '/RMBTControlServer/result'
    try:
        _post(url, result, debug)
    except Exception as e:
        print(f'Warning: result submission failed: {e}')
