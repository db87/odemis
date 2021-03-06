# -*- coding: utf-8 -*-
'''
Created on 19 Sep 2012

@author: piel

Copyright © 2012-2013 Éric Piel & Kimon Tsitsikas, Delmic

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
from __future__ import division

import logging
import numpy
from odemis import model
from odemis.util import img
import time
import unittest
from unittest.case import skip


logging.getLogger().setLevel(logging.DEBUG)


# @skip("faster")
class TestFindOptimalRange(unittest.TestCase):
    """
    Test findOptimalRange
    """

    def test_no_outliers(self):
        # just one value (middle)
        hist = numpy.zeros(256, dtype="int32")
        hist[128] = 4564
        irange = img.findOptimalRange(hist, (0, 255))
        self.assertEqual(irange, (128, 128))

        # first
        hist = numpy.zeros(256, dtype="int32")
        hist[0] = 4564
        irange = img.findOptimalRange(hist, (0, 255))
        self.assertEqual(irange, (0, 0))

        # last
        hist = numpy.zeros(256, dtype="int32")
        hist[255] = 4564
        irange = img.findOptimalRange(hist, (0, 255))
        self.assertEqual(irange, (255, 255))

        # first + last
        hist = numpy.zeros(256, dtype="int32")
        hist[0] = 456
        hist[255] = 4564
        irange = img.findOptimalRange(hist, (0, 255))
        self.assertEqual(irange, (0, 255))

        # average
        hist = numpy.zeros(256, dtype="int32") + 125
        irange = img.findOptimalRange(hist, (0, 255))
        self.assertEqual(irange, (0, 255))

    def test_with_outliers(self):
        # almost nothing, but more than 0
        hist = numpy.zeros(256, dtype="int32")
        hist[128] = 4564
        irange = img.findOptimalRange(hist, (0, 255), 1e-6)
        self.assertEqual(irange, (128, 128))

        # 1%
        hist = numpy.zeros(256, dtype="int32")
        hist[2] = 1
        hist[5] = 99
        hist[135] = 99
        hist[199] = 1

        irange = img.findOptimalRange(hist, (0, 255), 0.01)
        self.assertEqual(irange, (5, 135))

        # 5% -> same
        irange = img.findOptimalRange(hist, (0, 255), 0.05)
        self.assertEqual(irange, (5, 135))

        # 0.1 % -> include everything
        irange = img.findOptimalRange(hist, (0, 255), 0.001)
        self.assertEqual(irange, (2, 199))

    def test_speed(self):
        for depth in [16, 256, 4096]:
            # Check the shortcut when outliers = 0 is indeed faster
            hist = numpy.zeros(depth, dtype="int32")
            p1, p2 = depth // 2 - 4, depth // 2 + 3
            hist[p1] = 99
            hist[p2] = 99

            tstart = time.time()
            for i in range(10000):
                irange = img.findOptimalRange(hist, (0, depth - 1))
            dur_sc = time.time() - tstart
            self.assertEqual(irange, (p1, p2))

            # outliers is some small, it's same behaviour as with 0
            tstart = time.time()
            for i in range(10000):
                irange = img.findOptimalRange(hist, (0, depth - 1), 1e-6)
            dur_full = time.time() - tstart
            self.assertEqual(irange, (p1, p2))

            logging.info("shortcut took %g s, while full took %g s", dur_sc, dur_full)
            self.assertLessEqual(dur_sc, dur_full)


    def test_auto_vs_manual(self):
        """
        Checks that conversion with auto BC is the same as optimal BC + manual
        conversion.
        """
        size = (1024, 512)
        depth = 2 ** 12
        img12 = numpy.zeros(size, dtype="uint16") + depth // 2
        img12[0, 0] = depth - 1 - 240

        # automatic
        img_auto = img.DataArray2RGB(img12)

        # manual
        hist, edges = img.histogram(img12, (0, depth - 1))
        self.assertEqual(edges, (0, depth - 1))
        irange = img.findOptimalRange(hist, edges)
        img_manu = img.DataArray2RGB(img12, irange)

        numpy.testing.assert_equal(img_auto, img_manu)

        # second try
        img12 = numpy.zeros(size, dtype="uint16") + 4000
        img12[0, 0] = depth - 1 - 40
        img12[12, 12] = 50

        # automatic
        img_auto = img.DataArray2RGB(img12)

        # manual
        hist, edges = img.histogram(img12, (0, depth - 1))
        irange = img.findOptimalRange(hist, edges)
        img_manu = img.DataArray2RGB(img12, irange)

        numpy.testing.assert_equal(img_auto, img_manu)

    def test_uint32_small(self):
        """
        Test uint32, but with values very close from each other => the histogram
        will look like just one column not null. But we still want the image
        to display between 0->255 in RGB.
        """
        depth = 2 ** 32
        size = (512, 100)
        grey_img = numpy.zeros(size, dtype="uint32") + 3
        grey_img[0, :] = 0
        grey_img[:, 1] = 40
        hist, edges = img.histogram(grey_img)  # , (0, depth - 1))
        irange = img.findOptimalRange(hist, edges, 0)

        rgb = img.DataArray2RGB(grey_img, irange)

        self.assertEqual(rgb[0, 0].tolist(), [0, 0, 0])
        self.assertEqual(rgb[5, 1].tolist(), [255, 255, 255])
        self.assertTrue(0 < rgb[50, 50, 0] < 255)

class TestHistogram(unittest.TestCase):
    # 8 and 16 bit short-cuts test
    def test_uint8(self):
        # 8 bits
        depth = 256
        size = (1024, 512)
        grey_img = numpy.zeros(size, dtype="uint8") + depth // 2
        grey_img[0, 0] = 10
        grey_img[0, 1] = depth - 10
        hist, edges = img.histogram(grey_img, (0, depth - 1))
        self.assertEqual(len(hist), depth)
        self.assertEqual(edges, (0, depth - 1))
        self.assertEqual(hist[grey_img[0, 0]], 1)
        self.assertEqual(hist[grey_img[0, 1]], 1)
        self.assertEqual(hist[depth // 2], grey_img.size - 2)
        hist_auto, edges = img.histogram(grey_img)
        numpy.testing.assert_array_equal(hist, hist_auto)
        self.assertEqual(edges, (0, depth - 1))

    def test_uint16(self):
        # 16 bits
        depth = 4096 # limited depth
        size = (1024, 965)
        grey_img = numpy.zeros(size, dtype="uint16") + 1500
        grey_img[0, 0] = 0
        grey_img[0, 1] = depth - 1
        hist, edges = img.histogram(grey_img, (0, depth - 1))
        self.assertEqual(len(hist), depth)
        self.assertEqual(edges, (0, depth - 1))
        self.assertEqual(hist[0], 1)
        self.assertEqual(hist[-1], 1)
        u = numpy.unique(hist[1:-1])
        self.assertEqual(sorted(u.tolist()), [0, grey_img.size - 2])

        hist_auto, edges = img.histogram(grey_img)
        self.assertGreaterEqual(edges[1], depth - 1)
        numpy.testing.assert_array_equal(hist, hist_auto[:depth])

    def test_uint32(self):
        # 32 bits
        depth = 2 ** 32
        size = (512, 100)
        grey_img = numpy.zeros(size, dtype="uint32") + (depth // 3)
        grey_img[0, 0] = 0
        grey_img[0, 1] = depth - 1
        hist, edges = img.histogram(grey_img, (0, depth - 1))
        self.assertTrue(256 <= len(hist) <= depth)
        self.assertEqual(edges, (0, depth - 1))
        self.assertEqual(hist[0], 1)
        self.assertEqual(hist[-1], 1)
        u = numpy.unique(hist[1:-1])
        self.assertEqual(sorted(u.tolist()), [0, grey_img.size - 2])

        hist_auto, edges = img.histogram(grey_img)
        self.assertGreaterEqual(edges[1], depth - 1)
        numpy.testing.assert_array_equal(hist, hist_auto[:depth])

    def test_uint32_small(self):
        """
        Test uint32, but with values very close from each other => the histogram
        will look like just one column not null.
        """
        depth = 2 ** 32
        size = (512, 100)
        grey_img = numpy.zeros(size, dtype="uint32") + 3
        grey_img[0, 0] = 0
        grey_img[0, 1] = 40
        hist, edges = img.histogram(grey_img, (0, depth - 1))
        self.assertTrue(256 <= len(hist) <= depth)
        self.assertEqual(edges, (0, depth - 1))
        self.assertEqual(hist[0], grey_img.size)
        self.assertEqual(hist[-1], 0)

        # Only between 0 and next power above max data (40 -> 63)
        hist, edges = img.histogram(grey_img, (0, 63))
        self.assertTrue(len(hist) <= depth)
        self.assertEqual(edges, (0, 63))
        self.assertEqual(hist[0], 1)
        self.assertEqual(hist[40], 1)

        hist_auto, edges = img.histogram(grey_img)
        self.assertEqual(edges[1], grey_img.max())
        numpy.testing.assert_array_equal(hist[:len(hist_auto)], hist_auto[:len(hist)])

    def test_float(self):
        size = (102, 965)
        grey_img = numpy.zeros(size, dtype="float") + 15.05
        grey_img[0, 0] = -15.6
        grey_img[0, 1] = 500.6
        hist, edges = img.histogram(grey_img)
        self.assertGreaterEqual(len(hist), 256)
        self.assertEqual(numpy.sum(hist), numpy.prod(size))
        self.assertEqual(hist[0], 1)
        self.assertEqual(hist[-1], 1)
        u = numpy.unique(hist[1:-1])
        self.assertEqual(sorted(u.tolist()), [0, grey_img.size - 2])
        hist_forced, edges = img.histogram(grey_img, edges)
        numpy.testing.assert_array_equal(hist, hist_forced)

    def test_compact(self):
        """
        test the compactHistogram()
        """
        depth = 4096 # limited depth
        size = (1024, 965)
        grey_img = numpy.zeros(size, dtype="uint16") + 1500
        grey_img[0, 0] = 0
        grey_img[0, 1] = depth - 1
        hist, edges = img.histogram(grey_img, (0, depth - 1))
        # make it compact
        chist = img.compactHistogram(hist, 256)
        self.assertEqual(len(chist), 256)
        self.assertEqual(numpy.sum(chist), numpy.prod(size))

        # make it really compact
        vchist = img.compactHistogram(hist, 1)
        self.assertEqual(vchist[0], numpy.prod(size))

        # keep it the same length
        nchist = img.compactHistogram(hist, depth)
        numpy.testing.assert_array_equal(hist, nchist)


class TestDataArray2RGB(unittest.TestCase):
    @staticmethod
    def CountValues(array):
        return len(numpy.unique(array))

    def test_simple(self):
        # test with everything auto
        size = (1024, 512)
        grey_img = numpy.zeros(size, dtype="uint16") + 1500

        # one colour
        out = img.DataArray2RGB(grey_img)
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 1)

        # add black
        grey_img[0, 0] = 0
        out = img.DataArray2RGB(grey_img)
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 2)

        # add white
        grey_img[0, 1] = 4095
        out = img.DataArray2RGB(grey_img)
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 3)
        pixel0 = out[0, 0]
        pixel1 = out[0, 1]
        pixelg = out[0, 2]
        numpy.testing.assert_array_less(pixel0, pixel1)
        numpy.testing.assert_array_less(pixel0, pixelg)
        numpy.testing.assert_array_less(pixelg, pixel1)

    def test_direct_mapping(self):
        """test with irange fitting the whole depth"""
        # first 8 bit => no change (and test the short-cut)
        size = (1024, 1024)
        depth = 256
        grey_img = numpy.zeros(size, dtype="uint8") + depth // 2
        grey_img[0, 0] = 10
        grey_img[0, 1] = depth - 10

        # should keep the grey
        out = img.DataArray2RGB(grey_img, irange=(0, depth - 1))
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 3)
        pixel = out[2, 2]
        numpy.testing.assert_equal(pixel, [128, 128, 128])

        # 16 bits
        depth = 4096
        grey_img = numpy.zeros(size, dtype="uint16") + depth // 2
        grey_img[0, 0] = 100
        grey_img[0, 1] = depth - 100

        # should keep the grey
        out = img.DataArray2RGB(grey_img, irange=(0, depth - 1))
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 3)
        pixel = out[2, 2]
        numpy.testing.assert_equal(pixel, [128, 128, 128])

    def test_irange(self):
        """test with specific corner values of irange"""
        size = (1024, 1024)
        depth = 4096
        grey_img = numpy.zeros(size, dtype="uint16") + depth // 2
        grey_img[0, 0] = 100
        grey_img[0, 1] = depth - 100

        # slightly smaller range than everything => still 3 colours
        out = img.DataArray2RGB(grey_img, irange=(50, depth - 51))
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 3)
        pixel0 = out[0, 0]
        pixel1 = out[0, 1]
        pixelg = out[0, 2]
        numpy.testing.assert_array_less(pixel0, pixel1)
        numpy.testing.assert_array_less(pixel0, pixelg)
        numpy.testing.assert_array_less(pixelg, pixel1)

        # irange at the lowest value => all white (but the blacks)
        out = img.DataArray2RGB(grey_img, irange=(0, 1))
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 1)
        pixel = out[2, 2]
        numpy.testing.assert_equal(pixel, [255, 255, 255])

        # irange at the highest value => all blacks (but the whites)
        out = img.DataArray2RGB(grey_img, irange=(depth - 2, depth - 1))
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 1)
        pixel = out[2, 2]
        numpy.testing.assert_equal(pixel, [0, 0, 0])

        # irange at the middle value => black/white/grey (max)
        out = img.DataArray2RGB(grey_img, irange=(depth // 2 - 1, depth // 2 + 1))
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out), 3)
        hist, edges = img.histogram(out[:, :, 0]) # just use one RGB channel
        self.assertGreater(hist[0], 0)
        self.assertEqual(hist[1], 0)
        self.assertGreater(hist[-1], 0)
        self.assertEqual(hist[-2], 0)

    def test_fast(self):
        """Test the fast conversion"""
        data = numpy.ones((251, 200), dtype="uint16")
        data[:, :] = range(200)
        data[2, :] = 56
        data[200, 2] = 3

        data_nc = data.swapaxes(0, 1) # non-contiguous cannot be treated by fast conversion

        # convert to RGB
        hist, edges = img.histogram(data)
        irange = img.findOptimalRange(hist, edges, 1 / 256)
        tstart = time.time()
        for i in range(10):
            rgb = img.DataArray2RGB(data, irange)
        fast_dur = time.time() - tstart

        hist_nc, edges_nc = img.histogram(data_nc)
        irange_nc = img.findOptimalRange(hist_nc, edges_nc, 1 / 256)
        tstart = time.time()
        for i in range(10):
            rgb_nc = img.DataArray2RGB(data_nc, irange_nc)
        std_dur = time.time() - tstart
        rgb_nc_back = rgb_nc.swapaxes(0, 1)

        print("Time fast conversion = %g s, standard = %g s" % (fast_dur, std_dur))
        self.assertLess(fast_dur, std_dur)
        numpy.testing.assert_almost_equal(rgb, rgb_nc_back, decimal=0)
        numpy.testing.assert_equal(rgb, rgb_nc_back)

    def test_tint(self):
        """test with tint (on the fast path)"""
        size = (1024, 1024)
        depth = 4096
        grey_img = numpy.zeros(size, dtype="uint16") + depth // 2
        grey_img[0, 0] = 0
        grey_img[0, 1] = depth - 1

        # white should become same as the tint
        tint = (0, 73, 255)
        out = img.DataArray2RGB(grey_img, tint=tint)
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out[:, :, 0]), 1)  # R
        self.assertEqual(self.CountValues(out[:, :, 1]), 3)  # G
        self.assertEqual(self.CountValues(out[:, :, 2]), 3)  # B

        pixel0 = out[0, 0]
        pixel1 = out[0, 1]
        pixelg = out[0, 2]
        numpy.testing.assert_array_equal(pixel1, list(tint))
        self.assertTrue(numpy.all(pixel0 <= pixel1))
        self.assertTrue(numpy.all(pixel0 <= pixelg))
        self.assertTrue(numpy.all(pixelg <= pixel1))

    def test_tint_int16(self):
        """test with tint, with the slow path"""
        size = (1024, 1024)
        depth = 4096
        grey_img = numpy.zeros(size, dtype="int16") + depth // 2
        grey_img[0, 0] = 0
        grey_img[0, 1] = depth - 1

        # white should become same as the tint
        tint = (0, 73, 255)
        out = img.DataArray2RGB(grey_img, tint=tint)
        self.assertEqual(out.shape, size + (3,))
        self.assertEqual(self.CountValues(out[:, :, 0]), 1) # R
        self.assertEqual(self.CountValues(out[:, :, 1]), 3) # G
        self.assertEqual(self.CountValues(out[:, :, 2]), 3) # B

        pixel0 = out[0, 0]
        pixel1 = out[0, 1]
        pixelg = out[0, 2]
        numpy.testing.assert_array_equal(pixel1, list(tint))
        self.assertTrue(numpy.all(pixel0 <= pixel1))
        self.assertTrue(numpy.all(pixel0 <= pixelg))
        self.assertTrue(numpy.all(pixelg <= pixel1))

    def test_uint8(self):
        # uint8 is special because it's so close from the output that bytescale
        # normally does nothing
        irange = (25, 135)
        shape = (1024, 836)
        tint = (0, 73, 255)
        data = numpy.random.random_integers(irange[0], irange[1], shape).astype(numpy.uint8)
        # to be really sure there is at least one of the min and max values
        data[0, 0] = irange[0]
        data[0, 1] = irange[1]

        out = img.DataArray2RGB(data, irange, tint=tint)

        pixel1 = out[0, 1]
        numpy.testing.assert_array_equal(pixel1, list(tint))

        self.assertTrue(numpy.all(out[..., 0] == 0))

        self.assertEqual(out[..., 2].min(), 0)
        self.assertEqual(out[..., 2].max(), 255)

        # Same data, but now mapped between 0->255 => no scaling to do (just duplicate)
        irange = (0, 255)
        out = img.DataArray2RGB(data, irange, tint=tint)
        self.assertTrue(numpy.all(out[..., 0] == 0))
        numpy.testing.assert_array_equal(data, out[:, :, 2])

    def test_float(self):
        irange = (0.3, 468.4)
        shape = (102, 965)
        tint = (0, 73, 255)
        grey_img = numpy.zeros(shape, dtype="float") + 15.05
        grey_img[0, 0] = -15.6
        grey_img[0, 1] = 500.6

        out = img.DataArray2RGB(grey_img, irange, tint=tint)
        self.assertTrue(numpy.all(out[..., 0] == 0))
        self.assertEqual(out[..., 2].min(), 0)
        self.assertEqual(out[..., 2].max(), 255)

        # irange at the lowest value => all white (but the blacks)
        out = img.DataArray2RGB(grey_img, irange=(-100, -50))
        self.assertEqual(out.shape, shape + (3,))
        self.assertEqual(self.CountValues(out), 1)
        pixel = out[2, 2]
        numpy.testing.assert_equal(pixel, [255, 255, 255])

        # irange at the highest value => all blacks (but the whites)
        out = img.DataArray2RGB(grey_img, irange=(5000, 5000.1))
        self.assertEqual(out.shape, shape + (3,))
        self.assertEqual(self.CountValues(out), 1)
        pixel = out[2, 2]
        numpy.testing.assert_equal(pixel, [0, 0, 0])

        # irange at the middle => B&W only
        out = img.DataArray2RGB(grey_img, irange=(10, 10.1))
        self.assertEqual(out.shape, shape + (3,))
        self.assertEqual(self.CountValues(out), 2)
        hist, edges = img.histogram(out[:, :, 0])  # just use one RGB channel
        self.assertGreater(hist[0], 0)
        self.assertEqual(hist[1], 0)
        self.assertGreater(hist[-1], 0)
        self.assertEqual(hist[-2], 0)


class TestMergeMetadata(unittest.TestCase):

    def test_simple(self):
        # Try correction is null (ie, identity)
        md = {model.MD_ROTATION: 0, # °
              model.MD_PIXEL_SIZE: (1e-6, 1e-6), # m
              model.MD_POS: (-5e-3, 2e-3), # m
              model.MD_ROTATION_COR: 0, # °
              model.MD_PIXEL_SIZE_COR: (1, 1), # ratio
              model.MD_POS_COR: (0, 0), # m
              }
        orig_md = dict(md)
        img.mergeMetadata(md)
        for k in [model.MD_ROTATION, model.MD_PIXEL_SIZE, model.MD_POS]:
            self.assertEqual(orig_md[k], md[k])
        for k in [model.MD_ROTATION_COR, model.MD_PIXEL_SIZE_COR, model.MD_POS_COR]:
            self.assertNotIn(k, md)

        # Try the same but using a separate correction metadata
        id_cor = {model.MD_ROTATION_COR: 0, # °
                  model.MD_PIXEL_SIZE_COR: (1, 1), # ratio
                  model.MD_POS_COR: (0, 0), # m
                  }

        orig_md = dict(md)
        img.mergeMetadata(md, id_cor)
        for k in [model.MD_ROTATION, model.MD_PIXEL_SIZE, model.MD_POS]:
            self.assertEqual(orig_md[k], md[k])
        for k in [model.MD_ROTATION_COR, model.MD_PIXEL_SIZE_COR, model.MD_POS_COR]:
            self.assertNotIn(k, md)

        # Check that empty correction metadata is same as identity
        orig_md = dict(md)
        img.mergeMetadata(md, {})
        for k in [model.MD_ROTATION, model.MD_PIXEL_SIZE, model.MD_POS]:
            self.assertEqual(orig_md[k], md[k])
        for k in [model.MD_ROTATION_COR, model.MD_PIXEL_SIZE_COR, model.MD_POS_COR]:
            self.assertNotIn(k, md)

        # Check that providing a metadata without correction data doesn't change
        # anything
        simpl_md = {model.MD_ROTATION: 90, # °
                    model.MD_PIXEL_SIZE: (17e-8, 17e-8), # m
                    model.MD_POS: (5e-3, 2e-3), # m
                    }
        orig_md = dict(simpl_md)
        img.mergeMetadata(simpl_md)
        for k in [model.MD_ROTATION, model.MD_PIXEL_SIZE, model.MD_POS]:
            self.assertEqual(orig_md[k], simpl_md[k])
        for k in [model.MD_ROTATION_COR, model.MD_PIXEL_SIZE_COR, model.MD_POS_COR]:
            self.assertNotIn(k, simpl_md)

class TestEnsureYXC(unittest.TestCase):

    def test_simple(self):
        cyxim = numpy.zeros((3, 512, 256), dtype=numpy.uint8)
        cyxim = model.DataArray(cyxim)
        orig_shape = cyxim.shape
        orig_md = cyxim.metadata.copy()
        for i in range(3):
            cyxim[i] = i

        yxcim = img.ensureYXC(cyxim)
        self.assertEqual(yxcim.shape, (512, 256, 3))
        self.assertEqual(yxcim.metadata[model.MD_DIMS], "YXC")

        # check original da was not changed
        self.assertEqual(cyxim.shape, orig_shape)
        self.assertDictEqual(orig_md, cyxim.metadata)

        # try again with explicit metadata
        cyxim.metadata[model.MD_DIMS] = "CYX"
        orig_md = cyxim.metadata.copy()

        yxcim = img.ensureYXC(cyxim)
        self.assertEqual(yxcim.shape, (512, 256, 3))
        self.assertEqual(yxcim.metadata[model.MD_DIMS], "YXC")

        # check no metadata was changed
        self.assertDictEqual(orig_md, cyxim.metadata)

        for i in range(3):
            self.assertEqual(yxcim[0, 0, i], i)

    def test_no_change(self):
        yxcim = numpy.zeros((512, 256, 3), dtype=numpy.uint8)
        yxcim = model.DataArray(yxcim)
        yxcim.metadata[model.MD_DIMS] = "YXC"

        newim = img.ensureYXC(yxcim)
        self.assertEqual(newim.shape, (512, 256, 3))
        self.assertEqual(newim.metadata[model.MD_DIMS], "YXC")

# TODO: test isClipping()

# TODO: test guessDRange()

if __name__ == "__main__":
    unittest.main()

