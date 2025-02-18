# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import argparse
import sys
from collections import deque
from glob import glob
from locale import getpreferredencoding
from os import listdir
from os.path import exists, isdir, isfile, join

import conda.config as config
from conda.compat import PY3
from conda.cli.common import add_parser_channels, Completer
from conda.cli.conda_argparse import ArgumentParser

from conda_build import __version__, exceptions
from conda_build.index import update_index
from conda.install import delete_trash
on_win = (sys.platform == 'win32')

all_versions = {
    'python': [26, 27, 33, 34],
    'numpy': [16, 17, 18, 19],
    'perl': None,
    'R': None,
    }

class RecipeCompleter(Completer):
    def _get_items(self):
        completions = []
        for path in listdir('.'):
            if isdir(path) and isfile(join(path, 'meta.yaml')):
                completions.append(path)
        if isfile('meta.yaml'):
            completions.append('.')
        return completions

# These don't represent all supported versions. It's just for tab completion.

class PythonVersionCompleter(Completer):
    def _get_items(self):
        return ['all'] + [str(i/10) for i in all_versions['python']]

class NumPyVersionCompleter(Completer):
    def _get_items(self):
        return ['all'] + [str(i/10) for i in all_versions['numpy']]

class RVersionsCompleter(Completer):
    def _get_items(self):
        return ['3.1.2', '3.1.3', '3.2.0', '3.2.1']

def main():
    p = ArgumentParser(
        description="""
Tool for building conda packages. A conda package is a binary tarball
containing system-level libraries, Python modules, executable programs, or
other components. conda keeps track of dependencies between packages and
platform specifics, making it simple to create working environments from
different sets of packages."""
    )
    p.add_argument(
        '-V', '--version',
        action='version',
        help='Show the conda-build version number and exit.',
        version = 'conda-build %s' % __version__,
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Only check (validate) the recipe.",
    )
    p.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest='binstar_upload',
        default=config.binstar_upload,
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest='binstar_upload',
        default=config.binstar_upload,
    )
    p.add_argument(
        "--no-include-recipe",
        action="store_false",
        help="Don't include the recipe inside the built package.",
        dest='include_recipe',
        default=True,
    )
    p.add_argument(
        "--output",
        action="store_true",
        help="Output the conda package filename which would have been "
               "created and exit.",
    )
    p.add_argument(
        '-s', "--source",
        action="store_true",
        help="Only obtain the source (but don't build).",
    )
    p.add_argument(
        '-t', "--test",
        action="store_true",
        help="Test package (assumes package is already build).",
    )
    p.add_argument(
        'recipe',
        action="store",
        metavar='RECIPE_PATH',
        nargs='+',
        choices=RecipeCompleter(),
        help="Path to recipe directory.",
    )
    p.add_argument(
        '--no-test',
        action='store_true',
        dest='notest',
        help="Do not test the package.",
    )
    p.add_argument(
        '-b', '--build-only',
        action="store_true",
        help="""Only run the build, without any post processing or
        testing. Implies --no-test and --no-anaconda-upload.""",
    )
    p.add_argument(
        '-p', '--post',
        action="store_true",
        help="Run the post-build logic. Implies --no-test and --no-anaconda-upload.",
    )
    p.add_argument(
        '--skip-existing',
        action='store_true',
        help="""Skip recipes for which there already exists an existing build
        (locally or in the channels). """
        )
    p.add_argument(
        '-q', "--quiet",
        action="store_true",
        help="do not display progress bar",
    )
    p.add_argument(
        '--python',
        action="append",
        help="""Set the Python version used by conda build. Can be passed
        multiple times to build against multiple versions. Can be 'all' to
    build against all known versions (%r)""" % [i for i in
    PythonVersionCompleter() if '.' in i],
        metavar="PYTHON_VER",
        choices=PythonVersionCompleter(),
    )
    p.add_argument(
        '--perl',
        action="append",
        help="""Set the Perl version used by conda build. Can be passed
        multiple times to build against multiple versions.""",
        metavar="PERL_VER",
    )
    p.add_argument(
        '--numpy',
        action="append",
        help="""Set the NumPy version used by conda build. Can be passed
        multiple times to build against multiple versions. Can be 'all' to
    build against all known versions (%r)""" % [i for i in
    NumPyVersionCompleter() if '.' in i],
        metavar="NUMPY_VER",
        choices=NumPyVersionCompleter(),
    )
    p.add_argument(
        '--R',
        action="append",
        help="""Set the R version used by conda build. Can be passed
        multiple times to build against multiple versions.""",
        metavar="R_VER",
        choices=RVersionsCompleter(),
    )
    add_parser_channels(p)
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def handle_binstar_upload(path, args):
    import subprocess
    from conda_build.external import find_executable

    if args.binstar_upload is None:
        args.yes = False
        args.dry_run = False
