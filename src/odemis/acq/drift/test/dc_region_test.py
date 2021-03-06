# -*- coding: utf-8 -*-
'''
Created on 15 Jan 2014

@author: kimon

Copyright © 2013-2014 Éric Piel & Kimon Tsitsikas, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the terms 
of the GNU General Public License version 2 as published by the Free Software 
Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; 
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR 
PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with 
Odemis. If not, see http://www.gnu.org/licenses/.
'''
import numpy
import unittest

from odemis.dataio import hdf5
from odemis.acq.drift import dc_region

# @unittest.skip("skip")
class TestGuessAnchorRegion(unittest.TestCase):
    """
    Test GuessAnchorRegion
    """
    # @unittest.skip("skip")
    def setUp(self):
        # Input
        self.data = hdf5.read_data("example_input.h5")
        C, T, Z, Y, X = self.data[0].shape
        self.data[0].shape = Y, X

    # @unittest.skip("skip")
    def test_identical_inputs(self):
        """
        Tests for known roi.
        """
        roi = dc_region.GuessAnchorRegion(self.data[0], (0, 0, 0.87, 0.95))
        numpy.testing.assert_equal(roi, (0.86923076923076925, 0.74281609195402298, 0.9653846153846154, 0.81465517241379315))

if __name__ == '__main__':
    unittest.main()


