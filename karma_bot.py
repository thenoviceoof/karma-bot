#!/usr/bin/env python
################################################################################
# karma_bot
# --------------------
# For tracking karma in the wild-n-wooly IRC world
#
# "THE BEER-WARE LICENSE" (Revision 42):
# <thenoviceoof> wrote this file. As long as you retain this notice you
# can do whatever you want with this stuff. If we meet some day, and you
# think this stuff is worth it, you can buy me a beer in return
################################################################################

# twisted imports
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet import defer

# sqlalchemy
import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# system imports
import time
import sys
import re
from operator import itemgetter
import argparse
import daemon
import os.path

import logging
logging.basicConfig()
log = logging.getLogger(__name__)

################################################################################
# messages

HELP = """ABOUT:
This is a little bot to keep track of karma on IRC
USAGE:
To use {0}, you give each other points like:
\t10 points to harry!
\t+2 pts for hermoine
\t+3 @dumbledore
or if someone screws up:
\t-3 points to ron
To see who has points, message me with:
\tleaderboard
\t\t- to see who's doing what
\thelp
\t\t- to see this message
\t<name>
\t\t- to see their current score
\t.* (anything else)
\t\t- to see your current score
Or you can display a leaderboard for all to see on the channel with:
\tkarma_bot!leaderboard
Have fun!"""

################################################################################
# sql things

Base = declarative_base()
Session = sessionmaker()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    points = Column(Integer)
    help = Column(Boolean)

    def __init__(self, name):
        self.name = name
        self.points = 0
        self.help = True

# separate out the logging from the client
class KarmaLogger:
    def __init__(self):
        self.db = Session()
    def get_user(self, username):
        user = self.db.query(User).filter_by(name=username).first()
        if not user:
            user = User(username)
            self.db.add(user)
            self.db.commit()
        return user
    def help_user(self, username):
        user = self.get_user(username)
        if user.help:
            user.help = False
            self.db.add(user)
            self.db.commit()
            return True
        return False
    def __getitem__(self, username):
        user = self.get_user(username)
        return user.points
    def __setitem__(self, username, points):
        user = self.get_user(username)
        user.points = points
        self.db.add(user)
        self.db.commit()
    def close(self):
        self.db.close()
    def leaderboard(self):
        things = [(u.name,u.points) for u in self.db.query(User).all()
                  if u.points]
        return reversed(sorted(things, key=itemgetter(1)))

class Version(Base):
    __tablename__ = 'version'
    id = Column(Integer, primary_key=True)
    version = Column(Integer)

    def __init__(self):
        self.version = 0

LATEST_MIGRATION = 1
def db_migrate():
    """Bring the database up to the latest schema"""
    session = Session()
    v = session.query(Version).first()
    if not v:
        v = Version()
        v.version = LATEST_MIGRATION
        session.add(v)
        session.commit()
    # 1. apply first migration
    if v.version == 0:
        session.execute("ALTER TABLE users ADD COLUMN help boolean;")
        v.version = 1
        session.add(v)
        session.commit()
    # apply further migrations here

################################################################################
# IRC things

