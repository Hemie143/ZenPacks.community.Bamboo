# stdlib Imports
import base64
import json
import time

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

        # https://bamboo.fednot.be/rest/api/latest/plan/?expand=plans.plan

        # Projects, Plans
        urls = {
            'projects': 'https://{}:{}/rest/api/latest/project?max-result={}&start-index={}',
            'plans': 'https://{}:{}/rest/api/latest/plan/?expand=plans.plan&max-result={}&start-index={}',
        }

        limit = 25
        # base_url = 'https://{}:{}/rest/api/latest/project?max-result={}&start-index={}&expand=projects.project'
        for item, base_url in urls.items():
            data = []
            offset = 0
            item_single = item[:-1]
            while True:
                url = base_url.format(serverAlias, port, limit, offset)
                log.debug('collect url: {}'.format(url))
                response = yield agent.request('GET', url, Headers(headers))
                response_body = yield readBody(response)
                response_body = json.loads(response_body)
                data.extend(response_body[item][item_single])
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
                rm.append(self.model_projects(results['projects'], log))
                project_keys = [p['key'] for p in results['projects']]
                if 'plans' in results:
                    rm.extend(self.model_plans(results['plans'], project_keys, log))
        # log.debug('{}: process maps:{}'.format(device.id, rm))
        return rm

    def model_bamboo(self, data, log):
        om_bamboo = ObjectMap()
        om_bamboo.id = 'bamboo'
        om_bamboo.title = 'Bamboo {}'.format(data['version'])
        return RelationshipMap(relname='bambooServers',
                               modname='ZenPacks.community.Bamboo.BambooServer',
                               compname='',
                               objmaps=[om_bamboo])

    def model_projects(self, projects, log):
        project_maps = []
        for project in projects:
            om_project = ObjectMap()
            project_name = project['name']
            project_key = project['key']
            om_project.id = self.prepId(project_key)
            om_project.title = '{} ({})'.format(project_name, project_key)
            om_project.key = project_key
            om_project.desc = project.get('description', '')
            plans = project.get('plans', {})
            # log.debug('Project {} : Plans : {}'.format(project_name, plans['size']))
            project_maps.append(om_project)
        return RelationshipMap(compname='bambooServers/bamboo',
                               relname='bambooProjects',
                               modname='ZenPacks.community.Bamboo.BambooProject',
                               objmaps=project_maps,
                               )

    def model_plans(self, plans, project_keys, log):
        log.debug('Plans: {}'.format(len(plans)))
        log.debug('Plan: {}'.format(plans[0]))
        log.debug('project_keys: {}'.format(project_keys))
        rm = []
        start_time = time.time()
        for project_key in project_keys:
            compname = 'bambooServers/bamboo/bambooProjects/{}'.format(project_key)
            plan_maps = []
            plans_del = []
            project_plans = []
            # This method is faster than using a comprehension list and not editing the plans list.
            for i, plan in enumerate(plans):
                if plan['projectKey'] == project_key:
                    project_plans.append(plan)
                    plans_del.append(i)
            for i in sorted(plans_del, reverse=True):
                plans.pop(i)
            for plan in project_plans:
                om_plan = ObjectMap()
                plan_key = plan['key']
                plan_name = plan['name']
                om_plan.id = self.prepId(plan_key)
                om_plan.title = '{} ({})'.format(plan_name, plan_key)
                om_plan.enabled = plan['enabled']
                om_plan.type = plan['type']
                plan_maps.append(om_plan)
            rm.append(RelationshipMap(compname=compname,
                                      relname='bambooPlans',
                                      modname='ZenPacks.community.Bamboo.BambooPlan',
                                      objmaps=plan_maps,
                                      ))

        log.debug('timing: {}'.format(time.time() - start_time))
        log.debug('model_plans rm: {}'.format(len(rm)))
        return rm
