#!/usr/bin/env python3

# This file is part of Pext
#
# Pext is free software: you can redistribute it and/or modify
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

import getopt
import os
import signal
import sys
import re
import time
from helpers import Action
from subprocess import Popen, PIPE
from queue import Queue, Empty

from PyQt5.QtCore import QStringListModel
from PyQt5.QtWidgets import QApplication, QDialog, QInputDialog, QLabel, QLineEdit, QMessageBox, QTextEdit, QVBoxLayout, QDialogButtonBox
from PyQt5.Qt import QQmlApplicationEngine, QObject, QQmlProperty, QUrl

from module_base import ModuleBase


class SignalHandler():
    def __init__(self, window):
        self.window = window

    def handle(self, signum, frame):
        # Signal received
        self.window.show()


class ViewModel():
    def __init__(self):
        # Temporary values to allow binding. These will be properly set when
        # possible and relevant.
        self.filteredList = []
        self.resultListModelList = QStringListModel()
        self.resultListModelMaxIndex = -1
        self.messageList = []
        self.messageListModelList = QStringListModel()
        self.chosenEntry = None
        self.chosenEntryList = []

    def bindContext(self, context, window, searchInputModel, resultListModel):
        self.context = context
        self.window = window
        self.searchInputModel = searchInputModel
        self.resultListModel = resultListModel

    def bindModule(self, module):
        self.module = module

        self.commandsText = self.module.getCommands()
        self.entryList = self.module.getEntries()

        self.search()

    def addError(self, message):
        for line in message.splitlines():
            if not (not line or line.isspace()):
                self.messageList.append(["<font color='red'>{}</color>".format(line), time.time()])

        self.showMessages()

    def addMessage(self, message):
        for line in message.splitlines():
            if not (not line or line.isspace()):
                self.messageList.append([line, time.time()])

        self.showMessages()

    def showMessages(self):
        messageListForModel = [message[0] for message in self.messageList]
        self.messageListModelList = QStringListModel(messageListForModel)
        self.context.setContextProperty("messageListModelList", self.messageListModelList)

    def clearOldMessages(self):
        if len(self.messageList) == 0:
            return

        # Remove every error message older than 3 seconds and redraw the error list
        currentTime = time.time()
        self.messageList = [message for message in self.messageList if currentTime - message[1] < 3]
        self.showMessages()

    def goUp(self):
        if QQmlProperty.read(self.searchInputModel, "text") != "":
            QQmlProperty.write(self.searchInputModel, "text", "")
            return

        if self.chosenEntry is None:
            self.window.close()
            return

        self.chosenEntry = None
        self.search()

    def tabComplete(self):
        currentInput = QQmlProperty.read(self.searchInputModel, "text")
        stringToMatch = None
        for entry in self.filteredList:
            if entry in self.commandsText:
                continue

            if stringToMatch is None:
                stringToMatch = entry
            else:
                for i in range(len(stringToMatch)):
                    if entry[i] != stringToMatch[i]:
                        stringToMatch = stringToMatch[:i]
                        break

        possibleCommand = currentInput.split(" ", 1)[0]
        output = stringToMatch
        for command in self.commandsText:
            if command.startswith(possibleCommand):
                output = possibleCommand + " " + stringToMatch
                break

        if len(output) <= len(currentInput):
            self.addError("No tab completion possible")
            return

        QQmlProperty.write(self.searchInputModel, "text", output)
        self.search()

    def search(self):
        if self.chosenEntry is not None:
            self.searchChosenEntry()
            return

        currentIndex = QQmlProperty.read(self.resultListModel, "currentIndex")
        if currentIndex == -1 or len(self.filteredList) < currentIndex + 1:
            currentItem = None
        else:
            currentItem = self.filteredList[currentIndex]

        self.filteredList = []
        commandList = []

        searchStrings = QQmlProperty.read(self.searchInputModel, "text").lower().split(" ")
        for entry in self.entryList:
            if all(searchString in entry.lower() for searchString in searchStrings):
                self.filteredList.append(entry)

        self.resultListModelMaxIndex = len(self.filteredList) - 1
        self.context.setContextProperty("resultListModelMaxIndex", self.resultListModelMaxIndex)

        for command in self.commandsText:
            if searchStrings[0] in command:
                commandList.append(command)

        if len(self.filteredList) == 0 and len(commandList) > 0:
            self.filteredList = commandList
            for entry in self.entryList:
                if any(searchString in entry.lower() for searchString in searchStrings[1:]):
                    self.filteredList.append(entry)

            self.context.setContextProperty("resultListModelCommandMode", True)
        else:
            self.filteredList += commandList
            self.context.setContextProperty("resultListModelCommandMode", False)

        self.resultListModelList = QStringListModel(self.filteredList)
        self.context.setContextProperty("resultListModel", self.resultListModelList)

        if self.resultListModelMaxIndex == -1:
            currentIndex = -1
        elif currentItem is None:
            currentIndex = 0
        else:
            try:
                currentIndex = self.filteredList.index(currentItem)
            except ValueError:
                currentIndex = 0

        QQmlProperty.write(self.resultListModel, "currentIndex", currentIndex)

    def searchChosenEntry(self):
        # Ensure this entry still exists
        if self.chosenEntry not in self.entryList:
            self.addError(self.chosenEntry + " is no longer available")
            self.chosenEntry = None
            QQmlProperty.write(self.searchInputModel, "text", "")
            self.search()
            return

        if len(self.filteredList) == 0:
            currentItem = None
        else:
            currentIndex = QQmlProperty.read(self.resultListModel, "currentIndex")
            currentItem = self.filteredList[currentIndex]

        searchStrings = QQmlProperty.read(self.searchInputModel, "text").lower().split(" ")

        self.filteredList = []

        for entry in self.chosenEntryList:
            if any(searchString in entry.lower() for searchString in searchStrings):
                self.filteredList.append(entry)

        try:
            currentIndex = self.filteredList.index(currentItem)
        except ValueError:
            currentIndex = 0

        self.resultListModelList = QStringListModel(self.filteredList)
        self.context.setContextProperty("resultListModel", self.resultListModelList)

        QQmlProperty.write(self.resultListModel, "currentIndex", currentIndex)

    def select(self):
        if self.chosenEntry is not None:
            self.selectField()
            return

        if len(self.filteredList) == 0:
            return

        currentIndex = QQmlProperty.read(self.resultListModel, "currentIndex")

        if currentIndex == -1:
            commandTyped = QQmlProperty.read(self.searchInputModel, "text").split(" ")
            if commandTyped[0] not in self.module.getSupportedCommands():
                return

            result = self.module.runCommand(commandTyped, printOnSuccess=True)

            if result is not None:
                QQmlProperty.write(self.searchInputModel, "text", "")

            return

        self.chosenEntry = self.filteredList[currentIndex]
        entryContent = self.module.getAllEntryFields(self.chosenEntry)

        if len(entryContent) == 1:
            self.module.copyEntryToClipboard(self.chosenEntry)
            self.window.close()
            return

        # The first line is most likely the password. Do not show this on the
        # screen
        entryContent[0] = "********"

        # If the password entry has more than one line, fill the result list
        # with all lines, so the user can choose the line they want to copy to
        # the clipboard
        self.chosenEntryList = entryContent
        self.filteredList = entryContent

        self.resultListModelList = QStringListModel(self.filteredList)
        self.context.setContextProperty("resultListModel", self.resultListModelList)
        self.resultListModelMaxIndex = len(self.filteredList) - 1
        self.context.setContextProperty("resultListModelMaxIndex", self.resultListModelMaxIndex)
        QQmlProperty.write(self.resultListModel, "currentIndex", 0)
        QQmlProperty.write(self.searchInputModel, "text", "")

    def selectField(self):
        if len(self.filteredList) == 0:
            return

        currentIndex = QQmlProperty.read(self.resultListModel, "currentIndex")
        if self.filteredList[currentIndex] == "********":
            self.module.copyEntryToClipboard(self.chosenEntry)
            self.window.close()
            return

        # Only copy the final part. For example, if the entry is named
        # "URL: https://example.org/", only copy "https://example.org/" to the
        # clipboard
        copyStringParts = self.filteredList[currentIndex].split(": ", 1)

        copyString = copyStringParts[1] if len(copyStringParts) > 1 else copyStringParts[0]

        # Use the same clipboard that password store is set to use (untested)
        selection = os.getenv("PASSWORD_STORE_X_SELECTION", "clipboard")

        proc = Popen(["xclip", "-selection", selection], stdin=PIPE)
        proc.communicate(copyString.encode("ascii"))
        self.window.close()
        return


