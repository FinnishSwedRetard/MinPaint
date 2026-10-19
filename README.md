# MinPaint

**le art** is a shared 1920 × 1080 pixel canvas. Pick a color, zoom in, and drop a pixel into the internet's group masterpiece. Everyone connected sees new marks; each browser gets one pixel every 60 seconds.

## Download for Windows

Download **MinPaint.exe** from the [latest GitHub release](https://github.com/FinnishSwedRetard/MinPaint/releases/latest), then double-click it. The canvas opens in your browser at `http://localhost:3000`.

Keep the console window open while people are painting; close it or press Ctrl+C to stop the server. The board is saved in `%LOCALAPPDATA%\MinPaint\board.json`.

Zoom using the `+` and `−` buttons or your mouse wheel. When zoomed in, drag the canvas to pan around. Click a pixel to paint it.

To let people outside your Wi-Fi connect, you need to expose the server to the internet. The console shows your local address and setup steps for Windows Firewall and router port forwarding. Share your public IP with port `3000`, or configure a domain and HTTPS in front of the server. Your router or internet provider may block port forwarding, and a public MinPaint instance is not suitable for private information.

## Run from source

Requires Python 3.10 or newer. No runtime packages are needed.

```sh
python server.py
```

Open [http://localhost:3000](http://localhost:3000). Set the `PORT` environment variable to change the port. The board and cooldowns are saved in `data/board.json`.

## Build the Windows executable

Requires Python only to build the executable; people running the built `.exe` do not need Python.

```bat
py -3 -m pip install -r requirements-build.txt
build_exe.bat
```

The executable is written to `release\MinPaint.exe`.

The board is shared by all visitors to the same running server. The cooldown is tied to an anonymous browser cookie; clearing cookies or using another browser creates a new visitor identity. For a more reliable public site, run MinPaint on an always-on internet server instead of a home PC.
