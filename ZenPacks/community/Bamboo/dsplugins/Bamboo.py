
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
log = logging.getLogger('zen.PythonBambooServer')


class BambooServer(PythonDataSourcePlugin):

    proxy_attributes = (
        'zBambooPort',
        'zBambooUsername',
        'zBambooPassword',
        'zBambooServerAlias',
    )

    urls = {
        'bamboo_info': 'https://{}:{}/rest/api/latest/info',
        'bamboo_queue': 'https://{}:{}/rest/api/latest/queue',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                     context.id, 'bamboo'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            'bamboo'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting BambooServer params')
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting Bamboo collect')

        ds0 = config.datasources[0]
        if not ds0.zBambooServerAlias:
            log.error("%s: zBambooServerAlias cannot be empty", device.id)
            returnValue(None)

        basic_auth = base64.encodestring('{}:{}'.format(ds0.zBambooUsername, ds0.zBambooPassword))
        auth_header = "Basic " + basic_auth.strip()
        headers = {
                      "Accept": "application/json",
                      "Authorization": auth_header,
                      "User-Agent": "Mozilla/3.0Gold",
                  }

        deferreds = []
        sem = DeferredSemaphore(1)
        for datasource in config.datasources:
            url = self.urls[datasource.datasource].format(datasource.zBambooServerAlias, datasource.zBambooPort)
            # TODO: replace getPage (deprecated)
            d = sem.run(getPage, url, headers=headers)
            d.addCallback(self.add_tag, datasource.datasource)
            deferreds.append(d)
        return DeferredList(deferreds)

    def onSuccess(self, result, config):
        log.debug('Success - result is {}'.format(result))

        # TODO: Move following block under next loop, in case of multiple brokers
        data = self.new_data()
        broker_name = config.datasources[0].component
        ds_data = {}
        # TODO: fill in data in a single loop, instead of 2 loops

        # Check that all data has been received correctly
        if any([not s for s, d in result]):
            data['events'].append({
                'device': config.id,
                'component': broker_name,
                'severity': 3,
                'eventKey': 'Bamboo',
                'eventClassKey': 'Bamboo',
                'summary': 'Connection to Bamboo failed',
                'message': '{}'.format(d),
                'eventClass': '/Status/Bamboo',
            })
            return data

        # Collect metrics per datasource in ds_data. If failed, generate event
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics
            else:
                data['events'].append({
                    'device': config.id,
                    'component': broker_name,
                    'severity': 3,
                    'eventKey': 'Bamboo',
                    'eventClassKey': 'Bamboo',
                    'summary': 'Bamboo - Collection failed',
                    'message': '{}'.format(ddata.value),
                    'eventClass': '/Status/Bamboo',
                })

        # Broker data collection went fine
        data['events'].append({
            'device': config.id,
            'component': broker_name,
            'severity': 0,
            'eventKey': 'Bamboo',
            'eventClassKey': 'Bamboo',
            'summary': 'Bamboo - Collection OK',
            'message': '',
            'eventClass': '/Status/Bamboo',
        })

        # Generate metrics data per datasource
        for datasource in config.datasources:
            component = prepId(datasource.component)
            if datasource.datasource == 'bamboo_info':
                if ds_data[datasource.datasource]['state'] == 'RUNNING':
                    value = 0
                    msg = '{} - Status is OK'.format(component)
                else:
                    value = 5
                    msg = '{} - Status is OK'.format(ds_data[datasource.datasource]['state'])

                data['values'][component]['status'] = value
                data['events'].append({
                    'device': config.id,
                    'component': component,
                    'severity': value,
                    'eventKey': 'BambooState',
                    'eventClassKey': 'BambooState',
                    'summary': msg,
                    'message': msg,
                    'eventClass': '/Status/Bamboo',
                })
            elif datasource.datasource == 'bamboo_queue':
                value = ds_data[datasource.datasource]['queuedBuilds']['size']
                data['values'][component]['build_queue_length'] = value

        log.debug('BambooServer onSuccess data: {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
