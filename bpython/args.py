# The MIT License
#
# Copyright (c) 2008 Bob Farrell
# Copyright (c) 2012-2021 Sebastian Ramacher
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""
Module to handle command line argument parsing, for all front-ends.
"""

import argparse
from typing import Tuple
import curtsies
import cwcwidth
import greenlet
import importlib.util
import logging
import os
import pygments
import requests
import sys
from pathlib import Path

from . import __version__, __copyright__
from .config import default_config_path, Config
from .translations import _

logger = logging.getLogger(__name__)


class ArgumentParserFailed(ValueError):
    """Raised by the RaisingOptionParser for a bogus commandline."""


class RaisingArgumentParser(argparse.ArgumentParser):
    def error(self, msg):
        raise ArgumentParserFailed()


def version_banner(base="bpython") -> str:
    return _("{} version {} on top of Python {} {}").format(
        base, __version__, sys.version.split()[0], sys.executable,
    )


def copyright_banner() -> str:
    return _("{} See AUTHORS.rst for details.").format(__copyright__)


def parse(args, extras=None, ignore_stdin=False) -> Tuple:
    """Receive an argument list - if None, use sys.argv - parse all args and
    take appropriate action. Also receive optional extra argument: this should
    be a tuple of (title, description, callback)
        title:          The title for the argument group
        description:    A full description of the argument group
        callback:       A callback that adds argument to the argument group

    e.g.:

    def callback(group):
        group.add_argument('-f', action='store_true', dest='f', help='Explode')
        group.add_argument('-l', action='store_true', dest='l', help='Love')

    parse(
        ['-i', '-m', 'foo.py'],
        (
            'Front end-specific options',
            'A full description of what these options are for',
            callback
        ),
    )


    Return a tuple of (config, options, exec_args) wherein "config" is the
    config object either parsed from a default/specified config file or default
    config options, "options" is the parsed options from
    ArgumentParser.parse_args, and "exec_args" are the args (if any) to be parsed
    to the executed file (if any).
    """
    if args is None:
        args = sys.argv[1:]

    parser = RaisingArgumentParser(
        usage=_(
            "Usage: %(prog)s [options] [file [args]]\n"
            "NOTE: If bpython sees an argument it does "
            "not know, execution falls back to the "
            "regular Python interpreter."
        )
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        type=Path,
        help=_("Use CONFIG instead of default config file."),
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help=_("Drop to bpython shell after running file instead of exiting."),
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help=_("Don't flush the output to stdout."),
    )
    parser.add_argument(
        "--version",
        "-V",
        action="store_true",
        help=_("Print version and exit."),
    )
    parser.add_argument(
        "--log-level",
        "-l",
        choices=("debug", "info", "warning", "error", "critical"),
        default="error",
        help=_("Set log level for logging"),
    )
    parser.add_argument(
        "--log-output", "-L", help=_("Log output file"),
    )

    if extras is not None:
        extras_group = parser.add_argument_group(extras[0], extras[1])
        extras[2](extras_group)

    # collect all the remaining arguments into a list
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help=_(
            "File to execute and additional arguments passed on to the executed script."
        ),
    )

    try:
        options = parser.parse_args(args)
    except ArgumentParserFailed:
        # Just let Python handle this
        os.execv(sys.executable, [sys.executable] + args)

    if options.version:
        print(version_banner())
        print(copyright_banner())
        raise SystemExit

    if not ignore_stdin and not (sys.stdin.isatty() and sys.stdout.isatty()):
        # Just let Python handle this
        os.execv(sys.executable, [sys.executable] + args)

    # Configure logging handler
    bpython_logger = logging.getLogger("bpython")
    curtsies_logger = logging.getLogger("curtsies")
    bpython_logger.setLevel(options.log_level.upper())
    curtsies_logger.setLevel(options.log_level.upper())
    if options.log_output:
        handler = logging.FileHandler(filename=options.log_output)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s: %(name)s: %(levelname)s: %(message)s"
            )
        )
        bpython_logger.addHandler(handler)
        curtsies_logger.addHandler(handler)
        bpython_logger.propagate = curtsies_logger.propagate = False
    else:
        bpython_logger.addHandler(logging.NullHandler())
        curtsies_logger.addHandler(logging.NullHandler())

    logger.info(f"Starting bpython {__version__}")
    logger.info(f"Python {sys.executable}: {sys.version_info}")
    logger.info(f"curtsies: {curtsies.__version__}")
    logger.info(f"cwcwidth: {cwcwidth.__version__}")
    logger.info(f"greenlet: {greenlet.__version__}")
    logger.info(f"pygments: {pygments.__version__}")
    logger.info(f"requests: {requests.__version__}")
    logger.info(
        "environment:\n{}".format(
            "\n".join(
                f"{key}: {value}"
                for key, value in sorted(os.environ.items())
                if key.startswith("LC")
                or key.startswith("LANG")
                or key == "TERM"
            )
        )
    )

    return Config(options.config), options, options.args


def exec_code(interpreter, args):
    """
    Helper to execute code in a given interpreter. args should be a [faked]
    sys.argv
    """
    with open(args[0]) as sourcefile:
        source = sourcefile.read()
    old_argv, sys.argv = sys.argv, args
    sys.path.insert(0, os.path.abspath(os.path.dirname(args[0])))
    spec = importlib.util.spec_from_loader("__console__", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["__console__"] = mod
    interpreter.locals.update(mod.__dict__)
    interpreter.locals["__file__"] = args[0]
    interpreter.runsource(source, args[0], "exec")
    sys.argv = old_argv
