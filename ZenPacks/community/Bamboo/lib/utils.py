from twisted.internet import ssl
from twisted.web.client import BrowserLikePolicyForHTTPS
from twisted.web.iweb import IPolicyForHTTPS
from zope.interface import implementer


@implementer(IPolicyForHTTPS)
class SkipCertifContextFactory(object):
    def __init__(self):
        self.default_policy = BrowserLikePolicyForHTTPS()

    def creatorForNetloc(self, hostname, port):
        return ssl.CertificateOptions(verify=False)
