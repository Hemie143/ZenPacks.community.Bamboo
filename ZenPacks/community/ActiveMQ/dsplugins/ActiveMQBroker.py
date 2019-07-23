
# stdlib Imports
import json
import logging
import base64

# Twisted Imports
from twisted.internet.defer import returnValue, DeferredSemaphore, DeferredList
from twisted.web.client import getPage
from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.endpoints import TCP4ClientEndpoint, connectProtocol

# Zenoss imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSourcePlugin
from Products.ZenUtils.Utils import prepId

# Setup logging
log = logging.getLogger('zen.PythonAMQBroker')


class ActiveMQBroker(PythonDataSourcePlugin):

    proxy_attributes = (
        'zJolokiaPort',
        'zJolokiaUsername',
        'zJolokiaPassword',
    )

    # TODO: jolokia query should just get HTTP code back
    # TODO: process jolokia in separate module to run once per host ???
    urls = {
        'jolokia': 'http://{}:{}',
        'brokerhealth': 'http://{}:{}/api/jolokia/read/{},service=Health/CurrentStatus',
        'broker': 'http://{}:{}/api/jolokia/read/{}/UptimeMillis,StorePercentUsage,TempPercentUsage,CurrentConnectionsCount,MemoryPercentUsage',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                     context.id, 'amq-broker'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            'amq-broker'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting AMQDevice params')
        params = {'objectName': context.objectName}
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting ActiveMQ Broker collect')

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)

        '''
        ds0 = config.datasources[0]
        point = TCP4ClientEndpoint(reactor, ip_address, ds0.zJolokiaPort)
        d = connectProtocol(point, Protocol())
        d.addCallback(self.add_tag, 'JolokiaPort')
        deferreds.append(d)
        '''

        for datasource in config.datasources:
            object_name = datasource.params['objectName']
            url = self.urls[datasource.datasource].format(ip_address, datasource.zJolokiaPort, object_name)
            basic_auth = base64.encodestring('{}:{}'.format(datasource.zJolokiaUsername, datasource.zJolokiaPassword))
            auth_header = "Basic " + basic_auth.strip()
            # TODO: replace getPage (deprecated)
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "Authorization": auth_header,
                            "User-Agent": "Mozilla/3.0Gold",
                        },
                        )
            d.addCallback(self.add_tag, datasource.datasource)
            deferreds.append(d)
        return DeferredList(deferreds)

    def onSuccess(self, result, config):
        log.debug('AAASuccess - result is {}'.format(result))

        # TODO: Move following block under next loop, in case of multiple brokers
        data = self.new_data()
        broker_name = config.datasources[0].component
        ds_data = {}

        # Check that all data has been received correctly
        if all([not s for s, d in result]):
            data['events'].append({
                'device': config.id,
                'component': broker_name,
                'severity': 3,
                'eventKey': 'AMQBroker',
                'eventClassKey': 'AMQBroker',
                'summary': 'Connection to AMQ/Jolokia failed',
                'message': '{}'.format(d),
                'eventClass': '/Status/Jolokia',
            })
            return data

        # Collect metrics per datasource in ds_data. If failed, generate event
        for success, ddata in result:
            if success:
                ds = ddata[0]
                if ds == 'jolokia':
                    # Data is not in JSON format
                    ds_data[ds] = 'test'
                else:
                    metrics = json.loads(ddata[1])
                    ds_data[ds] = metrics
            else:
                data['events'].append({
                    'device': config.id,
                    'component': broker_name,
                    'severity': 3,
                    'eventKey': 'AMQBroker',
                    'eventClassKey': 'AMQBroker',
                    'summary': 'AMQBroker - Collection failed',
                    'message': '{}'.format(ddata.value),
                    'eventClass': '/Status/Jolokia',
                })

        # Broker data collection went fine
        data['events'].append({
            'device': config.id,
            'component': broker_name,
            'severity': 0,
            'eventKey': 'AMQBroker',
            'eventClassKey': 'AMQBroker',
            'summary': 'AMQBroker - Collection OK',
            'message': '',
            'eventClass': '/Status/Jolokia',
        })

        log.debug('AAA - ds_data is {}'.format(ds_data))
        # Generate metrics data per datasource
        for datasource in config.datasources:
            component = prepId(datasource.component)
            if 'brokerhealth' not in ds_data:
                continue
            broker_health = ds_data['brokerhealth']['value']
            if 'broker' not in ds_data:
                continue
            broker_values = ds_data['broker']['value']
            uptimemillis = broker_values['UptimeMillis']
            data['values'][component]['uptime'] = uptimemillis / 1000 / 60
            data['values'][component]['memoryusage'] = broker_values['MemoryPercentUsage']
            data['values'][component]['storeusage'] = broker_values['StorePercentUsage']
            data['values'][component]['tempusage'] = broker_values['TempPercentUsage']
            data['values'][component]['currentconnections'] = broker_values['CurrentConnectionsCount']
            if broker_health.startswith('Good'):
                data['values'][component]['health'] = 0
                data['events'].append({
                    'device': config.id,
                    'component': component,
                    'severity': 0,
                    'eventKey': 'AMQBrokerHealth',
                    'eventClassKey': 'AMQBrokerHealth',
                    'summary': 'Broker "{}" - Status is OK'.format(component),
                    'message': broker_health,
                    'eventClass': '/Status/ActiveMQ/Broker',
                    'amqHealth': broker_health
                })
            else:
                data['values'][component]['health'] = 3
                data['events'].append({
                    'device': config.id,
                    'component': component,
                    'severity': 3,
                    'eventKey': 'AMQBrokerHealth',
                    'eventClassKey': 'AMQBrokerHealth',
                    'summary': 'Broker "{}" - Status failure'.format(component),
                    'message': broker_health,
                    'eventClass': '/Status/ActiveMQ/Broker',
                    'amqHealth': broker_health
                })
        log.debug('ActiveMQBroker onSuccess data: {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
