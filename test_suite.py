#!/usr/bin/env python
################################################################################
# karma_bot test_suite
# --------------------
# tests for karma_bot
#
# "THE BEER-WARE LICENSE" (Revision 42):
# <thenoviceoof> wrote this file. As long as you retain this notice you
# can do whatever you want with this stuff. If we meet some day, and you
# think this stuff is worth it, you can buy me a beer in return
################################################################################

from karma_bot import User, KarmaBotFactory
from twisted.trial import unittest
from twisted.test import proto_helpers

class KarmaBotTestCase(unittest.TestCase):
    def setUp(self):
        channel = "_testing"
        factory = KarmaBotFactory(channel=channel)
        self.proto = factory.buildProtocol(('127.0.0.1', 0))
        self.trans = proto_helpers.StringTransport()
        self.proto.makeConnection(self.trans)

    def test(self):
        pass
