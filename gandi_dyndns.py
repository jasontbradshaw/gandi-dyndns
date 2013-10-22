#!/usr/bin/env python

import collections
import os
import random
import re
import time
import urllib2
import xmlrpclib

# matches all IPv4 addresses, including invalid ones. we look for
# multiple-provider agreement before returning an IP.
IP_ADDRESS_REGEX = re.compile('\d{1,3}(?:\.\d{1,3}){3}')

class GandiServerProxy(object):
  """
  Proxy calls to an internal xmlrpclib.ServerProxy instance, accounting for the
  quirks of the Gandi API format, namely dot-delimited method names. This allows
  calling the API using Python attribute accessors instead of strings, and
  allows for the API key to be pre-loaded into all method calls.
  """
  def __init__(self, api_key, proxy=None, chain=[], test=False):
    self.api_key = api_key
    self.chain = chain

    # create a new proxy if none was provided via chaining
    if proxy is None:
      # test and production environments use different URLs
      url = 'https://rpc.gandi.net/xmlrpc/'
      if test:
        url = 'https://rpc.ote.gandi.net/xmlrpc/'

      proxy = xmlrpclib.ServerProxy(url)

    self.proxy = proxy

  def __getattr__(self, method):
    # copy the chain with the new method added to the end
    new_chain = self.chain[:]
    new_chain.append(method)

    # return a new instance pre-loaded with the method chain so far
    return GandiServerProxy(self.api_key, self.proxy, chain=new_chain)

  def __call__(self, *args):
    """Call the chained XMLRPC method."""

    # build the method name and clear the chain
    method = '.'.join(self.chain)
    del self.chain[:]

    # prepend the API key to the method call
    key_args = (self.api_key,) + args

    # call the proxy's method with the modified arguments
    return getattr(self.proxy, method)(*key_args)

def get_external_ip(attempts=100, threshold=3):
  """Return our current external IP address, or None if there was an error."""

  # read the list of IP address providers, de-duping and normalizing them
  providers = []
  with open('ip-providers.txt') as f:
    providers = set(line.strip() for line in f)
    providers = filter(lambda x: not not x, providers)

  # we want several different providers to agree on the address, otherwise we
  # need to keep trying to get agreement. this prevents picking up 'addresses'
  # that are really just strings of four dot-delimited numbers.
  ip_counts = collections.Counter()

  # the providers we're round-robining from
  current_providers = []

  while attempts > 0:
    # reduce our attempt count every time, to ensure we'll exit eventually
    attempts -= 1

    # randomly shuffle the providers list when it's empty so we can round-robin
    # from all the providers. also reset the counts, since double-counting
    # results from the same providers might result in false-positives.
    if len(current_providers) == 0:
      current_providers = providers[:]
      random.shuffle(current_providers)
      ip_counts = collections.Counter()

    # get the provider we'll try this time
    provider = current_providers.pop()

    try:
      # open the website, download its data, and search for IP strings
      data = urllib2.urlopen(provider, timeout=10).read()
      addys = IP_ADDRESS_REGEX.findall(data)

      # add a single address to the counter randomly to help prevent false
      # positives. we don't add all the found addresses to guard against adding
      # multiple false positives for the same site. taking a single random
      # address and then checking it against the other sites is safer. what are
      # the chances that several sites will return the same false-positive
      # number?
      if len(addys) > 0:
        ip = random.choice(addys)
        ip_counts.update({ ip: 1 })

      # check for agreeing IP addresses, and return the first address that meets
      # or exceeds the count threshold.
      for ip, count in ip_counts.most_common():
        if count < threshold:
          break
        return ip

    except Exception, e:
      print 'error getting external IP address from %s:' % provider, e

      # sleep a bit after errors, in case it's a general network error. if it
      # is, hopefully this will give some time for the network to come back up.
      time.sleep(0.1 + random.random() * 2)

  # return None if no agreement could be reached
  return None

def main():
  """
  Check our external IP address and update Gandi's A-record to point to it if
  it has changed.
  """

  from pprint import pprint as pp

  # TODO: get the external IP address, since everything hinges on it
  # external_ip = get_external_ip()
  # print 'external IP address:', external_ip

  if 'APIKEY' not in os.environ:
    raise ValueError("'APIKEY' environment variable is required")

  api_key = os.environ['APIKEY']
  gandi = GandiServerProxy(api_key, test=False)

  print api.version.info()

if __name__ == '__main__':
  main()
