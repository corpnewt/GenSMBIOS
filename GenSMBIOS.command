#!/usr/bin/python
import os, subprocess, shlex, datetime, sys, plistlib, tempfile, shutil, random, uuid, zipfile
from Scripts import *
# Python-aware urllib stuff
if sys.version_info >= (3, 0):
    from urllib.request import urlopen
else:
    from urllib2 import urlopen

class Smbios:
    def __init__(self):
        self.u = utils.Utils("GenSMBIOS")
        self.d = downloader.Downloader()
        self.r = run.Run()
        self.url = "https://github.com/acidanthera/macserial/releases/latest"
        self.scripts = "Scripts"
        self.plist = None
        self.plist_data = None
        self.remote = self._get_remote_version()
        self.okay_keys = [
            "SerialNumber",
            "BoardSerialNumber",
            "SmUUID",
            "ProductName",
            "Trust",
            "Memory"
        ]

    def _get_macserial_url(self):
        # Get the latest version of macserial
        try:
            urlsource = self.d.get_string(self.url,False)
            versions = [[y for y in x.split('"') if ".zip" in y and "download" in y] for x in urlsource.lower().split("\n") if ("mac.zip" in x or "win32.zip" in x) and "download" in x]
            versions = [x[0] for x in versions]
            mac_version = next(("https://github.com" + x for x in versions if "mac.zip" in x),None)
            win_version = next(("https://github.com" + x for x in versions if "win32.zip" in x),None)
        except:
            # Not valid data
            return None
        return (mac_version,win_version)

    def _get_binary(self,binary_name=None):
        if not binary_name:
            return None
        # Check locally
        cwd = os.getcwd()
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        path = None
        if os.path.exists(binary_name):
            path = os.path.join(os.getcwd(), binary_name)
        elif os.path.exists(os.path.join(os.getcwd(), self.scripts, binary_name)):
            path = os.path.join(os.getcwd(),self.scripts,binary_name)
        os.chdir(cwd)
        return path

    def _get_version(self,macserial):
        # Gets the macserial version
        out, error, code = self.r.run({"args":[macserial]})
        if not len(out):
            return None
        for line in out.split("\n"):
            if not line.lower().startswith("version"):
                continue
            return next((x for x in line.lower().strip().split() if len(x) and x[0] in "0123456789"),None)
        return None

    def _download_and_extract(self, temp, url):
        ztemp = tempfile.mkdtemp(dir=temp)
        zfile = os.path.basename(url)
        print("Downloading {}...".format(os.path.basename(url)))
        self.d.stream_to_file(url, os.path.join(ztemp,zfile), False)
        print(" - Extracting...")
        btemp = tempfile.mkdtemp(dir=temp)
        os.chdir(os.path.join(temp,btemp))
        # Extract with built-in tools \o/
        # self.r.run({"args":["unzip",os.path.join(ztemp,zfile)]})
        with zipfile.ZipFile(os.path.join(ztemp,zfile)) as z:
            z.extractall(os.path.join(temp,btemp))
        script_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)),self.scripts)
        for x in os.listdir(os.path.join(temp,btemp)):
            print(x)
            if "macserial" in x.lower():
                # Found one
                print(" - Found {}".format(x))
                print("   - Copying to {} directory...".format(self.scripts))
                if not os.path.exists(script_dir):
                    os.mkdir(script_dir)
                shutil.copy(os.path.join(btemp,x), os.path.join(script_dir,x))

    def _get_macserial(self):
        # Download both the windows and mac versions of macserial and expand them to the Scripts dir
        self.u.head("Getting MacSerial")
        print("")
        print("Gathering latest macserial info...")
        urls = self._get_macserial_url()
        if not urls:
            print("Error checking for updates (network issue)\n")
            self.u.grab("Press [enter] to return...")
            return
        macurl,winurl = urls[0],urls[1]
        print(" - MacURL: {}\n - WinURL: {}\n".format(macurl,winurl))
        # Download the zips
        temp = tempfile.mkdtemp()
        cwd = os.getcwd()
        try:
            self._download_and_extract(temp,macurl)
            self._download_and_extract(temp,winurl)
        except Exception as e:
            print("We ran into some problems :(\n\n{}".format(e))
        print("Cleaning up...")
        os.chdir(cwd)
        shutil.rmtree(temp)
        self.u.grab("Done.",timeout=5)
        return

    def _get_remote_version(self):
        self.u.head("Getting MacSerial Remote Version")
        print("")
        print("Gathering latest macserial info...")
        urls = self._get_macserial_url()
        if not urls:
            print("Error checking for updates (network issue)\n")
            self.u.grab("Press [enter] to return...")
            return None
        try:
            return urls[0].split("/")[7]
        except:
            print("Error parsing update url\n")
            self.u.grab("Press [enter] to return...")
            return None

    def _get_plist(self):
        self.u.head("Select Plist")
        print("")
        print("Current: {}".format(self.plist))
        print("")
        print("C. Clear Selection")
        print("M. Main Menu")
        print("Q. Quit")
        print("")
        p = self.u.grab("Please draga and drop the target plist:  ")
        if p.lower() == "q":
            self.u.custom_quit()
        elif p.lower() == "m":
            return
        elif p.lower() == "c":
            self.plist = None
            self.plist_data = None
            return
        
        pc = self.u.check_path(p)
        if not pc:
            self.u.head("File Missing")
            print("")
            print("Plist file not found:\n\n{}".format(p))
            print("")
            self.u.grab("Press [enter] to return...")
            self._get_plist()
        try:
            with open(pc, "rb") as f:
                self.plist_data = plist.load(f)
        except Exception as e:
            self.u.head("Plist Malformed")
            print("")
            print("Plist file malformed:\n\n{}".format(e))
            print("")
            self.u.grab("Press [enter] to return...")
            self._get_plist()
        # Got a valid plist - let's check keys
        key_check = self.plist_data.get("SMBIOS",{})
        new_smbios = {}
        removed_keys = []
        for key in key_check:
            if key not in self.okay_keys:
                removed_keys.append(key)
            else:
                # Build our new SMBIOS
                new_smbios[key] = key_check[key]
        if len(removed_keys):
            while True:
                self.u.head("")
                print("")
                print("The following keys will be removed:\n\n{}\n".format(", ".join(removed_keys)))
                con = self.u.grab("Continue? (y/n):  ")
                if con.lower() == "y":
                    # Flush settings
                    self.plist_data["SMBIOS"] = new_smbios
                    break
                elif con.lower() == "n":
                    self.plist_data = None
                    return
        self.plist = pc

    def _generate_smbios(self, macserial):
        if not macserial or not os.path.exists(macserial):
            self.u.head("Missing MacSerial")
            print("")
            print("MacSerial binary not found.")
            print("")
            self.u.grab("Press [enter] to return...")
            return
        self.u.head("Generate SMBIOS")
        print("")
        print("M. Main Menu")
        print("Q. Quit")
        print("")
        menu = self.u.grab("Please type the SMBIOS to gen (i.e. iMac18,3):  ")
        if menu.lower() == "q":
            self.u.custom_quit()
        elif menu.lower() == "m":
            return
        smbios, err, code = self.r.run({"args":[macserial,"-a"]})
        if code != 0:
            # Issues generating
            print("Error - macserial returned an error:\n\n{}\n".format(err))
            self.u.grab("Press [enter] to return...")
            return
        # Got a list, parse it!
        line_list = []
        for line in smbios.split("\n"):
            line = line.strip()
            if line.lower().startswith(menu.lower()):
                line_list.append(line)
        if not len(line_list):
            print("\nError - {} not generated by macserial\n".format(menu))
            self.u.grab("Press [enter] to return...")
            return
        # Have a list of lines, need to format them!
        s = random.choice(line_list)
        s_list = [x.strip() for x in s.split("|")]
        # Add a uuid
        s_list.append(str(uuid.uuid4()).upper())
        if len(s_list) < 3:
            # Didn't get the right info
            print("\nError - {} not generated correctly by macserial\n".format(menu))
            self.u.grab("Press [enter] to return...")
            return
        self.u.head("{} SMBIOS Info".format(s_list[0]))
        print("\nType:         {}\nSerial:       {}\nBoard Serial: {}\nSmUUID:       {}\n".format(s_list[0], s_list[1], s_list[2], s_list[3]))
        if self.plist_data and self.plist and os.path.exists(self.plist):
            # Let's apply - got a valid file, and plist data
            print("Flushing changes to {}".format(self.plist))
            self.plist_data["SMBIOS"]["ProductName"] = s_list[0]
            self.plist_data["SMBIOS"]["SerialNumber"] = s_list[1]
            self.plist_data["SMBIOS"]["BoardSerialNumber"] = s_list[2]
            self.plist_data["SMBIOS"]["SmUUID"] = s_list[3]
            with open(self.plist, "wb") as f:
                plist.dump(self.plist_data, f)
            # Got only valid keys now
        self.u.grab("Press [enter] to return...")

    def _list_current(self, macserial):
        if not macserial or not os.path.exists(macserial):
            self.u.head("Missing MacSerial")
            print("")
            print("MacSerial binary not found.")
            print("")
            self.u.grab("Press [enter] to return...")
            return
        out, err, code = self.r.run({"args":[macserial]})
        out = "\n".join([x for x in out.split("\n") if not x.lower().startswith("version") and len(x)])
        self.u.head("Current SMBIOS Info")
        print("")
        print(out)
        print("")
        self.u.grab("Press [enter] to return...")

    def main(self):
        self.u.head()
        print("")
        if os.name == "nt":
            macserial = self._get_binary("macserial32.exe")
        else:
            macserial = self._get_binary("macserial")
        if macserial:
            macserial_v = self._get_version(macserial)
            print("MacSerial v{}".format(macserial_v))
        else:
            macserial_v = "0.0.0"
            print("MacSerial not found!")
        # Print remote version if possible
        if self.remote and self.u.compare_versions(macserial_v, self.remote):
            print("Remote Version v{}".format(self.remote))
        print("Current plist: {}".format(self.plist))
        print("")
        print("1. Install/Update MacSerial")
        print("2. Select config.plist")
        print("3. Generate SMBIOS")
        print("4. List Current SMBIOS")
        print("")
        print("Q. Quit")
        print("")
        menu = self.u.grab("Please select an option:  ").lower()
        if not len(menu):
            return
        if menu == "q":
            self.u.custom_quit()
        elif menu == "1":
            self._get_macserial()
        elif menu == "2":
            self._get_plist()
        elif menu == "3":
            self._generate_smbios(macserial)
        elif menu == "4":
            self._list_current(macserial)

s = Smbios()
while True:
    try:
        s.main()
    except Exception as e:
        print(e)
        if sys.version_info >= (3, 0):
            input("Press [enter] to return...")
        else:
            raw_input("Press [enter] to return...")