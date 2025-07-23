#!/usr/bin/env python
import os
import subprocess
import shlex
import sys
import tempfile
import shutil
import uuid
import zipfile
import json
import binascii
import requests
from collections import OrderedDict
import plistlib as plist
from secrets import randbits, choice

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError:
    tk = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


class Smbios:
    def __init__(self):
        os.chdir(os.path.dirname(os.path.realpath(sys.argv[0])))
        self.oc_release_url = (
            "https://github.com/acidanthera/OpenCorePkg/releases/latest"
        )
        self.scripts = "Scripts"
        self.plist = None
        self.plist_data = None
        self.plist_type = "Unknown"  # Can be "Clover" or "OpenCore" depending
        self.remote = self._get_remote_version()
        self.okay_keys = [
            "SerialNumber",
            "BoardSerialNumber",
            "SmUUID",
            "ProductName",
            "Trust",
            "Memory",
        ]
        try:
            with open(os.path.join(self.scripts, "prefix.json")) as f:
                self.rom_prefixes = json.load(f)
        except:
            self.rom_prefixes = []
        self.settings_file = os.path.join(self.scripts, "settings.json")
        try:
            with open(self.settings_file) as f:
                self.settings = json.load(f)
        except:
            self.settings = {}
        self.gen_rom = True

    def _save_settings(self):
        if self.settings:
            with open(self.settings_file, "w") as f:
                json.dump(self.settings, f, indent=2)
        elif os.path.exists(self.settings_file):
            os.remove(self.settings_file)

    def _get_macserial_version(self):
        macserial_v = None
        try:
            urlsource = requests.get(self.oc_release_url).text
            for line in urlsource.split("\n"):
                if "expanded_assets" in line:
                    # Get the version from the URL
                    oc_vers = line.split(' src="')[1].split('"')[0].split("/")[-1]
                    macserial_h_url = f"https://raw.githubusercontent.com/acidanthera/OpenCorePkg/{oc_vers}/Utilities/macserial/macserial.h"
                    macserial_h = requests.get(macserial_h_url).text
                    macserial_v = macserial_h.split('#define PROGRAM_VERSION "')[
                        1
                    ].split('"')[0]
        except:
            pass
        return macserial_v

    def _get_macserial_url(self):
        # Gets a URL to the latest release of OpenCorePkg
        try:
            urlsource = requests.get(self.oc_release_url).text
            for line in urlsource.split("\n"):
                if "expanded_assets" in line:
                    expanded_html = requests.get(
                        line.split(' src="')[1].split('"')[0]
                    ).text
                    for l in expanded_html.split("\n"):
                        if (
                            'href="/acidanthera/OpenCorePkg/releases/download/' in l
                            and "-RELEASE.zip" in l
                        ):
                            # Got it
                            return (
                                "https://github.com"
                                + l.split('href="')[1].split('"')[0]
                            )
        except:
            pass
        return None

    def _get_binary(self, binary_name=None):
        if not binary_name:
            if os.name == "nt":
                binary_name = ["macserial.exe", "macserial32.exe"]
            elif sys.platform.startswith("linux"):
                binary_name = ["macserial.linux", "macserial"]
            else:
                binary_name = ["macserial"]
        cwd = os.getcwd()
        os.chdir(os.path.dirname(os.path.realpath(sys.argv[0])))
        path = None
        for name in binary_name:
            if os.path.exists(name):
                path = os.path.join(os.getcwd(), name)
            elif os.path.exists(os.path.join(os.getcwd(), self.scripts, name)):
                path = os.path.join(os.getcwd(), self.scripts, name)
            if path:
                break  # Found it, bail
        os.chdir(cwd)
        return path

    def _get_version(self, macserial):
        # Gets the macserial version
        p = subprocess.run([macserial], capture_output=True, text=True)
        out = p.stdout
        if not out:
            return None
        for line in out.split("\n"):
            if not line.lower().startswith("version"):
                continue
            vers = next((x for x in line.strip().split() if x and x[0].isdigit()), None)
            if vers and vers[-1] == ".":
                vers = vers[:-1]
            return vers
        return None

    def _download_and_extract(self, temp, url, path_in_zip=[]):
        ztemp = tempfile.mkdtemp(dir=temp)
        zfile = os.path.basename(url)
        print("\nDownloading {}...".format(zfile))
        r = requests.get(url, stream=True)
        if not r.ok:
            raise Exception(" - Failed to download!")
        with open(os.path.join(ztemp, zfile), "wb") as f:
            total = int(r.headers.get("content-length", 0))
            if tqdm and total:
                with tqdm(total=total, unit="B", unit_scale=True) as pbar:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
            else:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
        print("")
        print(" - Extracting...")
        btemp = tempfile.mkdtemp(dir=temp)
        with zipfile.ZipFile(os.path.join(ztemp, zfile)) as z:
            z.extractall(btemp)
        script_dir = os.path.join(
            os.path.dirname(os.path.realpath(sys.argv[0])), self.scripts
        )
        search_path = btemp
        if path_in_zip:
            search_path = os.path.join(search_path, *path_in_zip)
        for x in os.listdir(search_path):
            if "macserial" in x.lower():
                # Found one
                print(" - Found {}".format(x))
                full_path = os.path.join(search_path, x)
                if os.name != "nt":
                    print("   - Chmod +x...")
                    os.chmod(full_path, 0o755)
                print("   - Copying to {} directory...".format(self.scripts))
                if not os.path.exists(script_dir):
                    os.makedirs(script_dir, exist_ok=True)
                shutil.copy(full_path, os.path.join(script_dir, x))

    def _get_macserial(self, from_gui=False):
        print("Gathering latest macserial info...")
        url = self._get_macserial_url()
        path_in_zip = ["Utilities", "macserial"]
        if not url:
            print("Error checking for updates (network issue)\n")
            if not from_gui:
                input("Press [enter] to return...")
            return
        temp = tempfile.mkdtemp()
        cwd = os.getcwd()
        try:
            print(" - {}".format(url))
            self._download_and_extract(temp, url, path_in_zip)
        except Exception as e:
            print("We ran into some problems :(\n\n{}".format(e))
        print("\nCleaning up...")
        os.chdir(cwd)
        shutil.rmtree(temp)
        if not from_gui:
            input("\nDone. Press [enter] to return...")

    def _get_remote_version(self):
        print("Gathering latest macserial info...")
        print(" - Gathering info from OpenCorePkg...")
        vers = self._get_macserial_version()
        if not vers:
            print("Error checking for updates (network issue)\n")
            input("Press [enter] to return...")
            return None
        return vers

    def _get_plist(self):
        print("Current: {}".format(self.plist))
        print("Type:    {}".format(self.plist_type))
        print("")
        print("C. Clear Selection")
        print("M. Main Menu")
        print("Q. Quit")
        print("")
        p = input("Please drag and drop the target plist:  ").strip('"').strip("'")
        if p.lower() == "q":
            sys.exit(0)
        elif p.lower() == "m":
            return
        elif p.lower() == "c":
            self.plist = None
            self.plist_data = None
            return
        if not os.path.exists(p):
            print("Plist file not found:\n\n{}".format(p))
            input("Press [enter] to return...")
            return self._get_plist()
        try:
            with open(p, "rb") as f:
                self.plist_data = plist.load(f, dict_type=OrderedDict)
        except Exception as e:
            print("Plist file malformed:\n\n{}".format(e))
            input("Press [enter] to return...")
            return self._get_plist()
        # Got a valid plist - let's try to check for Clover or OC structure
        detected_type = (
            "OpenCore"
            if "PlatformInfo" in self.plist_data
            else "Clover" if "SMBIOS" in self.plist_data else "Unknown"
        )
        if detected_type == "Unknown":
            while True:
                print("Could not auto-determine plist type!")
                print("")
                print("1. Clover")
                print("2. OpenCore")
                print("")
                print("M. Return to the Menu")
                print("")
                t = input("Please select the target type:  ").lower()
                if t == "m":
                    return self._get_plist()
                elif t in ("1", "2"):
                    detected_type = "Clover" if t == "1" else "OpenCore"
                    break
        # Got a plist and type - let's save it
        self.plist_type = detected_type
        # Apply any key-stripping or safety checks
        if self.plist_type == "Clover":
            # Got a valid clover plist - let's check keys
            key_check = self.plist_data.get("SMBIOS", {})
            new_smbios = {}
            removed_keys = []
            for key in key_check:
                if key not in self.okay_keys:
                    removed_keys.append(key)
                else:
                    # Build our new SMBIOS
                    new_smbios[key] = key_check[key]
            # We want the SmUUID to be the top-level - remove CustomUUID if exists
            if "CustomUUID" in self.plist_data.get("SystemParameters", {}):
                removed_keys.append("CustomUUID")
            if removed_keys:
                while True:
                    print(
                        "The following keys will be removed:\n\n{}\n".format(
                            ", ".join(removed_keys)
                        )
                    )
                    con = input("Continue? (y/n):  ")
                    if con.lower() == "y":
                        # Flush settings
                        self.plist_data["SMBIOS"] = new_smbios
                        # Remove the CustomUUID if present
                        self.plist_data.get("SystemParameters", {}).pop(
                            "CustomUUID", None
                        )
                        break
                    elif con.lower() == "n":
                        self.plist_data = None
                        return
        self.plist = p

    def _get_rom(self):
        # Generate 6-bytes of cryptographically random values
        rom_str = "{:x}".format(randbits(8 * 6)).upper().rjust(12, "0")
        if self.rom_prefixes:
            # Replace the prefix with one from our list
            prefix = choice(self.rom_prefixes)
            rom_str = prefix + rom_str[len(prefix) :]
        return rom_str

    def _get_smbios(self, macserial, smbios_type, times=1):
        # Returns a list of SMBIOS lines that match
        total = []
        # Get any additional args and ensure they're a string
        args = self.settings.get("macserial_args", "")
        args = shlex.split(args)
        while len(total) < times:
            total_len = len(total)
            p = subprocess.run([macserial, "-a"] + args, capture_output=True, text=True)
            smbios = p.stdout
            code = p.returncode
            if code != 0:
                # Issues generating
                return None
            # Got our text, let's see if the SMBIOS exists
            for line in smbios.split("\n"):
                line = line.strip()
                if line.lower().startswith(smbios_type.lower()):
                    total.append(line)
                    if len(total) >= times:
                        break
            if total_len == len(total):
                # Total didn't change - return False
                return False
        # Have a list now - let's format it
        output = []
        for sm in total:
            s_list = [x.strip() for x in sm.split("|")]
            # Add a uuid
            s_list.append(str(uuid.uuid4()).upper())
            # Generate a ROM value
            s_list.append(self._get_rom())
            # Format the text
            output.append(s_list)
        return output

    def _generate_smbios(self, macserial):
        if not macserial or not os.path.exists(macserial):
            # Attempt to download
            self._get_macserial()
            # Check it again
            macserial = self._get_binary()
            if not macserial or not os.path.exists(macserial):
                # Could not find it, and it failed to download :(
                print("MacSerial binary was not found and failed to download.")
                input("Press [enter] to return...")
                return
        print("Generate SMBIOS")
        print("")
        print("M. Main Menu")
        print("Q. Quit")
        print("")
        print("Please type the SMBIOS to gen and the number")
        menu = input("of times to generate [max 20] (i.e. iMac18,3 5):  ")
        if menu.lower() == "q":
            sys.exit(0)
        elif menu.lower() == "m":
            return
        menu = menu.split(" ")
        if len(menu) == 1:
            # Default of one time
            smtype = menu[0]
            times = 1
        else:
            smtype = menu[0]
            try:
                times = int(menu[1])
            except:
                print("Incorrect format - must be SMBIOS times - i.e. iMac18,3 5")
                input("Press [enter] to return...")
                self._generate_smbios(macserial)
                return
        # Keep it between 1 and 20
        times = max(1, min(20, times))
        smbios = self._get_smbios(macserial, smtype, times)
        if smbios is None:
            # Issues generating
            print("Error - macserial returned an error!")
            input("Press [enter] to return...")
            return
        if smbios == False:
            print("\nError - {} not generated by macserial\n".format(smtype))
            input("Press [enter] to return...")
            return
        print("{} SMBIOS Info".format(smbios[0][0]))
        print("")
        if self.settings.get("macserial_args"):
            print("Additional Arguments Passed:")
            print(" {}".format(self.settings["macserial_args"]))
            print("")
        f_string = (
            "Type:         {}\nSerial:       {}\nBoard Serial: {}\nSmUUID:       {}"
        )
        if self.gen_rom:
            f_string += (
                "\nApple ROM:    {}" if self.rom_prefixes else "\nRandom ROM:   {}"
            )
        print("\n\n".join([f_string.format(*x) for x in smbios]))
        if self.plist_data and self.plist and os.path.exists(self.plist):
            # Let's apply - got a valid file, and plist data
            if len(smbios) > 1:
                print("\nFlushing first SMBIOS entry to {}".format(self.plist))
            else:
                print("\nFlushing SMBIOS entry to {}".format(self.plist))
            if self.plist_type == "Clover":
                # Ensure plist data exists
                for x in ["SMBIOS", "RtVariables", "SystemParameters"]:
                    self.plist_data[x] = self.plist_data.get(x, {})
                self.plist_data["SMBIOS"]["ProductName"] = smbios[0][0]
                self.plist_data["SMBIOS"]["SerialNumber"] = smbios[0][1]
                self.plist_data["SMBIOS"]["BoardSerialNumber"] = smbios[0][2]
                self.plist_data["RtVariables"]["MLB"] = smbios[0][2]
                self.plist_data["SMBIOS"]["SmUUID"] = smbios[0][3]
                if self.gen_rom:
                    self.plist_data["RtVariables"]["ROM"] = binascii.unhexlify(
                        smbios[0][4].encode()
                    )
                self.plist_data["SystemParameters"]["InjectSystemID"] = True
            elif self.plist_type == "OpenCore":
                # Ensure data exists
                self.plist_data["PlatformInfo"] = self.plist_data.get(
                    "PlatformInfo", {}
                )
                self.plist_data["PlatformInfo"]["Generic"] = self.plist_data[
                    "PlatformInfo"
                ].get("Generic", {})
                # Set the values
                self.plist_data["PlatformInfo"]["Generic"]["SystemProductName"] = (
                    smbios[0][0]
                )
                self.plist_data["PlatformInfo"]["Generic"]["SystemSerialNumber"] = (
                    smbios[0][1]
                )
                self.plist_data["PlatformInfo"]["Generic"]["MLB"] = smbios[0][2]
                self.plist_data["PlatformInfo"]["Generic"]["SystemUUID"] = smbios[0][3]
                if self.gen_rom:
                    self.plist_data["PlatformInfo"]["Generic"]["ROM"] = (
                        binascii.unhexlify(smbios[0][4].encode())
                    )
            with open(self.plist, "wb") as f:
                plist.dump(self.plist_data, f, sort_keys=False)
            # Got only valid keys now
        print("")
        input("Press [enter] to return...")

    def _list_current(self, macserial):
        if not macserial or not os.path.exists(macserial):
            print("MacSerial binary not found.")
            input("Press [enter] to return...")
            return
        p = subprocess.run([macserial], capture_output=True, text=True)
        out = p.stdout
        out = "\n".join(
            [x for x in out.split("\n") if not x.lower().startswith("version") and x]
        )
        print("Current SMBIOS Info")
        print("")
        print(out)
        print("")
        input("Press [enter] to return...")

    def get_additional_args(self):
        while True:
            print("Additional Arguments")
            print("")
            args = self.settings.get("macserial_args")
            print("Current Additional Arguments: {}".format(args))
            print("")
            print(
                "The -a argument is always passed to macserial, but you can enter additional"
            )
            print("arguments to fine-tune SMBIOS generation.")
            print("")
            print("C. Clear Additional Arguments")
            print("M. Return To Main Menu")
            print("Q. Quit")
            print("")
            args = input("Please type the arguments to pass:  ")
            if not args:
                continue
            elif args.lower() == "m":
                return
            elif args.lower() == "q":
                sys.exit(0)
            elif args.lower() == "c":
                self.settings.pop("macserial_args", None)
                self._save_settings()
            else:
                self.settings["macserial_args"] = args
                self._save_settings()

    def main(self):
        macserial = self._get_binary()
        if macserial:
            macserial_v = self._get_version(macserial) or "Not Found"
            print("MacSerial v{}".format(macserial_v))
        else:
            macserial_v = "0.0.0"
            print("MacSerial not found!")
        # Print remote version if possible
        if self.remote and self._compare_versions(macserial_v, self.remote):
            print("Remote Version v{}".format(self.remote))
        print("Current plist: {}".format(self.plist))
        print("Plist type:    {}".format(self.plist_type))
        print("")
        print("1. Install/Update MacSerial")
        print("2. Select config.plist")
        print("3. Generate SMBIOS")
        print("4. Generate UUID")
        print("5. Generate ROM")
        print("6. List Current SMBIOS")
        print(
            "7. Generate ROM With SMBIOS (Currently {})".format(
                "Enabled" if self.gen_rom else "Disabled"
            )
        )
        args = self.settings.get("macserial_args")
        print("8. Additional Args (Currently: {})".format(args))
        print("")
        print("Q. Quit")
        print("")
        menu = input("Please select an option:  ").lower()
        if not menu:
            return
        if menu == "q":
            sys.exit(0)
        elif menu == "1":
            self._get_macserial()
        elif menu == "2":
            self._get_plist()
        elif menu == "3":
            self._generate_smbios(macserial)
        elif menu == "4":
            print("Generated UUID")
            print("")
            print(str(uuid.uuid4()).upper())
            print("")
            input("Press [enter] to return...")
        elif menu == "5":
            print("Generated ROM")
            print("")
            print(
                "{} ROM: {}".format(
                    "Apple" if self.rom_prefixes else "Random", self._get_rom()
                )
            )
            print("")
            input("Press [enter] to return...")
        elif menu == "6":
            self._list_current(macserial)
        elif menu == "7":
            self.gen_rom = not self.gen_rom
        elif menu == "8":
            self.get_additional_args()

    def _compare_versions(self, local, remote):
        def version_tuple(v):
            return tuple(map(int, v.split(".")))

        return version_tuple(local) < version_tuple(remote)


