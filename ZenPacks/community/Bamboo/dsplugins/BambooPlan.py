
# stdlib Imports
import base64
import json
import logging

from Products.ZenUtils.Utils import prepId
from ZenPacks.community.Bamboo.lib.utils import SkipCertifContextFactory

# Zenoss imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSourcePlugin

# Twisted Imports
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers

# Setup logging
log = logging.getLogger('zen.PythonBambooPlan')


class BambooPlan(PythonDataSourcePlugin):

    proxy_attributes = (
        'zBambooPort',
        'zBambooUsername',
        'zBambooPassword',
        'zBambooServerAlias',
    )

    # TODO: /status
    urls = {
        'bamboo_info': 'https://{}:{}/rest/api/latest/info',
        'bamboo_queue': 'https://{}:{}/rest/api/latest/queue',
    }

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id,
                                                     datasource.getCycleTime(context),
                                                     context.id,
                                                     'bambooPlan'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            'bambooPlan'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting BambooPlan params')
        log.debug('params is {}'.format(params))
        return params

    @inlineCallbacks
    def collect(self, config):
        log.debug('Starting Bamboo collect')

        ds0 = config.datasources[0]
        if not ds0.zBambooServerAlias:
            log.error("%s: zBambooServerAlias cannot be empty", device.id)
            returnValue(None)

        basic_auth = base64.encodestring('{}:{}'.format(ds0.zBambooUsername, ds0.zBambooPassword))
        auth_header = "Basic " + basic_auth.strip()
        headers = {
                      "Accept": ["application/json"],
                      "Authorization": [auth_header],
                      "User-Agent": ["Mozilla/3.0Gold"],
                  }
        base_url = 'https://{}:{}/rest/api/latest/result/{}/?expand=results.result'
        results = {}
        agent = Agent(reactor, contextFactory=SkipCertifContextFactory())
        for datasource in config.datasources:
            url = base_url.format(datasource.zBambooServerAlias, datasource.zBambooPort)
            try:
                response = yield agent.request('GET', url, Headers(headers))
                response_body = yield readBody(response)
                response_body = json.loads(response_body)
                results[datasource.datasource] = response_body

            except Exception as e:
                log.exception('{}: failed to get server data for {}'.format(config.id, ds0))
                log.exception('{}: Exception: {}'.format(config.id, e))
        returnValue(results)

    def onSuccess(self, result, config):
        log.debug('Success - result is {}'.format(result))

        # TODO: Move following block under next loop, in case of multiple brokers
        data = self.new_data()
        broker_name = config.datasources[0].component
        component = prepId(broker_name)
        ds_data = {}
        # TODO: fill in data in a single loop, instead of 2 loops

        # Generate metrics data per datasource
        if 'bamboo_info' in result:
            info_data = result['bamboo_info']
            if info_data['state'] == 'RUNNING':
                value = 0
                msg = '{} - Status is OK'.format(component)
            else:
                value = 5
                msg = '{} - Status is {}'.format(component, ds_data[datasource.datasource]['state'])

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
        if 'bamboo_queue' in result:
            data['values'][component]['build_queue_length'] = result['bamboo_queue']['queuedBuilds']['size']

        log.debug('BambooServer onSuccess data: {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