class InputDialog(QDialog):
    def __init__(self, question, text, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Pext")

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(question))
        self.textEdit = QTextEdit(self)
        self.textEdit.setPlainText(text)
        layout.addWidget(self.textEdit)
        button = QDialogButtonBox(QDialogButtonBox.Ok)
        button.accepted.connect(self.accept)
        layout.addWidget(button)

    def show(self):
        result = self.exec_()
        return (self.textEdit.toPlainText(), result == QDialog.Accepted)


class Window(QDialog):
    def __init__(self, vm, settings, parent=None):
        super().__init__(parent)

        self.engine = QQmlApplicationEngine(self)

        self.vm = vm

        context = self.engine.rootContext()
        context.setContextProperty("resultListModel", self.vm.resultListModelList)
        context.setContextProperty("resultListModelMaxIndex", self.vm.resultListModelMaxIndex)
        context.setContextProperty("resultListModelCommandMode", False)
        context.setContextProperty("messageListModelList", self.vm.messageListModelList)

        self.engine.load(QUrl.fromLocalFile(os.path.dirname(os.path.realpath(__file__)) + "/main.qml"))

        self.window = self.engine.rootObjects()[0]

        escapeShortcut = self.window.findChild(QObject, "escapeShortcut")
        tabShortcut = self.window.findChild(QObject, "tabShortcut")
        searchInputModel = self.window.findChild(QObject, "searchInputModel")
        resultListModel = self.window.findChild(QObject, "resultListModel")
        clearOldMessagesTimer = self.window.findChild(QObject, "clearOldMessagesTimer")

        self.vm.bindContext(context, self, searchInputModel, resultListModel)

        escapeShortcut.activated.connect(self.vm.goUp)
        tabShortcut.activated.connect(self.vm.tabComplete)

        searchInputModel.textChanged.connect(self.vm.search)
        searchInputModel.accepted.connect(self.vm.select)

        clearOldMessagesTimer.triggered.connect(self.vm.clearOldMessages)

    def show(self):
        self.window.show()
        self.activateWindow()

    def close(self):
        if not settings['closeWhenDone']:
            self.window.hide()
            QQmlProperty.write(self.vm.searchInputModel, "text", "")
            self.vm.chosenEntry = None
            self.vm.search()
        else:
            sys.exit(0)