class KarmaBot(irc.IRCClient):
    nickname = "karma_bot"

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        log.info("[Connected at {0}]".format(time.ctime()))

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        log.info("[Disconnected at {0}]".format(time.ctime()))

    def leaderboard(self, user=None):
        points = self.factory.points
        if user is None:
            user = self.channel
        self.msg(user, "----------------------------------------")
        self.msg(user, "From high to low:")
        for target, points in points.leaderboard():
            msg = "{0}\t has {1} points".format(target, points)
            self.msg(user, msg)
        self.msg(user, "----------------------------------------")

    ####################
    # callbacks for events

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        self.join(self.factory.channel)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        self.channel = channel
        log.info("[Joined {0}]".format(channel))
        self.names = None
        self._namescallback = {}

        # kick off getting the names
        d = self.get_names(self.channel)
        d.addCallback(self.update_names_list)

    # keep the user pool up-to-date
    def userJoined(self, user, channel):
        if self.names is not None:
            self.names.add(user)
    def userLeft(self, user, channel):
        if self.names is not None:
            self.names.remove(user)
    def userKicked(self, user, channel):
        if self.names is not None:
            self.names.remove(user)
    def userRenamed(self, oldname, newname):
        if self.names is not None:
            self.names.remove(oldname)
            self.names.add(newname)

    # handle the bulk of the messages
    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]
        log.info("{0}: {1}".format(user, msg))

        points = self.factory.points
        # Check to see if they're sending me a private message
        if channel == self.nickname:
            if msg == "leaderboard":
                self.leaderboard(user)
            elif msg == "help":
                lines = HELP.split("\n")
                for line in lines:
                    self.msg(user, line)
            elif points[msg]:
                # see if there's a user on file
                pts = points[msg]
                self.msg(user, "{0} has {1} points".format(msg, pts))
            else:
                self.msg(user, "You have {0} points".format(points[user]))
        else:
            # check if it's a command
            match = re.search("{0}!(\w+)".format(self.nickname), msg)
            if match:
                command = match.group(1)
                if command == "leaderboard":
                    log.info("Executing command, leaderboard")
                    self.leaderboard()
                else:
                    print "No such command"
                    self.msg(user, "No such command")
                return

            # check if message mentions me
            match = re.search(self.nickname, msg)
            if match and points.help_user(self.nickname):
                self.msg(user, "Message me 'help' if you seek enlightenment")
                return

            # otherwise, see if it contains a point message
            regpart = r"((points|pts)\s+(for|to)|for|to|points|pts)"
            reg = r"([+-]?)(\d+)\s+{0}\s+\@?(\w+)".format(regpart)
            creg = r"([+-])(\d+)\s+\@(\w+)"
            match = re.search(reg, msg)
            cmatch = re.search(creg, msg)
            if match:
                sign = {"-": -1}.get(match.group(1), 1)
                pts  = sign * int(match.group(2))
                target = match.group(6)
            elif cmatch:
                sign = {"-": -1}.get(cmatch.group(1), 1)
                pts  = sign * int(cmatch.group(2))
                target = cmatch.group(3)
            else:
                target = ""
            # check we're doing this
            if self.names is None:
                self.msg(user, "Wait a sec, we don't have a name list yet")
                log.info("<%s> tried to give points too early" % user)
            elif target not in self.names:
                self.msg(user, "Can't give points to <%s>, not a user" % target)
                log.info("<%s> tried to award ghost <%s>" % (user, target))
            elif target:
                if user == target:
                    self.msg(user, "Hey! It's not cool giving yourself points")
                    log.info("User %s tried to give eyself points" % user)
                if points[target] + pts > 2**32-1:
                    self.msg(user, "{0} has too many points".format(user))
                    log.info("{0} has too many points".format(user))
                else:
                    points[target] += pts
                    log.info("Match! {0} points for {1}".format(pts, target))

    ####################
    # irc callbacks

    def update_names_list(self, names):
        self.names = set(names)
        log.info("Got a list of names:")
        log.info("%s" % str(names))

    # getting a list of names
    def get_names(self, channel):
        channel = channel.lower()
        d = defer.Deferred()
        if channel not in self._namescallback:
            self._namescallback[channel] = ([], [])

        self._namescallback[channel][0].append(d)
        self.sendLine("NAMES %s" % channel)
        return d

    def irc_RPL_NAMREPLY(self, prefix, params):
        channel = params[2].lower()
        nicklist = params[3].split(' ')

        if channel not in self._namescallback:
            return

        # check if we have to strip off a leading @
        for i in range(len(nicklist)):
            if nicklist[i][0] == "@":
                nicklist[i] = nicklist[i][1:]
        self._namescallback[channel][1].extend(nicklist)
    def irc_RPL_ENDOFNAMES(self, prefix, params):
        channel = params[1].lower()
        if channel not in self._namescallback:
            return

        callbacks, namelist = self._namescallback[channel]
        for cb in callbacks:
            cb.callback(namelist)
        del self._namescallback[channel]

    # For fun, override the method that determines how a nickname is changed on
    # collisions. The default method appends an underscore.
    def alterCollidedNick(self, nickname):
        """
        Generate an altered version of a nickname that caused a
        collision in an effort to create an unused related name for
        subsequent registration.
        """
        return nickname + '_'

class KarmaBotFactory(protocol.ClientFactory):
    """
    A factory for KarmaBots.
    A new protocol instance will be created each time we connect to the server.
    """

    def __init__(self, channel):
        self.channel = channel
        self.points = KarmaLogger()

    def buildProtocol(self, addr):
        p = KarmaBot()
        p.factory = self
        return p

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        log.warning("Reconnecting to the server...")
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        log.error("connection failed: {0}".format(reason))
        reactor.stop()

################################################################################
# runner scaffolding

def run_irc_bot(server, channel, port, db_path):
    # set up your db
    engine = create_engine('sqlite:///{0}'.format(db_path))
    Session.configure(bind=engine)
    Base.metadata.create_all(engine)
    db_migrate()

    # create factory protocol and application
    fac = KarmaBotFactory(channel)
    # connect factory to this host and port
    reactor.connectTCP(server, port, fac)
    # run bot
    reactor.run()
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the karma_bot')
    parser.add_argument('server', type=unicode, help="IRC server domain name")
    parser.add_argument('channel', type=str, help="Channel to join")
    parser.add_argument('-p', '--port', dest="port", type=int, default=6667,
                        help="Port to connect to")
    parser.add_argument('-d', '--daemon', '--daemonize', dest="daemonize",
                        const=True, default=False, action='store_const',
                        help="Enable automatic daemonization")
    db_help = "Path to the sqlite file for storage (default=.irc_points.db)"
    parser.add_argument('-db', '--database', dest="db_path", type=unicode,
                        default=".irc_points.db", help=db_help)

    args = parser.parse_args()

    if args.daemonize:
        # when daemonizing, we cd "/", so we need an abspath
        db_path = os.path.abspath(args.db_path)
        print "daemonizing..."
        with daemon.DaemonContext():
            run_irc_bot(server = args.server,
                        channel = args.channel,
                        port = args.port,
                        db_path = db_path)
    # otherwise, just run it
    run_irc_bot(server = args.server,
                channel = args.channel,
                port = args.port,
                db_path = args.db_path)
