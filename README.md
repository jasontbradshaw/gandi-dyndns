gandi_dyndns
----

This implements a simple dynamic DNS updater for the
[Gandi](https://www.gandi.net) registrar. It uses their XML-RPC API to update
the zone file for a subdomain of a domain name to point at the external IPv4
address of the computer it has been run from.

It requires a server running a reasonably recent version of Python 2. It has
been tested on Ubuntu/Arch Linux using Python 2.7.

### Walkthrough
###### Last updated December 22nd, 2014.

Say you'd like to be able to access your home server externally at
`dynamic.example.com`.

#### API Key
First, you must apply for an API key with Gandi. Visit
https://www.gandi.net/admin/api_key and apply for (at least) the production API
key by following their directions. Once your request has been approved, you can
return to this page to retrieve the production API key.

#### A Record Setup
Then, you'll need to create a [DNS A
record](http://en.wikipedia.org/wiki/List_of_DNS_record_types) in the zone file
for your `example.com` domain. This is how you'll access your server over the
Internet at large!

1. Visit https://www.gandi.net/admin/domain and click on the `example.com`
   domain.
1. Click on "Edit the Zone" under "Zone files".
1. Click "Create a new version".
1. Click "Add".
1. Change the values to:

  | Field | Value
  | ----: | :----
  | Type  | A
  | TTL   | 5 minutes
  | Name  | dynamic
  | Value | 127.0.0.1

1. Click "Submit".
1. Click "Use this version".
1. Click "Submit".

#### Script Configuration
Then you'd need to configure the script.

1. Copy `config-example.json` to `config.json`, and put it in the same directory
   as the script.
1. Open it with a text editor, and change it to look like the following:

  ```json
  {
    "api_key": "yourtwentyfourcharapikey",
    "domain": "example.com",
    "names": ["dynamic"]
  }
  ```

  You can apply for/retrieve your production API key at
  https://www.gandi.net/admin/api_key.

  If you'd like to update more than one record with the external IP, simply add
  more values to the `names` list:

  ```json
    "names": ["dynamic", "@", "mail", "xmpp"]
  ```

1. Save and close the file.

#### Running the Script
You can run the script from the command line of an OSX/Unix system as described
in the [Use](#use) section. It will be useful to run this on a `cron` system of
some kind so that as long as the server is running, it will update its own IP
address (see:
http://code.tutsplus.com/tutorials/scheduling-tasks-with-cron-jobs--net-8800).
Running the script with the `test` parameter is also a good idea, so you can
ensure that good results come back from most of the providers.

#### Notes

The first time your A record is configured, it may take several hours
for the changes to propogate through the DNS system!

We set the A record's TTL to 5 minutes so that when the address is dynamically
updated by the script, that's the (hopefully) longest amount of time that would
pass before the DNS system caught up with the change. Setting this much lower
wouldn't be of much use, and could even cause DNS errors (see
http://www.zytrax.com/books/dns/info/minimum-ttl.html).

### Configuration

#### config.json
Config values for your Gandi account and domain/subdomain must be located in a
`config.json` file in the same directory as the script. `config-example.json`
contains an example configuration including all configurable options, and should
be used as a template for your personal `config.json`.

#### providers.json
The `providers.json` file contains a list of all providers that are queried for
an external IP address. The providers are always queried in a random order, and
several are queried each time the script is run in order to minimize the chance
of obtaining an invalid IP address as returned by a single provider. When the
results from several different providers concur, that address is used.

### Use
Simply running the script will cause it to update the IP address immediately.

```bash
./gandi_dyndns.py
```

To test all the providers and see what kind of results they return, you can run
the script with the `test` parameter:

```bash
./gandi_dyndns.py test
```

This will print out all the addressed received from each provider. Not every
provider may return a single, or even uniform/correct, IP address! This is
expected behavior, and the script waits for consensus around a given IP amongst
several providers before selecting it to be used.
