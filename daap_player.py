#!/usr/bin/python
#
# Minimalist audio player for DAAP (iTunes) collections.  Depends on
# python-gst and (a slightly modified) python-daap.
#
# Copyright 2008 Ron Weiss (ronw@ee.columbia.edu)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Minimalist audio player for DAAP (iTunes) collections.

Best experienced by people who just want to play their music without
worrying about heavyweight clients that are preoccupied with ugly
visualizations and downloading album art and crashing (I'm looking at
you amarok!).  There is no GUI here.

This is known to work with Firefly media server (mt-daapd), but
probably won't work with iTunes.

Run it from the python shell or use the included shell interface.
"""

__author__ = "Ron Weiss (ronw@ee.columbia.edu)"

import cmd
import glob
import inspect
import operator
import os
import pickle
import pydoc
import random
import re
import readline
import sys
import thread
import time
import types
import urllib

import tagpy

# for gstreamer
import gobject 
gobject.threads_init()
import pygst
pygst.require("0.10")
import gst

import daap


class Player(object):
    """
    Simple audio player based on GStreamer's playbin element.
    """

    def __init__(self):
        self.__player = gst.element_factory_make("playbin", "player")
        fakesink = gst.element_factory_make("fakesink", "my-fakesink")
        self.__player.set_property("video-sink", fakesink)
        bus = self.__player.get_bus()
        bus.add_watch(self.__handle_message, "message")

        self.__playlist = Playlist()
        self.__state = "STOPPED"
        self.__current_track = 0

        loop = gobject.MainLoop()
        context = loop.get_context()
        thread.start_new_thread(self.__poll_for_messages, (context,))

    def __handle_message(self, bus, message, tmp):
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.next()
        elif t == gst.MESSAGE_ERROR:
            self.__player.set_state(gst.STATE_NULL)
            err, debug = message.parse_error()
            print "GStreamer error: %s" % err, debug
        return True

    def __poll_for_messages(self, context):
        while True:
            context.iteration(True)
            time.sleep(0.1)

    def __get_status(self):
        """ Return a string describing the current status of the
        player. """
        if self.__state in ("PLAYING", "PAUSED"):
            try:
                track = self.__playlist[self.__current_track]
            except (TypeError, IndexError):
                return self.__state
            status = '%s: [%d/%d] %s' % (self.__state, self.__current_track + 1,
                                         len(self.__playlist), track)
            if self.position and self.duration:
                status = '%s [%0.1f/%0.1f sec]' % (status, self.position,
                                                   self.duration)
            return status
        else:
            return self.__state

    status = property(__get_status)

    def play(self):
        if self.__state == "PAUSED":
            self.__player.set_state(gst.STATE_PLAYING)
            self.__state = "PLAYING"
        elif (self.__state == "PLAYING" and
              self.__current_track >= len(self.__playlist)):
            self.__player.set_state(gst.STATE_NULL)
            self.__state = "STOPPED"
        elif self.__playlist:
            track = self.__playlist[self.__current_track]
            #fd = track.request().fp.fileno()
            self.__player.set_property('uri', track.uri)
            self.__player.set_state(gst.STATE_PLAYING)
            self.__state = "PLAYING"
            print self.status

    def pause(self):
        self.__player.set_state(gst.STATE_PAUSED)
        self.__state = "PAUSED"
        print self.status

    def stop(self):
        self.__player.set_state(gst.STATE_NULL)
        self.__state = "STOPPED"
        self.__current_track = 0
        print self.status

    def __get_current_track(self):
        """ Return current track number (starts from 1, not 0). """
        return self.__current_track + 1

    def __set_current_track(self, track):
        """ Move to given track. Note that track numbers start from 1, not
        0."""
        track = int(track)
        self.__current_track = max(track, 1) - 1
        self.__player.set_state(gst.STATE_NULL)
        if self.__current_track >= len(self.__playlist):
            self.stop()
        elif self.__state == "PLAYING":
            self.play()
        elif self.__state == "PAUSED":
            # If we switch tracks, we are no longer paused in the
            # middle of one of them.
            self.__state = "STOPPED"

    current_track = property(__get_current_track, __set_current_track)

    def __get_playlist(self):
        return self.__playlist

    def __set_playlist(self, playlist):
        self.__playlist = playlist
        self.current_track = 0

    playlist = property(__get_playlist, __set_playlist)

    def next(self, incr=1):
        """ Move to the next track. """
        self.current_track += incr

    def prev(self, decr=1):
        """ Move to the previous track. """
        self.current_track -= decr

    def __set_volume(self, volume):
        """ volume should be between 0.0 and 10.0 """
        volume = float(volume)
        if volume > 10.0:
            volume = 10.0
        elif volume < 0.0:
            volume = 0.0
        self.__player.set_property('volume', volume)

    def __get_volume(self):
        return self.__player.get_property('volume')

    volume = property(__get_volume, __set_volume)

    def mute(self):
        self.volume = 0.0

    def seek(self, time_sec):
        """ Seek to the given position (in seconds). """
        time_ns = time_sec * 1e9
        self.__player.seek_simple(gst.Format(gst.FORMAT_TIME),
                                 gst.SEEK_FLAG_FLUSH, time_ns)

    def __get_position(self):
        try:
            pos = 1e-9 * self.__player.query_position(
                gst.Format(gst.FORMAT_TIME), None)[0]
        except gst.QueryError:
            pos = None
        return pos

    position = property(__get_position, seek)

    def ff(self, time=10):
        """ Fast forward """
        self.position += time

    def rew(self, time=10):
        """ Rewind """
        self.position -= time

    def __get_duration(self):
        try:
            dur = 1e-9 * self.__player.query_duration(
                gst.Format(gst.FORMAT_TIME), None)[0]
        except gst.QueryError:
            dur = None
        return dur

    duration = property(__get_duration)


class Playlist(list):
    def shuffle(self):
        random.shuffle(self)

    def shuffle_albums(self):
        albums = {}
        for x in self:
            albums.setdefault(x.album, []).append(x)
        keys = albums.keys()
        random.shuffle(keys)
        self.clear()
        for k in keys:
            self.extend(albums[k])
        
    def clear(self):
        self.__delslice__(0, len(self))

    def search(self, pattern, fields=("artist", "album", "name"),
               flags=re.IGNORECASE):
        """ Return all tracks matching the given pattern. """
        pat = re.compile(pattern, flags)
        tracknums = []
        for n,x in enumerate(self):
            for y in fields:
                if getattr(x, y) and pat.search(getattr(x, y)):
                    tracknums.append(n)
                    break
        return tracknums

    def __str__(self):
        return '\n'.join(['%d: %s' % (n+1, x) for n,x in enumerate(self)])


class BaseCollection(object):
    """Base representation of a music collection."""
    def init(self):
        # Make sure tracks are sorted in some reasonable order.
        for x in ['uri', 'track', 'disc', 'album', 'year', 'artist']:
            self.tracks.sort(key=operator.attrgetter(x))
    
    def search(self, pattern, fields=("artist", "album", "name"),
               flags=re.IGNORECASE):
        """ Return all tracks matching the given pattern. """
        pat = re.compile(pattern, flags)
        tracks = Playlist()
        for x in self.tracks:
            for y in fields:
                if getattr(x, y) and pat.search(getattr(x, y)):
                    tracks.append(x)
                    break
        return tracks


class DaapCollection(BaseCollection):
    """Music collection contained on a DAAP server."""
    def __init__(self, server='localhost', port=3689, password=None):
        self.__session = None
        client = daap.DAAPClient();
        client.connect(server, port=port, password=password)
        self.__session = client.login()
        self.tracks = self.__session.library().tracks()

        self.init()
 
    def __del__(self):
        if self.__session:
            self.__session.logout()        


class DirectoryCollection(BaseCollection):
    """Music collection contained on the filesystem."""
    def __init__(self, basedir, extensions=['mp3', 'ogg', 'flac', 'wav']):
        basedir = os.path.abspath(os.path.expanduser(basedir))
        extensions = [x.lower() for x in extensions]
        tracks = []
        for path, dirs, files in os.walk(basedir):
            tracks.extend([Track(os.path.join(path, x)) for x in files
                           if os.path.splitext(x)[-1][1:].lower() in extensions])
        self.tracks = tracks

        self.init()


class Track(object):
    filetypes = {tagpy._tagpy.mpeg_File: 'mp3',
                 tagpy._tagpy.ogg_vorbis_File: 'ogg',
                 }

    def __init__(self, filename):
        self.uri = 'file://%s' % urllib.quote(filename)
        self.filename = filename
        self.name = os.path.basename(filename)

        print "Loading %s" % filename
        self._read_metadata_from_file()

    def _read_metadata_from_file(self):
        required_attrs = dict(track=None, disc=None, album=None, year=None,
                              artist=None, time=None, format=None)
        for key,val in required_attrs.iteritems():
            setattr(self, key, val)

        try:
            fileref = tagpy.FileRef(self.filename)
        except Exception, e:
            print "Could not read track metadata: ", e
            return

        tags = fileref.tag()
        tagmap = dict(name='title', album='album',
                      artist='artist', track='track', year='year')
        for key, val in tagmap.iteritems():
            setattr(self, key, getattr(tags, val))
        
        audioProperties = fileref.audioProperties()
        self.time = audioProperties.length

        self.format = type(fileref.file())
        if self.format in Track.filetypes:
            self.format = Track.filetypes[self.format]

    def __unicode__(self):
        tn = ''
        if self.track:
            tn = '%s - ' % self.track
        tm = ''
        if self.time:
            tm = ' [%0.2f]' % self.time
        yr = ''
        if self.year:
            yr = ' (%s)' % self.year
        return u'%s - %s%s - %s%s%s (%s)' % (self.artist, self.album, yr, tn,
                                             self.name, tm, self.format)

    def __str__(self):
        return str(self.__unicode__().encode('utf-8', 'replace'))


def print_to_pager(string):
    string = str(string)
    if len(string.splitlines()) > 20:
        pydoc.getpager()(string)
    else:
        print string


class PlayerShell(cmd.Cmd):
    history_file = os.path.expanduser('~/.daap_player_history')
    intro = """
    DaapPlayer interactive shell.
    Type 'help' for help.
    """
    
    # Define some easier to type aliases for certain commands.  Note
    # that the shell will automatically interpret all input that forms
    # a unique prefix for an existing command as if the whole command
    # had been given (e.g. 'mu' automatically resolves to 'mute'), so
    # there is no need to define such aliases here.
    command_aliases = {'na': 'next_album',
                       'pa': 'prev_album',
                       'n': 'next',
                       'pr': 'prev',
                       'pl': 'playlist',
                       'sa': 'shuffle_albums'}

    def __del__(self):
        del self.collection
        readline.write_history_file(self.history_file)

    def preloop(self):
        self.prompt = "DaapPlayer> "
        self.collection = None
        self.player = Player()

        if os.path.exists(self.history_file):
            readline.read_history_file(self.history_file)

        # Import functions from self.player and self.playlist that
        # don't take any arguments.
        methods = [(k,v,'player') for k,v in Player.__dict__.items()]
        methods.extend([(k,v,'playlist') for k,v in Playlist.__dict__.items()])
        for key,val,cls in methods:
            do_key = 'do_%s' % key
            if key.startswith('_') or do_key in self.__class__.__dict__:
                continue
            elif type(val) is types.FunctionType:
                (args, varargs, varkw, defaults) = inspect.getargspec(val)
                ndefaults = len(defaults) if defaults else 0
                if len(args) - ndefaults == 1:
                    def do_fun(obj, rest, fun=val, cls=cls):
                        if cls == 'player':
                            fun(obj.player)
                        elif cls == 'playlist':
                            fun(obj.player.playlist)
                    do_fun.__doc__ = val.__doc__
                    self.__class__.__dict__[do_key] = do_fun
            elif type(val) is property:
                def do_property(obj, rest, prop=key, cls=cls):
                    if not rest:
                        if cls == 'player':
                            val = obj.player.__getattribute__(prop)
                        elif cls == 'playlist':
                            val = obj.player.playlist.__getattribute__(prop)
                        print_to_pager(val)
                    else:
                        if cls == 'player':
                            obj.player.__setattr__(prop, rest)
                        elif cls == 'playlist ':
                            obj.player.playlist.__setattr__(prop, rest)
                do_property.__doc__ = val.__doc__
                self.__class__.__dict__[do_key] = do_property

        # Set up aliases.
        class_dict =  self.__class__.__dict__
        for k,v in PlayerShell.command_aliases.items():
            if not k in class_dict:
                class_dict['do_%s' % k] = class_dict['do_%s' % v]

    def precmd(self, s):
        if s:
            verb = s.split()[0]
            do_verb = 'do_%s' % verb
            matches = [x.replace('do_', '') for x in self.__class__.__dict__
                       if do_verb in x]
            if len(matches) == 1 and verb != matches[0]:
                s = s.replace(verb, matches[0])
            elif len(matches) > 1 and verb not in matches:
                print 'Command "%s" is ambiguous, options are:' % verb
                for x in matches:
                    print x
        return s

    def onecmd(self, s):
        try:
            cmd.Cmd.onecmd(self, s)
        except KeyboardInterrupt:
            print 'Type "exit" to quit.'

    def emptyline(self):
        pass

    def do_EOF(self, rest):
        self.do_exit(rest)

    def do_quit(self, rest):
        self.do_exit(rest)

    def do_exit(self, rest):
        sys.exit(0)

    def do_p(self, rest):
        """
        Pause/play toggle.
        """
        if self.player.status.startswith("PLAY"):
            self.player.pause()
        else:
            self.player.play()

    def do_next_album(self, rest):
        """
        Move to the first track of the next album in the playlist.
        """
        curr = self.player.current_track - 1;
        albums = [x.album for x in self.player.playlist]
        orig_album = albums[curr]
        for x in range(curr + 1, len(albums)):
            if albums[x] != orig_album:
                self.player.current_track = x + 1
                break
        # in case orig_album is the last albums
        if x == len(albums) - 1:
            self.current_track = len(albums)

    def do_prev_album(self, rest):
        """
        Move to the first track of the previous album in the playlist.
        """
        curr = self.player.current_track - 1;
        albums = [x.album for x in self.player.playlist[:curr+1]]
        orig_album = albums[curr]
        target_album = None
        for x in range(curr - 1, -1, -1):
            if not target_album:
                if albums[x] != orig_album:
                    target_album = albums[x]
            elif albums[x] != target_album:
                self.player.current_track = x + 2
                break
        # in case orig_album is the first album
        if x == 0:
            self.current_track = 1

    def do_loaddaap(self, rest):
        """
        loaddaap server[:port] [password]
        Load track collection from the given DAAP server.
        """
        server = "localhost"
        port = 3689
        password = None
        fields = rest.split()
        if len(fields) > 0:
            server = fields[0]
            if ':' in server:
                server,port = server.split(':')
                port = int(port)
        if len(fields) > 1:
            password = fields[1]
        print "Connecting to %s:%d" % (server,port)
        try:
            self.collection = DaapCollection(server, port, password)
            print "Loaded %d tracks." % len(self.collection.tracks)
        except Exception, e:
            print "Error:", e

    def do_loaddir(self, rest):
        """
        loaddaap basedir
        Load track collection from the given directory.
        """
        try:
            self.collection = DirectoryCollection(rest)
            print "Loaded %d tracks." % len(self.collection.tracks)
        except Exception, e:
            print "Error:", e

    def do_loadpkl(self, rest):
        """
        loadpkl /path/to/tracks.pkl
        Load previously saved track collection from the give pickle file.
        """
        try:
            f = open(rest, 'r')
            self.collection = pickle.load(f)
            f.close()
            print "Loaded %d tracks." % len(self.collection.tracks)
            print self.collection.tracks
        except Exception, e:
            print "Error:", e

    def do_savecollection(self, rest):
        """
        savecollection /path/to/tracks.pkl
        Save collection to the given pickle file.
        """
        try:
            f = open(rest, 'w')
            pickle.dump(self.collection, f, pickle.HIGHEST_PROTOCOL)
            f.close()
        except Exception, e:
            print "Error:", e

    def do_search(self, rest, print_tracks=True, collection=None):
        """
        search pattern [in field1 or field2 or ... [AND [pattern] [in field] ...]]
        Search collection for tracks whose given pattern matches any of
        the listed fields (defaults to "artist album name").
        """
        if collection is None:
            collection = self.collection
        
        if not self.collection:
            print "No collection loaded, run load first."
            return
        pattern = '.'
        default_attrs = ('artist', 'album', 'name')
        try:
            if not rest:
                tracks = collection.search(pattern, fields=default_attrs)
            else:
                tracks = None
                terms = re.compile('and', re.IGNORECASE).split(rest)
                for t in terms:
                    fields = t.split(' in ')
                    pattern = fields[0].strip()
                    attrs = default_attrs
                    if len(fields) > 1:
                        attrs = [x.strip() for x in fields[1].split(' or ')]
                    curr_tracks = collection.search(pattern, fields=attrs)
                    if not tracks:
                        tracks = curr_tracks
                    else:
                        track_set = set(tracks)
                        tracks = Playlist([x for x in curr_tracks
                                           if x in track_set])
        except AttributeError, name:
            print 'Error: no such attribute: "%s"' % name
            tracks = None
        except TypeError:
            print 'TypeError???'
            tracks = None
        if print_tracks and tracks:
            print_to_pager(tracks)
        else:
            return tracks

    def do_add(self, rest):
        """
        add pattern [in field1 or field2 or ... [AND [pattern] [in field] ...]]
        Search collection for tracks whose given pattern matches any of
        the listed fields (defaults to "artist album title") and add
        them to the current playlist.
        """
        playlist = self.do_search(rest, print_tracks=False)
        self.player.playlist.extend(playlist)
        print 'Added %d items.' % len(playlist)

    def do_skipto(self, rest):
        """
        skipto pattern [in field1 or field2 or ... [AND [pattern] [in field] ...]]
        Search current playlist for tracks whose given pattern matches any of
        the listed fields (defaults to "artist album title") and skip
        to the first matching result after the current track.
        """
        tracknums = self.do_search(rest, print_tracks=False,
                                   collection=self.player.playlist)
        if tracknums:
            print 'Found %d matching tracks in playlist.' % len(tracknums)
            futuretracknums = [x for x in tracknums
                               if x > self.player.current_track - 1]
            if futuretracknums:
                track = futuretracknums[0]
            else:
                # Have to wrap back to the beginning of the playlist.hem
                track = tracknums[0]

            print 'Skipping to [%d/%d]: %s' % (track+1,
                                               len(self.player.playlist),
                                               self.player.playlist[track])
            self.player.current_track = track + 1
        else:
            print "Couldn't find any matching tracks."

    def do_clear(self, rest):
        """
        Clear the current playlist.
        """
        self.player.stop()
        self.player.playlist.clear()


if __name__ == "__main__":
    #import logging
    #logging.basicConfig(level=logging.DEBUG,
    #        format='%(asctime)s %(levelname)s %(message)s')
    shell = PlayerShell()
    shell.cmdloop()

