#!/usr/bin/env python2

import collections
import json
import random
import re
import time
import urllib2
import xmlrpclib

import logging as log
log.basicConfig(format='%(asctime)-15s [%(levelname)s] %(message)s', level=log.DEBUG)

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

def get_external_ip_from_url(url):
  '''Get all the IP addresses found at a given URL.'''

  # open the website, download its data, and return all IP strings found
  # we want to respect some site's filtering on User-Agent.
  data = urllib2.urlopen(url, timeout=10).read()
  addys = IP_ADDRESS_REGEX.findall(data)
  return addys

def get_external_ip(attempts=100, threshold=3):
  '''Return our current external IP address, or None if there was an error.'''

  # load the list of IP address providers
  providers = load_providers()

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
    if not current_providers:
      current_providers = providers[:]
      random.shuffle(current_providers)
      ip_counts = collections.Counter()

    # get the provider we'll try this time
    provider = current_providers.pop()

    try:
      addys = get_external_ip_from_url(provider)

      # add a single address to the counter randomly to help prevent false
      # positives. we don't add all the found addresses to guard against adding
      # multiple false positives for the same site. taking a single random
      # address and then checking it against the other sites is safer. what are
      # the chances that several sites will return the same false-positive
      # number?
      if addys:
        ip = random.choice(addys)
        ip_counts.update({ ip: 1 })
        log.debug('Got IP from provider %s: %s', provider, ip)

      # check for agreeing IP addresses, and return the first address that meets
      # or exceeds the count threshold.
      for ip, count in ip_counts.most_common():
        if count < threshold:
          break
        return ip

    except Exception as e:
      log.warning('Error getting external IP address from %s: %s', provider, e)

      # sleep a bit after errors, in case it's a general network error. if it
      # is, hopefully this will give some time for the network to come back up.
      time.sleep(0.1 + random.random() * 2)

  log.warning('Failed to get an external IP address after %d attempts!', attempts)

  # return None if no agreement could be reached
  return None

def load_providers():
  '''Load the providers file as a de-duplicated and normalized list of URLs.'''
  with open('providers.json') as f:
    providers = json.load(f)['providers']
  return list(set([p.strip() for p in providers]))

def load_config():
  '''Load the config file from disk.'''
  with open('config.json') as f:
    return json.load(f)

def is_valid_dynamic_record(name, record):
  '''Return True if the record matched the given name and is an A record.'''
  return record['name'] == name and record['type'].lower() == 'a'

def check_config(conf):
  '''
  Alert the user that they're using invalid config options, such as when
  breaking changes to the config are made.
  '''

  if 'name' in conf:
    log.fatal("Parameter 'name' is now named 'names' and is an array.")
    return False

  return True

def test_providers():
  '''Test all IP providers and log the IPs they return.'''

  for provider in load_providers():
    log.debug('IPs found at %s:', provider)

    try:
      for ip in get_external_ip_from_url(provider):
        log.debug('  %s', ip)
    except Exception as e:
      log.warning('Error getting external IP address from %s: %s', provider, e)

def update_ip():
  '''
  Check our external IP address and update Gandi's A-record to point to it if
  it has changed.
  '''

  # load the config file so we can get our variables
  log.debug('Loading config file...')
  config = load_config()
  if not check_config(config):
    sys.exit(2)
  log.debug('Config file loaded.')

  # create a connection to the Gandi production API
  gandi = GandiServerProxy(config['api_key'])

  # get the current zone id for the configured domain
  log.debug("Getting domain info for domain '%s'...", config['domain'])
  domain_info = gandi.domain.info(config['domain'])
  zone_id = domain_info['zone_id']
  log.debug('Got domain info.')

  # get the list of records for the domain's current zone
  log.debug('Getting zone records for live zone version...')
  zone_records = gandi.domain.zone.record.list(zone_id, 0)
  log.debug('Got zone records.')

  # see if the record's IP differs from ours
  log.debug('Getting external IP...')
  external_ip = get_external_ip()

  log.debug('External IP is: %s', external_ip)

  # make sure we actually got the external IP
  if external_ip is None:
    log.fatal('Could not get external IP.')
    sys.exit(2)

  updates = []
  for rec in config['names']:
    rec = rec.strip()

    # find the configured record, or None if there's not a valid one
    log.debug("Searching for dynamic record '%s'...", rec)
    dynamic_record = None
    for record in zone_records:
      if is_valid_dynamic_record(rec, record):
        dynamic_record = record
        break

    # fail if we found no valid record to update
    if dynamic_record is None:
      log.error('No record found - there must be an A record with a matching name.')
      continue

    log.debug('  Dynamic record found.')

    # extract the current live IP
    record_ip = dynamic_record['value'].strip()
    log.debug('  Current dynamic record IP is: %s', record_ip)

    # compare the IPs, and exit if they match
    if external_ip == record_ip:
      log.debug('  External IP matches current dynamic record IP, no update necessary.')
      continue

    log.debug('  External IP differs from current dynamic record IP!')
    updates.append(rec)

  if not updates:
    log.info('External IP matches current dynamic records IPs, no update necessary.')
    sys.exit(0)

  # clone the active zone version so we can modify it
  log.info('Cloning current zone version...')
  new_version_id = gandi.domain.zone.version.new(zone_id)
  log.info('Current zone version cloned.')

  log.info('Getting cloned zone records...')
  new_zone_records = gandi.domain.zone.record.list(zone_id, new_version_id)
  log.info('Cloned zone records retrieved.')

  errors = 0
  for rec in updates:
    # find the configured record, or None if there's not a valid one
    log.debug('Locating dynamic record in cloned zone version...')
    new_dynamic_record = None
    for record in new_zone_records:
      if is_valid_dynamic_record(rec, record):
        new_dynamic_record = record
        break

    # fail if we couldn't find the dynamic record again (this shouldn't happen...)
    if new_dynamic_record is None:
      log.error('Could not find dynamic record in cloned zone version!')
      errors += 1
      continue

    log.debug('Cloned dynamic record found.')

    # update the new version's dynamic record value (i.e. its IP address)
    log.debug('Updating dynamic record with current external IP...')
    updated_records = gandi.domain.zone.record.update(zone_id, new_version_id, {
      'id': new_dynamic_record['id']
    }, {
      'name': new_dynamic_record['name'],
      'type': new_dynamic_record['type'],
      'value': external_ip
    })

    # ensure that we successfully set the new dynamic record
    if (not updated_records or
        'value' not in updated_records[0] or
        updated_records[0]['value'] != external_ip):
      log.fatal('Failed to successfully update dynamic record!')
      errors += 1
      continue

    log.info('Dynamic record updated.')

  if errors:
    log.info('Errors during processing, zone NOT UPDATED.')
    sys.exit(1)

  # set the new zone version as the active version
  log.info('Updating active zone version...')
  gandi.domain.zone.version.set(zone_id, new_version_id)

  log.info('Set zone %d as the active zone version.', new_version_id)
  log.info('Dynamic record successfully updated to %s!', external_ip)

def main(args):
  # test all providers if specified, otherwise update the IP
  if args[-1] == 'test':
    test_providers()
  else:
    update_ip()

if __name__ == '__main__':
  import sys
  main(sys.argv)
