import sys
import shutil
import os
from typing import Tuple, List
import shlex
import readline
import subprocess


def completer(text, state):
    load_exec()
    autocomplete_list = list(set(commands + list(executables.keys())))
    autocomplete_list.sort()
    matches = [cmd for cmd in autocomplete_list if cmd.startswith(text)]

    if tab_state["last_text"] != text:
        tab_state["count"] = 0
        tab_state["last_text"] = text

    def longest_common_prefix(strings):
        if not strings:
            return ""
        prefix = strings[0]
        for s in strings[1:]:
            while not s.startswith(prefix):
                prefix = prefix[:-1]
                if not prefix:
                    return ""
        return prefix

    if state == 0:
        if len(matches) == 1:
            return matches[0] + " "
        elif len(matches) > 1:
            prefix = longest_common_prefix(matches)
            if prefix != text:
                return prefix
            elif tab_state["count"] == 0:
                sys.stdout.write("\a")
                sys.stdout.flush()
                tab_state["count"] += 1
                return None
            else:
                print()
                print("  ".join(matches))
                sys.stdout.write(f"$ {text}")
                sys.stdout.flush()
                return None

    if state < len(matches):
        return matches[state] + " "
    sys.stdout.write("\a")
    sys.stdout.flush()
    return None


history_list = []
last_history_index_written = 0

def parse_arguments(command: str) -> Tuple[str, List[str], str, str]:
    command_parts = shlex.split(command)
    filename = None
    redirect_mode = ""
    if not command_parts:
        return ("", [], None, "")

    cmd = command_parts[0]

    if len(command_parts) == 1:
        return (cmd, [], None, redirect_mode)

    args = command_parts[1:]
    out_op_idx = -1

    modes = ["1>", "2>", ">", ">>", "1>>", "2>>"]

    for mode in modes:
        if mode in args:
            out_op_idx = args.index(mode)
            redirect_mode = mode
            break

    if out_op_idx != -1 and out_op_idx + 1 < len(args):
        filename = args[out_op_idx + 1]
        args = args[:out_op_idx]

    return (cmd, args, filename, redirect_mode)


def is_builtin(cmd):
    return cmd in commands


def run_builtin(cmd, args, file):
    global last_history_index_written

    if cmd == "echo":
        print(" ".join(args), file=file)
    elif cmd == "type":
        if len(args) == 0:
            print(f"{cmd}: missing file operand", file=file)
        elif args[0] in commands:
            print(f"{args[0]} is a shell builtin", file=file)
        elif path := shutil.which(args[0]):
            print(f"{args[0]} is {path}", file=file)
        else:
            print(f"{args[0]}: not found", file=file)
    elif cmd == "exit":
        err_code = int(args[0]) if args else 0
        histfile = os.environ.get("HISTFILE")
        if histfile:
            try:
                with open(histfile, "w") as f:
                    for cmd in history_list:
                        f.write(cmd + "\n")
            except Exception as e:
                print(f"Error writing HISTFILE: {e}", file=sys.stderr)
        sys.exit(err_code)
    elif cmd == "pwd":
        print(os.getcwd(), file=file)
    elif cmd == "cd":
        if len(args) == 1:
            dir_path = os.path.expanduser(args[0])
            if os.path.exists(dir_path):
                os.chdir(dir_path)
            else:
                print(f"{cmd}: {args[0]}: No such file or directory", file=file)
    elif cmd == "history":
        if args and args[0] == "-r" and len(args) > 1:
            try:
                with open(args[1], "r") as f:
                    lines = f.read().splitlines()
                    for line in lines:
                        if line.strip():
                            history_list.append(line.strip())
            except Exception as e:
                print(f"history: cannot read file {args[1]}: {e}", file=file)
            return
        elif args and args[0] == "-w" and len(args) > 1:
            try:
                with open(args[1], "w") as f:
                    for cmd in history_list:
                        f.write(cmd + "\n")
            except Exception as e:
                print(f"history: cannot write file {args[1]}: {e}", file=file)
            return
        elif args and args[0] == "-a" and len(args) > 1:
            try:
                with open(args[1], "a") as f:
                    for cmd in history_list[last_history_index_written:]:
                        f.write(cmd + "\n")
                last_history_index_written = len(history_list)
            except Exception as e:
                print(f"history: cannot append file {args[1]}: {e}", file=file)
            return
        try:
            count = int(args[0]) if args else len(history_list)
        except ValueError:
            count = len(history_list)
        start = max(0, len(history_list) - count)
        for i in range(start, len(history_list)):
            print(f"{i+1}  {history_list[i]}", file=file)


