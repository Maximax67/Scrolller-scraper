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


def download_single(sources: list, path: str, title: str, max_retries: int, timeout: int, headers=dict()):
    for source in sources:
        url = source['url']
        extension = getFileExtension(url)
        filename = f"{title}{f'.{extension}' if extension else ''}"
        retries = 0
        while retries < max_retries:
            try:
                session = requests.Session()
                response = session.get(url, stream=True, timeout=timeout, headers=headers)
                if response.status_code == 200:
                    file_path = os.path.join(path, filename)
                    with open(file_path, 'wb') as f:
                        for chunk in response.iter_content(64 * 1024):
                            f.write(chunk)
                    return  # Successful download
                else:
                    retries += 1
                    print(f"Failed to download image {filename} - Status Code: {response.status_code}. Retrying ({retries}/{max_retries})...")
                    time.sleep(5)
            except requests.exceptions.ReadTimeout:
                retries += 1
                print(f"Read timeout occurred while downloading image {filename}. Retrying ({retries}/{max_retries})...")
                time.sleep(5)
            except requests.exceptions.RequestException as e:
                retries += 1
                print(f"Error downloading image {filename}: {e}")
                time.sleep(5)

        print(f"Downloading '{filename}' in lower quality...")


def getFileExtension(file_path: str):
    last_dot_index = file_path.rfind('.')
    if last_dot_index == -1 and last_dot_index != len(file_path) - 1:
        return None

    return file_path[last_dot_index + 1:].lower()


def to_valid_filename(name: str):
    filename = name.replace(" ", "_")
    filename = re.sub(r'[^\w.-]', '', filename)

    if len(filename) > 25:
        filename = filename[:25]

    return filename


