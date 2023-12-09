import requests
from commons.utils import timestamp
import logging

class Jackett():

    def __init__(self, host, port, api_key) -> None:
        self.api_key = api_key
        self.url = 'http://' + host + ':' + str(port) + '/api/v2.0/'

    def get_valid_indexers(self):
        response = requests.get(self.url + 'indexers?_=' + timestamp())
        if response.status_code != 200: return []
        return [indexer for indexer in response.json() if indexer['configured'] and indexer['last_error'] == '']

    def query(self, query_string : str, trackers : list) -> list:
        params = {
            'apikey': self.api_key,
            'Query' : query_string, 
            '_' : timestamp()
        }
        if len(trackers) > 0:
            params['Tracker[]'] = trackers
                                            #indexers/<filter>/results  ||| 'indexers/all/results'
        response = requests.get(self.url + 'indexers/status:healthy,test:passed/results', params)
        if response.status_code != 200: return []

        results = response.json()['Results']
        return results