class GUI:
    def __init__(self, s):
        self.s = s
        self.root = tk.Tk()
        self.root.title("GenSMBIOS")
        frame = tk.Frame(self.root)
        frame.pack(padx=10, pady=10)
        self.plist_label = tk.Label(
            frame, text=f"Current plist: {self.s.plist or 'None'} ({self.s.plist_type})"
        )
        self.plist_label.pack()
        tk.Button(frame, text="Select config.plist", command=self.select_plist).pack()
        tk.Label(frame, text="SMBIOS Type (e.g. iMac18,3)").pack()
        self.smbios_type = tk.Entry(frame)
        self.smbios_type.pack()
        tk.Label(frame, text="Count (1-20, default 1)").pack()
        self.times = tk.Entry(frame)
        self.times.pack()
        tk.Button(frame, text="Generate SMBIOS", command=self.generate_smbios).pack()
        self.gen_rom_var = tk.BooleanVar(value=self.s.gen_rom)
        tk.Checkbutton(
            frame,
            text="Generate ROM with SMBIOS",
            variable=self.gen_rom_var,
            command=self.toggle_gen_rom,
        ).pack()
        tk.Label(frame, text="Additional Args").pack()
        self.args_entry = tk.Entry(frame)
        self.args_entry.insert(0, self.s.settings.get("macserial_args", ""))
        self.args_entry.pack()
        tk.Button(frame, text="Set Additional Args", command=self.set_args).pack()
        tk.Button(frame, text="Install/Update MacSerial", command=self.install).pack()
        tk.Button(frame, text="Generate UUID", command=self.gen_uuid).pack()
        tk.Button(frame, text="Generate ROM", command=self.gen_rom_func).pack()
        tk.Button(frame, text="List Current SMBIOS", command=self.list_smbios).pack()
        self.output = tk.Text(frame, height=15, width=60)
        self.output.pack()
        self.root.mainloop()

    def toggle_gen_rom(self):
        self.s.gen_rom = self.gen_rom_var.get()

    def set_args(self):
        args = self.args_entry.get().strip()
        if args:
            self.s.settings["macserial_args"] = args
        else:
            self.s.settings.pop("macserial_args", None)
        self.s._save_settings()
        messagebox.showinfo("Success", "Additional arguments updated.")

    def install(self):
        self.s._get_macserial(from_gui=True)
        messagebox.showinfo("Success", "MacSerial installed/updated.")

    def gen_uuid(self):
        u = str(uuid.uuid4()).upper()
        self.output.insert(tk.END, f"Generated UUID: {u}\n\n")
        self.output.see(tk.END)

    def gen_rom_func(self):
        r = self.s._get_rom()
        prefix = "Apple" if self.s.rom_prefixes else "Random"
        self.output.insert(tk.END, f"Generated {prefix} ROM: {r}\n\n")
        self.output.see(tk.END)

    def list_smbios(self):
        macserial = self.s._get_binary()
        if not macserial:
            messagebox.showerror("Error", "MacSerial not found. Try installing it.")
            return
        p = subprocess.run([macserial], capture_output=True, text=True)
        out = "\n".join(
            [
                x
                for x in p.stdout.split("\n")
                if not x.lower().startswith("version") and x
            ]
        )
        self.output.insert(tk.END, f"Current SMBIOS Info:\n{out}\n\n")
        self.output.see(tk.END)

    def select_plist(self):
        path = filedialog.askopenfilename(
            title="Select config.plist",
            filetypes=(("Plist files", "*.plist"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                self.s.plist_data = plist.load(f, dict_type=OrderedDict)
            detected_type = (
                "OpenCore"
                if "PlatformInfo" in self.s.plist_data
                else "Clover" if "SMBIOS" in self.s.plist_data else "Unknown"
            )
            if detected_type == "Unknown":
                if messagebox.askyesno(
                    "Plist Type", "Is this an OpenCore plist? (Click No for Clover)"
                ):
                    detected_type = "OpenCore"
                else:
                    detected_type = "Clover"
            self.s.plist_type = detected_type
            if detected_type == "Clover":
                key_check = self.s.plist_data.get("SMBIOS", {})
                new_smbios = {
                    k: v for k, v in key_check.items() if k in self.s.okay_keys
                }
                removed_keys = [k for k in key_check if k not in self.s.okay_keys]
                if "CustomUUID" in self.s.plist_data.get("SystemParameters", {}):
                    removed_keys.append("CustomUUID")
                    self.s.plist_data.get("SystemParameters", {}).pop(
                        "CustomUUID", None
                    )
                if removed_keys:
                    if not messagebox.askyesno(
                        "Confirm",
                        f"The following keys will be removed:\n{', '.join(removed_keys)}\nContinue?",
                    ):
                        self.s.plist_data = None
                        return
                self.s.plist_data["SMBIOS"] = new_smbios
            self.s.plist = path
            self.plist_label.config(
                text=f"Current plist: {self.s.plist} ({self.s.plist_type})"
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load plist: {e}")

    def generate_smbios(self):
        smtype = self.smbios_type.get().strip()
        if not smtype:
            messagebox.showerror("Error", "Enter SMBIOS type.")
            return
        times_input = self.times.get().strip()
        try:
            times = int(times_input) if times_input else 1
            if not 1 <= times <= 20:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Count must be an integer between 1 and 20.")
            return
        macserial = self.s._get_binary()
        if not macserial:
            if messagebox.askyesno("Download", "MacSerial not found. Download now?"):
                self.s._get_macserial(from_gui=True)
                macserial = self.s._get_binary()
        if not macserial:
            messagebox.showerror("Error", "MacSerial not found.")
            return
        smbios = self.s._get_smbios(macserial, smtype, times)
        if smbios is None:
            messagebox.showerror("Error", "macserial returned an error.")
            return
        if smbios == False:
            messagebox.showerror("Error", f"{smtype} not supported by macserial.")
            return
        out = f"{smbios[0][0]} SMBIOS Info\n"
        if "macserial_args" in self.s.settings:
            out += f"Additional Arguments Passed: {self.s.settings['macserial_args']}\n"
        f_string = (
            "Type:         {}\nSerial:       {}\nBoard Serial: {}\nSmUUID:       {}\n"
        )
        if self.s.gen_rom:
            f_string += (
                "Apple ROM:    {}\n" if self.s.rom_prefixes else "Random ROM:   {}\n"
            )
        out += "\n".join([f_string.format(*x) for x in smbios])
        if self.s.plist_data and self.s.plist:
            if messagebox.askyesno("Apply", "Apply first SMBIOS entry to plist?"):
                sm = smbios[0]
                if self.s.plist_type == "Clover":
                    for x in ["SMBIOS", "RtVariables", "SystemParameters"]:
                        self.s.plist_data[x] = self.s.plist_data.get(x, {})
                    self.s.plist_data["SMBIOS"]["ProductName"] = sm[0]
                    self.s.plist_data["SMBIOS"]["SerialNumber"] = sm[1]
                    self.s.plist_data["SMBIOS"]["BoardSerialNumber"] = sm[2]
                    self.s.plist_data["RtVariables"]["MLB"] = sm[2]
                    self.s.plist_data["SMBIOS"]["SmUUID"] = sm[3]
                    if self.s.gen_rom:
                        self.s.plist_data["RtVariables"]["ROM"] = binascii.unhexlify(
                            sm[4].encode()
                        )
                    self.s.plist_data["SystemParameters"]["InjectSystemID"] = True
                elif self.s.plist_type == "OpenCore":
                    self.s.plist_data["PlatformInfo"] = self.s.plist_data.get(
                        "PlatformInfo", {}
                    )
                    self.s.plist_data["PlatformInfo"]["Generic"] = self.s.plist_data[
                        "PlatformInfo"
                    ].get("Generic", {})
                    self.s.plist_data["PlatformInfo"]["Generic"][
                        "SystemProductName"
                    ] = sm[0]
                    self.s.plist_data["PlatformInfo"]["Generic"][
                        "SystemSerialNumber"
                    ] = sm[1]
                    self.s.plist_data["PlatformInfo"]["Generic"]["MLB"] = sm[2]
                    self.s.plist_data["PlatformInfo"]["Generic"]["SystemUUID"] = sm[3]
                    if self.s.gen_rom:
                        self.s.plist_data["PlatformInfo"]["Generic"]["ROM"] = (
                            binascii.unhexlify(sm[4].encode())
                        )
                with open(self.s.plist, "wb") as f:
                    plist.dump(self.s.plist_data, f, sort_keys=False)
                out += f"\nFlushed to {self.s.plist}"
        self.output.insert(tk.END, out + "\n\n")
        self.output.see(tk.END)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GenSMBIOS CLI")
    parser.add_argument(
        "--install", action="store_true", help="Install/Update MacSerial"
    )
    parser.add_argument("-p", "--plist", type=str, help="Path to config.plist")
    parser.add_argument(
        "--plist-type",
        choices=["clover", "opencore"],
        help="Specify plist type if not auto-detected",
    )
    parser.add_argument(
        "-g",
        "--generate",
        nargs="+",
        help="Generate SMBIOS: <type> [times] (e.g., iMac18,3 5)",
    )
    parser.add_argument("-u", "--uuid", action="store_true", help="Generate UUID")
    parser.add_argument("--rom", action="store_true", help="Generate ROM")
    parser.add_argument("--list", action="store_true", help="List current SMBIOS")
    parser.add_argument(
        "--toggle-rom", action="store_true", help="Toggle generate ROM with SMBIOS"
    )
    parser.add_argument("--args", type=str, help="Set additional args for macserial")
    parser.add_argument(
        "--clear-args", action="store_true", help="Clear additional args for macserial"
    )
    parser.add_argument("--version", action="store_true", help="Show MacSerial version")
    parser.add_argument(
        "-j", "--json", type=str, help="Export generated SMBIOS to JSON file"
    )
    parser.add_argument("--gui", action="store_true", help="Run in GUI mode")
    parser.add_argument("--tui", action="store_true", help="Run in text UI mode")
    args = parser.parse_args()

    s = Smbios()
    processed = False

    if args.install:
        s._get_macserial()
        processed = True

    if args.plist:
        pc = args.plist
        if not os.path.exists(pc):
            print("Plist file not found: {}".format(args.plist))
            sys.exit(1)
        try:
            with open(pc, "rb") as f:
                s.plist_data = plist.load(f, dict_type=OrderedDict)
        except Exception as e:
            print("Plist malformed: {}".format(e))
            sys.exit(1)
        detected_type = (
            "OpenCore"
            if "PlatformInfo" in s.plist_data
            else "Clover" if "SMBIOS" in s.plist_data else "Unknown"
        )
        if detected_type == "Unknown":
            if args.plist_type:
                detected_type = args.plist_type.capitalize()
            else:
                print("Could not determine plist type! Use --plist-type to specify.")
                sys.exit(1)
        if detected_type not in ("Clover", "OpenCore"):
            print("Invalid plist type: {}".format(detected_type))
            sys.exit(1)
        s.plist_type = detected_type
        if s.plist_type == "Clover":
            key_check = s.plist_data.get("SMBIOS", {})
            new_smbios = {k: v for k, v in key_check.items() if k in s.okay_keys}
            removed_keys = [k for k in key_check if k not in s.okay_keys]
            if "CustomUUID" in s.plist_data.get("SystemParameters", {}):
                removed_keys.append("CustomUUID")
                s.plist_data["SystemParameters"].pop("CustomUUID", None)
            if removed_keys:
                print("Removed keys from plist: {}".format(", ".join(removed_keys)))
            s.plist_data["SMBIOS"] = new_smbios
        s.plist = pc

    if args.clear_args:
        s.settings.pop("macserial_args", None)
        s._save_settings()

    if args.args is not None:
        s.settings["macserial_args"] = args.args
        s._save_settings()

    if args.toggle_rom:
        s.gen_rom = not s.gen_rom
        print(
            "Generate ROM with SMBIOS: {}".format(
                "Enabled" if s.gen_rom else "Disabled"
            )
        )

    if args.generate:
        macserial = s._get_binary()
        if not macserial:
            print("MacSerial not found! Use --install to download.")
            sys.exit(1)
        menu = args.generate
        smtype = menu[0]
        times = 1 if len(menu) < 2 else int(menu[1])
        times = max(1, min(20, times))
        smbios = s._get_smbios(macserial, smtype, times)
        if smbios is None:
            print("Error - macserial returned an error!")
            sys.exit(1)
        if smbios == False:
            print("Error - {} not generated by macserial".format(smtype))
            sys.exit(1)
        print("{} SMBIOS Info".format(smbios[0][0]))
        if s.settings.get("macserial_args"):
            print(
                "Additional Arguments Passed: {}".format(s.settings["macserial_args"])
            )
        f_string = (
            "Type:         {}\nSerial:       {}\nBoard Serial: {}\nSmUUID:       {}"
        )
        if s.gen_rom:
            f_string += (
                "\nApple ROM:    {}" if self.rom_prefixes else "\nRandom ROM:   {}"
            )
        print("\n\n".join([f_string.format(*x) for x in smbios]))
        if s.plist_data and s.plist:
            if len(smbios) > 1:
                print("\nFlushing first SMBIOS entry to {}".format(s.plist))
            else:
                print("\nFlushing SMBIOS entry to {}".format(s.plist))
            if s.plist_type == "Clover":
                for x in ["SMBIOS", "RtVariables", "SystemParameters"]:
                    if x not in s.plist_data:
                        s.plist_data[x] = {}
                s.plist_data["SMBIOS"]["ProductName"] = smbios[0][0]
                s.plist_data["SMBIOS"]["SerialNumber"] = smbios[0][1]
                s.plist_data["SMBIOS"]["BoardSerialNumber"] = smbios[0][2]
                s.plist_data["RtVariables"]["MLB"] = smbios[0][2]
                s.plist_data["SMBIOS"]["SmUUID"] = smbios[0][3]
                if s.gen_rom:
                    s.plist_data["RtVariables"]["ROM"] = binascii.unhexlify(
                        smbios[0][4].encode()
                    )
                s.plist_data["SystemParameters"]["InjectSystemID"] = True
            elif s.plist_type == "OpenCore":
                if "PlatformInfo" not in s.plist_data:
                    s.plist_data["PlatformInfo"] = {}
                if "Generic" not in s.plist_data["PlatformInfo"]:
                    s.plist_data["PlatformInfo"]["Generic"] = {}
                s.plist_data["PlatformInfo"]["Generic"]["SystemProductName"] = smbios[
                    0
                ][0]
                s.plist_data["PlatformInfo"]["Generic"]["SystemSerialNumber"] = smbios[
                    0
                ][1]
                s.plist_data["PlatformInfo"]["Generic"]["MLB"] = smbios[0][2]
                s.plist_data["PlatformInfo"]["Generic"]["SystemUUID"] = smbios[0][3]
                if s.gen_rom:
                    s.plist_data["PlatformInfo"]["Generic"]["ROM"] = binascii.unhexlify(
                        smbios[0][4].encode()
                    )
                with open(s.plist, "wb") as f:
                    plist.dump(s.plist_data, f, sort_keys=False)
        if args.json:
            data = []
            for x in smbios:
                d = {"Type": x[0], "Serial": x[1], "Board Serial": x[2], "SmUUID": x[3]}
                if len(x) > 4:
                    d["ROM"] = x[4]
                data.append(d)
            with open(args.json, "w") as f:
                json.dump(data if len(data) > 1 else data[0], f, indent=4)
            print("\nExported to {}".format(args.json))
        processed = True

    if args.uuid:
        print(str(uuid.uuid4()).upper())
        processed = True

    if args.rom:
        prefix = "Apple" if s.rom_prefixes else "Random"
        print("{} ROM: {}".format(prefix, s._get_rom()))
        processed = True

    if args.list:
        macserial = s._get_binary()
        if not macserial:
            print("MacSerial not found! Use --install to download.")
            sys.exit(1)
        p = subprocess.run([macserial], capture_output=True, text=True)
        out = p.stdout
        out = "\n".join(
            [x for x in out.split("\n") if not x.lower().startswith("version") and x]
        )
        print("Current SMBIOS Info")
        print(out)
        processed = True

    if args.version:
        macserial = s._get_binary()
        if macserial:
            print("MacSerial v{}".format(s._get_version(macserial)))
        else:
            print("MacSerial not found!")
        if s.remote:
            print("Remote Version v{}".format(s.remote))
        processed = True

    if args.gui:
        if tk is not None:
            GUI(s)
        else:
            print("Tkinter is not available on this system. Falling back to CLI mode.")
            while True:
                s.main()
    else:
        if not processed:
            if args.tui:
                while True:
                    s.main()
            elif tk is not None:
                GUI(s)
            else:
                while True:
                    s.main()
