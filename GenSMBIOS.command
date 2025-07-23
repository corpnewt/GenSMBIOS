#!/usr/bin/env bash

# Get the current directory, script name, and target Python script
args=( "$@" )
dir="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
script="${0##*/}"
target="${script%.*}.py"

tempdir=""
kernel="$(uname -s)"
downloaded="FALSE"
just_installing="FALSE"

compare_to_version () {
    # Compare macOS version to the passed version
    # $1 = 0 (equal), 1 (greater), 2 (less), 3 (gequal), 4 (lequal)
    # $2 = OS version to compare ours to
    if [ -z "$1" ] || [ -z "$2" ]; then
        return
    fi
    local current_os comp
    current_os="$(sw_vers -productVersion 2>/dev/null || echo "0.0.0")"
    comp="$(vercomp "$current_os" "$2")"
    if [[ "$1" == "3" && ("$comp" == "1" || "$comp" == "0") ]] || \
       [[ "$1" == "4" && ("$comp" == "2" || "$comp" == "0") ]] || \
       [[ "$comp" == "$1" ]]; then
        echo "1"
    else
        echo "0"
    fi
}

format_version () {
    local vers="$1"
    echo "$(echo "$1" | awk -F. '{ printf("%d%03d%03d%03d\n", $1,$2,$3,$4); }')"
}

vercomp () {
    local ver1="$(format_version "$1")" ver2="$(format_version "$2")"
    if [ "$ver1" -gt "$ver2" ]; then
        echo "1"
    elif [ "$ver1" -lt "$ver2" ]; then
        echo "2"
    else
        echo "0"
    fi
}

get_remote_py_version () {
    local pyurl py_html py_vers
    pyurl="https://www.python.org/downloads/macos/"
    py_html="$(curl -sL "$pyurl" --compressed 2>/dev/null)"
    py_vers="$(echo "$py_html" | grep -i "Latest Python 3 Release" | awk '{print $8}' | cut -d'<' -f1)"
    echo "$py_vers"
}

download_py () {
    local vers="$1" url
    clear
    echo "  ###                        ###"
    echo " #     Downloading Python     #"
    echo "###                        ###"
    echo
    if [ -z "$vers" ]; then
        echo "Gathering latest version..."
        vers="$(get_remote_py_version)"
    fi
    if [ -z "$vers" ]; then
        print_error
    fi
    echo "Located Version:  $vers"
    echo
    echo "Building download url..."
    url="$(curl -sL "https://www.python.org/downloads/release/python-${vers//./}/" --compressed 2>/dev/null | \
           grep -iE "python-$vers-macos.*.pkg\"" | awk -F'"' '{ print $2 }')"
    if [ -z "$url" ]; then
        print_error
    fi
    echo " - $url"
    echo
    echo "Downloading..."
    echo
    tempdir="$(mktemp -d 2>/dev/null || mktemp -d -t 'tempdir')"
    curl -sL "$url" -o "$tempdir/python.pkg"
    if [ "$?" != "0" ]; then
        echo " - Failed to download python installer!"
        exit 1
    fi
    echo "Running python install package..."
    echo
    sudo installer -pkg "$tempdir/python.pkg" -target /
    if [ "$?" != "0" ]; then
        echo " - Failed to install python!"
        exit 1
    fi
    pkgutil --expand "$tempdir/python.pkg" "$tempdir/python" 2>/dev/null
    if [ -e "$tempdir/python/Python_Shell_Profile_Updater.pkg/Scripts/postinstall" ]; then
        echo "Updating PATH..."
        echo
        "$tempdir/python/Python_Shell_Profile_Updater.pkg/Scripts/postinstall"
    fi
    vers_folder="Python $(echo "$vers" | cut -d'.' -f1 -f2)"
    if [ -f "/Applications/$vers_folder/Install Certificates.command" ]; then
        echo "Updating Certificates..."
        echo
        "/Applications/$vers_folder/Install Certificates.command"
    fi
    echo "Cleaning up..."
    cleanup
    echo
    if [ "$just_installing" == "TRUE" ]; then
        echo "Done."
    else
        echo "Rechecking Python..."
        downloaded="TRUE"
        clear
        main
    fi
}

cleanup () {
    if [ -d "$tempdir" ]; then
        rm -rf "$tempdir"
    fi
}

print_error() {
    clear
    cleanup
    echo "  ###                      ###"
    echo " #     Python Not Found     #"
    echo "###                      ###"
    echo
    echo "Python 3 is not installed or not found in your PATH."
    echo
    if [ "$kernel" == "Darwin" ]; then
        echo "Please go to https://www.python.org/downloads/macos/ to"
        echo "download and install the latest version, then try again."
    else
        echo "Please install python3 through your package manager and try again."
    fi
    echo
    exit 1
}

