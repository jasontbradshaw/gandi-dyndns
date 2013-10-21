#!/usr/bin/env python

import collections
import os
import random
import re
import urllib2
import xmlrpclib

# matches all IPv4 addresses, including invalid ones. we look for
# multiple-provider agreement before returning an IP.
IP_ADDRESS_REGEX = re.compile('\d{1,3}(?:\.\d{1,3}){3}')

def get_external_ip(attempts=100, threshold=3):
  """Return our current external IP address, or None if there was an error."""

  # read the list of IP address providers, de-duping and normalizing them
  providers = []
  with open('ip-providers.txt') as f:
    providers = set(line.strip() for line in f)
    providers = filter(lambda x: not not x, providers)

  # we want different providers to agree on the address, otherwise we need to
  # keep trying to get agreement. this prevents picking up 'addresses' that are
  # really just strings of four dot-delimited numbers
  ip_counts = collections.Counter()

  # the providers we're round-robining from
  current_providers = []

  while attempts > 0:
    # reduce our attempt count every time, to ensure we'll exit eventually
    attempts -= 1

    # randomly shuffle the providers list when it's empty so we can round-robin
    # from all the providers.
    if len(current_providers) == 0:
      current_providers = providers[:]
      random.shuffle(current_providers)

    # get the provider we'll try this time
    provider = current_providers.pop()

    try:
      # open the website, download its data, and search for IP strings
      data = urllib2.urlopen(provider, timeout=10).read()
      addys = IP_ADDRESS_REGEX.findall(data)

      # add an address to the counter randomly to help prevent false positives
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

  # return None if no agreement could be reached
  return None

def get_gandi_xmlrpc(api_key):
  """
  Return an xmlrpclib.ServerProxy object for the Gandi account with the given
  API key.
  """

  return None

def main():
  """
  Check our external IP address and update Gandi's A-record to point to it if
  it has changed.
  """

  print get_external_ip()

if __name__ == '__main__':
  main()
