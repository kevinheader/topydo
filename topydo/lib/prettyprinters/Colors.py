# Topydo - A todo.txt client written in Python.
# Copyright (C) 2014 - 2015 Bram Schoenmakers <me@bramschoenmakers.nl>
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

""" Provides a pretty printer filter that colorizes todo items. """

import re

from topydo.lib.Color import Color
from topydo.lib.Config import config
from topydo.lib.PrettyPrinterFilter import PrettyPrinterFilter


class PrettyPrinterColorFilter(PrettyPrinterFilter):
    """
    Adds colors to the todo string by inserting ANSI codes.

    Should be passed as a filter in the filter list of pretty_print()
    """

    def filter(self, p_todo_str, p_todo):
        """ Applies the colors. """
        if config().colors():
            priority_color = config().priority_color(p_todo.priority())
            project_color = config().project_color()
            context_color = config().context_color()
            metadata_color = config().metadata_color()
            link_color = config().link_color()
            neutral_color = Color('NEUTRAL')

            # color projects / contexts
            p_todo_str = re.sub(
                r'\B(\+|@)(\S*\w)',
                lambda m: (
                    context_color.as_ansi() if m.group(0)[0] == "@"
                    else project_color.as_ansi()) + m.group(0) + priority_color.as_ansi(),
                p_todo_str)

            # tags
            p_todo_str = re.sub(r'\b\S+:[^/\s]\S*\b',
                                metadata_color.as_ansi() + r'\g<0>' + priority_color.as_ansi(),
                                p_todo_str)

            # add link_color to any valid URL specified outside of the tag.
            p_todo_str = re.sub(r'(^|\s)(\w+:){1}(//\S+)',
                                r'\1' + link_color.as_ansi() + r'\2\3' + priority_color.as_ansi(),
                                p_todo_str)

            p_todo_str += neutral_color.as_ansi()

            # color by priority
            p_todo_str = priority_color.as_ansi() + p_todo_str

        return p_todo_str