print_target_missing() {
    clear
    cleanup
    echo "  ###                      ###"
    echo " #     Target Not Found     #"
    echo "###                      ###"
    echo
    echo "Could not locate $target!"
    echo
    exit 1
}

get_local_python_version() {
    # Find the active python3 in PATH
    local python
    python="$(command -v python3 2>/dev/null)"
    if [ -z "$python" ]; then
        return
    fi
    # Check if it's the macOS stub
    if [ "$kernel" == "Darwin" ] && [ "$python" == "/usr/bin/python3" ] && \
       [ "$(compare_to_version "3" "10.15")" == "1" ]; then
        xcode-select -p >/dev/null 2>&1
        if [ "$?" != "0" ]; then
            return
        fi
    fi
    python_version="$("$python" -V 2>&1 | grep -i python | cut -d' ' -f2 | grep -E "[0-9]+\.[0-9]+\.[0-9]+")"
    if [ -n "$python_version" ]; then
        echo "$python"
    fi
}

prompt_and_download() {
    if [ "$downloaded" == "TRUE" ] || [ "$kernel" != "Darwin" ]; then
        print_error
    fi
    clear
    echo "  ###                      ###"
    echo " #     Python Not Found     #"
    echo "###                      ###"
    echo
    echo "Could not locate Python 3!"
    echo
    echo "This script requires Python 3 to run."
    echo
    while true; do
        read -p "Would you like to install the latest Python 3 now? (y/n):  " yn
        case $yn in
            [Yy]* ) download_py; break;;
            [Nn]* ) print_error;;
        esac
    done
}

main() {
    # Verify target Python script exists
    if [ ! -f "$dir/$target" ]; then
        print_target_missing
    fi
    # Check for base Python 3
    local base_python
    base_python="$(get_local_python_version)"
    if [ -z "$base_python" ]; then
        prompt_and_download
        return 1
    fi
    # Create venv in the directory if not exists
    local venv_dir="$dir/.venv"
    if [ ! -d "$venv_dir" ]; then
        echo "Creating virtual environment..."
        "$base_python" -m venv "$venv_dir"
        if [ $? -ne 0 ]; then
            echo "Failed to create virtual environment. Falling back to base Python."
            venv_python="$base_python"
        else
            venv_python="$venv_dir/bin/python"
        fi
    else
        venv_python="$venv_dir/bin/python"
    fi
    # Upgrade pip in venv
    "$venv_python" -m pip install --upgrade pip >/dev/null 2>&1
    # Check and install required modules in venv
    echo "Checking Python modules..."
    "$venv_python" -c "import tqdm" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "tqdm not found. Attempting to install in venv..."
        "$venv_python" -m pip install tqdm 2>/dev/null
        if [ $? -ne 0 ]; then
            echo "Failed to install tqdm. Continuing without it..."
        fi
    fi
    "$venv_python" -c "import requests" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "requests not found. Attempting to install in venv..."
        "$venv_python" -m pip install requests 2>/dev/null
        if [ $? -ne 0 ]; then
            echo "Failed to install requests. The script may not run without it."
        fi
    fi
    # Check tkinter
    "$venv_python" -c "import tkinter" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "tkinter module not found."
        if [ -n "$CONDA_PREFIX" ]; then
            echo "Detected Conda environment. Attempting to install tk..."
            conda install -y tk >/dev/null 2>&1
            if [ $? -ne 0 ]; then
                echo "Failed to install tk via conda. Continuing without tkinter..."
            else
                # Recheck after install
                "$venv_python" -c "import tkinter" 2>/dev/null
                if [ $? -ne 0 ]; then
                    echo "tkinter still not available. Continuing without it..."
                fi
            fi
        elif [ "$kernel" == "Darwin" ]; then
            echo "The official Python installer includes tkinter. Attempting reinstall..."
            download_py
            # After reinstall, main is called again, so venv will be checked/created with potentially new base
        else
            echo "Please install the tkinter package for Python 3 on your system (e.g., sudo apt install python3-tk on Ubuntu)."
            echo "Continuing without tkinter..."
        fi
    fi
    # Run the target script in venv
    "$venv_python" "$dir/$target" "${args[@]}"
}

# Check for macOS stub
check_py3_stub="$(compare_to_version "3" "10.15")"
trap cleanup EXIT
if [ "$1" == "--install-python" ] && [ "$kernel" == "Darwin" ]; then
    just_installing="TRUE"
    download_py
else
    main
fi