#        upload = common.confirm_yn(
#            args,
#            message="Do you want to upload this "
#            "package to binstar", default='yes', exit_no=False)
        upload = False
    else:
        upload = args.binstar_upload

    no_upload_message = """\
# If you want to upload this package to anaconda.org later, type:
#
# $ binstar upload %s
#
# To have conda build upload to binstar automatically, use
# $ conda config --set binstar_upload yes
""" % path
    if not upload:
        print(no_upload_message)
        return

    binstar = find_executable('anaconda')
    if binstar is None:
        print(no_upload_message)
        sys.exit('''
Error: cannot locate anaconda command (required for upload)
# Try:
# $ conda install anaconda-client
''')
    print("Uploading to anaconda.org")
    args = [binstar, 'upload', path]
    try:
        subprocess.call(args)
    except:
        print(no_upload_message)
        raise


def check_external():
    import os
    import conda_build.external as external

    if sys.platform.startswith('linux'):
        patchelf = external.find_executable('patchelf')
        if patchelf is None:
            sys.exit("""\
Error:
    Did not find 'patchelf' in: %s
    'patchelf' is necessary for building conda packages on Linux with
    relocatable ELF libraries.  You can install patchelf using conda install
    patchelf.
""" % (os.pathsep.join(external.dir_paths)))


