#!/usr/bin/env python3
"""Fetch live travel data from Transport for London"""

WHITE=1
BLACK=0

import argparse
import datetime
import json
import logging
import sys

import iso8601
import PIL
import requests

from apscheduler.schedulers.blocking import BlockingScheduler
from EPD import EPD
from PIL import ImageFont, ImageDraw


def parse_options(args=None):
    """Parse command line options"""
    formatter = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(description='Information from TfL',
                                     formatter_class=formatter)
    parser.add_argument('-b', '--bus-stop', action='store', dest='busStopID',
                        help='TfL identifier of a bus stop')
    parser.add_argument('-l', '--bus-line', action='store', dest='busLine',
                        help='Name of a bus route')
    parser.add_argument('-u', '--base-url', action='store', dest='baseURL',
                        help='Base URL of TFL API endpoint',
                        default="https://api.tfl.gov.uk")
    parser.add_argument('-d', '--debug', action='store_true', dest='debug',
                        help='Turn on debugging', default=False)

    options = parser.parse_args(args)
    return options


class PyBus:
    options = None
    scheduler = None
    currentJSON = None
    logger = None
    fontTiny = None
    fontMedium = None
    fontLarge = None
    fontHuge = None
    panel = None
    partialCount = None

    def __init__(self, options, scheduler):
        self.options = options
        self.scheduler = scheduler
        self.logger = logging.getLogger("PyBus")

        if options.debug:
            self.logger.setLevel(logging.DEBUG)

        self.logger.debug("Command line options: %s" % self.options)

        if not self.options.busStopID or not self.options.busLine:
            self.logger.error("You must provide both bus stop and bus route")
            sys.exit(1)

        self.partialCount = 0

        self.fontTiny = ImageFont.truetype("font.ttf", size=10)
        self.fontMedium = ImageFont.truetype("font.ttf", size=50)
        self.fontLarge = ImageFont.truetype("font.ttf", size=80)
        self.fontHuge= ImageFont.truetype("font.ttf", size=150)

        try:
            self.panel = EPD()

            self.logger.debug("Panel: {w:d}x{h:d}".format(w=self.panel.width,
                                                          h=self.panel.height))
        except Exception as e:
            self.panel = None
            self.logger.warn("No panel found: %s" % e)

        self.scheduler.add_job(self.updateBusInfo,
                               trigger='interval',
                               seconds=30,
                               next_run_time=datetime.datetime.now(),
                               max_instances=1)
        self.scheduler.add_job(self.dummyShowBusInfo,
                               trigger='interval',
                               seconds=5,
                               next_run_time=datetime.datetime.now(),
                               max_instances=1)

    def prettifyJSON(self, jsonText):
        """Neatly format JSON to make it human readable"""
        return json.dumps(jsonText, sort_keys=True, indent=4,
                          separators=(',', ': '))

    def fetchBusJSON(self, baseURL, stopID):
        """Fetch the JSON for a bus stop"""
        try:
            url = "%s/StopPoint/%s/arrivals" % (baseURL, stopID)
            self.logger.debug("Fetching: %s" % url)
            result = requests.get(url)
        except Exception as e:
            self.logger.error("fetchBusJSON error. Stop %s: %s" % (stopID, e))
            return None

        jsonResult = result.json()
        self.logger.debug("Raw JSON: %s" % self.prettifyJSON(jsonResult))

        return jsonResult

    def updateBusInfo(self):
        """Update the bus information"""
        rawJSON = self.fetchBusJSON(self.options.baseURL,
                                    self.options.busStopID)
        if not rawJSON:
            self.currentJSON = None
            return False

        self.currentJSON = []
        for busItem in rawJSON:
            if busItem[u'lineName'].lower() == \
               self.options.busLine.lower():
                self.currentJSON.append(busItem)

        return True

    def getTimes(self):
        """Fetch the number of minutes until each bus is due"""
        if not self.currentJSON:
            return None

        times = []

        now = datetime.datetime.now(datetime.timezone.utc)
        for bus in self.currentJSON:
            due = iso8601.parse_date(bus["expectedArrival"])
            dueDiff = due - now
            minutesDue = divmod(dueDiff.total_seconds(), 60)[0]
            times.append("%02d" % max(minutesDue, 0))

        times.sort()

        if len(times) == 0:
            times.append("--")
        if len(times) == 1:
            times.append("--")
        if len(times) == 2:
            times.append("--")

        return times

    def renderBusInfo(self):
        """Render the available bus information to the e-Ink display"""
        # the first argument means we get a 1 bit depth
        image = PIL.Image.new('1', self.panel.size, WHITE)
        draw = ImageDraw.Draw(image)

        times = self.getTimes()
        if not times:
            # TODO: Display a message
            self.panel.clear()
            return

        draw.text((-3, 0), times[0], font=self.fontHuge, fill=BLACK)
        draw.text((170, 13), times[1], font=self.fontLarge, fill=BLACK)
        draw.text((172, 95), times[2], font=self.fontMedium, fill=BLACK)

        self.panel.display(image)

        if self.partialCount >= 10:
            self.panel.update()
            self.partialCount = 0
        else:
            self.panel.partial_update()
            self.partialCount += 1

    def dummyShowBusInfo(self):
        """blah"""
        times = self.getTimes()

        print("")

        if not times:
            print("No time information is available")
            return

        if len(times) == 0:
            print("Times info is empty")
            return

        for time in times:
            print("Bus due in %d minutes" % time)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig()
    scheduler = BlockingScheduler()
    options = parse_options()
    pybus = PyBus(options, scheduler)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        pass
