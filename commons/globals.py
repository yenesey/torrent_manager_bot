from transmission_rpc import Client as Transmission
from .torrserver_api import Torrserver
from .jackett_api import Jackett
import json

settings = json.load( open('settings.json') )

torrserver = Torrserver(**settings['torrserver'])
transmission = Transmission(**settings['transmission'])
jackett = Jackett(**settings['jackett'])