def execute(args, parser):
    import sys
    import shutil
    import tarfile
    import tempfile
    from os.path import abspath, isdir, isfile

    from conda.lock import Locked
    import conda_build.build as build
    import conda_build.source as source
    from conda_build.config import config
    from conda_build.metadata import MetaData

    check_external()
    channel_urls = args.channel or ()

    if on_win:
        # needs to happen before any c extensions are imported that might be
        # hard-linked by files in the trash. one of those is markupsafe, used
        # by jinja2. see https://github.com/conda/conda-build/pull/520
        assert 'markupsafe' not in sys.modules
        delete_trash(None)

    conda_version = {
        'python': 'CONDA_PY',
        'numpy': 'CONDA_NPY',
        'perl': 'CONDA_PERL',
        'R': 'CONDA_R',
        }

    for lang in ['python', 'numpy', 'perl', 'R']:
        versions = getattr(args, lang)
        if not versions:
            continue
        if versions == ['all']:
            if all_versions[lang]:
                versions = all_versions[lang]
            else:
                parser.error("'all' is not supported for --%s" % lang)
        if len(versions) > 1:
            for ver in versions[:]:
                setattr(args, lang, [str(ver)])
                execute(args, parser)
                # This is necessary to make all combinations build.
                setattr(args, lang, versions)
            return
        else:
            version = int(versions[0].replace('.', ''))
            setattr(config, conda_version[lang], version)
        if not len(str(version)) == 2 and lang in ['python', 'numpy']:
            if all_versions[lang]:
                raise RuntimeError("%s must be major.minor, like %s, not %s" %
                    (conda_version[lang], all_versions[lang][-1]/10, version))
            else:
                raise RuntimeError("%s must be major.minor, not %s" %
                    (conda_version[lang], version))

    if args.skip_existing:
        update_index(config.bldpkgs_dir)
        index = build.get_build_index(clear_cache=True,
            channel_urls=channel_urls,
            override_channels=args.override_channels)

    already_built = []
    with Locked(config.croot):
        recipes = deque(args.recipe)
        while recipes:
            arg = recipes.popleft()
            try_again = False
            # Don't use byte literals for paths in Python 2
            if not PY3:
                arg = arg.decode(getpreferredencoding() or 'utf-8')
            if isfile(arg):
                if arg.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2')):
                    recipe_dir = tempfile.mkdtemp()
                    t = tarfile.open(arg, 'r:*')
                    t.extractall(path=recipe_dir)
                    t.close()
                    need_cleanup = True
                else:
                    print("Ignoring non-recipe: %s" % arg)
                    continue
            else:
                recipe_dir = abspath(arg)
                need_cleanup = False

            if not isdir(recipe_dir):
                sys.exit("Error: no such directory: %s" % recipe_dir)

            try:
                m = MetaData(recipe_dir)
                if m.get_value('build/noarch_python'):
                    config.noarch = True
            except exceptions.YamlParsingError as e:
                sys.stderr.write(e.error_msg())
                sys.exit(1)
            binstar_upload = False
            if args.check and len(args.recipe) > 1:
                print(m.path)
            m.check_fields()
            if args.check:
                continue
            if args.skip_existing:
                if m.pkg_fn() in index or m.pkg_fn() in already_built:
                    print("%s is already built, skipping." % m.dist())
                    continue
            if args.output:
                print(build.bldpkg_path(m))
                continue
            elif args.test:
                build.test(m, verbose=not args.quiet,
                    channel_urls=channel_urls, override_channels=args.override_channels)
            elif args.source:
                source.provide(m.path, m.get_section('source'))
                print('Source tree in:', source.get_dir())
            else:
                # This loop recursively builds dependencies if recipes exist
                if args.build_only:
                    post = False
                    args.notest = True
                    args.binstar_upload = False
                elif args.post:
                    post = True
                    args.notest = True
                    args.binstar_upload = False
                else:
                    post = None
                try:
                    build.build(m, verbose=not args.quiet, post=post,
                        channel_urls=channel_urls,
                        override_channels=args.override_channels, include_recipe=args.include_recipe)
                except RuntimeError as e:
                    error_str = str(e)
                    if error_str.startswith('No packages found') or error_str.startswith('Could not find some'):
                        # Build dependency if recipe exists
                        dep_pkg = error_str.split(': ')[1]
                        # Handle package names that contain version deps.
                        if ' ' in dep_pkg:
                            dep_pkg = dep_pkg.split(' ')[0]
                        recipe_glob = glob(dep_pkg + '-[v0-9][0-9.]*')
                        if exists(dep_pkg):
                            recipe_glob.append(dep_pkg)
                        if recipe_glob:
                            recipes.appendleft(arg)
                            try_again = True
                            for recipe_dir in recipe_glob:
                                print(("Missing dependency {0}, but found" +
                                       " recipe directory, so building " +
                                       "{0} first").format(dep_pkg))
                                recipes.appendleft(recipe_dir)
                        else:
                            raise
                    else:
                        raise
                if try_again:
                    continue

                if not args.notest:
                    build.test(m, verbose=not args.quiet,
                        channel_urls=channel_urls, override_channels=args.override_channels)
                binstar_upload = True

            if need_cleanup:
                shutil.rmtree(recipe_dir)

            if binstar_upload:
                handle_binstar_upload(build.bldpkg_path(m), args)

            already_built.append(m.pkg_fn())

def args_func(args, p):
    try:
        args.func(args, p)
    except RuntimeError as e:
        if 'maximum recursion depth exceeded' in str(e):
            print_issue_message(e)
            raise
        sys.exit("Error: %s" % e)
    except Exception as e:
        print_issue_message(e)
        raise  # as if we did not catch it

def print_issue_message(e):
    if e.__class__.__name__ not in ('ScannerError', 'ParserError'):
        message = """\
An unexpected error has occurred, please consider sending the
following traceback to the conda GitHub issue tracker at:

    https://github.com/conda/conda-build/issues

Include the output of the command 'conda info' in your report.

"""
        print(message, file=sys.stderr)

if __name__ == '__main__':
    main()
