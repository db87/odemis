# -*- coding: utf-8 -*-
"""
Created on 27 Feb 2014

@author: Kimon Tsitsikas

Copyright © 2013-2014 Éric Piel & Kimon Tsitsikas, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the
terms  of the GNU General Public License version 2 as published by the Free
Software  Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY;  without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR  PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
Odemis. If not, see http://www.gnu.org/licenses/.
"""

from __future__ import division
from .calculation import CalculateDrift
from .dc_region import GuessAnchorRegion
from odemis.util import TimeoutError

import logging
import numpy
import threading

# to identify a ROI which must still be defined by the user
UNDEFINED_ROI = (0, 0, 0, 0)

class AnchoredEstimator(object):
    """
    Drift estimator based on an "anchor" area. Periodically, a small region
    (the anchor) is scanned. By comparing the images of the anchor area over
    time, an estimation of the drift is computed.
    
    To use, call .scan() periodically (and preferably at specific places of 
    the global scan, such as at the beginning of a line), and call .estimate()
    to measure the drift.
    """
    def __init__(self, scanner, detector, region, dwell_time):
        """
        """
        self._emitter = scanner
        self._semd = detector
        self._semd_df = detector.data
        self._dcRegion = region
        self._dcDwellTime = dwell_time
        self.orig_drift = (0, 0)
        self.raw = [] # all the anchor areas acquired (in order)
        self._sr_data = []
        self._acq_sem_complete = threading.Event()
        
        # Calculate initial translation for anchor region acquisition
        self._roi = self._dcRegion.value
        center = ((self._roi[0] + self._roi[2]) / 2,
                  (self._roi[1] + self._roi[3]) / 2)
        width = (self._roi[2] - self._roi[0], self._roi[3] - self._roi[1])
        shape = self._emitter.shape

        # translation is distance from center (situated at 0.5, 0.5), can be floats
        self._trans = (shape[0] * (center[0] - 0.5) - self.orig_drift[1],
                       shape[1] * (center[1] - 0.5) - self.orig_drift[0])
        # self._transl = (shape[0] * (center[0] - 0.5) - drift[1],
        #                 shape[1] * (center[1] - 0.5) - drift[0])

        # resolution is the maximum resolution at the scale in proportion of the width
        self._res = (max(1, int(round(shape[0] * width[0]))),
                     max(1, int(round(shape[1] * width[1]))))

        # Demand large enough anchor region for drift calculation
        if self._res[0] < 2 or self._res[1] < 2:
            # TODO: just use a smaller scale (if possible) in that case?
            raise ValueError("Anchor region too small for drift detection.")

        self.safety_bounds = (-0.99 * (shape[0] / 2), 0.99 * (shape[1] / 2))
        self._min_bound = self.safety_bounds[0] + (max(self._res[0],
                                                        self._res[1]) / 2)
        self._max_bound = self.safety_bounds[1] - (max(self._res[0],
                                                        self._res[1]) / 2)

    def scan(self):
        """
        Scan the anchor area
        """
        if self._roi != UNDEFINED_ROI:
            self._onAnchorRegion()
            logging.debug("E-beam spot to anchor region: %s",
                          self._emitter.translation.value)
            self._acq_sem_complete.clear()
            self._semd_df.subscribe(self._ssOnAnchorRegion)
            logging.debug("Scanning anchor region with resolution %s \
                            and dwelltime %s and scale %s",
                          self._emitter.resolution.value,
                          self._emitter.dwellTime.value,
                          self._emitter.scale.value)
            prod_res = numpy.prod(self._emitter.resolution.value)
            if not self._acq_sem_complete.wait(self._emitter.dwellTime.value *
                                               prod_res * 4 + 1):
                raise TimeoutError("Acquisition of anchor region frame timed out")
            self._semd_df.unsubscribe(self._ssOnAnchorRegion)
     
    def estimate(self):
        """
        return (float, float): estimated current drift in X/Y SEM px
        """
        # Calculate the drift between the last two frames and
        # between the last and fisrt frame
        if len(self._sr_data) > 1:
            prev_drift = CalculateDrift(self._sr_data[-2],
                                        self._sr_data[-1], 10)
            self.orig_drift = CalculateDrift(self._sr_data[0],
                                             self._sr_data[-1], 10)

            logging.debug("Current drift: %s", self.orig_drift)
            logging.debug("Previous frame diff: %s", prev_drift)
            if (abs(self.orig_drift[0] - prev_drift[0]) > 5 or
                abs(self.orig_drift[1] - prev_drift[1]) > 5):
                logging.warning("Drift cannot be measured precisely, "
                                "hesitating between %s and %s px",
                                 self.orig_drift, prev_drift)

        return self.orig_drift
    
    def estimateAcquisitionTime(self):
        """
        return (float): estimated time to acquire 1 anchor area
        """
        anchor_time = 0
        roi = self._dcRegion.value
        if roi != UNDEFINED_ROI:
            width = (roi[2] - roi[0], roi[3] - roi[1])
            shape = self._emitter.shape
            res = (max(1, int(round(shape[0] * width[0]))),
                   max(1, int(round(shape[1] * width[1]))))
            anchor_time = numpy.prod(res) * self._dcDwellTime.value + 0.01

        return anchor_time

    def _onAnchorRegion(self):
        """
        Update the scanning area of the SEM according to the anchor region
        for drift correction.
        """
        # translation is distance from center (situated at 0.5, 0.5), can be floats
        # we clip translation inside of bounds in case of huge drift
        new_translation = (self._trans[0] - self.orig_drift[0],
                           self._trans[1] - self.orig_drift[1])

        if (abs(new_translation[0]) > abs(self.safety_bounds[0])
            or abs(new_translation[1]) > abs(self.safety_bounds[1])):
            logging.warning("Generated image may be incorrect due to extensive drift. \
                            Do you want to continue scanning?")

        self._trans = (numpy.clip(new_translation[0], self._min_bound, self._max_bound),
                       numpy.clip(new_translation[1], self._min_bound, self._max_bound))

        # always in this order
        self._emitter.scale.value = (1, 1)
        self._emitter.resolution.value = self._res
        self._emitter.translation.value = self._trans
        self._emitter.dwellTime.value = self._dcDwellTime.value

    def _ssOnAnchorRegion(self, df, data):
        logging.debug("Anchor Region data received")

        # Do not stop the acquisition, as it ensures the e-beam is at the right place
        if (not self._acq_sem_complete.is_set()) and data.shape != (1, 1):
            # only use the first data per pixel
            self._sr_data.append(data)
            self._acq_sem_complete.set()
