# Topydo - A todo.txt client written in Python.
# Copyright (C) 2015 Bram Schoenmakers <me@bramschoenmakers.nl>
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
Provides a printer that transforms a list of Todo items to an iCalendar
file according to RFC 2445.
"""

try:
    import icalendar as ical
    ICAL_PRESENT = True
except ImportError:
    ICAL_PRESENT = False

from datetime import datetime, time
import random
import string

from topydo.lib.PrettyPrinter import Printer

def _convert_priority(p_priority):
    """
    Converts todo.txt priority to an iCalendar priority (RFC 2445).

    Priority A gets priority 1, priority B gets priority 5 and priority C-F get
    priorities 6-9. This scheme makes sure that clients that use "high",
    "medium" and "low" show the correct priority.
    """
    result = 0

    prio_map = {
        'A': 1,
        'B': 5,
        'C': 6,
        'D': 7,
        'E': 8,
        'F': 9,
    }

    try:
        result = prio_map[p_priority]
    except KeyError:
        if p_priority:
            # todos with no priority have priority None, and result of this
            # function will be 0. For all other letters, return 9 (lowest
            # priority in RFC 2445).
            result = 9

    return result

class IcalPrinter(Printer):
    """
    A printer that converts a list of Todo items to a string in iCalendar
    format (RFC 2445).

    https://www.rfc-editor.org/rfc/rfc2445.txt
    """
    def __init__(self, p_todolist):
        super(IcalPrinter, self).__init__()
        self.todolist = p_todolist

    def print_todo(self, p_todo):
        return self._convert_todo(p_todo).to_ical() if ICAL_PRESENT else ""

    def print_list(self, p_todos):
        result = ""

        if ICAL_PRESENT:
            cal = ical.Calendar()
            cal.add('prodid', '-//bramschoenmakers.nl//topydo//')
            cal.add('version', '2.0')

            for todo in p_todos:
                cal.add_component(self._convert_todo(todo))

            result = cal.to_ical().decode('utf-8')

        return result

    def _convert_todo(self, p_todo):
        """ Converts a Todo instance (Topydo) to an icalendar Todo instance. """

        def _get_uid(p_todo):
            """
            Gets a unique ID from a todo item, stored by the ical tag. If the
            tag is not present, a random value is assigned to it and returned.
            """
            def generate_uid(p_length=4):
                """
                Generates a random string of the given length, used as
                identifier.
                """
                return ''.join(
                    random.choice(string.ascii_letters + string.digits)
                        for i in range(p_length))

            uid = p_todo.tag_value('ical')
            if not uid:
                uid = generate_uid()
                p_todo.set_tag('ical', uid)
                self.todolist.set_dirty()

            return uid

        result = ical.Todo()

        # this should be called first, it may set the ical: tag and therefore
        # change the source() output.
        result['uid'] = _get_uid(p_todo)

        result['summary'] = ical.vText(p_todo.text())
        result['description'] = ical.vText(p_todo.source())
        result.add('priority', _convert_priority(p_todo.priority()))

        start = p_todo.start_date()
        if start:
            result.add('dtstart', start)

        due = p_todo.due_date()
        if due:
            result.add('due', due)

        created = p_todo.creation_date()
        if created:
            result.add('created', created)

        completed = p_todo.completion_date()
        if completed:
            completed = datetime.combine(completed, time(0, 0))
            result.add('completed', completed)

        return result
