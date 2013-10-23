#!/usr/bin/env python

import collections
import json
import random
import re
import time
import urllib2
import xmlrpclib

# matches all IPv4 addresses, including invalid ones. we look for
# multiple-provider agreement before returning an IP.
IP_ADDRESS_REGEX = re.compile('\d{1,3}(?:\.\d{1,3}){3}')

class GandiServerProxy(object):
  '''
  Proxy calls to an internal xmlrpclib.ServerProxy instance, accounting for the
  quirks of the Gandi API format, namely dot-delimited method names. This allows
  calling the API using Python attribute accessors instead of strings, and
  allows for the API key to be pre-loaded into all method calls.
  '''
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
    '''Call the chained XMLRPC method.'''

    # build the method name and clear the chain
    method = '.'.join(self.chain)
    del self.chain[:]

    # prepend the API key to the method call
    key_args = (self.api_key,) + args

    # call the proxy's method with the modified arguments
    return getattr(self.proxy, method)(*key_args)

def get_external_ip(attempts=100, threshold=3):
  '''Return our current external IP address, or None if there was an error.'''

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

def load_config():
  '''Load the config file from disk'''
  with open('config.json') as f:
    return json.load(f)

def is_valid_dynamic_record(name, record):
  '''Return True if the record matched the given name and is an A record.'''
  return record['name'] == name and record['type'].lower() == 'a'

def main():
  '''
  Check our external IP address and update Gandi's A-record to point to it if
  it has changed.
  '''

  import sys
  from pprint import pprint as pp

  # TODO: get the external IP address, since everything hinges on it
  # external_ip = get_external_ip()
  # print 'external IP address:', external_ip

  # load the config file so we can get our variables
  print 'loading config file'
  config = load_config()

  # create a connection to the Gandi production API
  gandi = GandiServerProxy(config['api_key'])

  # get the current zone id for the configured domain
  print "getting domain info for domain '%s'" % config['domain']
  domain_info = gandi.domain.info(config['domain'])
  zone_id = domain_info['zone_id']

  # get the list of records for the domain's current zone
  print 'getting zone records for live zone version'
  zone_records = gandi.domain.zone.record.list(zone_id, 0)

  # find the configured record, or None if there's not a valid one
  print "searching for dynamic record '%s'" % config['name']
  dynamic_record = None
  for record in zone_records:
    if is_valid_dynamic_record(config['name'], record):
      dynamic_record = record
      break

  # fail if we found no valid record to update
  if dynamic_record is None:
    print 'no matching record found - must be an A record with a matching name'
    sys.exit(1)

  print 'dynamic record found'

  # see if the record's IP differs from ours
  print 'getting external IP'
  external_ip = get_external_ip()

  # make sure we actually got the external IP
  if external_ip is None:
    print 'could not get external IP'
    sys.exit(2)

  print 'external IP is %s' % external_ip

  # compare the IPs, and exit if they match
  if external_ip == dynamic_record['value'].strip():
    print 'external IP %s matches current IP, no update necessary' % external_ip
    sys.exit(0)

  # clone the active zone version so we can modify it
  print 'cloning current zone version'
  new_version_id = gandi.domain.zone.version.new(zone_id)
  new_zone_records = gandi.domain.zone.record.list(zone_id, new_version_id)

  # find the configured record, or None if there's not a valid one
  print 'locating dynamic record in new version'
  new_dynamic_record = None
  for record in new_zone_records:
    if is_valid_dynamic_record(config['name'], record):
      new_dynamic_record = record
      break

  # fail if we couldn't find the dynamic record again (this shouldn't happen...)
  if new_dynamic_record is None:
    print 'could not find dynamic record in new zone version!'
    sys.exit(3)

  # update the new version's dynamic record value (i.e. its IP address)
  print 'updating dynamic record with new external IP %s' % external_ip
  updated_records = gandi.domain.zone.record.update(zone_id, new_version_id, {
    'id': new_dynamic_record['id']
  }, {
    'name': new_dynamic_record['name'],
    'type': new_dynamic_record['type'],
    'value': external_ip
  })

  # ensure that we successfully set the new dynamic record
  if (len(updated_records) <= 0 or
      'value' not in updated_records[0] or
      updated_records[0]['value'] != external_ip):
    print 'failed to successfully update dynamic record'
    sys.exit(4)

  # set the new zone version as the active version
  print 'setting updated zone version as the active version'
  gandi.domain.zone.version.set(zone_id, new_version_id)

  print 'set zone %d as active zone version' % new_version_id

if __name__ == '__main__':
  main()
