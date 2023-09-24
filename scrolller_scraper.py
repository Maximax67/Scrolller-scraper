import os
import re
import time
import requests
import concurrent.futures
import threading
import argparse
from tqdm import tqdm

def makeAPIRequest(api_url: str, payload: dict, headers=dict()):
    response = requests.post(api_url, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json()


def getFileExtension(file_path: str):
    last_dot_index = file_path.rfind('.')
    if last_dot_index == -1 and last_dot_index != len(file_path) - 1:
        return None

    return file_path[last_dot_index + 1:].lower()


def get_unique_filename(path: str, title: str, url: str):
    extension = getFileExtension(url)
    filename = f"{title}{f'.{extension}' if extension else ''}"
    counter = 1
    while os.path.exists(os.path.join(path, filename)):
        filename = f"{title}_{counter}{f'.{extension}' if extension else ''}"
        counter += 1

    return filename


def get_filepath(path: str, title: str, url: str):
    extension = getFileExtension(url)
    filename = f"{title}{f'.{extension}' if extension else ''}"
    filepath = os.path.join(path, filename)

    return filepath


def show_error_and_retry(error: str, retries: int, max_retries: int):
    if retries <= max_retries:
        print(f"{error}. Retrying ({retries}/{max_retries})...")
    else:
        print(error)


def download_single(sources: list, path: str, title: str, max_retries: int, timeout: int, headers=dict()):
    for source in sources:
        url = source['url']
        filename = get_unique_filename(path, title, url)
        retries = 0
        while retries <= max_retries:
            try:
                session = requests.Session()
                response = session.get(url, stream=True, timeout=timeout, headers=headers)
                if response.status_code == 200:
                    filename = get_unique_filename(path, title, url) # File may be created with the same filename in different thread, get filename again
                    file_path = os.path.join(path, filename)
                    with open(file_path, 'wb') as f:
                        for chunk in response.iter_content(1024 * 1024):
                            f.write(chunk)
                    return True # Successful download
                else:
                    retries += 1
                    error = f" Failed to download image {filename} - Status Code: {response.status_code}"
                    show_error_and_retry(error, retries, max_retries)
                    time.sleep(3)
            except requests.exceptions.ReadTimeout:
                retries += 1
                error = f" Read timeout occurred while downloading image {filename}"
                show_error_and_retry(error, retries, max_retries)
                time.sleep(3)
            except requests.exceptions.RequestException as e:
                retries += 1
                error = f"Error downloading image {filename}: {e}"
                show_error_and_retry(error, retries, max_retries)
                time.sleep(3)

        print(f" Downloading '{filename}' in lower quality...")
    print(f" Can't download: {filename}")

    return False


def to_valid_filename(name: str, maxfilename=100):
    filename = name.replace(" ", "_")
    filename = re.sub(r'[^\w.-]', '', filename)

    if len(filename) > maxfilename:
        filename = filename[:maxfilename]

    return filename


def downloadMedia(media: dict, output_path: str, retries: int, timeout: int, headers=dict(),
                    threads=5, maxfilename=100, low_quality=False, output=True, total_progress=None):
    os.makedirs(output_path, exist_ok=True)

    total = len(media)
    lock = threading.Lock()

    downloaded = 0

    def update_progress(success=False):
        with lock:
            if output:
                pbar.update(1)
                total_progress.refresh()
            if success:
                nonlocal downloaded
                downloaded += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = []
        for value in media.values():
            try:
                title, sources = value

                if not sources:
                    print(f"Sources not found, may be media was deleted: '{title}'")
                    update_progress()
                    continue

                # Best quality media are always last in the list
                if not low_quality:
                    sources.reverse()

                title = to_valid_filename(title, maxfilename)
                future = executor.submit(download_single, sources, output_path, title, retries, timeout, headers)
                future.add_done_callback(lambda _: update_progress(future.result()))
                futures.append(future)
            except requests.exceptions.RequestException as e:
                print(f"Error! {e}")

        if output:
            with tqdm(total=total, desc="Current progress", dynamic_ncols=True, position=0) as pbar:
                if total_progress:
                    total_progress.refresh()

                for future in concurrent.futures.as_completed(futures):
                    future.result()

                if total_progress:
                    total_progress.update(1)

                time.sleep(0.1) # Wait for updating progressbars

    return downloaded


def getToken(username: str, password: str, api_url: str, headers=dict()):
    payload = {
        "query": "query LoginQuery($username: String!, $password: String!) { \
                    login(username: $username, password: $password) { \
                        token \
                    } \
                }",
        "variables": {
            "username": username,
            "password": password
        }
    }

    try:
        response = makeAPIRequest(api_url, payload, headers)
        if not response:
            return

        token = response["data"]["login"]["token"]
        return token
    except Exception as e:
        print(f"Login error: {str(e)}")


def getCategories(headers=dict()):
    payload = {
        "query": "query getCategories( $sort: String, $nsfw: Boolean!, $getTest: Boolean ) { categories( data: { order_by: $sort, is_nsfw: $nsfw, getTest: $getTest } ) { title subreddits } }",
        "variables": {
            "nsfw": True,
            "sort": "alphabet",
            "getTest": False
        }
    }

    try:
        response = makeAPIRequest("https://api.scrolller.com/admin", payload, headers)
        if not response:
            return

        categories = response["data"]["categories"]

        result = dict()
        for category in categories:
            title = category["title"]
            subreddits = category["subreddits"]
            result[title] = subreddits

        return result
    except Exception as e:
        print(f"Get categories request error: {str(e)}")


def getSubredditsFromChosen(categories: list, orig_categories: dict):
    result = []
    for category in categories:
        if category == "all":
            values = orig_categories.values()
            flat_list = [item for sublist in values for item in sublist]
            result.append(("all", flat_list))
        else:
            if category in orig_categories:
                result.append((category, orig_categories[category]))
            else:
                print(f"Can't find category {category}. SKIPPED!")

    return result


# Prioritize video sources in low_quality mode first
def prioritize_media_sources(media_sources: list):
    video_sources = []
    image_sources = []

    for source in media_sources:
        if source['url'].endswith('.mp4'):
            video_sources.append(source)
        else:
            image_sources.append(source)

    return video_sources + image_sources


def runParser(url: str, amount: int, token: str, api_url: str, req_limit=50, retries=3, headers=dict(),
                item_limit=2, filter='', low_quality=False, is_downloaded_check=False, out="", output=True):
    old_counter = 0
    counter = 0
    retry = 0
    media = {}
    amount_str = str(amount)

    # Preparing payload
    if url.startswith("/r/"):
        payload = {
            "query": "query SubredditQuery( $url: String! $filter: SubredditPostFilter $iterator: String ) { \
                getSubreddit(url: $url) { \
                    children( limit: " f"{req_limit}" "iterator: $iterator filter: $filter disabledHosts: null ) { \
                        items { \
                            id title mediaSources { url width height isOptimized } \
                        } \
                    } \
                } \
            }",
            "variables": {
                "url": url,
                "filter": filter,
            }
        }
    elif url == "discover":
        payload = {
            "query": "query DiscoverSubredditsQuery( $filter: MediaFilter $limit: Int $iterator: String ) { \
                discoverSubreddits( isNsfw: true filter: $filter limit: $limit iterator: $iterator ) { \
                    items { \
                        children( limit: " f"{item_limit}" " iterator: null filter: " f"{filter if filter else 'null'}" " disabledHosts: null ) { \
                            items { \
                                id title mediaSources { url width height isOptimized } \
                            } \
                        } \
                    } \
                } \
            }",
            "variables": {
                "limit": req_limit,
                "filter": filter if filter != "SOUND" else "VIDEO",
            }
        }
    elif url == "following":
        payload = {
            "query": "query FollowingQuery( $iterator: String ) { \
                getFollowing( isNsfw: true limit: " f"{req_limit}" " iterator: $iterator ) { \
                    items { \
                        children( limit: " f"{item_limit}" " iterator: null filter: " f"{filter if filter else 'null'}" " disabledHosts: null ) { \
                            items { \
                                id title mediaSources { url width height isOptimized } \
                            } \
                        } \
                    } \
                } \
            }"
        }
    else:
        print(f"Error, unknown url param: {url}")
        return

    if token:
        payload["authorization"] = token

    while counter < amount:
        response_data = makeAPIRequest(api_url, payload, headers)
        if not response_data:
            print("API error! Can't get response!")
            return

        try:
            if url.startswith("/r/"):
                items = response_data["data"]["getSubreddit"]["children"]["items"]
            else:
                if url == "discover":
                    data = response_data["data"]["discoverSubreddits"]["items"]
                else:
                    data = response_data["data"]["getFollowing"]["items"]

                items = []
                for item in data:
                    items.extend(item["children"]["items"])

            for item in items:
                id = item["id"]
                if not id in media:
                    sources = item["mediaSources"]

                    if not sources:
                        continue

                    if low_quality:
                        sources = prioritize_media_sources(sources)

                    title = item["title"]
                    sizes = sources[0] if low_quality else sources[-1] # Best quality size are always last in the list

                    if is_downloaded_check:
                        valid_title = to_valid_filename(title)
                        filepath = get_filepath(out, valid_title, sizes["url"])
                        if os.path.exists(filepath):
                            continue

                    media[id] = (title, sources)
                    counter += 1
                    if output:
                        size = f"{sizes['width']}".rjust(4) + f" x {sizes['height']}".ljust(7)
                        print(f"{str(counter).rjust(len(amount_str))}/{amount_str}: {size} {title}")

                    if counter == amount:
                        return media

        except Exception:
            print(f"Can't parse responce! May be there was an error or images doesn't contain sources! API Response: {response_data}")

        time.sleep(2) # Sleep for getting different results

        if counter == old_counter:
            retry += 1
            error = f"Can't parse your amount: {url}! New data not provided, possibly all unique data is scraped"
            show_error_and_retry(error, retry, retries)
            if retry > retries:
                return media    # Return all results which were scraped

            time.sleep(3)
        else:
            retry = 0

        old_counter = counter


def process_all(
    options: list,
    amount: int,
    output_path: str,
    api_url: str,
    req_limit: int,
    retries: int,
    timeout: int,
    headers=dict(),
    item_limit=10,
    threads=5,
    subfolders=False,
    maxfilename=100,
    filter=None,
    token=None,
    low_quality=False,
    is_downloaded_check=False,
    output=True
):
    def process_one(task: str):
        if output:
            print(f"\n\nscraping '{task}'")

        if task != "following" and task != "discover":
            url = f"/r/{task}"
        else:
            url = task

        media = runParser(url, amount, token, api_url, req_limit, retries, headers, item_limit, filter, low_quality, is_downloaded_check, out, output)

        if not media:
            print(f"Media not scraped: {task}")
            if output:
                main_pbar.update(1)
                print()
            return 0

        if output:
            print(f"\nDonwloading '{task}'...")

        return downloadMedia(media, out, retries, timeout, headers, threads, maxfilename, low_quality, output, main_pbar)

    total = 0
    for option in options:
        if option == "discover" or option == "following":
            total += 1
        elif len(option) == 2:
            total += len(option[1])
        else:
            print(f"Option unknown: {option}! Will be skipped next!")

    if output and total:
        main_pbar = tqdm(total=total, desc="Total progress  ", position=1, dynamic_ncols=True)
        print()
    else:
        main_pbar = None

    downloaded = 0
    for option in options:
        if option == "discover" or option == "following":
            out = os.path.join(output_path, option) if subfolders else output_path
            if output:
                print(f"\n\n*** Processing '{option}' ***")
            downloaded += process_one(option)
            continue

        if len(option) != 2:
            continue

        out_subfolder = os.path.join(output_path, option[0]) if subfolders else output_path
        if output:
            print(f"\n\n*** Processing category '{option[0]}' ***")
        for subreddit in option[1]:
            out = os.path.join(out_subfolder, subreddit) if subfolders else output_path
            downloaded += process_one(subreddit)

    if main_pbar is not None:
        main_pbar.close()

    return downloaded


def isValid(only_video: bool, only_video_sound: bool, onlyImages: bool, following: bool, username: str, password: str):
    valid = True

    if only_video and (onlyImages or only_video_sound):
        print("ERROR! --only-video, --only-video-sound and --only-img can't be enabled together. Can't do anything!")
        valid = False

    if username and not password:
        print("ERROR! You don't enter --password for login!")
        valid = False
    elif not username and password:
        print("ERROR! You provide password, but don't enter --username!")
        valid = False

    if following and (not username or not password):
        print("ERROR! You can't scrape your following threads without login in your account!")
        valid = False

    return valid


def positive_int(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is not a positive integer")
    return ivalue


def non_negative_int(value):
    ivalue = int(value)
    if ivalue < 0:
        raise argparse.ArgumentTypeError(f"{value} is a negtive int")
    return ivalue


def parseOpt():
    parser = argparse.ArgumentParser(description="Scroller image scraper")

    parser.add_argument('--subreddits', type=str, help="Scrape from subbreddits (multiple allowed, splitted by comma)")
    parser.add_argument('--categories', type=str, help="Scrape from category (total media files = amount * categories * category_subreddits). 'all' - download from all categories")
    parser.add_argument('--discover', action='store_true', default=False, help="Scrape from discover page")
    parser.add_argument('--following', action='store_true', default=False, help="Scrape from following page (login required)")
    parser.add_argument('--only-video', action='store_true', default=False, help="Scrape only video")
    parser.add_argument('--only-video-sound', action='store_true', default=False, help="Scrape only video with sound")
    parser.add_argument('--only-img', action='store_true', default=False, help="Scrape only images")
    parser.add_argument('--low-quality', action='store_true', default=False, help="Download videos and images in low quality (much faster)")
    parser.add_argument('--subfolders', action='store_true', default=False, help="Put subreddits, discover and following in separate folders")
    parser.add_argument('--is-downloaded-check', action='store_true', default=False, help="Check if image already exist in output folder, don't download it again")
    parser.add_argument('--output-path', type=str, default="./media", help="Output path (default './media')")

    parser.add_argument('--username', type=str, help="Your username (for logging, optional)")
    parser.add_argument('--password', type=str, help="Your password (for logging, optional)")

    parser.add_argument('--api-url', type=str, default="https://api.scrolller.com/api/v2/graphql", help="API URL (if API was suddenly moved to another endpoint, don't provide)")

    parser.add_argument('--amount', type=positive_int, default=100, help="Amount (for each subreddit/page)")
    parser.add_argument('--timeout', type=positive_int, default=15, help="Timeout for each media request (in seconds)")
    parser.add_argument('--retries', type=non_negative_int, default=3, help="Max retries for each media request")
    parser.add_argument('--req-limit', type=positive_int, default=100, help="Media limit for each media API request")
    parser.add_argument('--item-limit', type=positive_int, default=10, help="Max media limit for each subreddit on discover or following page")
    parser.add_argument('--threads', type=positive_int, default=5, help="Number of threads for downloading media")
    parser.add_argument('--maxfilename', type=positive_int, default=100, help="Max filename length (without extension)")

    parser.add_argument('--user-agent', type=str, help="User agent header")

    parser.add_argument('--no-output', action='store_true', default=False, help="Will print only errors")

    return parser.parse_args()


def main(options):
    subreddits = options.subreddits
    categories = options.categories
    discover = options.discover
    following = options.following
    only_video = options.only_video
    only_video_sound = options.only_video_sound
    onlyImages = options.only_img
    low_quality = options.low_quality
    subfolders = options.subfolders
    is_downloaded_check = options.is_downloaded_check
    output_path = options.output_path
    username = options.username
    password = options.password
    api_url = options.api_url
    amount = options.amount
    timeout = options.timeout
    retries = options.retries
    req_limit = options.req_limit
    item_limit = options.item_limit
    threads = options.threads
    maxfilename = options.maxfilename
    output = not options.no_output
    headers = {"User-Agent": options.user_agent}

    if not isValid(only_video, only_video_sound, onlyImages, following, username, password):
        return

    if not subreddits and not categories and not discover and not following:
        if output:
            print("Nothing to scrape!")

        return

    if subreddits:
        subreddits = subreddits.split(',')

    if categories:
        categories = categories.split(',')

    token = None
    if username and password:
        token = getToken(username, password, api_url)
        if not token:
            print("Login failed!")
            return

        if output:
            print("Login success!")

    if output:
        print("\nParsing and downloading...")

    if onlyImages:
        filter = "PICTURE"
    elif only_video:
        filter = "VIDEO"
    elif only_video_sound:
        filter = "SOUND"
    else:
        filter = None

    to_process = []

    if subreddits:
        to_process.append(("subreddits", subreddits))

    if categories:
        orig_categories = getCategories(headers)
        if orig_categories:
            chosen = getSubredditsFromChosen(categories, orig_categories) # [(title, [subreddits]), ...]
            to_process.extend(chosen)

    if discover:
        to_process.append("discover")

    if following:
        to_process.append("following")

    downloaded = process_all(to_process, amount, output_path, api_url, req_limit, retries, timeout, headers, item_limit, threads,
                subfolders, maxfilename, filter, token, low_quality, is_downloaded_check, output)

    if output:
        print(f"\nDone! Total downloaded: {downloaded} media files")


if __name__ == '__main__':
    options = parseOpt()
    main(options)
