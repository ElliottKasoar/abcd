import unittest
from tests.parsers import ParsingQueries, ParsingExtras
from tests.database import Mongo, OpenSearch
from tests.properties import PropertiesTests
from tests.opensearch import OpenSearch

import logging

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    unittest.main(verbosity=1, exit=False)
