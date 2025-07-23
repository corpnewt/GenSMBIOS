import sys
import os
import time
import ssl
import gzip
import multiprocessing
from io import BytesIO
from urllib.request import urlopen, Request
import queue as q

TERMINAL_WIDTH = (
    os.get_terminal_size().columns
    if hasattr(os, "get_terminal_size")
    else (120 if os.name == "nt" else 80)
)


def get_size(size, suffix=None, use_1024=False, round_to=2, strip_zeroes=False):
    # size is the number of bytes
    # suffix is the target suffix to locate (B, KB, MB, etc) - if found
    # use_1024 denotes whether or not we display in MiB vs MB
    # round_to is the number of decimal points to round our result to (0-15)
    # strip_zeroes denotes whether we strip out zeroes

    # Failsafe in case our size is unknown
    if size == -1:
        return "Unknown"
    # Get our suffixes based on use_1024
    ext = (
        ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
        if use_1024
        else ["B", "KB", "MB", "GB", "TB", "PB"]
    )
    div = 1024 if use_1024 else 1000
    s = float(size)
    s_dict = {}  # Initialize our dict
    # Iterate the ext, and divide by 1000 or 1024 each time to setup the dict {ext:val}
    for e in ext:
        s_dict[e] = s
        s /= div
    # Get our suffix if provided - will be set to None if not found, or if started as None
    suffix = (
        next((x for x in ext if x.lower() == suffix.lower()), None)
        if suffix
        else suffix
    )
    # Get the largest value that's still over 1
    biggest = suffix if suffix else next((x for x in ext[::-1] if s_dict[x] >= 1), "B")
    # Determine our rounding approach - first make sure it's an int; default to 2 on error
    try:
        round_to = int(round_to)
    except:
        round_to = 2
    round_to = (
        0 if round_to < 0 else 15 if round_to > 15 else round_to
    )  # Ensure it's between 0 and 15
    bval = round(s_dict[biggest], round_to)
    # Split our number based on decimal points
    a, b = str(bval).split(".")
    # Check if we need to strip or pad zeroes
    b = (
        b.rstrip("0")
        if strip_zeroes
        else b.ljust(round_to, "0") if round_to > 0 else ""
    )
    return "{:,}{} {}".format(int(a), "" if not b else "." + b, biggest)


