# Copyright 2014-2016 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This is a helper script for IDE developers. It allows you to
extract information such as list of targets, files, compiler flags,
tests and so on. All output is in JSON for simple parsing.

Currently only works for the Ninja backend. Others use generated
project files and don't need this info."""

import json
from . import build, mtest, coredata as cdata
from . import mesonlib
from .backend import ninjabackend
import argparse
import sys, os
import pathlib

def buildparser():
    parser = argparse.ArgumentParser(prog='meson introspect')
    parser.add_argument('--targets', action='store_true', dest='list_targets', default=False,
                        help='List top level targets.')
    parser.add_argument('--installed', action='store_true', dest='list_installed', default=False,
                        help='List all installed files and directories.')
    parser.add_argument('--target-files', action='store', dest='target_files', default=None,
                        help='List source files for a given target.')
    parser.add_argument('--buildsystem-files', action='store_true', dest='buildsystem_files', default=False,
                        help='List files that make up the build system.')
    parser.add_argument('--buildoptions', action='store_true', dest='buildoptions', default=False,
                        help='List all build options.')
    parser.add_argument('--tests', action='store_true', dest='tests', default=False,
                        help='List all unit tests.')
    parser.add_argument('--benchmarks', action='store_true', dest='benchmarks', default=False,
                        help='List all benchmarks.')
    parser.add_argument('--dependencies', action='store_true', dest='dependencies', default=False,
                        help='List external dependencies.')
    parser.add_argument('--projectinfo', action='store_true', dest='projectinfo', default=False,
                        help='Information about projects.')
    parser.add_argument('builddir', nargs='?', default='.', help='The build directory')
    return parser

def determine_installed_path(target, installdata):
    install_target = None
    for i in installdata.targets:
        if os.path.basename(i.fname) == target.get_filename(): # FIXME, might clash due to subprojects.
            install_target = i
            break
    if install_target is None:
        raise RuntimeError('Something weird happened. File a bug.')
    outname = os.path.join(installdata.prefix, i.outdir, os.path.basename(i.fname))
    # Normalize the path by using os.path.sep consistently, etc.
    # Does not change the effective path.
    return str(pathlib.PurePath(outname))


def list_installed(installdata):
    res = {}
    if installdata is not None:
        for t in installdata.targets:
            res[os.path.join(installdata.build_dir, t.fname)] = \
                os.path.join(installdata.prefix, t.outdir, os.path.basename(t.fname))
        for path, installpath, unused_prefix in installdata.data:
            res[path] = os.path.join(installdata.prefix, installpath)
        for path, installdir in installdata.headers:
            res[path] = os.path.join(installdata.prefix, installdir, os.path.basename(path))
        for path, installpath in installdata.man:
            res[path] = os.path.join(installdata.prefix, installpath)
    print(json.dumps(res))


def list_targets(coredata, builddata, installdata):
    tlist = []
    for (idname, target) in builddata.get_targets().items():
        t = {'name': target.get_basename(), 'id': idname}
        fname = target.get_filename()
        if isinstance(fname, list):
            fname = [os.path.join(target.subdir, x) for x in fname]
        else:
            fname = os.path.join(target.subdir, fname)
        t['filename'] = fname
        if isinstance(target, build.Executable):
            typename = 'executable'
        elif isinstance(target, build.SharedLibrary):
            typename = 'shared library'
        elif isinstance(target, build.StaticLibrary):
            typename = 'static library'
        elif isinstance(target, build.CustomTarget):
            typename = 'custom'
        elif isinstance(target, build.RunTarget):
            typename = 'run'
        else:
            typename = 'unknown'
        t['type'] = typename
        if installdata and target.should_install():
            t['installed'] = True
            t['install_filename'] = determine_installed_path(target, installdata)
        else:
            t['installed'] = False
        t['build_by_default'] = target.build_by_default
        tlist.append(t)
    print(json.dumps(tlist))

def list_target_files(target_name, coredata, builddata):
    try:
        t = builddata.targets[target_name]
        sources = t.sources + t.extra_files
    except KeyError:
        print("Unknown target %s." % target_name)
        sys.exit(1)
    out = []
    for i in sources:
        if isinstance(i, mesonlib.File):
            i = os.path.join(i.subdir, i.fname)
        out.append(i)
    print(json.dumps(out))

