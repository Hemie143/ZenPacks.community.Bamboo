# stdlib Imports
import json

# Twisted Imports
from twisted.internet.defer import inlineCallbacks, returnValue, DeferredSemaphore, DeferredList
from twisted.web.client import getPage

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from Products.ZenCollector.interfaces import IEventService
from Products.ZenEvents import ZenEventClasses
import zope.component

import base64


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
        # url = 'https://{}:{}/rest/api/latest/info'.format(serverAlias, port)

        headers = {
                      "Accept": 'application/json',
                      "Authorization": auth_header,
                      "User-Agent": 'Mozilla/3.0Gold',
                  }

        deferreds = []
        sem = DeferredSemaphore(1)
        for comp in self.components:
            url = comp[1].format(serverAlias, port)
            log.debug('collect url: {}'.format(url))
            d = sem.run(getPage, url,
                        headers=headers,
                        )
            d.addCallback(self.add_tag, comp[0])
            deferreds.append(d)

        results = yield DeferredList(deferreds, consumeErrors=True)
        for success, result in results:
            if not success:
                errorMessage = result.getErrorMessage()
                log.error('{}: {}'.format(device.id, errorMessage))
                self._eventService.sendEvent(dict(
                    summary='Modeler plugin community.json.Bamboo returned no results.',
                    message=errorMessage,
                    eventClass='/Status/Bamboo',
                    eventClassKey='Bamboo_ConnectionError',
                    device=device.id,
                    eventKey='|'.join(('BambooPlugin', device.id)),
                    severity=ZenEventClasses.Error,
                    ))
                returnValue(None)

        log.debug('Bamboo collect results: {}'.format(results))
        self._eventService.sendEvent(dict(
            summary='Modeler plugin community.json.Bamboo successful.',
            message='',
            eventClass='/Status/Bamboo',
            eventClassKey='Bamboo_ConnectionOK',
            device=device.id,
            eventKey='|'.join(('BambooPlugin', device.id)),
            severity=ZenEventClasses.Clear,
        ))
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

        self.result_data = {}
        for success, result in results:
            if success:
                if result:
                    content = json.loads(result[1])
                else:
                    content = {}
                self.result_data[result[0]] = content

        bamboo_data = self.result_data.get('bamboo', '')
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
