
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
log = logging.getLogger('zen.PythonAMQJVM')

# https://www.cs.mun.ca/java-api-1.5/guide/management/overview.html

class ActiveMQJVM(PythonDataSourcePlugin):

    proxy_attributes = (
        'zJolokiaPort',
        'zJolokiaUsername',
        'zJolokiaPassword',
    )

    # TODO: jolokia query should just get HTTP code back
    # TODO: process jolokia in separate module to run once per host, but then how to use the result in other modules ?
    urls = {
        'jolokia': 'http://{}:{}/',
        #TODO: change next to jvm_mem
        'jvm_memory': 'http://{}:{}/api/jolokia/read/java.lang:type=Memory',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key jvm
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                     context.id, 'amq-jvm'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            'amq-jvm'
        )

    @classmethod
    def params(cls, datasource, context):
        # TODO: is it required ?
        log.debug('Starting AMQDevice params')
        # params = {'objectName': context.objectName}
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting ActiveMQ JVM collect')

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)

        ds0 = config.datasources[0]

        # for datasource in config.datasources:
        for endpoint in self.urls:

            # object_name = datasource.params['objectName']
            # url = self.urls[datasource.datasource].format(ip_address, datasource.zJolokiaPort)
            url = self.urls[endpoint].format(ip_address, ds0.zJolokiaPort)
            # basic_auth = base64.encodestring('{}:{}'.format(datasource.zJolokiaUsername, datasource.zJolokiaPassword))
            basic_auth = base64.encodestring('{}:{}'.format(ds0.zJolokiaUsername, ds0.zJolokiaPassword))
            auth_header = "Basic " + basic_auth.strip()
            # TODO: replace getPage (deprecated)
            # TODO: Use a POST instead of GET ???
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "Authorization": auth_header,
                            "User-Agent": "Mozilla/3.0Gold",
                        },
                        )
            d.addCallback(self.add_tag, endpoint)
            deferreds.append(d)
        return DeferredList(deferreds)

    def onSuccess(self, result, config):
        log.debug('Success - result is {}'.format(result))

        data = self.new_data()
        jvm_name = config.datasources[0].component
        ds_data = {}

        # Check that all data has been received correctly
        if any([not s for s, d in result]):
            data['events'].append({
                'device': config.id,
                'component': jvm_name,
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
                    ds_data[ds] = 'OK'
                else:
                    metrics = json.loads(ddata[1])
                    ds_data[ds] = metrics
            else:
                data['events'].append({
                    'device': config.id,
                    'component': jvm_name,
                    'severity': 3,
                    'eventKey': 'AMQBroker',
                    'eventClassKey': 'AMQBroker',
                    'summary': 'AMQBroker - Collection failed',
                    'message': '{}'.format(ddata.value),
                    'eventClass': '/Status/Jolokia',
                })

        # JVM data collection went fine
        data['events'].append({
            'device': config.id,
            'component': jvm_name,
            'severity': 0,
            'eventKey': 'AMQBroker',
            'eventClassKey': 'AMQBroker',
            'summary': 'AMQBroker - Collection OK',
            'message': '',
            'eventClass': '/Status/Jolokia',
        })

        # Generate metrics data per datasource
        for datasource in config.datasources:
            component = prepId(datasource.component)
            if datasource.datasource == 'jvm_memory':
                status = ds_data[datasource.datasource]['status']
                if status != 200:
                    data['events'].append({
                        'device': config.id,
                        'component': jvm_name,
                        'severity': 3,
                        'eventKey': 'JVMMemory',
                        'eventClassKey': 'JVMMemory',
                        'summary': 'JVMMemory - Collection failed',
                        'message': 'Memory MBean Status: {}'.format(status),
                        'eventClass': '/Status/Jolokia',
                    })
                data['events'].append({
                    'device': config.id,
                    'component': jvm_name,
                    'severity': 0,
                    'eventKey': 'JVMMemory',
                    'eventClassKey': 'JVMMemory',
                    'summary': 'JVMMemory - OK',
                    'message': 'JVMMemory - OK',
                    'eventClass': '/Status/Jolokia',
                })
                jvm_memory_values = ds_data[datasource.datasource]['value']
                heap_values = jvm_memory_values['HeapMemoryUsage']
                data['values'][component]['heap_committed'] = heap_values['committed']
                data['values'][component]['heap_max'] = heap_values['max']
                data['values'][component]['heap_used'] = heap_values['used']
                data['values'][component]['heap_used_percent'] = round(float(heap_values['used'])/heap_values['max']*100, 2)
                nonheap_values = jvm_memory_values['NonHeapMemoryUsage']
                data['values'][component]['nonheap_committed'] = nonheap_values['committed']
                data['values'][component]['nonheap_used'] = nonheap_values['used']

        log.debug('ActiveMQJVM onSuccess data: {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
