import sys
import subprocess
import time
import threading
import shlex
from queue import Queue, Empty

ON_POSIX = "posix" in sys.builtin_module_names


class Run:

    def __init__(self):
        pass

    def _read_output(self, pipe, q):
        try:
            for line in iter(lambda: pipe.read(1), ""):
                q.put(line)
        except ValueError:
            pass
        pipe.close()

    def _create_thread(self, output):
        # Creates a new queue and thread object to watch based on the output pipe sent
        q = Queue()
        t = threading.Thread(target=self._read_output, args=(output, q))
        t.daemon = True
        return (q, t)

    def _stream_output(self, comm, shell=False):
        output = error = ""
        p = None
        try:
            if shell and isinstance(comm, list):
                comm = " ".join(shlex.quote(x) for x in comm)
            if not shell and isinstance(comm, str):
                comm = shlex.split(comm)
            p = subprocess.Popen(
                comm,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                text=True,
                close_fds=ON_POSIX,
            )
            # Setup the stdout thread/queue
            q, t = self._create_thread(p.stdout)
            qe, te = self._create_thread(p.stderr)
            # Start both threads
            t.start()
            te.start()

            while True:
                c = z = ""
                try:
                    c = q.get_nowait()
                except Empty:
                    pass
                else:
                    sys.stdout.write(c)
                    output += c
                    sys.stdout.flush()
                try:
                    z = qe.get_nowait()
                except Empty:
                    pass
                else:
                    sys.stderr.write(z)
                    error += z
                    sys.stderr.flush()
                if c == z == "":
                    # No output - see if still running
                    p.poll()
                    if p.returncode is not None:
                        # Subprocess ended
                        break
                    # No output, but subprocess still running - stall for 20ms
                    time.sleep(0.02)

            o, e = p.communicate()
            return (output + o, error + e, p.returncode)
        except Exception:
            if p:
                try:
                    o, e = p.communicate()
                except Exception:
                    o = e = ""
                return (output + o, error + e, p.returncode)
            return ("", "Command not found!", 1)

    def _run_command(self, comm, shell=False):
        c = None
        try:
            if shell and isinstance(comm, list):
                comm = " ".join(shlex.quote(x) for x in comm)
            if not shell and isinstance(comm, str):
                comm = shlex.split(comm)
            p = subprocess.Popen(
                comm,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            c = p.communicate()
            return (c[0], c[1], p.returncode)
        except Exception:
            return ("", "Command not found!", 1)

    def run(self, command_list, leave_on_fail=False):
        # Command list should be a list of dicts
        if isinstance(command_list, dict):
            # We only have one command
            command_list = [command_list]
        output_list = []
        for comm in command_list:
            args = comm.get("args", [])
            shell = comm.get("shell", False)
            stream = comm.get("stream", False)
            sudo = comm.get("sudo", False)
            stdout = comm.get("stdout", False)
            stderr = comm.get("stderr", False)
            mess = comm.get("message", None)
            show = comm.get("show", False)

            if mess is not None:
                print(mess)

            if not args:
                # nothing to process
                continue
            if sudo:
                # Check if we have sudo
                out = self._run_command(["which", "sudo"])
                if "sudo" in out[0]:
                    # Can sudo
                    if isinstance(args, list):
                        args.insert(0, out[0].strip())  # add to start of list
                    elif isinstance(args, str):
                        args = out[0].strip() + " " + args  # add to start of string

            if show:
                print(" ".join(args) if isinstance(args, list) else args)

            if stream:
                # Stream it!
                out = self._stream_output(args, shell)
            else:
                # Just run and gather output
                out = self._run_command(args, shell)
                if stdout and out[0]:
                    print(out[0])
                if stderr and out[1]:
                    print(out[1])
            # Append output
            output_list.append(out)
            # Check for errors
            if leave_on_fail and out[2] != 0:
                # Got an error - leave
                break
        if len(output_list) == 1:
            # We only ran one command - just return that output
            return output_list[0]
        return output_list
