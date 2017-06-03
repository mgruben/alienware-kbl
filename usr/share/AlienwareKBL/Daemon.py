#!/usr/bin/python3
#

#  Copyright (C) 2015-2017  Rafael Senties Martinelli <rafael@senties-martinelli.com>
#
#  This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License 3 as published by
#   the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software Foundation,
#   Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA.


import Pyro4
import os
import pwd
from traceback import format_exc
from time import time, sleep

# Local imports
from texts import *
from utils import getuser, print_warning, print_debug
from Engine.Controller import Controller
from Engine.Driver import Driver
from Configuration import Theme
from Configuration.Paths import Paths
from Configuration.CCParser import CCParser

class ConnectDaemon:

    def __init__(self):
        self.daemon = Pyro4.Daemon()
        self.paths = Paths()

        uri = self.daemon.register(Daemon(self))
        with open(self.paths.DAEMON_PYRO_PATH, encoding='utf-8', mode='wt') as f:
            f.write(str(uri))

        self.daemon.requestLoop()


class Daemon:

    def __init__(self, loop_self):

        driver = Driver()
        if not driver.has_device():
            print_warning("The computer is not supported")
            exit(1)
        self._computer = driver.computer
        self._controller = Controller(driver)
        print_debug('Controller loaded: {}'.format(self._controller))

        self.loop_self = loop_self

        # Get the user that the daemon should use
        #
        self._paths = Paths()
        _global_ccp = CCParser(self._paths.GLOBAL_CONFIG, 'Global alienware-kbl Theme')
        self._user = _global_ccp.get_str_defval('boot_user', 'root')

        # Check if the user of the configuration file exists
        #
        try:
            pwd.getpwnam(self._user)
        except:
            user = getuser()
            print_warning('The `{}` of the configuration file does not exist, it has been replaced by `{}`'.format(self._user, user))
            self._user = user

        self._paths = Paths(self._user)

        # Initialize the daemon
        #
        self._ccp = CCParser(self._paths.CONFIGURATION_PATH, 'GUI Theme')
        self._indicator_pyro = False
        self.reload_configurations(self._user)
        self.set_lights(self._user, self._ccp.get_bool_defval('boot', True))

    def _iluminate_keyboard(self):

        os.utime(self._theme.path, None)  # This is to recognize the last theme that has been used.
        self._lights_state = True

        # Update the indicator
        #
        if self._indicator_pyro:
            self._indicator_send_code(100)
            try:
                self._indicator_pyro.load_profiles(
                    list(Theme.profiles.keys()),
                    self.profile_name,
                    self._lights_state)
            except Exception as e:
                print(format_exc())

        # Iluminate the computer lights
        #
        self._controller.start_loop(save=False, block=self._computer.get_power_block())
        self._controller.set_speed(self._theme.get_speed())
        
        for area in self._theme.get_areas():
            for zone in area.get_zones():
                self._controller.add_loop(zone.get_hex_id(),
                                          zone.get_mode(),
                                          zone.get_left_color(),
                                          zone.get_right_color())

            self._controller.end_loop()

        self._controller.end_transfer()
        self._controller.write()

    def _indicator_send_code(self, val):
        if self._indicator_pyro:
            try:
                self._indicator_pyro.set_code(val)
            except Exception as e:
                print(format_exc())

    """
        General Bindings
    """

    @Pyro4.expose
    def ping(self):
        pass

    @Pyro4.expose
    def reload_configurations(self, user, indicator=True, set_default=True):

        if user != self._user:
            self._user = user
            self._paths = Paths(user)

        Theme.LOAD_profiles(self._computer, self._paths.PROFILES_PATH)

        if set_default:
            _, self.profile_name = Theme.GET_last_configuration()
            self._theme = Theme.get_theme_by_name(self.profile_name)

        if self._indicator_pyro and indicator:
            try:
                self._indicator_pyro.load_profiles(
                    list(Theme.profiles.keys()),
                    self.profile_name,
                    self._lights_state)
            except Exception as e:
                print(format_exc())

    """
        Bindings for the users
    """

    @Pyro4.expose
    def set_profile(self, user, profile):
        """
            Set a profile from the existing profiles.

            + 'profile' is the profile name
        """
        if user != self._user:
            self._user = user
            self._paths = Paths(user)

        self.reload_configurations(user, False, False)

        if profile in Theme.profiles.keys():
            self._theme = Theme.profiles[profile]
            self.profile_name = profile
            self._iluminate_keyboard()
            self._iluminate_keyboard()

    @Pyro4.expose
    def switch_lights(self, user):
        """
            If the lights are on, put them off
            or if the lights are off put them on
        """
        if self._lights_state:
            self.set_lights(user, False)
        else:
            self.set_lights(user, True)

    @Pyro4.expose
    def set_lights(self, user, state):
        """
            Turn the lights on or off, 'state' can be a boolean or a string.
        """
        if state in (False, 'False', 'false'):

            keep_alive_zones = self._ccp.get_str_defval('zones_to_keep_alive', '')

            if keep_alive_zones == '':
                self._controller.start_loop(save=False, block=self._computer.get_power_block())
                self._controller.reset(self._computer.RESET_ALL_LIGHTS_OFF)
            else:
                keep_alive_zones = keep_alive_zones.split('|')

                """
                    This hack, it will set black as color to all the lights that should be turned off.
                """
                self._controller.start_loop(
                    False, self._computer.BLOCK_LOAD_ON_BOOT)
                self._controller.add_speed_conf(1)

                for key in sorted(self._theme.area.keys()):
                    if key not in keep_alive_zones:
                        area = self._theme.area[key]
                        for zone in area:
                            self._controller.add_loop(zone.get_hex_id(), 'fixed', '#000000', '#000000')

                        self._controller.end_loop()

                self._controller.end_transfer()
                self._controller.write()

            self._lights_state = False
            self._indicator_send_code(150)
        else:
            if user != self._user:
                self.reload_configurations(user)

            self._iluminate_keyboard()

    @Pyro4.expose
    def set_colors(self, mode, speed, left_colors, right_colors=None):
        """
            Change the colors and the mode of the keyboard.

            + The available modes are: 'fixed', 'morph', 'blink'
                'fixed' and 'blink' only takes left_colors

            + Speed must be an integer. 1 =< speed =< 256

            + left_colors and right_colors can be a single hex color or a list.
              If both arguments are used, both arguments must have
              the same number of items.
        """

        if mode not in ('fixed', 'morph', 'blink'):
            print("Warning Daemon: Wrong mode", mode)
            return
        elif not isinstance(speed, int):
            print("Warning Daemon: Speed must be an integer.")
            return
        elif speed >= 256:
            speed = 255
        elif speed < 1:
            speed = 1

        speed = speed * 256

        if not isinstance(left_colors, list):
            left_colors = [left_colors]

        if right_colors is None:
            right_colors = left_colors

        if not isinstance(right_colors, list):
            right_colors = [right_colors]

        if len(left_colors) != len(right_colors):
            print_warning("The colors list do not have the same lenght")
            return

        self._lights_state = True
        self._controller.start_loop(
            False, self._computer.BLOCK_LOAD_ON_BOOT)
        self._controller.add_speed_conf(speed)

        for zone in self._computer.regions.keys():
            for i in range(len(left_colors)):

                self._controller.add_loop(
                    self._computer.regions[zone].region_id, 
                    mode, 
                    left_colors[i], 
                    right_colors[i])

            self._controller.end_loop()

        self._controller.end_transfer()
        self._controller.write()

    """
        Bindings for the graphical interphase
    """

    @Pyro4.expose
    def get_computer_name(self):
        return self._computer.NAME

    @Pyro4.expose
    def get_computer_info(self):
        return (self._computer.NAME, 
                self._computer.VENDOR_ID,
                self._computer.PRODUCT_ID, 
                str(self._controller.driver.dev))

    @Pyro4.expose
    def modify_lights_state(self, bool):
        """
            This method does not changes the lights of the keyboard,
            it only updates the daemon and the indicator
        """
        if bool in (False, 'False', 'false'):
            self._lights_state = False
            self._indicator_send_code(150)
        else:
            self._lights_stae = True
            self._indicator_send_code(100)

    """
        Indicator Bindings
    """

    @Pyro4.expose
    def indicator_get_state(self):
        if self._lights_state:
            self._indicator_send_code(100)
        else:
            self._indicator_send_code(150)

    @Pyro4.expose
    def indicator_init(self, uri):
        try:
            self._indicator_pyro = Pyro4.Proxy(str(uri))
            self.reload_configurations(self._user)
        except Exception as e:
            print_warning("Failed initialization")
            print(format_exc())
            self._indicator_pyro = False

    @Pyro4.expose
    def indicator_kill(self):
        self._indicator_pyro = False


if __name__ == '__main__':
    if getuser() != 'root':
        print(TEXT_ONLY_ROOT)
    else:
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        ConnectDaemon()