def execute_pipeline(commands):
    processes = []
    prev_pipe = None

    for i, cmd_str in enumerate(commands):
        args = shlex.split(cmd_str)
        cmd = args[0]

        stdin = prev_pipe if prev_pipe else None
        stdout = subprocess.PIPE if i < len(commands) - 1 else None

        if is_builtin(cmd):
            r, w = os.pipe()
            if i == len(commands) - 1:
                w_file = sys.stdout
            else:
                w_file = os.fdopen(w, 'w')
            run_builtin(cmd, args[1:], w_file)
            if w_file != sys.stdout:
                w_file.close()
            prev_pipe = os.fdopen(r, 'r')
        else:
            try:
                process = subprocess.Popen(args, stdin=stdin, stdout=stdout)
            except FileNotFoundError:
                print(f"{args[0]}: command not found", file=sys.stderr)
                return

            if prev_pipe:
                prev_pipe.close()
            if stdout:
                prev_pipe = process.stdout

            processes.append(process)

    for process in processes:
        process.wait()


def parse_command(command: str):
    if not command.strip():
        return
    history_list.append(command.strip())

    if '|' in command:
        pipeline_cmds = command.split('|')
        pipeline_cmds = [c.strip() for c in pipeline_cmds if c.strip()]
        if len(pipeline_cmds) >= 2:
            execute_pipeline(pipeline_cmds)
            return

    cmd, args, filename, redirect_mode = parse_arguments(command)

    if redirect_mode == "1>" or redirect_mode == ">":
        file = open(filename, "w")
    elif redirect_mode == "2>":
        with open(filename, "w") as f:
            f.write("")
        file = sys.stderr
    elif redirect_mode == ">>" or redirect_mode == "1>>":
        file = open(filename, "a")
    elif redirect_mode == "2>>":
        with open(filename, "a") as f:
            f.write("")
        file = sys.stderr
    else:
        file = sys.stdout

    if cmd == "":
        return

    if is_builtin(cmd):
        run_builtin(cmd, args, file)
        return

    if cmd in executables:
        os.system(command)
        return

    print(f"{cmd}: command not found", file=file)


def main():
    histfile = os.environ.get("HISTFILE")
    if histfile and os.path.exists(histfile):
        try:
            with open(histfile, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        history_list.append(line)
        except Exception as e:
            print(f"Error reading HISTFILE: {e}", file=sys.stderr)

    try:
        while True:
            command = input("$ ")
            parse_command(command)
    except EOFError:
        print()
        histfile = os.environ.get("HISTFILE")
        if histfile:
            try:
                with open(histfile, "w") as f:
                    for cmd in history_list:
                        f.write(cmd + "\n")
            except Exception as e:
                print(f"Error writing HISTFILE on EOF: {e}", file=sys.stderr)
        sys.exit(0)


def load_exec():
    paths = os.getenv("PATH").split(os.pathsep)
    for dir in paths:
        if os.path.isdir(dir):
            for file in os.listdir(dir):
                full_path = os.path.join(dir, file)
                if file not in executables and os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                    executables[file] = full_path


if __name__ == "__main__":
    commands = ["echo", "exit", "type", "pwd", "cd", "history"]
    executables = {}
    tab_state = {"count": 0, "last_text": ""}

    load_exec()
    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    main()
