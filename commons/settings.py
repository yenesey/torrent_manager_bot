import json
settings = json.load( open('settings.json') )

def get_url(service_name):
    return settings[service_name]['host'] + ':' + str(settings[service_name]['port'])