def list_buildoptions(coredata, builddata):
    optlist = []
    add_keys(optlist, coredata.user_options)
    add_keys(optlist, coredata.compiler_options)
    add_keys(optlist, coredata.base_options)
    add_keys(optlist, coredata.builtins)
    print(json.dumps(optlist))

def add_keys(optlist, options):
    keys = list(options.keys())
    keys.sort()
    for key in keys:
        opt = options[key]
        optdict = {'name': key, 'value': opt.value}
        if isinstance(opt, cdata.UserStringOption):
            typestr = 'string'
        elif isinstance(opt, cdata.UserBooleanOption):
            typestr = 'boolean'
        elif isinstance(opt, cdata.UserComboOption):
            optdict['choices'] = opt.choices
            typestr = 'combo'
        elif isinstance(opt, cdata.UserIntegerOption):
            typestr = 'integer'
        elif isinstance(opt, cdata.UserArrayOption):
            typestr = 'array'
        else:
            raise RuntimeError("Unknown option type")
        optdict['type'] = typestr
        optdict['description'] = opt.description
        optlist.append(optdict)

def list_buildsystem_files(builddata):
    src_dir = builddata.environment.get_source_dir()
    # I feel dirty about this. But only slightly.
    filelist = []
    for root, _, files in os.walk(src_dir):
        for f in files:
            if f == 'meson.build' or f == 'meson_options.txt':
                filelist.append(os.path.relpath(os.path.join(root, f), src_dir))
    print(json.dumps(filelist))

def list_deps(coredata):
    result = []
    for d in coredata.deps.values():
        if d.found():
            result += [{'name': d.name,
                        'compile_args': d.get_compile_args(),
                        'link_args': d.get_link_args()}]
    print(json.dumps(result))

def list_tests(testdata):
    result = []
    for t in testdata:
        to = {}
        if isinstance(t.fname, str):
            fname = [t.fname]
        else:
            fname = t.fname
        to['cmd'] = fname + t.cmd_args
        if isinstance(t.env, build.EnvironmentVariables):
            to['env'] = t.env.get_env(os.environ)
        else:
            to['env'] = t.env
        to['name'] = t.name
        to['workdir'] = t.workdir
        to['timeout'] = t.timeout
        to['suite'] = t.suite
        to['is_parallel'] = t.is_parallel
        result.append(to)
    print(json.dumps(result))

def list_projinfo(builddata):
    result = {'name': builddata.project_name, 'version': builddata.project_version}
    subprojects = []
    for k, v in builddata.subprojects.items():
        c = {'name': k,
             'version': v}
        subprojects.append(c)
    result['subprojects'] = subprojects
    print(json.dumps(result))

def run(args):
    datadir = 'meson-private'
    options = buildparser().parse_args(args)
    if options.builddir is not None:
        datadir = os.path.join(options.builddir, datadir)
    if not os.path.isdir(datadir):
        print('Current directory is not a build dir. Please specify it or '
              'change the working directory to it.')
        return 1

    coredata = cdata.load(options.builddir)
    builddata = build.load(options.builddir)
    testdata = mtest.load_tests(options.builddir)
    benchmarkdata = mtest.load_benchmarks(options.builddir)

    # Install data is only available with the Ninja backend
    try:
        installdata = ninjabackend.load(options.builddir)
    except FileNotFoundError:
        installdata = None

    if options.list_targets:
        list_targets(coredata, builddata, installdata)
    elif options.list_installed:
        list_installed(installdata)
    elif options.target_files is not None:
        list_target_files(options.target_files, coredata, builddata)
    elif options.buildsystem_files:
        list_buildsystem_files(builddata)
    elif options.buildoptions:
        list_buildoptions(coredata, builddata)
    elif options.tests:
        list_tests(testdata)
    elif options.benchmarks:
        list_tests(benchmarkdata)
    elif options.dependencies:
        list_deps(coredata)
    elif options.projectinfo:
        list_projinfo(builddata)
    else:
        print('No command specified')
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(run(sys.argv[1:]))
