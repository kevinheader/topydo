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

from collections import namedtuple
import datetime
import shlex
import time
import urwid

from topydo.cli.CLIApplicationBase import CLIApplicationBase
from topydo.Commands import get_subcommand
from topydo.ui.CommandLineWidget import CommandLineWidget
from topydo.ui.ConsoleWidget import ConsoleWidget
from topydo.ui.KeystateWidget import KeystateWidget
from topydo.ui.TodoListWidget import TodoListWidget
from topydo.ui.ViewWidget import ViewWidget
from topydo.ui.ColumnLayout import columns
from topydo.lib.Config import config, ConfigError
from topydo.lib.Sorter import Sorter
from topydo.lib.Filter import get_filter_list, RelevanceFilter, DependencyFilter
from topydo.lib.Utils import get_terminal_size
from topydo.lib.View import View
from topydo.lib import TodoFile
from topydo.lib import TodoList

COLUMN_WIDTH = 40


class UIView(View):
    """
    A subclass of view holding user input data that constructed the view (i.e.
    the sort expression and the filter expression, etc.)
    """
    def __init__(self, p_sorter, p_filter, p_todolist, p_data):
        super().__init__(p_sorter, p_filter, p_todolist)
        self.data = p_data

_APPEND_COLUMN = 1
_EDIT_COLUMN = 2
_COPY_COLUMN = 3
_INSERT_COLUMN = 4


class MainPile(urwid.Pile):
    """
    This subclass of Pile doesn't change focus on cursor up/down / mouse press
    events. The implementation was taken from its base class.
    """
    def __init__(self, p_widget_list, p_focus_item=None):
        urwid.register_signal(MainPile, ['blur_console'])

        super().__init__(p_widget_list, p_focus_item)

    def mouse_event(self, p_size, p_event, p_button, p_col, p_row, p_focus):
        if self.focus_position != 2:
            urwid.emit_signal(self, 'blur_console')

        return super().mouse_event(p_size, p_event, p_button, p_col, p_row, p_focus)  # pylint: disable=E1102

    def keypress(self, p_size, p_key):
        if not self.contents:
            return p_key

        item_rows = None
        if len(p_size) == 2:
            item_rows = self.get_item_rows(p_size, focus=True)

        i = self.focus_position
        if self.selectable():
            tsize = self.get_item_size(p_size, i, True, item_rows)
            key = self.focus.keypress(tsize, p_key)
            if self._command_map[key] not in ('cursor up', 'cursor down'):
                return key


