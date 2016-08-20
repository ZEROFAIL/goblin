import asyncio
import collections
import configparser
import json
import ssl

from goblin import driver, exception


class Cluster:

    DEFAULT_CONFIG = {
        'scheme': 'ws',
        'hosts': ['localhost'],
        'port': 8182,
        'ssl_certfile': '',
        'ssl_keyfile': '',
        'ssl_password': '',
        'username': '',
        'password': ''
    }

    def __init__(self, loop, **config):
        self._loop = loop
        self._config = dict(self.DEFAULT_CONFIG)
        self._config.update(config)
        self._hosts = collections.deque()
        self._closed = False

    @classmethod
    async def open(cls, loop, *, config_filename=None, **config):
        cluster = cls(loop, **config)
        if config_filename:
            cluster.config_from_file(config_filename)
        await cluster.establish_hosts()
        return cluster

    @property
    def config(self):
        return self._config

    async def get_connection(self):
        """Get connection from next available host in a round robin fashion"""
        if not self._hosts:
            await self.establish_hosts()
        host = self._hosts.popleft()
        conn = await host.connect()
        self._hosts.append(host)
        return conn

    async def establish_hosts(self):
        scheme = self._config['scheme']
        hosts = self._config['hosts']
        port = self._config['port']
        username = self._config['username']
        password = self._config['password']
        if scheme in ['https', 'wss']:
            certfile = self._config['ssl_certfile']
            keyfile = self._config['ssl_keyfile']
            ssl_password = self._config['ssl_password']
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
            ssl_context.load_cert_chain(
                certfile, keyfile=keyfile, password=ssl_password)
        else:
            ssl_context = None
        for host in hosts:
            url = '{}://{}:{}/'.format(scheme, host, port)
            host = await driver.GremlinServer.open(
                url, self._loop, ssl_context=ssl_context, username=username,
                password=password)
            self._hosts.append(host)

    def config_from_file(self, filename):
        if filename.endswith('ini'):
            self.config_from_ini(filename)
        elif filename.endswith('.json'):
            self.config_from_json(filename)
        else:
            try:
                self.config_from_module(filename)
            except:
                raise exception.ConfigurationError(
                    'Unknown config file format')

    def config_from_ini(self, filename):
        # HMMM
        with open(filename, 'r') as f:
            config = configparser.ConfigParser()
            config.read_file(f, source='filename')
            config = dict(config['CLUSTER'])
            config['hosts'] = [
                host.strip() for host in config['hosts'].split(',')]
            self.config.update(config)

    def config_from_json(self, filename):
        with open(filename, 'r') as f:
            config = json.load(f)
            self.config.update(config)

    def config_from_module(self, filename):
        raise NotImplementedError

    async def connect(self):
        if not self._hosts:
            await self.establish_hosts()
        return driver.Client(self)

    async def close(self):
        waiters = []
        while self._hosts:
            host = self._hosts.popleft()
            waiters.append(host.close())
        await asyncio.gather(*waiters)
        self._closed = True
