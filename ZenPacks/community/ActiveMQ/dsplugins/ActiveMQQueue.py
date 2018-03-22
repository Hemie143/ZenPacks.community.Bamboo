
# stdlib Imports
import json
import logging
import base64

# Twisted Imports
from twisted.internet.defer import returnValue, DeferredSemaphore, DeferredList
from twisted.web.client import getPage

# Zenoss imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSourcePlugin
from Products.ZenUtils.Utils import prepId

# Setup logging
log = logging.getLogger('zen.PythonAMQQueue')


class ActiveMQQueue(PythonDataSourcePlugin):

    # TODO : Cleanup
    # TODO : Hide attributes from grid

    proxy_attributes = (
        'zJolokiaPort',
        'zJolokiaUsername',
        'zJolokiaPassword',
    )

    urls = {
        'delete': 'http://{}:{}/api/jolokia/read/org.apache.activemq:type=Broker,brokerName=*/'
                    'BrokerName,BrokerVersion,BrokerId',
        'broker': 'http://{}:{}/api/jolokia/read/{},service=Health/CurrentStatus',
        'queue': 'http://{}:{}/api/jolokia/read/{}/ConsumerCount,DequeueCount,EnqueueCount,ExpiredCount,QueueSize',
        }

    #                   org.apache.activemq:brokerName=service-node1-master,type=Broker
    # /api/jolokia/read/org.apache.activemq:type=Broker,brokerName=service-node1-master,service=Health/CurrentStatus
    # /api/jolokia/read/org.apache.activemq:type=Broker,brokerName=service-node1-master,destinationType=Queue,destinationName=be.fednot.delivery.topic/ConsumerCount,DequeueCount,EnqueueCount,ExpiredCount,QueueSize
    #                   org.apache.activemq:brokerName=service-node1-master,destinationName=be.fednot.delivery.topic,destinationType=Queue,type=Broker
    # DequeueCount,   EnqueueCount,   ExpiredCount, QueueSize
    # /api/jolokia/read/org.apache.activemq:type=Broker,brokerName=service-node1-master,destinationType=Queue,destinationName=be.fednot.delivery.topic/ConsumerCount,DequeueCount,EnqueueCount,ExpiredCount,QueueSize


    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    @classmethod
    def config_key(cls, datasource, context):
        # To run per broker or queue ???
        log.debug(
            'In config_key context.device().id is %s datasource.getCycleTime(context) is %s datasource.rrdTemplate().id is %s datasource.id is %s datasource.plugin_classname is %s  ' % (
            context.device().id, datasource.getCycleTime(context), datasource.rrdTemplate().id, datasource.id,
            datasource.plugin_classname))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            'amq-broker'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting AMQDevice params')
        params = {}
        params['objectName'] = context.objectName
        log.debug(' params is %s \n' % (params))
        return params

    # TODO : with inlinebacks and return yields
    def collect(self, config):
        log.debug('Starting ActiveMQ Broker collect')

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)
        for datasource in config.datasources:
            # timespan = max(120, 2 * datasource.cycletime)
            objectName = datasource.params['objectName']
            log.debug('objectName: {}'.format(objectName))
            url = self.urls[datasource.datasource].format(ip_address, datasource.zJolokiaPort, objectName)
            basicAuth = base64.encodestring('{}:{}'.format(datasource.zJolokiaUsername, datasource.zJolokiaPassword))
            authHeader = "Basic " + basicAuth.strip()
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "Authorization": authHeader,
                            "User-Agent": "Mozilla/3.0Gold",
                        },
                        )
            d.addCallback(self.add_tag, datasource.datasource)
            deferreds.append(d)
        return DeferredList(deferreds)

    # TODO: def onResult and check status within result, should be 200

    def onSuccess(self, result, config):
        log.debug('Success - result is {}'.format(result))
        log.debug('Success - config is {}'.format(config.datasources[0].__dict__))

        ds_data = {}
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics

        log.debug('ds_data: {}'.format(ds_data))
        data = self.new_data()
        for datasource in config.datasources:
            component = prepId(datasource.component)
            values = ds_data['queue']['value']
            log.debug('component: {}'.format(component))
            log.debug('values: {}'.format(values))
            data['values'][component]['consumerCount'] = values['ConsumerCount']
            data['values'][component]['enqueueCount'] = values['EnqueueCount']
            data['values'][component]['dequeueCount'] = values['DequeueCount']
            data['values'][component]['expiredCount'] = values['ExpiredCount']
            data['values'][component]['queueSize'] = values['QueueSize']
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
