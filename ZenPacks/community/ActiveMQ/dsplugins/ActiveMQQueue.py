
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

    proxy_attributes = (
        'zJolokiaPort',
        'zJolokiaUsername',
        'zJolokiaPassword',
    )

    urls = {
        'broker': 'http://{}:{}/api/jolokia/read/{},service=Health/CurrentStatus',
        'queue': 'http://{}:{}/api/jolokia/read/{}/ConsumerCount,DequeueCount,EnqueueCount,ExpiredCount,QueueSize,AverageMessageSize,MaxMessageSize',
        }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key queue
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                     context.id, 'amq-queue'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            'amq-queue'
        )

    @classmethod
    def params(cls, datasource, context):
        # TODO log.debug
        log.debug('Starting AMQQueue params')
        params = {}
        params['objectName'] = context.objectName
        if hasattr(context, 'queueSize'):
            # First method based on property, but shouldn't update as quickly as the others
            # queueSize = context.queueSize()
            # Second method, based on getRRDValue, therefore reading the RRD file (slower, normally)
            # queueSize = context.getRRDValue('queue_queueSize', cf="LAST")
            # Third method, fetching the latest value from the cache, but it's not refreshing as fast as expected
            queueSize = context.cacheRRDValue('queue_queueSize')
            params['queueSize'] = queueSize
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting AMQQueue collect')

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)
        for datasource in config.datasources:
            object_name = datasource.params['objectName']
            url = self.urls[datasource.datasource].format(ip_address, datasource.zJolokiaPort, object_name)
            # log.debug('ActiveMQ Broker url: {}'.format(url))
            basic_auth = base64.encodestring('{}:{}'.format(datasource.zJolokiaUsername, datasource.zJolokiaPassword))
            auth_header = "Basic " + basic_auth.strip()
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

    # TODO: def onResult and check status within result, should be 200

    def onSuccess(self, result, config):
        log.debug('Success - result is {}'.format(result))

        data = self.new_data()
        ds_data = {}
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics
            else:
                data['events'].append({
                    'device': config.id,
                    'severity': 3,
                    'eventKey': 'AMQQueue',
                    'eventClassKey': 'AMQQueue',
                    'summary': 'AMQQueue - Collection failed',
                    'message': '{}'.format(ddata.value),
                    'eventClass': '/Status/Jolokia',
                })
                return data

        data['events'].append({
            'device': config.id,
            'severity': 0,
            'eventKey': 'AMQQueue',
            'eventClassKey': 'AMQQueue',
            'summary': 'AMQQueue - Collection OK',
            'message': '',
            'eventClass': '/Status/Jolokia',
        })

        for datasource in config.datasources:
            if 'queue' not in ds_data:
                continue
            component = prepId(datasource.component)
            values = ds_data['queue']['value']
            data['values'][component]['consumerCount'] = values['ConsumerCount']
            data['values'][component]['enqueueCount'] = values['EnqueueCount']
            data['values'][component]['dequeueCount'] = values['DequeueCount']
            data['values'][component]['expiredCount'] = values['ExpiredCount']
            data['values'][component]['averageMessageSize'] = values['AverageMessageSize']
            data['values'][component]['maxMessageSize'] = values['MaxMessageSize']

            queueSize = float(values['QueueSize'])
            if datasource.template == 'ActiveMQQueueDLQ':
                queueSize_prev = float(datasource.params.get('queueSize', queueSize))
                log.debug(
                    'DLQ QueueSize {}/{}: Size:{} - Prev:{}'.format(config.id, component, queueSize, queueSize_prev))
                queueSizeDelta = queueSize - queueSize_prev
                data['values'][component]['queueSizeDelta'] = queueSizeDelta
                if queueSizeDelta > 0:
                    data['events'].append({
                        'device': config.id,
                        'component': component,
                        'severity': 3,
                        'eventKey': 'AMQQueueDLQ_{}'.format(queueSize),
                        'eventClassKey': 'AMQQueueDLQ',
                        'summary': 'There is a new message in the DLQ {}'.format(component),
                        'message': 'There is a new message in the DLQ {}\r\nTotal number of messages: {}'.format(component, queueSize),
                        'eventClass': '/Status/ActiveMQ/DLQ',
                    })
            data['values'][component]['queueSize'] = queueSize

        log.debug('ActiveMQQueue onSuccess data: {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
