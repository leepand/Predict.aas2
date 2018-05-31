import falcon
import json
import sys
import logging

class DelWorkersResource(object):
    """
    To del Model to Workers info
    """
    def __init__(self, load_balancer):
        self.load_balancer = load_balancer
        self.logger = logging.getLogger(__name__)

    def on_put(self, req, resp):
        """
        Method to update model to workers map
        :param req:
        :param resp:
        :return:
        """
        model_to_workers_dels = json.loads(req.stream.read())
        self.logger.debug('Update request received with payload: %s', str(model_to_workers_dels))
        self.load_balancer.remove_workers(model_to_workers_dels)
        #model_type=model_to_workers_map['model_type']
        
        resp.status = falcon.HTTP_200
        #resp.content=json.dumps({"reg info":"sucess"})
        resp.body = json.dumps({"Remove Model Service": "Success"})
