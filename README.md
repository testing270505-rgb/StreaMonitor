# StreaMonitor
A Python3 application for monitoring and saving (mostly adult) live streams from various websites.

Inspired by [Recordurbate](https://github.com/oliverjrose99/Recordurbate)

## Supported sites
| Site name     | Abbreviation | Aliases                     | Quirks                 | Selectable resolution |
|---------------|--------------|-----------------------------|------------------------|-----------------------|
| Bongacams     | `BC`         |                             |                        | Yes                   |
| Cam4          | `C4`         |                             |                        | Yes                   |
| Cams.com      | `CC`         |                             |                        | Currently only 360p   |
| CamSoda       | `CS`         |                             |                        | Yes                   |
| Chaturbate    | `CB`         |                             |                        | Yes                   |
| DreamCam      | `DC`         |                             |                        | No                    |
| DreamCam VR   | `DCVR`       |                             | for VR videos          | No                    |
| FanslyLive    | `FL`         |                             |                        | Yes                   |
| Flirt4Free    | `F4F`        |                             |                        | Yes                   |
| MyFreeCams    | `MFC`        |                             |                        | Yes                   |
| SexChat.hu    | `SCHU`       |                             | use the id as username | No                    |
| StreaMate     | `SM`         | PornHubLive, PepperCams,... |                        | Yes                   |
| StripChat     | `SC`         | XHamsterLive,...            | must add crypto keys   | Yes                   |
| StripChat VR  | `SCVR`       |                             | for VR videos          | No                    |
| XLoveCam      | `XLC`        |                             |                        | No                    |

Currently not supported:
* Amateur.TV (They use Widevine now)
* Cherry.tv (They switched to Agora)
* ImLive (Too strict captcha protection for scraping)
* LiveJasmin (No nudity in free streams)
* ManyVids Live (They switched to Agora)

There are hundreds of clones of the sites above, you can read about them on [this site](https://adultwebcam.site/clone-sites-by-platform/).

## Requirements
* Python 3
  * Install packages listed in requirements.txt with pip.
* FFmpeg

## Usage

The application has the following interfaces:
* Console
* External console via ZeroMQ (sort of working)
* Web interface

#### Starting and console
Start the downloader (it does not fork yet)\
Automatically imports all streamers from the config file.
```
python3 Downloader.py
```

On the console you can use the following commands:
```
add <username> <site> - Add streamer to the list (also starts monitoring)
remove <username> [<site>] - Remove streamer from the list
start <username> [<site>] - Start monitoring streamer
start * - Start all
stop <username> [<site>] - Stop monitoring
stop * - stop all
status - Status display 
status2 - A slightly more readable status table
quit - Clean exit (Pressing CTRL-C also behaves like this)
```
For the `username` input, you usually have to enter the username as represented in the original URL of the room. 
Some sites are case-sensitive.

For the `site` input, you can use either the full or the short format of the site name. (And it is case-insensitive)

#### "Remote" controller
Add or remove a streamer to record (Also saves config file)
```
python3 Controller.py add <username> <website>
python3 Controller.py remove <username>
```

Start/stop recording streamers
```
python3 Controller.py <start|stop> <username>
```

List the streamers in the config
```
python3 Controller.py status
```

#### Web interface

You can access the web interface on port 5000. 
If set password in parameters.py username is admin, password admin, empty password is also allowed.
When you set the WEBSERVER_HOST it is also accesible to from other computers in the network

## Docker support

You can run this application in docker. I prefer docker-compose so I included an example docker-compose.yml file that you can use.
Simply start it in the folder with `docker-compose up`.

## Configuration

You can set some parameters in the [parameters.py](parameters.py).

### Proxy fallback and stalled recordings

Status and stream requests start with the direct connection. A rate-limit
switches that streamer's session to the rate-limit proxy, while a geographic
restriction switches it to the geo proxy. The selected route remains active
for playlist and FFmpeg requests and is included in the recording log.

```dotenv
STRMNTR_RATE_LIMIT_PROXY=http://127.0.0.1:8881
STRMNTR_RATE_LIMIT_PROXY_NAME=India proxy
STRMNTR_GEO_PROXY=http://127.0.0.1:8882
STRMNTR_GEO_PROXY_NAME=US proxy
STRMNTR_FLARESOLVERR_URL=http://127.0.0.1:8191/v1
STRMNTR_FLARESOLVERR_RATE_LIMIT_PROXY=http://proton-india:8888
STRMNTR_FLARESOLVERR_GEO_PROXY=http://proton-us:8888
STRMNTR_FFMPEG_STALL_TIMEOUT=60
```

When a response contains Cloudflare challenge markers, StreaMonitor asks
FlareSolverr to solve it, imports the returned cookies and browser user agent,
and continues through the same direct/VPN route. FlareSolverr and the Gluetun
containers must share a container network for the internal proxy addresses
above to resolve. FlareSolverr is not used for media downloads.

When StreaMonitor itself runs in a container, `127.0.0.1` refers to that
container. Use the Podman host address instead, for example
`http://host.containers.internal:8881` and `:8882`.

You also have to add decryption keys yourself for StripChat in the `stripchat_mouflon_keys.json` file.

## Disclaimer

This program is only a proof of concept and education project, I don't encourage anybody to use it. \
Most (if not every) streamers disallow recording their shows. Please respect their wish. \
If you don't, and you record them despite this request, please don't ever publish or share any recordings. \
If you either record or share the recorded shows, you might be legally punished. \
Also, please don't use this tool for monetization in any way.
