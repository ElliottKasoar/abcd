from importlib import reload
from io import StringIO
import logging
import os
import unittest

from ase.atoms import Atoms
from ase.io import read
from openmock import openmock

from abcd import ABCD
from abcd.backends import atoms_opensearch
from abcd.backends.atoms_opensearch import AtomsModel


class OpenSearchMock(unittest.TestCase):
    """
    Testing mock OpenSearch database functions.
    """

    @classmethod
    @openmock
    def setUpClass(cls):
        """
        Set up database connection.
        """
        reload(atoms_opensearch)
        from abcd.backends.atoms_opensearch import OpenSearchDatabase

        if "port" in os.environ:
            cls.port = int(os.environ["port"])
        else:
            cls.port = 9200
        cls.host = "localhost"

        logging.basicConfig(level=logging.INFO)

        url = f"opensearch://admin:admin@{cls.host}:{cls.port}"
        abcd = ABCD.from_url(url, index_name="test_index", analyse_schema=False)
        assert isinstance(abcd, OpenSearchDatabase)
        cls.abcd = abcd

    @classmethod
    def tearDownClass(cls):
        """
        Delete index from database.
        """
        cls.abcd.destroy()

    def test_destroy(self):
        """
        Test destroying database index.
        """
        self.assertTrue(self.abcd.client.indices.exists("test_index"))
        self.abcd.destroy()
        self.assertFalse(self.abcd.client.indices.exists("test_index"))

    def test_create(self):
        """
        Test creating database index.
        """
        self.abcd.destroy()
        self.abcd.create()
        self.assertTrue(self.abcd.client.indices.exists("test_index"))
        self.assertFalse(self.abcd.client.indices.exists("fake_index"))

    def test_push(self):
        """
        Test pushing atoms objects to database individually.
        """
        self.abcd.destroy()
        self.abcd.create()
        xyz_1 = StringIO(
            """2
            Properties=species:S:1:pos:R:3 s="sadf" _vtk_test="t _ e s t" pbc="F F F"
            Si       0.00000000       0.00000000       0.00000000
            Si       0.00000000       0.00000000       0.00000000
            """
        )
        atoms_1 = read(xyz_1, format="extxyz")
        assert isinstance(atoms_1, Atoms)
        atoms_1.set_cell([1, 1, 1])
        self.abcd.push(atoms_1)

        xyz_2 = StringIO(
            """2
            Properties=species:S:1:pos:R:3 s="sadf" _vtk_test="t _ e s t" pbc="F F F"
            W       0.00000000       0.00000000       0.00000000
            W       0.00000000       0.00000000       0.00000000
            """
        )
        atoms_2 = read(xyz_2, format="extxyz")
        assert isinstance(atoms_2, Atoms)
        atoms_2.set_cell([1, 1, 1])

        result = AtomsModel(
            None,
            None,
            self.abcd.client.search(index="test_index")["hits"]["hits"][0]["_source"],
        ).to_ase()
        self.assertEqual(atoms_1, result)
        self.assertNotEqual(atoms_2, result)

    def test_bulk(self):
        """
        Test pushing atoms object to database together.
        """
        self.abcd.destroy()
        self.abcd.create()
        xyz_1 = StringIO(
            """2
            Properties=species:S:1:pos:R:3 s="sadf" _vtk_test="t _ e s t" pbc="F F F"
            Si       0.00000000       0.00000000       0.00000000
            Si       0.00000000       0.00000000       0.00000000
            """
        )
        atoms_1 = read(xyz_1, format="extxyz")
        assert isinstance(atoms_1, Atoms)
        atoms_1.set_cell([1, 1, 1])

        xyz_2 = StringIO(
            """1
            Properties=species:S:1:pos:R:3 s="sadf" _vtk_test="t _ e s t" pbc="F F F"
            Si       0.00000000       0.00000000       0.00000000
            """
        )
        atoms_2 = read(xyz_2, format="extxyz")
        assert isinstance(atoms_2, Atoms)
        atoms_2.set_cell([1, 1, 1])

        atoms_list = []
        atoms_list.append(atoms_1)
        atoms_list.append(atoms_2)
        self.abcd.push(atoms_list)
        self.assertEqual(self.abcd.count(), 2)

        result_1 = AtomsModel(
            None,
            None,
            self.abcd.client.search(index="test_index")["hits"]["hits"][0]["_source"],
        ).to_ase()
        result_2 = AtomsModel(
            None,
            None,
            self.abcd.client.search(index="test_index")["hits"]["hits"][1]["_source"],
        ).to_ase()
        self.assertEqual(atoms_1, result_1)
        self.assertEqual(atoms_2, result_2)

    def test_count(self):
        """
        Test counting the number of documents in the database.
        """
        self.abcd.destroy()
        self.abcd.create()
        xyz = StringIO(
            """2
            Properties=species:S:1:pos:R:3 s="sadf" _vtk_test="t _ e s t" pbc="F F F"
            Si       0.00000000       0.00000000       0.00000000
            Si       0.00000000       0.00000000       0.00000000
            """
        )

        atoms = read(xyz, format="extxyz")
        assert isinstance(atoms, Atoms)
        atoms.set_cell([1, 1, 1])
        self.abcd.push(atoms)
        self.abcd.push(atoms)
        self.assertEqual(self.abcd.count(), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1, exit=False)