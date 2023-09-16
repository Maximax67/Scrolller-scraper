# Scrolller scraper

This script is designed to scrape images and videos from [scrolller.com](https://scrolller.com/), a website that aggregates content from various subreddits. It provides you with the flexibility to scrape media from specific subreddits, categories, the discover page, or your following page (requires login). You can also filter media to scrape only images, videos, or videos with sound.

## Requirements

Make sure you have the following prerequisites:

- Python 3.x
- Python `requests` library
- Python `tqdm` library

You can install the required libraries using pip:

```bash
pip install requests tqdm
```

## Usage

1. Clone this repository or download the script to your local machine.
2. Open a terminal or command prompt and navigate to the directory containing the script.
3. Run the script with the desired options. You can see the available options by running:

```bash
python scrolller_scraper.py --help
```

4. The script will scrape and download media based on your specified options.

## Options

Here are the available options for the script:

- `--subreddits`: Specify subreddits to scrape from (multiple subreddits can be provided, separated by commas).
- `--categories`: Specify categories to scrape from (will download "amount" of media files for each subreddit in categories). 'all' - download from all categories (not recommended).
- `--discover`: Enable scraping from the discover page.
- `--following`: Enable scraping from the following page (requires login).
- `--only-video`: Scrape only videos.
- `--only-video-sound`: Scrape only videos with sound.
- `--only-img`: Scrape only images.
- `--low-quality`: Download videos and images in low quality (much faster)
- `--subfolders`: Organize scraped media into separate subfolders for each source (subreddits, discover, following).
- `--is-downloaded-check`: Check if image already exist in output folder, don't download it again.
- `--output-path`: Specify the output directory where the scraped media will be saved (default is "./media").
- `--username`: Your username for login (optional, only for following page).
- `--password`: Your password for login (optional, only for following page).
- `--api-url`: API URL for scrolller (usually, you don't need to change this).
- `--amount`: The number of media items to scrape for each source (default is 100).
- `--timeout`: Timeout for each media request in seconds (default is 15).
- `--retries`: Maximum retries for each media request (default is 3).
- `--req-limit`: Media limit for each API request (default is 100).
- `--item-limit`: Maximum media limit for each subreddit on the discover or following page (default is 10).
- `--threads`: Number of threads for downloading media (default is 5).
- `--maxfilename`: Max filename length (without extension, default is 100).
- `--user-agent`: User agent header.
- `--no-output`: Disable all output except for errors.

## Examples

1. Scrape 100 images from the subreddit "cats" and save them to the "./cat_images" directory:

```bash
python scrolller_scraper.py --subreddits cats --only-img --output-path ./cat_images
```

2. Scrape media from the following page (requires login):
```bash
python scrolller_scraper.py --following --subfolders --username your_username --password your_password
```

3. Scrape 20 videos with sound from the discover page and save them to the "./discover_videos" directory:
```bash
python scrolller_scraper.py --discover --only-video-sound --amount 200 --output-path ./discover_videos
```

4. Scrape 50 media files (images and videos) for each of multiple subreddits and save them to the "./mixed_media" directory, organize them into subfolders:
```bash
python scrolller_scraper.py --subreddits cats,dogs --amount 50 --output-path ./mixed_media --subfolders
```

5. Silently download 10 videos from cats subreddit and discovery page:
```bash
python scrolller_scraper.py --subreddits cats --discover --amount 10 --only-video --no-output
```

6. Download 10 images from each subreddit of "asian" and "guns" categories, organize them in subfolders:
```bash
python scrolller_scraper.py --categories asian,guns --amount 10 --only-img --subfolders
```

## License

This script is provided under the MIT License. You are free to use, modify, and distribute it as per the terms of the license.
