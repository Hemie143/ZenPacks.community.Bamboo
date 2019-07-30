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


class ActiveMQ(PythonPlugin):
    """
    Doc about this plugin
    """

    _eventService = zope.component.queryUtility(IEventService)

    requiredProperties = (
        'zJolokiaPort',
        'zJolokiaUsername',
        'zJolokiaPassword',
    )

    deviceProperties = PythonPlugin.deviceProperties + requiredProperties

    components = [
        ['brokers', 'http://{}:{}/api/jolokia/read/org.apache.activemq:type=Broker,brokerName=*/'
                    'BrokerName,BrokerVersion,BrokerId,Queues'],
        ['queues', 'http://{}:{}/api/jolokia/read/org.apache.activemq:*,type=Broker,destinationType=Queue'],
    ]

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    @inlineCallbacks
    def collect(self, device, log):
        log.debug('{}: Modeling collect'.format(device.id))

        port = getattr(device, 'zJolokiaPort', None)
        username = getattr(device, 'zJolokiaUsername', None)
        password = getattr(device, 'zJolokiaPassword', None)

        ip_address = device.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        basic_auth = base64.encodestring('{}:{}'.format(username, password))
        auth_header = "Basic " + basic_auth.strip()

        deferreds = []
        sem = DeferredSemaphore(1)
        for comp in self.components:
            url = comp[1].format(ip_address, port)
            log.debug('collect url: {}'.format(url))
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "Authorization": auth_header,
                            "User-Agent": "Mozilla/3.0Gold",
                        },
                        )
            d.addCallback(self.add_tag, comp[0])
            deferreds.append(d)

        results = yield DeferredList(deferreds, consumeErrors=True)
        for success, result in results:
            if not success:
                errorMessage = result.getErrorMessage()
                log.error('{}: {}'.format(device.id, errorMessage))
                self._eventService.sendEvent(dict(
                    summary='Modeler plugin community.json.ActiveMQ returned no results.',
                    message=errorMessage,
                    eventClass='/Status/Jolokia',
                    eventClassKey='ActiveMQ_ConnectionError',
                    device=device.id,
                    eventKey='|'.join(('ActiveMQPlugin', device.id)),
                    severity=ZenEventClasses.Error,
                    ))
                returnValue(None)

        log.debug('ActiveMQ collect results: {}'.format(results))
        self._eventService.sendEvent(dict(
            summary='Modeler plugin community.json.ActiveMQ successful.',
            message='',
            eventClass='/Status/Jolokia',
            eventClassKey='ActiveMQ_ConnectionOK',
            device=device.id,
            eventKey='|'.join(('ActiveMQPlugin', device.id)),
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

        self.result_data = {}
        for success, result in results:
            if success:
                if result:
                    content = json.loads(result[1])
                else:
                    content = {}
                self.result_data[result[0]] = content

        brokers_data = self.result_data.get('brokers', '')
        if brokers_data and brokers_data['status'] == 200:
            brokers_data = brokers_data.get('value', '')
        else:
            return []

        queues_data = self.result_data.get('queues', '')
        if queues_data and queues_data['status'] == 200:
            queues_data = queues_data.get('value', '')

        broker_maps = []
        jvm_maps = []
        rm = []
        rm_queues = []
        rm_queuesdlq = []

        for broker, brokerAttr in brokers_data.items():
            om_broker = ObjectMap()
            om_jvm = ObjectMap()
            queue_maps = []
            queuedlq_maps = []

            broker_name = brokerAttr.get('BrokerName')
            om_broker.id = self.prepId(broker_name)
            om_broker.title = broker_name
            om_broker.brokerId = brokerAttr.get('BrokerId')
            om_broker.version = brokerAttr.get('BrokerVersion')
            om_broker.objectName = broker
            broker_maps.append(om_broker)
            om_jvm.id = self.prepId(broker_name)
            om_jvm.title = broker_name
            jvm_maps.append(om_jvm)

            compname_broker = 'activeMQBrokers/{}'.format(om_broker.id)
            queues = brokerAttr.get('Queues')
            for _, queue in [(_, queue) for q in queues for (_, queue) in q.items()]:
                # TODO: What if queue with same name in different broker ?
                # TODO: create queue id with broker id included
                queue_data = queues_data.get(queue, '')
                if queue_data:
                    om_queue = ObjectMap()
                    queue_name = queue_data['Name']
                    om_queue.id = self.prepId(queue_name)
                    om_queue.title = queue_name
                    om_queue.objectName = queue
                    om_queue.brokerName = broker_name

                    # DLQ detection based on attribute
                    # queue_dlq = queue_data['DLQ']
                    queue_dlq = queue_name.startswith('DLQ')
                    if queue_dlq:
                        queuedlq_maps.append(om_queue)
                    else:
                        queue_maps.append(om_queue)

            rm_queues.append(RelationshipMap(relname='activeMQQueues',
                                             modname='ZenPacks.community.ActiveMQ.ActiveMQQueue',
                                             compname=compname_broker,
                                             objmaps=queue_maps))
            rm_queuesdlq.append(RelationshipMap(relname='activeMQQueueDLQs',
                                                modname='ZenPacks.community.ActiveMQ.ActiveMQQueueDLQ',
                                                compname=compname_broker,
                                                objmaps=queuedlq_maps))

        rm.append(RelationshipMap(relname='activeMQBrokers',
                                  modname='ZenPacks.community.ActiveMQ.ActiveMQBroker',
                                  compname='',
                                  objmaps=broker_maps))

        rm.append(RelationshipMap(relname='activeMQJVMs',
                                  modname='ZenPacks.community.ActiveMQ.ActiveMQJVM',
                                  compname='',
                                  objmaps=jvm_maps))


        rm.extend(rm_queues)
        rm.extend(rm_queuesdlq)

        log.debug('{}: process maps:{}'.format(device.id, rm))
        return rm