def downloadMedia(media: dict, output_path: str, retries: int, timeout: int, headers=dict(), threads=5, low_quality=False, output=True):
    os.makedirs(output_path, exist_ok=True)

    total = len(media)
    lock = threading.Lock()

    def update_progress():
        with lock:
            if output:
                pbar.update(1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = []
        for value in media.values():
            try:
                title, sources = value
                # Best quality media are always last in the list
                if not low_quality:
                    sources.reverse()
                title = to_valid_filename(title)
                future = executor.submit(download_single, sources, output_path, title, retries, timeout, headers)
                future.add_done_callback(lambda _: update_progress())
                futures.append(future)
            except requests.exceptions.RequestException as e:
                print(f"Error! {e}")

        if output:
            with tqdm(total=total) as pbar:
                for future in concurrent.futures.as_completed(futures):
                    future.result()


def getToken(username: str, password: str, api_url: str, headers=dict()):
    payload = {
        "query": "query LoginQuery($username: String!, $password: String!) { \
                    login(username: $username, password: $password) { \
                        token expiresAt \
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


def runParser(url: str, amount: int, token: str, api_url: str, req_limit=50, headers=dict(), item_limit=2, filter='', low_quality=False, output=True):
    old_counter = 0
    counter = 0
    media = {}
    amount_str = str(amount)
    while counter < amount:
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

        payload["authorization"] = token

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

                    if low_quality:
                        sources = prioritize_media_sources(sources)

                    title = item["title"]
                    media[id] = (title, sources)
                    sizes = sources[0] if low_quality else sources[-1] # Best quality size are always last in the list
                    counter += 1
                    if output:
                        size = f"{sizes['width']}".rjust(4) + f" x {sizes['height']}".ljust(7)
                        print(f"{str(counter).rjust(len(amount_str))}/{amount_str}: {size} {title}")

                if counter == amount:
                    break
        except Exception:
            print(f"Can't parse responce! May be it is empty! API Response: {response_data}")

        if counter == old_counter:
            print(f"Can't parse your amount: {url}! New data not provided, all unique data is scrapped! Total scrapped {counter}/{amount_str}")
            return media

        old_counter = counter

    return media


def process_options(
    option: str,
    amount: int,
    output_path: str,
    api_url: str,
    req_limit: int,
    retries: int,
    timeout: int,
    headers=dict(),
    item_limit=10,
    threads=5,
    filter=None,
    token=None,
    low_quality=False,
    output=True
):
    if output:
        print(f"Scrapping '{option}'")

    if option != "following" and option != "discover":
        url = f"/r/{option}"
    else:
        url = option

    media = runParser(url, amount, token, api_url, req_limit, headers, item_limit, filter, low_quality, output)

    if not media:
        print("Media not scrapped!")
        return

    if output:
        print(f"\nDonwloading '{option}'...\n")

    downloadMedia(media, output_path, retries, timeout, headers, threads, low_quality, output)


def isValid(retries: int, timeout: int, req_limit: int, threads: int, onlyVideo: bool, onlyVideoSound: bool, onlyImages: bool, following: bool, username: str, password: str):
    valid = True

    if retries < 1:
        print("Retries can't be less than 1!")
        valid = False

    if timeout < 1:
        print("Timeout can't be less than 1")
        valid = False

    if req_limit < 1:
        print("Request limit can't be less than 1")
        valid = False

    if threads < 1:
        print("Threads can't be less than 1")
        valid = False

    if onlyVideo and (onlyImages or onlyVideoSound):
        print("--only-video, --only-video-sound and --only-img can't be enabled together. Can't do anything!")
        valid = False

    if username and not password:
        print("You don't enter --password for login!")
        valid = False
    elif not username and password:
        print("You provide password, but don't enter --username!")
        valid = False

    if following and (not username or not password):
        print("You can't scrape your following threads without login in your account!")
        valid = False

    return valid


def parseOpt():
    parser = argparse.ArgumentParser(description="Scroller image scrapper")

    parser.add_argument('--subreddits', type=str, help="Scrape from subbreddits (multiple allowed, splitted by comma)")
    parser.add_argument('--discover', action='store_true', default=False, help="Scrape from discover page")
    parser.add_argument('--following', action='store_true', default=False, help="Scrape from following page (login required)")
    parser.add_argument('--only-video', action='store_true', default=False, help="Scrape only video")
    parser.add_argument('--only-video-sound', action='store_true', default=False, help="Scrape only video with sound")
    parser.add_argument('--only-img', action='store_true', default=False, help="Scrape only images")
    parser.add_argument('--low-quality', action='store_true', default=False, help="Download videos and images in low quality (much faster)")
    parser.add_argument('--subfolders', action='store_true', default=False, help="Put subreddits, discover and following in separate folders")
    parser.add_argument('--output-path', type=str, default="./media", help="Output path (default './media')")

    parser.add_argument('--username', type=str, help="Your username (for logging, optional)")
    parser.add_argument('--password', type=str, help="Your password (for logging, optional)")

    parser.add_argument('--api-url', type=str, default="https://api.scrolller.com/api/v2/graphql", help="API URL (if API was suddenly moved to another endpoint, don't provide)")

    parser.add_argument('--amount', type=int, default=100, help="Amount (for each subreddit/page)")
    parser.add_argument('--timeout', type=int, default=15, help="Timeout for each media request (in seconds)")
    parser.add_argument('--retries', type=int, default=3, help="Max retries for each media request")
    parser.add_argument('--req-limit', type=int, default=100, help="Media limit for each media API request")
    parser.add_argument('--item-limit', type=int, default=10, help="Max media limit for each subreddit on discover or following page")
    parser.add_argument('--threads', type=int, default=5, help="Number of threads for downloading media")

    parser.add_argument('--user-agent', type=str, default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36", help="User agent header")

    parser.add_argument('--no-output', action='store_true', default=False, help="Will print only errors")

    return parser.parse_args()


def main(options):
    subreddits = options.subreddits
    discover = options.discover
    following = options.following
    onlyVideo = options.only_video
    onlyVideoSound = options.only_video_sound
    onlyImages = options.only_img
    low_quality = options.low_quality
    subfolders = options.subfolders
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
    output = not options.no_output
    headers = {"User-Agent": options.user_agent}

    if not isValid(retries, timeout, req_limit, threads, onlyVideo, onlyVideoSound, onlyImages, following, username, password):
        return

    if not subreddits and not discover and not following:
        if output:
            print("Nothing to scrape!")
        return

    if subreddits:
        subreddits = subreddits.split(',')

    token = None
    if username and password:
        token = getToken(username, password, api_url)
        if not token:
            print("Login failed!")
            return

        if output:
            print("Login success!")

    if output:
        print("\nParsing and downloading...\n")

    if onlyImages:
        filter = "PICTURE"
    elif onlyVideo:
        filter = "VIDEO"
    elif onlyVideoSound:
        filter = "SOUND"
    else:
        filter = None

    if subreddits:
        for subreddit in subreddits:
            out = os.path.join(output_path, subreddit) if subfolders else output_path
            process_options(subreddit, amount, out, api_url, req_limit, retries, timeout, headers,
                            item_limit, threads, filter, token, low_quality, output)

    if discover:
        out = os.path.join(output_path, "discover") if subfolders else output_path
        process_options("discover", amount, out, api_url, req_limit, retries, timeout, headers,
                        item_limit, threads, filter, token, low_quality, output)

    if following:
        out = os.path.join(output_path, "following") if subfolders else output_path
        process_options("following", amount, out, api_url, req_limit, retries, timeout, headers,
                        item_limit, threads, filter, token, low_quality, output)

    if output:
        print("\nDone!")


if __name__ == '__main__':
    options = parseOpt()
    main(options)
