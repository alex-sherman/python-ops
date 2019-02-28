import glob
import yaml
import os
import json
from collections import defaultdict
import argparse
import re
import subprocess

class State:
    def __init__(self):
        self.paths = {}
        self.all_commands = defaultdict(lambda: defaultdict(list))
        self.variables = defaultdict(lambda: defaultdict(dict))
        self.webhooks = []
        self.files = []
        self.owd = os.getcwd()

    def refresh(self):
        self.paths = {}
        self.all_commands = defaultdict(lambda: defaultdict(list))
        self.variables = defaultdict(lambda: defaultdict(dict))
        self.webhooks = []
        self.files = list([filename for filename in glob.iglob('**/*.ops', recursive=True)])

        os.chdir(self.owd)
        for filename in glob.iglob('**/ops.yaml', recursive=True):
            with open(filename) as f:
                comp = yaml.load(f)
                name = None
                if "name" in comp:
                    name = comp["name"]
                    self.paths[name] = os.path.dirname(filename)
                if "cmds" in comp:
                    for cmd in comp["cmds"]:
                        for part in comp["cmds"][cmd]:
                            self.all_commands[cmd][name].append(part)
                if "vars" in comp:
                    for env in comp["vars"]:
                        env_vars = comp["vars"][env]
                        for var in env_vars:
                            self.variables[env][name][var] = env_vars[var]
                if "webhooks" in comp:
                    for hook in comp["webhooks"]:
                        if "name" not in hook: hook["name"] = None
                        if "full_name" not in hook: hook["full_name"] = None
                        self.webhooks.append(hook)

    def rewrite_files(self, env):
        os.chdir(self.owd)
        for filename in self.files:
            with open(filename[:-4], 'w') as newf:
                with open(filename) as f:
                    for line in f.readlines():
                        newf.write(self.str_replace(line, None, env))

    def run_cmds(self, cmds):
        for cmd in cmds:
            os.chdir(self.owd)
            if 'path' in cmd:
                os.chdir(cmd['path'])
            print(cmd["cmd"])
            ret = subprocess.call(cmd["cmd"], shell=True)

    def var_lookup(self, name, comp, env):
        orig_name = name
        orig_comp = comp
        prefixes = []

        spec_comp = None
        if ':' in name:
            env, name = name.split(':')
        if '.' in name:
            spec_comp, name = name.split('.')
            if spec_comp != '':
                comp = spec_comp

        names = []
        if spec_comp == '':
            names = [(comp, name)]
        else:
            names = [(None, '^' + name), (comp, name)]
            if comp:
                names.append((None, comp + '.' + name))
        env_vars = self.variables[env]
        for _name in names:
            if _name[1] in env_vars[_name[0]]:
                return self.str_replace(env_vars[_name[0]][_name[1]], comp, env)
            if _name[1] in self.variables['default'][_name[0]]:
                return self.str_replace(self.variables['default'][_name[0]][_name[1]], comp, env)
        return None

    def str_replace(self, string, comp, env):
        reg = re.compile(r'(?<!\\){(.*?)(?<!\\)}')
        while True:
            match = reg.search(string)
            if not match: break
            var = match.group(1)
            value = self.var_lookup(var, comp, env)
            if not value:
                print("Failed to find variable {} {}".format(comp, var))
                exit(1)
            string = string[:match.span()[0]] + str(value) + string[match.span()[1]:]
        string = string.replace("\\{", "{").replace("\\}", "}")
        return string

    def parse_cmd(self, cmd, comp = None, env = 'default'):
        if 'cmd' in cmd and type(cmd['cmd']) is str:
            output = {'comp': comp, 'cmd': self.str_replace(cmd['cmd'], comp, env)}
            if comp:
                output['path'] = self.paths[comp]
            yield output
        if 'steps' in cmd and type(cmd['steps']) is list:
            for step in cmd['steps']:
                yield from self.get_cmds(step, comp)

    def get_cmds(self, command, comp = None, env = 'default'):
        if '.' in command:
            comp, command = command.split('.')
        comps = self.all_commands[command]
        if comp:
            comp_cmds = comps[None] + comps[comp]
            return [part for cmd in comp_cmds for part in self.parse_cmd(cmd, comp, env)]
        else:
            return [part for comp, cmds in comps.items() for cmd in cmds for part in self.parse_cmd(cmd, comp, env)]

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

state = State()
state.refresh()

env = "default"

if args.env:
    env = args.env

if args.vars:
    if args.command:
        try:
            print(var_lookup(args.command, None, env))
        except:
            pass
        exit(0)
    env_vars = dict(state.variables['default'])
    for comp, values in state.variables[env].items():
        if comp in env_vars:
            env_vars[comp].update(values)
        else:
            env_vars[comp] = values
    print(json.dumps(env_vars, indent = 2))
    exit(0)

if args.files:
    print(json.dumps(files, indent = 2))
    exit(0)

def run_webhooks():
    from flask import Flask, request
    from threading import Thread
    app = Flask(__name__)
    cur_thread = None

    @app.route('/', methods=['POST'])
    def webhook():
        state.refresh()
        data = request.get_json()
        if "repository" not in data or "ref" not in data:
            return "Not a push event"
        full_name = data["repository"]["full_name"]
        name = data["repository"]["name"]
        branch = data["ref"].split('/')[-1]
        webhook = next((h for h in state.webhooks if h["full_name"] == full_name or h["name"] == name), None)
        if not webhook:
            return "No hook defined"
        if not branch in webhook["branch"]:
            return "No env for branch " + branch
        print("Running webhook:", webhook)
        env = webhook["branch"][branch]
        def thread_run(cmds):
            state.refresh()
            state.rewrite_files(env)
            state.run_cmds(cmds)
        if 'refresh' in webhook:
            refresh_cmd = {'steps': webhook['refresh']}
            thread_run(list(state.parse_cmd(refresh_cmd, None, env)))
            state.refresh()
        Thread(target=thread_run, args=[list(state.parse_cmd(webhook, None, env))]).start()
        return "OK"

    app.run('0.0.0.0', 9000)


if args.command:
    if args.command == "webhook":
        run_webhooks()
        exit(0)
    cmds = state.get_cmds(args.command, None, env)
    if args.cmds:
        print(json.dumps(cmds, indent = 2))
        exit(0)

    state.rewrite_files(env)
    state.run_cmds(cmds)