def _process_hook(
    queue, total_size, bytes_so_far=0, update_interval=1.0, max_packets=0
):
    packets = []
    speed = remaining = ""
    last_update = time.time()
    while True:
        # Write our info first so we have *some* status while
        # waiting for packets
        if total_size > 0:
            percent = float(bytes_so_far) / total_size
            percent = round(percent * 100, 2)
            t_s = get_size(total_size)
            try:
                b_s = get_size(bytes_so_far, t_s.split(" ")[1])
            except:
                b_s = get_size(bytes_so_far)
            perc_str = " {:.2f}%".format(percent)
            bar_width = (TERMINAL_WIDTH // 3) - len(perc_str)
            progress = "=" * int(bar_width * (percent / 100))
            sys.stdout.write(
                "\r\033[K{}/{} | {}{}{}{}{}".format(
                    b_s,
                    t_s,
                    progress,
                    " " * (bar_width - len(progress)),
                    perc_str,
                    speed,
                    remaining,
                )
            )
        else:
            b_s = get_size(bytes_so_far)
            sys.stdout.write("\r\033[K{}{}".format(b_s, speed))
        sys.stdout.flush()
        # Now we gather the next packet
        try:
            packet = queue.get(timeout=update_interval)
            # Packets should be formatted as a tuple of
            # (timestamp, len(bytes_downloaded))
            # If "DONE" is passed, we assume the download
            # finished - and bail
            if packet == "DONE":
                print("")  # Jump to the next line
                return
            # Append our packet to the list and ensure we're not
            # beyond our max.
            # Only check max if it's > 0
            packets.append(packet)
            if max_packets > 0:
                packets = packets[-max_packets:]
            # Increment our bytes so far as well
            bytes_so_far += packet[1]
        except q.Empty:
            # Didn't get anything - reset the speed
            # and packets
            packets = []
            speed = " | 0 B/s"
            remaining = " | ?? left" if total_size > 0 else ""
        except KeyboardInterrupt:
            print("")  # Jump to the next line
            return
        # If we have packets and it's time for an update, process
        # the info.
        update_check = time.time()
        if packets and update_check - last_update >= update_interval:
            last_update = update_check  # Refresh our update timestamp
            speed = " | ?? B/s"
            if len(packets) > 1:
                # Let's calculate the amount downloaded over how long
                try:
                    first, last = packets[0][0], packets[-1][0]
                    chunks = sum([float(x[1]) for x in packets])
                    t = last - first
                    assert t >= 0
                    bytes_speed = 1.0 / t * chunks
                    speed = " | {}/s".format(get_size(bytes_speed, round_to=1))
                    # Get our remaining time
                    if total_size > 0:
                        seconds_left = (total_size - bytes_so_far) / bytes_speed
                        days = seconds_left // 86400
                        hours = (seconds_left - (days * 86400)) // 3600
                        mins = (seconds_left - (days * 86400) - (hours * 3600)) // 60
                        secs = (
                            seconds_left - (days * 86400) - (hours * 3600) - (mins * 60)
                        )
                        if days > 99 or bytes_speed == 0:
                            remaining = " | ?? left"
                        else:
                            remaining = " | {}{:02d}:{:02d}:{:02d} left".format(
                                "{}:".format(int(days)) if days else "",
                                int(hours),
                                int(mins),
                                int(round(secs)),
                            )
                except Exception:
                    pass
                # Clear the packets so we don't reuse the same ones
                packets = []


class Downloader:

    def __init__(self, **kwargs):
        self.ua = kwargs.get("useragent", {"User-Agent": "Mozilla"})
        self.chunk = 1048576  # 1024 x 1024 i.e. 1MiB
        if os.name == "nt":
            os.system("color")  # Initialize cmd for ANSI escapes
        # Provide reasonable default logic to workaround macOS CA file handling
        cafile = ssl.get_default_verify_paths().openssl_cafile
        try:
            # If default OpenSSL CA file does not exist, use that from certifi
            if not os.path.exists(cafile):
                import certifi

                cafile = certifi.where()
            self.ssl_context = ssl.create_default_context(cafile=cafile)
        except Exception:
            # None of the above worked, disable certificate verification for now
            self.ssl_context = ssl._create_unverified_context()

    def _get_headers(self, headers=None):
        # Fall back on the default ua if none provided
        target = headers if isinstance(headers, dict) else self.ua
        new_headers = {}
        # Shallow copy to prevent changes to the headers
        # overriding the original
        for k in target:
            new_headers[k] = target[k]
        return new_headers

    def open_url(self, url, headers=None):
        headers = self._get_headers(headers)
        # Wrap up the try/except block so we don't have to do this for each function
        try:
            response = urlopen(Request(url, headers=headers), context=self.ssl_context)
        except Exception:
            # No fixing this - bail
            return None
        return response

    def get_size(self, *args, **kwargs):
        return get_size(*args, **kwargs)

    def get_string(self, url, progress=True, headers=None, expand_gzip=True):
        response = self.get_bytes(url, progress, headers, expand_gzip)
        if response is None:
            return None
        return response.decode()

    def get_bytes(self, url, progress=True, headers=None, expand_gzip=True):
        response = self.open_url(url, headers)
        if response is None:
            return None
        try:
            total_size = int(response.headers["Content-Length"])
        except Exception:
            total_size = -1
        chunk_so_far = b""
        queue = process = None
        if progress:
            queue = multiprocessing.Queue()
            # Create the multiprocess and start it
            process = multiprocessing.Process(
                target=_process_hook, args=(queue, total_size)
            )
            process.daemon = True
            process.start()
        try:
            while True:
                chunk = response.read(self.chunk)
                if progress:
                    # Add our items to the queue
                    queue.put((time.time(), len(chunk)))
                if not chunk:
                    break
                chunk_so_far += chunk
        finally:
            # Close the response whenever we're done
            response.close()
        if (
            expand_gzip
            and response.headers.get("Content-Encoding", "unknown").lower() == "gzip"
        ):
            fileobj = BytesIO(chunk_so_far)
            gfile = gzip.GzipFile(fileobj=fileobj)
            return gfile.read()
        if progress:
            # Finalize the queue and wait
            queue.put("DONE")
            process.join()
        return chunk_so_far

    def stream_to_file(
        self,
        url,
        file_path,
        progress=True,
        headers=None,
        ensure_size_if_present=True,
        allow_resume=False,
    ):
        response = self.open_url(url, headers)
        if response is None:
            return None
        bytes_so_far = 0
        try:
            total_size = int(response.headers["Content-Length"])
        except Exception:
            total_size = -1
        mode = "wb"
        if allow_resume and os.path.isfile(file_path) and total_size != -1:
            # File exists, we're resuming and have a target size.  Check the
            # local file size.
            current_size = os.stat(file_path).st_size
            if current_size == total_size:
                # File is already complete - return the path
                return file_path
            elif current_size < total_size:
                response.close()
                # File is not complete - seek to our current size
                bytes_so_far = current_size
                mode = "ab"  # Append
                # We also need to try creating a new request
                # in order to pass our range header
                new_headers = self._get_headers(headers)
                # Get the start byte, 0-indexed
                byte_string = "bytes={}-".format(current_size)
                new_headers["Range"] = byte_string
                response = self.open_url(url, new_headers)
                if response is None:
                    return None
        queue = process = None
        if progress:
            queue = multiprocessing.Queue()
            # Create the multiprocess and start it
            process = multiprocessing.Process(
                target=_process_hook, args=(queue, total_size, bytes_so_far)
            )
            process.daemon = True
            process.start()
        with open(file_path, mode) as f:
            try:
                while True:
                    chunk = response.read(self.chunk)
                    bytes_so_far += len(chunk)
                    if progress:
                        # Add our items to the queue
                        queue.put((time.time(), len(chunk)))
                    if not chunk:
                        break
                    f.write(chunk)
            finally:
                # Close the response whenever we're done
                response.close()
        if progress:
            # Finalize the queue and wait
            queue.put("DONE")
            process.join()
        if ensure_size_if_present and total_size != -1:
            # We're verifying size - make sure we got what we asked for
            if bytes_so_far != total_size:
                return None  # We didn't - imply it failed
        return file_path if os.path.exists(file_path) else None
