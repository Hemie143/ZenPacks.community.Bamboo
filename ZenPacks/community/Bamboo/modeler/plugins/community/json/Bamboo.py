# stdlib Imports
import base64
import json

import zope.component
# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from Products.ZenCollector.interfaces import IEventService
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

    _eventService = zope.component.queryUtility(IEventService)

    requiredProperties = (
        'zBambooPort',
        'zBambooUsername',
        'zBambooPassword',
        'zBambooServerAlias',
    )

    deviceProperties = PythonPlugin.deviceProperties + requiredProperties

    components = [
        ['bamboo', 'https://{}:{}/rest/api/latest/info'],
    ]

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

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

        # deferreds = []
        # sem = DeferredSemaphore(1)
        # TODO: use try..except
        # TODO: check response.code
        for component, url_pattern in self.components:
            url = url_pattern.format(serverAlias, port)
            log.debug('collect url: {}'.format(url))

            response = yield agent.request('GET', url, Headers(headers))
            response_body = yield readBody(response)
            response_body = json.loads(response_body)
            log.debug('response_body: {}'.format(response_body))
            results[component] = response_body
        returnValue(results)

    def process(self, device, results, log):
        """
        Must return one of :
            - None, changes nothing. Good in error cases.
            - A RelationshipMap, for the device to component information
            - An ObjectMap, for the device device information
            - A list of RelationshipMaps and ObjectMaps, both
        """
        log.debug('Process results: {}'.format(results))

        bamboo_data = results.get('bamboo', '')
        rm = []
        if bamboo_data:
            bamboo_maps = []
            om_bamboo = ObjectMap()
            bamboo_name = 'Bamboo {}'.format(bamboo_data['version'])
            om_bamboo.id = self.prepId(bamboo_name)
            om_bamboo.title = bamboo_name
            bamboo_maps.append(om_bamboo)

            rm.append(RelationshipMap(relname='bambooServers',
                                      modname='ZenPacks.community.Bamboo.BambooServer',
                                      compname='',
                                      objmaps=bamboo_maps))

        log.debug('{}: process maps:{}'.format(device.id, rm))
        return rm
