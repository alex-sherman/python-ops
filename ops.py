import glob
import yaml
import os
import json
from collections import defaultdict
import argparse
import re
import subprocess

def var_lookup(name, env_vars, prefixes = None):
    if prefixes:
        for prefix in prefixes:
            if prefix + name in env_vars:
                return env_vars[prefix + name]
    if name in env_vars:
        return env_vars[name]
    return None

def str_replace(string, comp = None):
    reg = re.compile(r'(?<!\\){(.*?)(?<!\\)}')
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
                prefixes = ["^" + comp + "."] + prefixes + [comp + "."]
        value = var_lookup(var, env_vars, prefixes)
        if not value:
            print("Failed to find variable {} {}".format(comp, var))
        string = string[:match.span()[0]] + str(value) + string[match.span()[1]:]
    string = string.replace("\\{", "{").replace("\\}", "}")
    return string

def parse_cmd(cmd, comp = None):
    if 'cmd' in cmd and type(cmd['cmd']) is str:
        output = {'comp': comp, 'cmd': str_replace(cmd['cmd'], comp)}
        if comp:
            output['path'] = paths[comp]
        yield output
    if 'steps' in cmd and type(cmd['steps']) is list:
        for step in cmd['steps']:
            yield from get_cmds(step, comp)

def get_cmds(command, comp = None):
    if '.' in command:
        comp, command = command.split('.')

    comps = all_commands[command]
    if comp:
        comp_cmds = comps[None] + comps[comp]
        return [part for cmd in comp_cmds for part in parse_cmd(cmd, comp)]
    else:
        return [part for comp, cmds in comps.items() for cmd in cmds for part in parse_cmd(cmd, comp)]

paths = {}
all_commands = defaultdict(lambda: defaultdict(list))
variables = defaultdict(dict)
webhooks = []
files = []

parser = argparse.ArgumentParser(description='Ops commands')
parser.add_argument('command', nargs="?", help='The command to run')
parser.add_argument('--vars', action="store_true", help='Print the variables which will be used')
parser.add_argument('--env', help='Specify an environment (defaults to \'default\')')
parser.add_argument('--cmds', action="store_true", help='Print the commands that will be run')
parser.add_argument('--dir', '-d', help='The directory to operate in')
parser.add_argument('--files', action="store_true", help='List files that will be templated')
args = parser.parse_args()

if args.dir:
    os.chdir(args.dir)

owd = os.getcwd()

files = list([filename for filename in glob.iglob('**/*.ops', recursive=True)])

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
        if "webhooks" in comp:
            for hook in comp["webhooks"]:
                if "name" not in hook: hook["name"] = None
                if "full_name" not in hook: hook["full_name"] = None
                webhooks.append(hook)

env_vars = variables["default"]

if args.env:
    for var in variables[args.env]:
        env_vars[var] = variables[args.env][var]

if args.vars:
    print(json.dumps(env_vars, indent = 2))
    exit(0)

if args.files:
    print(json.dumps(files, indent = 2))
    exit(0)

def rewrite_files(files):
    for filename in files:
        with open(filename[:-4], 'w') as newf:
            with open(filename) as f:
                for line in f.readlines():
                    newf.write(str_replace(line, None))

def run_cmds(cmds):
    for cmd in cmds:
        os.chdir(owd)
        if 'path' in cmd:
            os.chdir(cmd['path'])
        print(cmd["cmd"])
        ret = subprocess.call(cmd["cmd"], shell=True)

def run_webhooks():
    from flask import Flask, request
    from threading import Thread
    app = Flask(__name__)
    cur_thread = None

    @app.route('/', methods=['POST'])
    def webhook():
        data = request.get_json()
        if "repository" not in data or "ref" not in data:
            return "Not a push event"
        full_name = data["repository"]["full_name"]
        name = data["repository"]["name"]
        branch = data["ref"].split('/')[-1]
        webhook = next((h for h in webhooks if h["full_name"] == full_name or h["name"] == name), None)
        if not webhook:
            return "No hook defined"
        def thread_run(cmds):
            rewrite_files(files)
            run_cmds(cmds)
        Thread(target=thread_run, args=[parse_cmd(webhook)]).start()
        return "OK"

    app.run('0.0.0.0', 9000)


if args.command:
    if args.command == "webhook":
        run_webhooks()
        exit(0)
    cmds = get_cmds(args.command)
    if args.cmds:
        print(json.dumps(cmds, indent = 2))
        exit(0)

    rewrite_files(files)
    run_cmds(cmds)