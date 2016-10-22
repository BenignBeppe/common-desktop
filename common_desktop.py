import urllib
import urllib2
import json
import sqlite3
import random
import os
import logging
import datetime
import argparse

LOGS_PATH = "logs"
IMAGES_PATH = "images"
DB_PATH = "images.db"
URL = "https://commons.wikimedia.org/w/api.php"
CATEGORY = "Category:Commons featured widescreen desktop backgrounds"
INSERT_IMAGE = "INSERT INTO images VALUES({id})"
GET_PAGE_IDS = "SELECT * from images"

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
    for page_ids in get_page_ids():
        for page_id in page_ids:
            try:
                connection.execute(INSERT_IMAGE.format(id=page_id))
                connection.commit()
                logging.info("Added page id to database: %s", page_id)
            except sqlite3.IntegrityError:
                # Skip if the id is already in the table.
                logging.debug("Didn't add page id %s to database. Probably since it was already present.", page_id)
                continue
    connection.close()

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
    page_ids = connection.execute(GET_PAGE_IDS).fetchall()
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
    ensure_path_exists(IMAGES_PATH)
    file_ending = os.path.splitext(image_url)[1]
    path = "{}/{}{}".format(IMAGES_PATH, page_id, file_ending)
    logging.info("Downloading %s to %s.", image_url, path)
    urllib.urlretrieve(image_url, path)
    return path

def set_desktop_image(image_path):
    command = "gsettings set org.mate.background picture-filename {}".format(
        os.path.abspath(image_path))
    logging.info("Running: %s", command)
    os.system(command)

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
    if args.update:
        populate_table()
    if args.new_image:
        change_image()
