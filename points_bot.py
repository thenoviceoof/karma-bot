# twisted imports
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.python import log

# system imports
import time, sys

import re
from operator import itemgetter

# sqlalchemy
import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
Base = declarative_base()

db_path = ".irc_points.db"

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

class PointLogger:
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
        things = [(u.name,u.points) for u in self.db.query(User).all()]
        return reversed(sorted(things, key=itemgetter(1)))

HELP = """USAGE:
To use {0}, you give each other points like:
\t10 points to harry!
\t+2 pts for hermoine
or if someone screws up:
\t-3 points to ron
To see who has points, message me with:
\tleaderboard
\t\t- to see who's doing what
\thelp
\t\t- to see this message
\t.* (anything else)
\t\t- to see your current score
Have fun!"""

class PointBot(irc.IRCClient):
    nickname = "points_bot"

    def __init__(self):
        self.points = PointLogger(db_path)

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
            else:
                self.msg(user, "You have {0} points".format(self.points[user]))
        else:
            reg = r"([+-]?)(\d+)\s+(points|pts)\s+(for|to)\s+\@?(\w+)"
            match = re.search(reg, msg)
            if match:
                sign = {"-": -1}.get(match.group(1), 1)
                points = sign * int(match.group(2))
                target = match.group(5)
                if user == target:
                    self.msg(user, "Hey! It's not cool giving yourself points")
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

class PointBotFactory(protocol.ClientFactory):
    """A factory for PointBots.

    A new protocol instance will be created each time we connect to the server.
    """

    def __init__(self, channel):
        self.channel = channel

    def buildProtocol(self, addr):
        p = PointBot()
        p.factory = self
        return p

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "connection failed:", reason
        reactor.stop()

USAGE = """
python {0} <host> <#channel>
"""

if __name__ == '__main__':
    init_db()

    if len(sys.argv) != 3:
        print USAGE.format(sys.argv[0])
        sys.exit(0)

    # initialize logging
    log.startLogging(sys.stdout)

    # create factory protocol and application
    f = PointBotFactory(sys.argv[2])

    # connect factory to this host and port
    reactor.connectTCP(sys.argv[1], 6667, f)

    # run bot
    reactor.run()
