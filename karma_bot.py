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

# sqlalchemy
import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# system imports
import time
import sys
import re
from operator import itemgetter
import argparse
import daemon


################################################################################
# messages
USAGE = """
python {0} <host> <#channel>
"""

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
Have fun!"""

################################################################################
# sql things

Base = declarative_base()

# !! so bad. not going into v1.0
db_path = ".irc_points.db"

# !! so bad. not going into v1.0
engine = create_engine('sqlite:///{0}'.format(db_path))

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    points = Column(Integer)

    def __init__(self, name):
        self.name = name
        self.points = 0

def init_db():
    Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)

# separate out the logging from the client
class KarmaLogger:
    def __init__(self, db_path):
        self.file = db_path
        self.db = Session()
    def get_user(self, username):
        user = self.db.query(User).filter_by(name=username).first()
        if not user:
            user = User(username)
            self.db.add(user)
            self.db.commit()
        return user
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

################################################################################
# IRC things

class KarmaBot(irc.IRCClient):
    nickname = "karma_bot"

    def __init__(self):
        self.points = KarmaLogger(db_path)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        print "[Connected at {0}]".format(time.ctime())

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        print "[Disconnected at {0}]".format(time.ctime())

    ####################
    # callbacks for events

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        self.join(self.factory.channel)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        print "[Joined {0}]".format(channel)

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]
        print "{0}: {1}".format(user, msg)

        # Check to see if they're sending me a private message
        if channel == self.nickname:
            if msg == "leaderboard":
                self.msg(user, "----------------------------------------")
                self.msg(user, "From high to low:")
                for target, points in self.points.leaderboard():
                    msg = "{0}\t has {1} points".format(target, points)
                    self.msg(user, msg)
                self.msg(user, "----------------------------------------")
            elif msg == "help":
                lines = HELP.split("\n")
                for line in lines:
                    self.msg(user, line)
            elif self.points[msg]:
                # see if there's a user on file
                pts = self.points[msg]
                self.msg(user, "{0} has {1} points".format(msg, pts))
            else:
                self.msg(user, "You have {0} points".format(self.points[user]))
        else:
            # check if message mentions me
            match = re.search(self.nickname, msg)
            if match:
                self.msg(user, "Message me 'help' if you seek enlightenment")
                return

            # otherwise, see if it contains a point message
            regpart = r"((points|pts)\s+(for|to)|for|to|points|pts)"
            reg = r"([+-]?)(\d+)\s+{0}\s+\@?(\w+)".format(regpart)
            print reg
            creg = r"([+-])(\d+)\s+\@(\w+)"
            match = re.search(reg, msg)
            cmatch = re.search(creg, msg)
            if match:
                sign = {"-": -1}.get(match.group(1), 1)
                points = sign * int(match.group(2))
                target = match.group(6)
            elif cmatch:
                sign = {"-": -1}.get(cmatch.group(1), 1)
                points = sign * int(cmatch.group(2))
                target = cmatch.group(3)
            else:
                target = ""
            # check we're doing this
            if target:
                if user == target:
                    self.msg(user, "Hey! It's not cool giving yourself points")
                if self.points[target] + points > 2**32-1:
                    self.msg(user, "{0} has too many points Oo".format(user))
                else:
                    self.points[target] += points
                    print "Match! {0} points for {1}".format(points, target)

    ####################
    # irc callbacks

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
    """A factory for PointBots.

    A new protocol instance will be created each time we connect to the server.
    """

    def __init__(self, channel):
        self.channel = channel

    def buildProtocol(self, addr):
        p = KarmaBot()
        p.factory = self
        return p

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "connection failed:", reason
        reactor.stop()


def run_irc_bot(server, channel, port):
    # create factory protocol and application
    fac = KarmaBotFactory(channel)
    # connect factory to this host and port
    reactor.connectTCP(server, port, fac)
    # run bot
    reactor.run()
    

if __name__ == '__main__':
    init_db()

    parser = argparse.ArgumentParser(description='Run a karma bot')
    parser.add_argument('server', type=unicode, help="IRC server domain name")
    parser.add_argument('channel', type=str, help="Channel to join")
    parser.add_argument('-p', '--port', dest="port", type=int, default=6667,
                        help="Port to connect to")
    parser.add_argument('-d', '--daemon', '--daemonize', dest="daemonize",
                        const=True, default=False, action='store_const',
                        help="Whether to automatically daemonize")

    args = parser.parse_args()

    if args.daemonize:
        print "daemonizing..."
        with daemon.DaemonContext():
            run_irc_bot(server=args.server,
                        channel=args.channel,
                        port=args.port)
    # otherwise, just run it
    run_irc_bot(server=args.server,
                channel=args.channel,
                port=args.port)