def loadSettings(argv):
    # Default options
    settings = {'binary': None, 'closeWhenDone': False}

    try:
        opts, args = getopt.getopt(argv, "hb:s:", ["help", "binary=", "close-when-done", "module="])
    except getopt.GetoptError as err:
        print("{}\n".format(err))
        usage()
        sys.exit(1)

    for opt, args in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit()
        elif opt == "--close-when-done":
            settings['closeWhenDone'] = True
        elif opt in ("-s", "--module"):
            settings['module'] = args
        elif opt in ("-b", "--binary"):
            settings['binary'] = args

    return settings


def usage():
    print('''Options:

--binary          : choose the name of the binary to use. Defaults to 'pass' for
                    the pass module and todo.sh for the todo.sh module. Paths
                    are allowed.

--close-when-done : close after completing an action such as copying
                    a password or closing the application (through
                    escape or (on most systems) Alt+F4) instead of
                    staying in memory. This also allows multiple
                    instances to be ran at once.

--module          : name the module to use.''')


def initPersist(module):
    # Ensure only one Pext instance is running. If one already exists,
    # signal it to open the password selection window.
    # This way, we can keep the password list in memory and start up extra
    # quickly.
    pidfile = "/tmp/pext-" + module + ".pid"

    if os.path.isfile(pidfile):
        # Notify the main process
        try:
            os.kill(int(open(pidfile, 'r').read()), signal.SIGUSR1)
            sys.exit()
        except ProcessLookupError:
            # Pext closed, but did not clean up its pidfile
            pass

    # We are the only instance, claim our pidfile
    pid = str(os.getpid())
    open(pidfile, 'w').write(pid)

    # Return the filename to delete it later
    return pidfile


