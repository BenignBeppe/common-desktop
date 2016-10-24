import urllib
import urllib2
import json
import sqlite3
import random
import os
import logging
import datetime
import argparse
import subprocess

LOGS_PATH = "logs"
IMAGES_PATH = "images"
DB_PATH = "images.db"
URL = "https://commons.wikimedia.org/w/api.php"
CATEGORY = "Category:Commons featured widescreen desktop backgrounds"
GNOME_SET_BACKGROUND_COMMAND = "gsettings set org.gnome.desktop.background picture-uri file://{image_path}"
MATE_SET_BACKGROUND_COMMAND = "gsettings set org.mate.background picture-filename {image_path}"

def setup_loggin(print_log):
    ensure_path_exists(LOGS_PATH)
    log_path = "{}/{}.log".format(LOGS_PATH, datetime.datetime.now())
    logging.basicConfig(filename=log_path, level=logging.DEBUG)
    if print_log:
        logging.getLogger().addHandler(logging.StreamHandler())

def ensure_path_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def populate_table():
    connection = sqlite3.connect(DB_PATH)
    ensure_images_table_exists(connection)
    for page_ids in get_page_ids():
        for page_id in page_ids:
            try:
                connection.execute(
                    "INSERT INTO images VALUES({id})".format(id=page_id)
                )
                connection.commit()
                logging.info("Added page id to database: %s", page_id)
            except sqlite3.IntegrityError:
                # Skip if the id is already in the table.
                logging.debug("Didn't add page id %s to database. Probably since it was already present.", page_id)
                continue
    connection.close()

def ensure_images_table_exists(connection):
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='image'"
    ).fetchall()
    if not table:
        logging.debug("No image table found, creating new.")
        connection.execute("CREATE TABLE images (int RPIMARY KEY)")
        connection.commit()

def get_page_ids():
    parameters = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": CATEGORY,
        "cmtype": "file",
        "continue": ""
    }
    while True:
        response = send_request(parameters)
        pages = response["query"]["categorymembers"]
        page_ids = [p["pageid"] for p in pages]
        yield page_ids
        if "continue" not in response:
            # Keep fetching until there is no continue paramter.
            break
        parameters["continue"] = response["continue"]["continue"]
        parameters["cmcontinue"] = response["continue"]["cmcontinue"]

def send_request(parameters):
    logging.debug("PARAMETERS: %s", parameters)
    request = urllib2.Request(URL)
    request.add_data(urllib.urlencode(parameters))
    logging.debug("REQUEST: %s?%s", request.get_full_url(), request.get_data())
    response_string = urllib2.urlopen(request).read()
    logging.debug("RESPONSE: %s", response_string)
    response = json.loads(response_string)
    return response

def change_image():
    page_id = pick_page()
    if not image_exists(page_id):
        image_url = get_image_url(page_id)
        download_image(image_url, page_id)
    image_path = get_path_for_page_id(page_id)
    set_desktop_image(image_path)

def pick_page():
    connection = sqlite3.connect(DB_PATH)
    page_ids = connection.execute("SELECT * from images").fetchall()
    connection.close()
    return random.choice(page_ids)[0]

def image_exists(page_id):
    return get_path_for_page_id(page_id)

def get_path_for_page_id(page_id):
    files = os.listdir(IMAGES_PATH)
    for file_ in files:
        if os.path.splitext(file_)[0] == str(page_id):
            return "{}/{}".format(IMAGES_PATH, file_)

def get_image_url(page_id):
    parameters = {
        "action": "query",
        "format": "json",
        "pageids": page_id,
        "prop": "imageinfo",
        "iiprop": "url"
    }
    response = send_request(parameters)
    pages = response["query"]["pages"]
    url = pages[pages.keys()[0]]["imageinfo"][0]["url"]
    return url

def download_image(image_url, page_id):
    file_ending = os.path.splitext(image_url)[1]
    path = "{}/{}{}".format(IMAGES_PATH, page_id, file_ending)
    logging.info("Downloading %s to %s.", image_url, path)
    urllib.urlretrieve(image_url, path)

def set_desktop_image(image_path):
    command = get_set_background_command().format(
        image_path=os.path.abspath(image_path)
    )
    logging.info("Running: %s", command)
    subprocess.call(command.split())

def get_set_background_command():
    if process_is_running("gnome-session"):
        return GNOME_SET_BACKGROUND_COMMAND
    elif process_is_running("mate-session"):
        return MATE_SET_BACKGROUND_COMMAND

def process_is_running(process_name):
    user_name = subprocess.check_output(["whoami"])
    command = "pgrep -u {} {}".format(user_name, process_name).split()
    try:
        return subprocess.check_output(command) != ""
    except subprocess.CalledProcessError:
        # This seems to happen when the program isn't installed.
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update",
        "-u",
        help="Update the page ids in the database.",
        action="store_true"
    )
    parser.add_argument(
        "--print-log",
        "-l",
        help="Write log messages to stderr as well as log file.",
        action="store_true"
    )
    parser.add_argument(
        "--new-image",
        "-n",
        help="Change to a new desktop image.",
        action="store_true"
    )
    args = parser.parse_args()
    setup_loggin(args.print_log)
    ensure_path_exists(IMAGES_PATH)
    if args.update:
        populate_table()
    if args.new_image:
        change_image()
