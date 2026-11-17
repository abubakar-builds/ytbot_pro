# Video Downloader

Flask + yt-dlp web app.

## Structure
```
app.py            API + serves public/index.html
public/index.html frontend (move your index.html here)
requirements.txt  Python dependencies
vercel.json       Vercel function settings
Dockerfile        for Render / Railway / Fly.io / VPS
```

## Run locally
```
pip install -r requirements.txt
python app.py        # http://localhost:5000
```

## Deploy
- **Vercel**: import the GitHub repo. Works for the page and `/api/info`.
  Downloads are limited (see below).
- **Render / Railway / Fly.io** (recommended for downloads): deploy with the
  Dockerfile. Optionally host only the frontend on Vercel and set `API_BASE`
  in `index.html`, plus `ALLOWED_ORIGIN` on the API host.

## Environment variables
| Name | Purpose |
|------|---------|
| `MAX_FILESIZE_MB` | Max download size (default 500) |
| `ALLOWED_ORIGIN` | Frontend origin allowed to call the API (CORS) |
| `YT_COOKIES` | Optional cookies.txt contents if YouTube shows a bot check |
| `FFMPEG_LOCATION` | Optional custom ffmpeg path |

## Known Vercel limits
- Responses are capped at ~4.5 MB, so real video files cannot be streamed back.
- Function time limit depends on your plan.
- YouTube often blocks cloud/datacenter IPs.