class UIApplication(CLIApplicationBase):
    def __init__(self):
        super().__init__()

        self._process_flags()
        config(p_overrides={('topydo', 'colors'): '0'}) # disable color in output

        self.todofile = TodoFile.TodoFile(config().todotxt())
        self.todolist = TodoList.TodoList(self.todofile.read())

        self.marked_todos = []

        self.columns = urwid.Columns([], dividechars=0, min_width=COLUMN_WIDTH)
        self.commandline = CommandLineWidget('topydo> ')
        self.keystate_widget = KeystateWidget()
        self.status_line = urwid.Columns([
            ('weight', 1, urwid.Filler(self.commandline)),
        ])

        self.keymap = config().column_keymap()
        self._alarm = None

        self._last_cmd = None

        # console widget
        self.console = ConsoleWidget()
        get_terminal_size(self._console_width)

        urwid.connect_signal(self.commandline, 'blur', self._blur_commandline)
        urwid.connect_signal(self.commandline, 'execute_command',
                             self._execute_handler)

        def hide_console(p_focus_commandline=False):
            self._console_visible = False
            if p_focus_commandline:
                self._focus_commandline()
        urwid.connect_signal(self.console, 'close', hide_console)

        # view widget
        self.viewwidget = ViewWidget(self.todolist)

        urwid.connect_signal(self.viewwidget, 'save',
                             lambda: self._update_view(self.viewwidget.data))

        def hide_viewwidget():
            self._viewwidget_visible = False
            self._blur_commandline()

        urwid.connect_signal(self.viewwidget, 'close', hide_viewwidget)

        self.mainwindow = MainPile([
            ('weight', 1, self.columns),
            (1, self.status_line),
        ])

        urwid.connect_signal(self.mainwindow, 'blur_console', hide_console)

        # the columns should have keyboard focus
        self._blur_commandline()

        self.mainloop = urwid.MainLoop(
            self.mainwindow,
            unhandled_input=self._handle_input,
            pop_ups=True
        )

        self.column_mode = _APPEND_COLUMN
        self._set_alarm_for_next_midnight_update()

    def _set_alarm_for_next_midnight_update(self):
        def callback(p_loop, p_data):
            self._update_all_columns()
            self._set_alarm_for_next_midnight_update()

        tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
        # turn it into midnight
        tomorrow = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

        self.mainloop.set_alarm_at(time.mktime(tomorrow.timetuple()), callback)

    def _output(self, p_text):
        self._print_to_console(p_text + "\n")

    def _execute_handler(self, p_command, p_todo_id=None, p_output=None):
        """
        Executes a command, given as a string.
        """
        p_output = p_output or self._output

        self._last_cmd = (p_command, p_output == self._output)

        if '{}' in p_command:
            if self._has_marked_todos():
                p_todo_id = ' '.join(self.marked_todos)
            p_command = p_command.format(p_todo_id)

        p_command = shlex.split(p_command)
        try:
            (subcommand, args) = get_subcommand(p_command)
        except ConfigError as cerr:
            self._print_to_console(
                'Error: {}. Check your aliases configuration.'.format(cerr))
            return

        self._backup(subcommand, args)

        try:
            command = subcommand(
                args,
                self.todolist,
                p_output,
                self._output,
                self._input,
            )

            if command.execute() != False:
                self._post_execute()

        except TypeError:
            # TODO: show error message
            pass

    def _update_all_columns(self):
        for column, _ in self.columns.contents:
            column.update()
            column.keystate = None

    def _post_execute(self):
        # store dirty flag because base _post_execute will reset it after flush
        dirty = self.todolist.dirty
        super()._post_execute()

        if dirty or self.marked_todos:
            self._reset_state()

    def _repeat_last_cmd(self, p_todo_id=None):
        try:
            cmd, verbosity = self._last_cmd
        except TypeError:
            return

        self._execute_handler(cmd, p_todo_id,
                              self._output if verbosity else lambda _: None)

    def _reset_state(self):
        self.marked_todos = []
        self._update_all_columns()

    def _blur_commandline(self):
        self.mainwindow.focus_item = 0

    def _focus_commandline(self):
        self.mainwindow.focus_item = 1

    def _focus_first_column(self):
        self.columns.focus_position = 0

    def _focus_last_column(self):
        end_pos = len(self.columns.contents) - 1
        self.columns.focus_position = end_pos

    def _focus_next_column(self):
        size = len(self.columns.contents)
        if self.columns.focus_position < size -1:
            self.columns.focus_position += 1

    def _focus_previous_column(self):
        if self.columns.focus_position > 0:
            self.columns.focus_position -= 1

    def _append_column(self):
        self.viewwidget.reset()
        self.column_mode = _APPEND_COLUMN
        self._viewwidget_visible = True

    def _insert_column(self):
        self.viewwidget.reset()
        self.column_mode = _INSERT_COLUMN
        self._viewwidget_visible = True

    def _edit_column(self):
        self.viewwidget.data = self.columns.focus.view.data
        self.column_mode = _EDIT_COLUMN
        self._viewwidget_visible = True

    def _delete_column(self):
        try:
            focus = self.columns.focus_position
            del self.columns.contents[focus]

            if self.columns.contents:
                self.columns.focus_position = focus
            else:
                self._focus_commandline()
        except IndexError:
            # no columns
            pass

    def _copy_column(self):
        self.viewwidget.data = self.columns.focus.view.data
        self.column_mode = _COPY_COLUMN
        self._viewwidget_visible = True

    def _column_action_handler(self, p_action):
        dispatch = {
            'first_column': self._focus_first_column,
            'last_column': self._focus_last_column,
            'prev_column': self._focus_previous_column,
            'next_column': self._focus_next_column,
            'append_column': self._append_column,
            'insert_column': self._insert_column,
            'edit_column': self._edit_column,
            'delete_column': self._delete_column,
            'copy_column': self._copy_column,
            'swap_left': self._swap_column_left,
            'swap_right': self._swap_column_right,
            'reset': self._reset_state,
        }
        dispatch[p_action]()

    def _handle_input(self, p_input):
        dispatch = {
            ':': self._focus_commandline,
        }

        try:
            dispatch[p_input]()
        except KeyError:
            # the key is unknown, ignore
            pass

    def _viewdata_to_view(self, p_data):
        """
        Converts a dictionary describing a view to an actual UIView instance.
        """
        sorter = Sorter(p_data['sortexpr'])
        filters = []

        if not p_data['show_all']:
            filters.append(DependencyFilter(self.todolist))
            filters.append(RelevanceFilter())

        filters += get_filter_list(p_data['filterexpr'].split())

        return UIView(sorter, filters, self.todolist, p_data)

    def _update_view(self, p_data):
        """ Creates a view from the data entered in the view widget. """
        view = self._viewdata_to_view(p_data)

        if self.column_mode == _APPEND_COLUMN or self.column_mode == _COPY_COLUMN:
            self._add_column(view)
        elif self.column_mode == _INSERT_COLUMN:
            self._add_column(view, self.columns.focus_position)
        elif self.column_mode == _EDIT_COLUMN:
            current_column = self.columns.focus

            current_column.title = p_data['title']
            current_column.view = view

        self._viewwidget_visible = False

    def _add_column(self, p_view, p_pos=None):
        """
        Given an UIView, adds a new column widget with the todos in that view.

        When no position is given, it is added to the end, otherwise inserted
        before that position.
        """
        def execute_silent(p_cmd, p_todo_id=None):
            self._execute_handler(p_cmd, p_todo_id, lambda _: None)

        todolist = TodoListWidget(p_view, p_view.data['title'], self.keymap)
        urwid.connect_signal(todolist, 'execute_command_silent',
                             execute_silent)
        urwid.connect_signal(todolist, 'execute_command', self._execute_handler)
        urwid.connect_signal(todolist, 'repeat_cmd', self._repeat_last_cmd)
        urwid.connect_signal(todolist, 'refresh', self.mainloop.screen.clear)
        urwid.connect_signal(todolist, 'add_pending_action', self._set_alarm)
        urwid.connect_signal(todolist, 'remove_pending_action', self._remove_alarm)
        urwid.connect_signal(todolist, 'column_action', self._column_action_handler)
        urwid.connect_signal(todolist, 'show_keystate', self._print_keystate)
        urwid.connect_signal(todolist, 'toggle_mark',
                             self._process_mark_toggle)

        options = self.columns.options(
            width_type='given',
            width_amount=COLUMN_WIDTH,
            box_widget=True
        )

        item = (todolist, options)

        if p_pos == None:
            p_pos = len(self.columns.contents)

        self.columns.contents.insert(p_pos, item)

        self.columns.focus_position = p_pos
        self._blur_commandline()

    def _print_keystate(self, p_keystate):
        self.keystate_widget.set_text(p_keystate)
        self._keystate_visible = len(p_keystate) > 0

    def _set_alarm(self, p_callback):
        """ Sets alarm to execute p_action specified in 0.5 sec. """
        self._alarm = self.mainloop.set_alarm_in(0.5, p_callback)

    def _remove_alarm(self):
        """ Removes pending action alarm stored in _alarm attribute. """
        self.mainloop.remove_alarm(self._alarm)
        self._alarm = None

    def _swap_column_left(self):
        pos = self.columns.focus_position
        if pos > 0:
            _columns = self.columns.contents
            _columns[pos], _columns[pos - 1] = _columns[pos - 1], _columns[pos]
            self.columns.focus_position -= 1

    def _swap_column_right(self):
        pos = self.columns.focus_position
        _columns = self.columns.contents
        if pos < len(_columns) - 1:
            _columns[pos], _columns[pos + 1] = _columns[pos + 1], _columns[pos]
            self.columns.focus_position += 1

    @property
    def _console_visible(self):
        contents = self.mainwindow.contents
        return len(contents) == 3 and isinstance(contents[2][0], ConsoleWidget)

    @_console_visible.setter
    def _console_visible(self, p_enabled):
        contents = self.mainwindow.contents

        if p_enabled == True and len(contents) == 2:
            contents.append((self.console, ('pack', None)))
            self.mainwindow.focus_position = 2
        elif p_enabled == False and self._console_visible:
            self.console.clear()
            del contents[2]
            self.mainwindow.focus_position = 0

    @property
    def _keystate_visible(self):
        contents = self.status_line.contents
        return len(contents) == 2 and isinstance(contents[1][0].original_widget,
                                                 KeystateWidget)

    @_keystate_visible.setter
    def _keystate_visible(self, p_enabled):
        contents = self.status_line.contents

        if p_enabled and len(contents) == 1:
            contents.append((urwid.Filler(self.keystate_widget),
                             ('weight', 1, True)))
        elif not p_enabled and self._keystate_visible:
            del contents[1]

    @property
    def _viewwidget_visible(self):
        contents = self.mainwindow.contents
        return len(contents) == 3 and isinstance(contents[2][0], ViewWidget)

    @_viewwidget_visible.setter
    def _viewwidget_visible(self, p_enabled):
        contents = self.mainwindow.contents

        if p_enabled == True and len(contents) == 2:
            contents.append((self.viewwidget, ('pack', None)))
            self.mainwindow.focus_position = 2
        elif p_enabled == False and self._viewwidget_visible:
            del contents[2]

    def _print_to_console(self, p_text):
        self._console_visible = True
        self.console.print_text(p_text)

    def _input(self, p_question):
        self._print_to_console(p_question)

        # don't wait for the event loop to enter idle, there is a command
        # waiting for input right now, so already go ahead and draw the
        # question on screen.
        self.mainloop.draw_screen()

        user_input = self.mainloop.screen.get_input()
        self._console_visible = False

        return user_input[0]

    def _console_width(self):
        terminal_size = namedtuple('Terminal_Size', 'columns lines')
        width = self.console.console_width() - 2
        sz = terminal_size(width, 1)

        return sz

    def _has_marked_todos(self):
        return len(self.marked_todos) > 0

    def _process_mark_toggle(self, p_todo_id):
        """
        Adds p_todo_id to marked_todos attribute and returns True if p_todo_id
        is not already present. Removes p_todo_id from marked_todos and returns
        False otherwise.
        """
        if p_todo_id not in self.marked_todos:
            self.marked_todos.append(p_todo_id)
            return True
        else:
            self.marked_todos.remove(p_todo_id)
            return False

    def run(self):
        layout = columns()
        if len(layout) > 0:
            for column in layout:
                self._add_column(self._viewdata_to_view(column))
        else:
            dummy = {
                "title": "All tasks",
                "sortexpr": "desc:prio",
                "filterexpr": "",
                "show_all": True,
            }
            self._add_column(self._viewdata_to_view(dummy))

        # make sure that the first column is focused on startup
        self.columns.focus_position = 0

        self.mainloop.run()

if __name__ == '__main__':
    UIApplication().run()