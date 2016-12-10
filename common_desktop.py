#! /usr/bin/env python3

import urllib.request
import urllib.parse
import json
import sqlite3
import random
import os
import logging
import datetime
import argparse
import subprocess
import webbrowser

LOGS_PATH = "logs"
IMAGES_PATH = "images"
DB_PATH = "images.db"
URL = "https://commons.wikimedia.org/w/api.php"
GNOME_SET_BACKGROUND_COMMAND = "gsettings set org.gnome.desktop.background picture-uri file://{image_path}"
MATE_SET_BACKGROUND_COMMAND = "gsettings set org.mate.background picture-filename {image_path}"
COMMONS_PAGE_BY_ID = "https://commons.wikimedia.org/w/?curid={page_id}"

def setup_loggin(print_log):
    ensure_path_exists(LOGS_PATH)
    log_path = "{}/{}.log".format(LOGS_PATH, datetime.datetime.now())
    logging.basicConfig(filename=log_path, level=logging.DEBUG)
    if print_log:
        logging.getLogger().addHandler(logging.StreamHandler())

def ensure_path_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def populate_table(connection, category):
    ensure_images_table_exists(connection)
    for page_id in get_page_ids(category):
        try:
            connection.execute(
                "INSERT INTO images VALUES({id}, 0)".format(id=page_id)
            )
            connection.commit()
            logging.info("Added page id to database: %s", page_id)
        except sqlite3.IntegrityError:
            # Skip if the id is already in the table.
            logging.debug("Didn't add page id %s to database. Probably since it was already present.", page_id)
            continue
    connection.close()

def ensure_images_table_exists(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS images (id int UNIQUE, current boolean DEFAULT 0)")
    connection.commit()

def get_page_ids(category):
    parameters = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": category,
        "cmtype": "file|subcat",
        "continue": ""
    }
    while True:
        response = send_request(parameters)
        pages = response["query"]["categorymembers"]
        for page in pages:
            if page["ns"] == 6:
                # Page is in the File namespace.
                yield page["pageid"]
            elif page["ns"] == 14:
                # Page is in the Category namespace.
                catergory = page["title"]
                for id in get_page_ids(catergory):
                    yield id
        if "continue" not in response:
            # Keep fetching until there is no continue paramter.
            break
        parameters["continue"] = response["continue"]["continue"]
        parameters["cmcontinue"] = response["continue"]["cmcontinue"]

def send_request(parameters):
    logging.debug("PARAMETERS: %s", parameters)
    data = urllib.parse.urlencode(parameters)
    request = urllib.request.Request(URL, data.encode())
    logging.debug("REQUEST: %s?%s", request.get_full_url(), data)
    response_string = urllib.request.urlopen(request).read().decode()
    logging.debug("RESPONSE: %s", response_string)
    response = json.loads(response_string)
    return response

def change_image(connection):
    old_page_id = get_current_id(connection)
    if old_page_id:
        connection.execute(
            "REPLACE INTO images VALUES({id}, 0)".format(id=old_page_id)
        )
    page_id = pick_page(connection)
    if not image_exists(page_id):
        image_url = get_image_url(page_id)
        download_image(image_url, page_id)
    image_path = get_path_for_page_id(page_id)
    set_desktop_image(image_path)
    connection.execute(
        "REPLACE INTO images VALUES({id}, 1)".format(id=page_id)
    )
    connection.commit()

def pick_page(connection):
    page_ids = connection.execute("SELECT id FROM images").fetchall()
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
    url = pages[list(pages)[0]]["imageinfo"][0]["url"]
    return url

def download_image(image_url, page_id):
    file_ending = os.path.splitext(image_url)[1]
    path = "{}/{}{}".format(IMAGES_PATH, page_id, file_ending)
    logging.info("Downloading %s to %s.", image_url, path)
    urllib.request.urlretrieve(image_url, path)

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
    user_name = subprocess.check_output(["whoami"]).decode()
    command = "pgrep -u {} {}".format(user_name, process_name).split()
    try:
        return subprocess.check_output(command) != ""
    except subprocess.CalledProcessError:
        # This seems to happen when the program isn't installed.
        return False

def show_image_page(connection):
    page_id = get_current_id(connection)
    webbrowser.open(COMMONS_PAGE_BY_ID.format(page_id=page_id))

def get_current_id(connection):
    current_id = connection.execute(
        "SELECT id FROM images WHERE current=1"
    ).fetchone()
    if current_id != None:
        return current_id[0]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fetch-ids",
        "-f",
        help="Update the page ids in the database by getting the page ids from CATEGORY and its subcategories.",
        metavar="CATEGORY"
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
    parser.add_argument(
        "--information",
        "-i",
        help="Open the page for the current image on Wikimedia Commons in the default web browser.",
        action="store_true"
    )
    args = parser.parse_args()
    setup_loggin(args.print_log)
    ensure_path_exists(IMAGES_PATH)
    connection = sqlite3.connect(DB_PATH)
    if args.fetch_ids:
        populate_table(connection, "Category:{}".format(args.fetch_ids))
    if args.new_image:
        change_image(connection)
    if args.information:
        show_image_page(connection)
    connection.close()
