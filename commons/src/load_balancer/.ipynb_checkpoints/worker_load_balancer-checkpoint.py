# -*- coding:utf-8 -*-
# Copyright 2017-2018, the original author or authors.

# Licensed under the Apache License, Version 2.0 (the "License");
# You may not use this file except in compliance
# with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.
#
import logging
import random
import json
import yaml

from commons.src.config import config_loader
from commons.src.load_balancer.worker_info import WorkerInfo
from random import randint

from KeepAlive.redis_utils import get_redis_conn,dict_to_redis_hset
import requests
import redis




class AIinfoLoadError(Exception):
    pass

def worklist2worker(adict):
    """
    for a key:[value(s)] dict, return value:[key(s)],
    e.g. dict[doc] = [terms] --> dict[term] = [docs]
    """
    inv_dict = {}
    out_dict = {}
    tmp_dict={}
    [inv_dict.setdefault(v, []).append(k) for k, vlist in adict.items() for v in vlist]
    for k,v in inv_dict.items():
        tmp={}
        host=k.split('-')[0]
        port= k.split('-')[1]
        local_id=k.split('-')[2]
        tmp['local_worker_id']=int(local_id)
        tmp['host']=str(host)
        tmp['port']=int(port)
        tmp['global_worker_id']=str(k)
        tmp_dict[str(k)]=tmp
    
    out_dict = tmp_dict 
    return out_dict


class UserEncoder(json.JSONEncoder):  
    def default(self, obj):  
        if isinstance(obj, WorkerInfo):  
            return {'host':obj.host,'port':obj.port,'local_worker_id':obj.local_worker_id,'global_worker_id':obj.global_worker_id}
        return json.JSONEncoder.default(self, obj)
def worker_info2dict(obj):
    return {'host':obj.host,'port':obj.port,'local_worker_id':obj.local_worker_id,'global_worker_id':obj.global_worker_id}
