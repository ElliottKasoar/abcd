import types
import logging

from typing import Union, Iterable
from os import linesep
from datetime import datetime

from ase import Atoms
from ase.io import iread

import abcd.errors
from abcd.model import AbstractModel
from abcd.database import AbstractABCD
from abcd.parsers import extras

from pathlib import Path

from opensearchpy import OpenSearch, helpers, AuthenticationException, ConnectionTimeout

logger = logging.getLogger(__name__)

map_types = {
    bool: "bool",
    float: "float",
    int: "int",
    str: "str",
    datetime: "date",
    dict: "dict"
}


class AtomsModel(AbstractModel):
    def __init__(self, client=None, index_name=None, dict=None):
        super().__init__(dict)

        self._client = client
        self._index_name = index_name

    @classmethod
    def from_atoms(cls, client, index_name, atoms: Atoms, extra_info=None, store_calc=True):
        obj = super().from_atoms(atoms, extra_info, store_calc)
        obj._client = client
        obj._index_name = index_name
        return obj

    @property
    def _id(self):
        return self.get("_id", None)

    def save(self):
        if not self._id:
            body = {}
            body.update(self.data)
            body["derived"] = self.derived
            self._client.index(index=self._index_name, body=body)


class OpenSearchDatabase(AbstractABCD):
    """Wrapper to make database operations easy"""

    def __init__(
            self,
            host="localhost",
            port=9200,
            index_name="atoms",
            username="admin",
            password="admin",
            **kwargs):

        super().__init__()

        logger.info((host, port, index_name, username, password, kwargs))

        self.client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=(username, password),
            verify_certs=False,
            ca_certs=False,
            use_ssl=True,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
        )

        try:
            info = self.client.info()
            logger.info("DB info: {}".format(info))

        except AuthenticationException:
            raise abcd.errors.AuthenticationError()

        except ConnectionTimeout:
            raise abcd.errors.TimeoutError()

        self.index_name = index_name
        self.create()

    def info(self):
        host = self.client.transport.hosts[0]["host"]
        port = self.client.transport.hosts[0]["port"]

        self.client.indices.refresh(index=self.index_name)
        return {
            "host": host,
            "port": port,
            "index": self.index_name,
            "number of confs": self.client.count(index=self.index_name)["count"],
            "type": "opensearch"
        }

    def delete(self, query=None):
        # query = parser(query)
        if not query:
            query = {
                "match_all": {}
            }

        self.client.delete_by_query(
            index=self.index_name,
            body={
                "query": query,
            },
        )

    def destroy(self):
        self.client.indices.delete(index=self.index_name, ignore=404)

    def create(self):
        self.client.indices.create(index=self.index_name, ignore=400)

    def save_bulk(self, actions: Iterable):
        helpers.bulk(client=self.client, actions=actions, index=self.index_name)

    def push(self, atoms: Union[Atoms, Iterable], extra_info=None, store_calc=True):

        if extra_info and isinstance(extra_info, str):
            extra_info = extras.parser.parse(extra_info)

        # Could combine into single data.save, but keep separate for option of bulk insertion?
        if isinstance(atoms, Atoms):
            data = AtomsModel.from_atoms(self.client, self.index_name, atoms, extra_info=extra_info, store_calc=store_calc)
            data.save()

        elif isinstance(atoms, types.GeneratorType) or isinstance(atoms, list):

            actions = []
            for item in atoms:
                data = AtomsModel.from_atoms(self.client, self.index_name, item, extra_info=extra_info, store_calc=store_calc)
                actions.append(data.data)
                actions[-1]["derived"] = data.derived
            self.save_bulk(actions)

    def upload(self, file: Path, extra_infos=None, store_calc=True):

        if isinstance(file, str):
            file = Path(file)

        extra_info = {}
        if extra_infos:
            for info in extra_infos:
                extra_info.update(extras.parser.parse(info))

        extra_info["filename"] = str(file)

        data = iread(str(file))
        self.push(data, extra_info, store_calc=store_calc)

    def get_atoms(self, query=None):
        # query = parser(query)
        if not query:
            query = {
                "query": {
                    "match_all": {}
                }
            }

        for hit in helpers.scan(
            self.client,
            index=self.index_name,
            query=query,
        ):
            yield AtomsModel(None, None, hit["_source"]).to_ase()

    def count(self, query=None):
        # query = parser(query)
        logger.info("query; {}".format(query))

        if not query:
            query = {
                "match_all": {}
            }

        return self.client.count(index=self.index_name, body={"query": query})["count"]

    # Slow - use count_property where possible!
    def property(self, name, query=None):
        # query = parser(query)
        if not query:
            query = {
                "match_all": {}
            }

        body = {
            "query": query,
        }

        return [hit["_source"][format(name)] for hit in helpers.scan(
            self.client,
            index=self.index_name,
            query=body,
            stored_fields=format(name),
            _source=format(name),
        )]

    def count_property(self, name, query=None):
        # query = parser(query)
        if not query:
            query = {
                "match_all": {}
            }

        body = {
            "size" : 0,
            "query": query,
            "aggs": {
                format(name): {
                    "terms": {
                        "field": format(name),
                        "size": 10000, # Use composite for all results?
                    },
                },
            }
        }

        prop = {}

        for val in self.client.search(
            index=self.index_name,
            body=body,
        )["aggregations"][format(name)]["buckets"]:
            prop[val["key"]] = val["doc_count"]

        return prop

    def properties(self, query=None):
        # query = parser(query)
        if not query:
            query = {
                "match_all": {}
            }

        properties = {}

        for prop in self.client.indices.get_mapping(self.index_name)[self.index_name]["mappings"]["properties"].keys():

            body = {
                "size" : 0,
                "query": query,
                "aggs": {
                    "info_keys": {
                        "filter": {
                            "term": {
                                "derived.info_keys.keyword": prop
                            }
                        },
                    },
                    "derived_keys": {
                        "filter": {
                            "term": {
                                "derived.derived_keys.keyword": prop
                            }
                        },
                    },
                    "arrays_keys": {
                        "filter": {
                            "term": {
                                "derived.arrays_keys.keyword": prop
                            }
                        },
                    },
                }
            }

            res = self.client.search(
                index=self.index_name,
                body=body,
            )

            derived = ["info_keys", "derived_keys", "arrays_keys"]
            for label in derived:
                count = res["aggregations"][label]["doc_count"]
                if count > 0:
                    key = label.split("_")[0]
                    if key in properties:
                        properties[key].append(prop)
                    else:
                        properties[key] = [prop]

        return properties

    def get_type_of_property(self, prop, category):
        # TODO: Probably it would be nicer to store the type info in the database from the beginning.
        atoms = self.client.search(
            index=self.index_name,
            body = {
                "size" : 1,
                "query": {
                   "exists" : {
                        "field": prop
                    }
                }
            }
        )

        data = atoms["hits"]["hits"][0]["_source"][prop]

        if category == "arrays":
            if type(data[0]) == list:
                return "array({}, N x {})".format(map_types[type(data[0][0])], len(data[0]))
            else:
                return "vector({}, N)".format(map_types[type(data[0])])

        if type(data) == list:
            if type(data[0]) == list:
                if type(data[0][0]) == list:
                    return "list(list(...)"
                else:
                    return "array({})".format(map_types[type(data[0][0])])
            else:
                return "vector({})".format(map_types[type(data[0])])
        else:
            return "scalar({})".format(map_types[type(data)])

    def count_properties(self, query=None):
        # query = parser(query)
        if not query:
            query = {
                "match_all": {}
            }

        properties = {}

        try:
            keys = self.client.indices.get_mapping(self.index_name)[self.index_name]["mappings"]["properties"].keys()
        except KeyError:
            return properties

        for key in keys:

            body = {
                "size" : 0,
                "query": query,
                "aggs": {
                    "info_keys": {
                        "filter": {
                            "term": {
                                "derived.info_keys.keyword": key
                            }
                        },
                    },
                    "derived_keys": {
                        "filter": {
                            "term": {
                                "derived.derived_keys.keyword": key
                            }
                        },
                    },
                    "arrays_keys": {
                        "filter": {
                            "term": {
                                "derived.arrays_keys.keyword": key
                            }
                        },
                    },
                }
            }

            res = self.client.search(
                index=self.index_name,
                body=body,
            )

            derived = ["info_keys", "derived_keys", "arrays_keys"]
            for label in derived:
                count = res["aggregations"][label]["doc_count"]
                if count > 0:
                    properties[key] = {
                        "count": count,
                        "category": label.split("_")[0],
                        "dtype": self.get_type_of_property(key, label.split("_")[0])
                    }

        return properties

    def __repr__(self):
        host = self.client.transport.hosts[0]["host"]
        port = self.client.transport.hosts[0]["port"]

        return "{}(".format(self.__class__.__name__) + \
               "url={}:{}, ".format(host, port) + \
               "index={}) ".format(self.index_name)

    def _repr_html_(self):
        """Jupyter notebook representation"""
        return "<b>ABCD OpenSearch database</b>"

    def print_info(self):
        """shows basic information about the connected database"""

        out = linesep.join(["{:=^50}".format(" ABCD OpenSearch "),
                            "{:>10}: {}".format("type", "opensearch"),
                            linesep.join("{:>10}: {}".format(k, v) for k, v in self.info().items())])

        print(out)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


if __name__ == "__main__":
    db = OpenSearchDatabase(username="admin", password="admin")
    print(db.info())