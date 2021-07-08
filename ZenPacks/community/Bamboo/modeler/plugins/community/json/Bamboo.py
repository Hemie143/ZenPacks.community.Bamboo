# stdlib Imports
import base64
import json

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from ZenPacks.community.Bamboo.lib.utils import SkipCertifContextFactory

# Twisted Imports
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers


class Bamboo(PythonPlugin):
    """
    Doc about this plugin
    """

    requiredProperties = (
        'zBambooPort',
        'zBambooUsername',
        'zBambooPassword',
        'zBambooServerAlias',
    )

    deviceProperties = PythonPlugin.deviceProperties + requiredProperties


    @inlineCallbacks
    def collect(self, device, log):
        log.debug('{}: Modeling collect'.format(device.id))

        port = getattr(device, 'zBambooPort', None)
        username = getattr(device, 'zBambooUsername', None)
        password = getattr(device, 'zBambooPassword', None)
        serverAlias = getattr(device, 'zBambooServerAlias', None)
        if not serverAlias:
            log.error("%s: zBambooServerAlias cannot be empty", device.id)
            returnValue(None)

        basic_auth = base64.encodestring('{}:{}'.format(username, password))
        auth_header = "Basic " + basic_auth.strip()
        headers = {
                      "Accept":['application/json'],
                      "Authorization": [auth_header],
                      "User-Agent": ['Mozilla/3.0Gold'],
                  }

        results = {}
        agent = Agent(reactor, contextFactory=SkipCertifContextFactory())

        # TODO: use try..except
        # TODO: check response.code
        # Bamboo server
        url = 'https://{}:{}/rest/api/latest/info'.format(serverAlias, port)
        log.debug('collect url: {}'.format(url))

        response = yield agent.request('GET', url, Headers(headers))
        response_body = yield readBody(response)
        response_body = json.loads(response_body)
        results['bamboo'] = response_body

        # Sized output
        limit = 25
        urls = {
            'projects': 'https://{}:{}/rest/api/latest/project?max-result={}&start-index={}',
        }
        for item, base_url in urls.items():
            data = []
            offset = 0
            while True:
                url = base_url.format(serverAlias, port, limit, offset)
                log.debug('collect url: {}'.format(url))
                response = yield agent.request('GET', url, Headers(headers))
                response_body = yield readBody(response)
                log.debug('response_body: {}'.format(response_body))
                response_body = json.loads(response_body)
                log.debug('projects: {}'.format(len(response_body['projects']['project'])))
                log.debug('max-result: {}'.format(response_body['projects']['max-result']))
                log.debug('size: {}'.format(response_body['projects']['size']))
                # TODO: do not use project as string
                data.extend(response_body['projects']['project'])
                offset += limit
                if len(data) >= response_body[item]['size'] or offset > response_body[item]['size']:
                    break
            results[item] = data
        returnValue(results)

    def process(self, device, results, log):
        """
        Must return one of :
            - None, changes nothing. Good in error cases.
            - A RelationshipMap, for the device to component information
            - An ObjectMap, for the device device information
            - A list of RelationshipMaps and ObjectMaps, both
        """
        # log.debug('Process results: {}'.format(results))

        rm = []
        if 'bamboo' in results:
            rm.append(self.model_bamboo(results['bamboo'], log))
            if 'projects' in results:
                # log.debug('project: {}'.format(results['project']))
                log.debug('project: {}'.format(len(results['projects'])))
        log.debug('{}: process maps:{}'.format(device.id, rm))
        return rm

    def model_bamboo(self, data, log):
        om_bamboo = ObjectMap()
        om_bamboo.id = 'bamboo'
        om_bamboo.title = 'Bamboo {}'.format(data['version'])

        return RelationshipMap(relname='bambooServers',
                               modname='ZenPacks.community.Bamboo.BambooServer',
                               compname='',
                               objmaps=[om_bamboo])