class WorkerLoadBalancer:
    """
    A generic worker load balancer which helps in choosing a worker randomly.
    """

    def __init__(self):
        """
            Constructor
            Returns: None
        """

        """dict model type to model to worker list map."""
        self.model_type_to_model_to_worker_list = {}
        """dict model type to worker id to worker info map."""
        self.model_type_to_worker_id_to_worker = {}
        """dict Model type to model to workers map."""
        self.model_type_to_model_to_workers_map ={}
        """Request counts."""
        self.model_id_request_count={}
        self.worker_request_count={}
        """Logger instance."""
        self.logger = logging.getLogger(__name__)
        self.conn=get_redis_conn()

    def update_workers_list(self, model_to_workers_map):
        """
        Updates model to workers list map
        param model_to_workers_map:
        Input
            - 模型类型
            - 模型ID
            - 服务信息(List)：host/port/local_worker_id 
            - {'CTR':[{'host':127.0.0.1,port:90,'local_worker_id': 2},
            {'host': 'localhost', 'port': 9019, 'local_worker_id': 2}]}
        Return:
        """
        db_id=[]
        if model_to_workers_map:
            """model_id：区分具体模型集群"""
            model_to_worker_list = {}
            worker_id_to_worker = {}
            for model_id in model_to_workers_map.keys():                       
                """遍历输入信息取出服务信息list"""
                if model_id in self.conn.hgetall('model_to_worker_list'):
                    db_id=json.loads(self.conn.hgetall('model_to_worker_list')[model_id])
                for worker in model_to_workers_map[model_id]:
                    worker_info = WorkerInfo(worker["host"], worker["port"], worker["local_worker_id"])
                    worker_id=worker_info.global_worker_id
                    """解析服务信息至dict"""
                    worker_id_to_worker[worker_id] = json.dumps(worker_info2dict(worker_info))
                    """解析global-id信息至list"""
                    if len(db_id)>0:
                        if worker_id not in db_id:
                            db_id.append(worker_id)
                    else:
                        db_id.append(worker_id)
                model_to_worker_list[model_id]=json.dumps(db_id)
        """update:更新model_to_worker_list、worker_id_to_worker至redis"""
        dict_to_redis_hset(self.conn, 'model_to_worker_list', model_to_worker_list)
        dict_to_redis_hset(self.conn, 'worker_id_to_worker', worker_id_to_worker)


    def remove_workers(self, model_to_workers_dels):
        """
         Used to remove workers to a model
         :param model_id:
         :param workers:
         :return: None
         """
        model_id=model_to_workers_dels['model_id']
        worker_ids=model_to_workers_dels['worker_ids']
        all_id=model_to_workers_dels['all_id']
        if all_id:
            alllist=self.conn.hgetall('model_to_worker_list')
            if model_id in alllist:
                self.conn.hdel('model_to_worker_list',model_id)
                for worker_id in json.loads(alllist[model_id]):
                    self.conn.hdel('worker_id_to_worker',worker_id)
        else:
            oldlist=self.conn.hgetall('model_to_worker_list')[model_id]
            newlist=[]
            newdict={}
            """del worker from worker dict"""
            for worker_id in worker_ids:   
                self.conn.hdel('worker_id_to_worker',worker_id)
            """del worker from worker list"""
            for worker in json.loads(oldlist):
                if worker not in worker_ids:
                    newlist.append(worker)
            newdict[model_id]=json.dumps(newlist)
            dict_to_redis_hset(self.conn, 'model_to_worker_list', newdict)
            

    def choose_worker(self, model_id):
        """
        Picks a worker(random) from available workers

        :param model_type
        :param model_id:
        :return: a randomly chosen worker
        """
        if model_id in self.conn.hgetall('model_to_worker_list').keys():
            worker_id_list = json.loads(self.conn.hgetall('model_to_worker_list')[model_id])
            #keep alive by leepand
            worker_id=random.choice(worker_id_list)
            #keepa alive  end by leepand
            #count requests by leepand
            model_id_request_count=self.conn.hgetall('model_id_request_count')
            
            if model_id in model_id_request_count:
                worker_request_count=json.loads(model_id_request_count[model_id])
                if worker_id in worker_request_count:
                    worker_request_count[worker_id]+=1
                else:
                    worker_request_count[worker_id]=1
            else:
                worker_request_count[worker_id]=1
            model_id_request_count[model_id]=json.dumps(worker_request_count)
            #end compute count by leepand
            dict_to_redis_hset(self.conn, 'model_id_request_count', model_id_request_count)
            return  json.loads(self.conn.hgetall('worker_id_to_worker')[worker_id])
        else:
            raise Exception("No worker available for the given model! ")

    def get_all_workers(self):
        """
        Returns all the workers available for the given model type
        Args:
            model_type: Type of the model

        Returns: all the workers available for the given model type

        """
        #return self.model_type_to_worker_id_to_worker.get(model_type)
        try:
            return self.conn.hgetall('worker_id_to_worker')
        except:
            return {'success':False,'message':'The specified model/version doesn\'t exist!'}

    def get_model_to_workers_list(self):
        """
        Returns the list of workers for a given model_id
        Args:
            model_type: Type of the model
        Returns: List of workers for the given model type

        """
        return self.conn.hgetall('model_to_worker_list')


    def get_worker_info(self, worker_id):
        """
        Returns worker information of a given worker
        Args:
            worker_id: Global worker id
            model_type: Type of the model

        Returns: Worker information of the given worker

        """
        if self.conn.hgetall('worker_id_to_worker'):
            return self.conn.hgetall('worker_id_to_worker').get(worker_id)
        else:
            return None

    def check_if_model_to_workers_map_is_empty(self):
        """
        Checks if model to workers map is empty
        Returns: False if model to workers map is empty else True

        """
        #return False if self.model_type_to_model_to_worker_list else True
        return False if self.conn.hgetall('model_to_worker_list') else True
    


