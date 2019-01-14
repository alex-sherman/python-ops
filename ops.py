import glob
import yaml
import os
import json
from collections import defaultdict
import argparse
import re

def var_lookup(name, env_vars, prefixes = None):
    if prefixes:
        for prefix in prefixes:
            if prefix + name in env_vars:
                return env_vars[prefix + name]
    if name in env_vars:
        return env_vars[name]
    return None

def str_replace(string, comp = None):
    reg = re.compile(r'{(.*?)}')
    while True:
        match = reg.search(string)
        if not match: break
        var = match.group(1)
        prefixes = []
        if var[0] == '.':
            var = comp + '.' + var[1:]
        elif var[0] != '^':
            prefixes = ["^"]
            if comp:
                prefixes.append(comp + ".")
        value = var_lookup(var, env_vars, prefixes)
        if not value:
            print("Failed to find variable {} {}".format(comp, var))
        string = string[:match.span()[0]] + value + string[match.span()[1]:]
    return string

def get_cmds(command):
    def parse_cmd(cmd, comp = None):
        if 'cmd' in cmd and type(cmd['cmd']) is str:
            yield {'comp': comp, 'path': paths[comp], 'cmd': str_replace(cmd['cmd'], comp)}
        if 'steps' in cmd and type(cmd['steps']) is list:
            for step in cmd['steps']:
                yield from get_cmds(step)
    comps = all_commands[command]
    return [part for comp, cmds in comps.items() for cmd in cmds for part in parse_cmd(cmd, comp)]


paths = {}
all_commands = defaultdict(lambda: defaultdict(list))
variables = defaultdict(dict)

#print(json.dumps(list(paths.keys()), indent = 2))

parser = argparse.ArgumentParser(description='Ops commands')
parser.add_argument('command', nargs="?", help='The command to run')
parser.add_argument('--vars', action="store_true", help='Print the variables which will be used')
parser.add_argument('--env', help='Specify an environment (defaults to \'default\')')
parser.add_argument('--cmds', action="store_true", help='Print the commands that will be run')
parser.add_argument('--dir', '-d', help='The directory to search in')
args = parser.parse_args()

if args.dir:
    os.chdir(args.dir)

for filename in glob.iglob('**/ops.yaml', recursive=True):
    with open(filename) as f:
        comp = yaml.load(f)
        name = None
        if "name" in comp:
            name = comp["name"]
            paths[name] = os.path.dirname(filename)
        if "cmds" in comp:
            for cmd in comp["cmds"]:
                for part in comp["cmds"][cmd]:
                    all_commands[cmd][name].append(part)
        if "vars" in comp:
            for env in comp["vars"]:
                env_vars = comp["vars"][env]
                for var in env_vars:
                    if name:
                        varName = name + "." + var
                    else:
                        varName = var
                    variables[env][varName] = env_vars[var]

env_vars = variables["default"]

if args.env:
    for var in variables[args.env]:
        env_vars[var] = variables[args.env][var]

if args.vars:
    print(json.dumps(env_vars, indent = 2))
    exit(0)

if args.cmds:
    print(json.dumps(list(all_commands.keys()), indent = 2))
    exit(0)

if args.command:
    print(json.dumps(get_cmds(args.command), indent = 2))
