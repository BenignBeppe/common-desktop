#! /usr/bin/env python3

import urllib
import json
import sqlite3
import random
import os
import logging
import datetime
import argparse
import subprocess
import webbrowser

import requests

LOGS_PATH = "logs"
IMAGES_PATH = "images"
DB_PATH = "images.db"
URL = "https://commons.wikimedia.org/w/api.php"
GNOME_SET_BACKGROUND_COMMAND = "gsettings set org.gnome.desktop.background picture-uri file://{image_path}"
MATE_SET_BACKGROUND_COMMAND = "gsettings set org.mate.background picture-filename {image_path}"
COMMONS_PAGE_BY_ID = "https://commons.wikimedia.org/w/?curid={page_id}"
DEFAULT_FETCH_AMOUNT = 100
# Statuses for an image.
FAVORITE = 1

def setup_loggin(print_log):
    ensure_path_exists(LOGS_PATH)
    log_path = "{}/common-desktop.log".format(LOGS_PATH)
    logging.basicConfig(
        filename=log_path,
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    if print_log:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)s %(message)s")
        )
        logging.getLogger().addHandler(stream_handler)

def ensure_path_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def populate_table(connection, category, number_of_pages_to_fetch):
    ensure_images_table_exists(connection)
    number_of_added_pages = 0
    for page_id in get_page_ids(category):
        page = connection.execute(
            "SELECT * FROM images WHERE id={}".format(page_id)
        ).fetchone()
        if page is not None:
            logging.info("Id {} already exists, skipping.".format(page_id))
        else:
            connection.execute(
                "INSERT INTO images VALUES({id}, 0, 0, 0)".format(id=page_id)
            )
            connection.commit()
            logging.info("Added page id to database: {}".format(page_id))
            number_of_added_pages += 1
        if number_of_added_pages == number_of_pages_to_fetch:
            break
    logging.info(
        "Added {} new pages to database.".format(number_of_added_pages)
    )

def ensure_images_table_exists(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS images (id int UNIQUE, current boolean, status int, last_shown int)")
    connection.commit()

def get_page_ids(category):
    parameters = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": category,
        "cmtype": "file|subcat",
        "cmlimit": "500",
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
    parameters_string = urllib.parse.urlencode(parameters)
    logging.debug("REQUEST: {}?{}".format(URL, parameters_string))
    response = requests.get(URL, params=parameters)
    logging.debug("RESPONSE: {}".format(response.json()))
    return response.json()

def change_image(connection):
    old_id = get_current_id(connection)
    if old_id is not None:
        status = connection.execute(
            "SELECT status FROM images WHERE id={}".format(old_id)
        ).fetchone()[0]
        if status != FAVORITE:
            old_path = get_path_for_page_id(old_id)
            if old_path is not None:
                logging.info("Removing image: {}.".format(old_path))
                os.remove(old_path)
        connection.execute(
            "UPDATE images SET current=0, last_shown=strftime('%s','now') WHERE id={}".format(old_id)
        )
    page_id = pick_page(connection)
    if page_id is None:
        logging.info("No new image to switch to, keeping current one.");
    else:
        if not image_exists(page_id):
            image_url = get_image_url(page_id)
            download_image(image_url, page_id)
        image_path = get_path_for_page_id(page_id)
        set_desktop_image(image_path)
        connection.execute(
            "UPDATE images SET current=1 WHERE id={}".format(page_id)
        )
    connection.commit()

def pick_page(connection):
    # Pick from favorites and images that hasn't been shown yet.
    page_ids = connection.execute(
        "SELECT id FROM images WHERE status=1 or last_shown=0"
    ).fetchall()
    if page_ids:
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
    logging.info("Downloading {} to {}.".format(image_url, path))
    urllib.request.urlretrieve(image_url, path)

def set_desktop_image(image_path):
    command = get_set_background_command().format(
        image_path=os.path.abspath(image_path)
    )
    logging.info("Running: {}".format(command))
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
    if current_id is not None:
        return current_id[0]

def set_current_status(connection, new_status):
    current_id = get_current_id(connection)
    logging.info(
        "Setting status of current image (id={}) to: {}."
        .format(current_id, new_status)
    )
    connection.execute(
        "UPDATE images SET status={} WHERE id={}".format(
            new_status, current_id
        )
    )
    connection.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fetch-ids",
        "-f",
        nargs="+",
        metavar=("CATEGORY", "AMOUNT"),
        help="Update the page ids in the database by getting the page ids from CATEGORY and its subcategories. AMOUNT is the maximum number of ids that will be fetched, default {}.".format(DEFAULT_FETCH_AMOUNT)
    )
    parser.add_argument(
        "--print-log",
        "-l",
        action="store_true",
        help="Write log messages to stderr as well as log file."
    )
    parser.add_argument(
        "--new-image",
        "-n",
        action="store_true",
        help="Change to a new desktop image."
    )
    parser.add_argument(
        "--information",
        "-i",
        action="store_true",
        help="Open the page for the current image on Wikimedia Commons in the default web browser."
    )
    parser.add_argument(
        "--favorite",
        "-a",
        action="store_true",
        help="Marks the current image as a favorite. Favorites won't be deleted when swithing to a new image."
    )
    args = parser.parse_args()
    setup_loggin(args.print_log)
    ensure_path_exists(IMAGES_PATH)
    connection = sqlite3.connect(DB_PATH)
    if args.fetch_ids:
        if len(args.fetch_ids) > 1:
            amount = int(args.fetch_ids[1])
        else:
            amount = DEFAULT_FETCH_AMOUNT
        populate_table(
            connection,
            "Category:{}".format(args.fetch_ids[0]),
            amount
        )
    if args.new_image:
        change_image(connection)
    if args.information:
        show_image_page(connection)
    if args.favorite:
        set_current_status(connection, FAVORITE)
    connection.close()
