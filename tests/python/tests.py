import unittest
from dtcc_data import *


class TestFoo(unittest.TestCase):

    def test_add(self):
        assert 1 + 2 == 3


if __name__ == '__main__':
    unittest.main()