def mainLoop(app, q, vm, window):
    while True:
        try:
            action = q.get_nowait()
            if action[0] == Action.addMessage:
                vm.addMessage(action[1])
            elif action[0] == Action.addError:
                vm.addError(action[1])
            elif action[0] == Action.prependEntry:
                vm.entryList = [action[1]] + vm.entryList
            elif action[0] == Action.removeEntry:
                vm.entryList.remove(action[1])
            elif action[0] == Action.replaceEntryList:
                vm.entryList = action[1]
            elif action[0] == Action.setFilter:
                QQmlProperty.write(vm.searchInputModel, "text", action[1])
            elif action[0] == Action.askQuestionDefaultYes:
                answer = QMessageBox.question(window, "Pext", action[1], QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                vm.module.processResponse(True if (answer == QMessageBox.Yes) else False)
            elif action[0] == Action.askQuestionDefaultNo:
                answer = QMessageBox.question(window, "Pext", action[1], QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                vm.module.processResponse(True if (answer == QMessageBox.Yes) else False)
            elif action[0] == Action.askInput:
                answer, ok = QInputDialog.getText(window, "Pext", action[1])
                vm.module.processResponse(answer if ok else None)
            elif action[0] == Action.askInputPassword:
                answer, ok = QInputDialog.getText(window, "Pext", action[1], QLineEdit.Password)
                vm.module.processResponse(answer if ok else None)
            elif action[0] == Action.askInputMultiLine:
                dialog = InputDialog(action[1], action[2] if action[2] else "", window)
                answer, ok = dialog.show()
                vm.module.processResponse(answer if ok else None)
            else:
                print('WARN: Module requested unknown action {}'.format(action[0]))

            vm.search()
            window.update()
            q.task_done()
        except Empty:
            app.processEvents()
            time.sleep(0.01)
            continue
        except Exception as e:
            print('WARN: Module caused exception {} with call {}'.format(e, action))

if __name__ == "__main__":
    settings = loadSettings(sys.argv[1:])

    if 'module' not in settings:
        print('A module must be given.')
        sys.exit(2)

    moduleImport = __import__('module_' + settings['module'].replace('.', '_'), fromlist=['Module'])

    Module = getattr(moduleImport, 'Module')

    # Ensure the module implements the base
    assert issubclass(Module, ModuleBase)

    if not settings['closeWhenDone']:
        pidfile = initPersist(settings['module'])

    # Set up a queue so that the module can communicate with the main thread
    q = Queue()

    app = QApplication(sys.argv)

    # Set up the window
    viewModel = ViewModel()
    window = Window(viewModel, settings)

    # This will (correctly) fail if the module doesn't implement all necessary
    # functionality
    module = Module(settings['binary'], q)

    viewModel.bindModule(module)

    # Handle signal
    signalHandler = SignalHandler(window)
    signal.signal(signal.SIGUSR1, signalHandler.handle)

    # Run until the app quits, then clean up
    window.show()
    mainLoop(app, q, viewModel, window)
    sys.exit(app.exec_())
    module.stop()

    if not settings['closeWhenDone']:
        os.unlink(pidfile)
