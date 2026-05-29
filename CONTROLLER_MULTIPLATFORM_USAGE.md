# Controller.py - Multiplatform Model Usage

## Overview
The `Controller.py` script sends remote commands via ZMQ to the running Downloader instance. It now supports multiplatform model commands.

## Installation & Setup

### Prerequisites
```bash
# Make sure Downloader.py is running in background
python3 Downloader.py &
```

## Usage Examples

### 1. Add Parent Stream
```bash
python3 Controller.py add model1 CS
```

### 2. Add Child Stream (NEW!)
```bash
python3 Controller.py add model1 CB parent model1 CS
```

### 3. Remove Streamer
```bash
# Remove specific site
python3 Controller.py remove model1 CB

# Remove parent (warns about orphaned children)
python3 Controller.py remove model1 CS
```

### 4. Start/Stop
```bash
# Start specific streamer
python3 Controller.py start model1 CS

# Stop specific streamer
python3 Controller.py stop model1 CB

# Start all
python3 Controller.py start *

# Stop all
python3 Controller.py stop *
```

### 5. View Status
```bash
# Full status with relationships
python3 Controller.py status

# Status for specific streamer
python3 Controller.py status model1 CS
```

### 6. Help
```bash
python3 Controller.py help
```

## Remote Host Usage

You can control a remote Downloader instance:

```bash
# Using -h flag with host:port
python3 Controller.py -h 192.168.1.100:6969 add model1 CS
python3 Controller.py -h 192.168.1.100:6969 add model1 CB parent model1 CS

# Or use environment
python3 Controller.py -h192.168.1.100:6969 status
```

## Real-World Example

### Setup Multiple Models with Multiplatform Support

```bash
# Terminal 1: Start Downloader
python3 Downloader.py

# Terminal 2: Add models using Controller

# Model 1 - CamSoda primary, Chaturbate fallback
python3 Controller.py add model1 CS
python3 Controller.py add model1 CB parent model1 CS

# Model 2 - Chaturbate primary, CamSoda fallback
python3 Controller.py add model2 CB
python3 Controller.py add model2 CS parent model2 CB

# Model 3 - Three platforms (Model3 on SC, CB, F4F)
python3 Controller.py add model3 SC              # Parent
python3 Controller.py add model3 CB parent model3 SC   # Child 1
python3 Controller.py add model3 F4F parent model3 SC  # Child 2

# Start all
python3 Controller.py start *

# Check status
python3 Controller.py status

# Stop a specific child
python3 Controller.py stop model1 CB

# Remove a child
python3 Controller.py remove model1 CB
```

## Recording Behavior with Controller

When you use Controller.py to set up multiplatform models:

```bash
# Setup
python3 Controller.py add model1 CS
python3 Controller.py add model1 CB parent model1 CS

# Both streams added to config.json
# Start monitoring
python3 Controller.py start *

# Recording happens:
# - If model1 live on CS → records to: model1 [CS]/
# - If model1 live only on CB → records to: model1 [CB]/
# - If both live → only model1 [CS]/ records (CB is fallback)
# - If model1 offline on CS but live on CB → falls back to model1 [CB]/
```

## Status Display with Controller

```bash
$ python3 Controller.py status

Status:
Free space: 45.234%

+-----------+-----------+---------+---------+---------+
| Username  | Site      | Started | Status  | Type    |
+-----------+-----------+---------+---------+---------+
| model1    | CS        | True    | Channel | Parent  |
| model1    | CB        | True    | No      | Child   |
| model2    | SC        | True    | Channel | Single  |
+-----------+-----------+---------+---------+---------+
```

## Configuration Auto-Generated

After using Controller.py to add multiplatform models, your `config.json` will look like:

```json
[
  {
    "site": "CS",
    "username": "model1",
    "running": true,
    "country": null,
    "gender": null,
    "priority": 1,
    "is_child": false,
    "parent_username": null,
    "parent_site": null
  },
  {
    "site": "CB",
    "username": "model1",
    "running": true,
    "country": null,
    "gender": null,
    "priority": 2,
    "is_child": true,
    "parent_username": "model1",
    "parent_site": "CS"
  }
]
```

## Troubleshooting

### "Streamer not found" error
```bash
# When adding child, parent must already exist
# Wrong - parent doesn't exist yet:
python3 Controller.py add model1 CB parent model1 CS  # ❌

# Correct - add parent first:
python3 Controller.py add model1 CS                   # ✓
python3 Controller.py add model1 CB parent model1 CS  # ✓
```

### "Connection refused"
```bash
# Make sure Downloader is running
python3 Downloader.py &

# Then use Controller
python3 Controller.py status
```

### Can't connect to remote host
```bash
# Check firewall allows port 6969
# Check WEBSERVER_HOST in parameters.py
python3 Controller.py -h 192.168.1.100:6969 status
```

## File Storage with Controller

When using Controller.py to add models:

```
DOWNLOADS_DIR/
├── model1 [CS]/           ← Added via: python3 Controller.py add model1 CS
│   └── model1-*.mp4       ← Parent recordings
├── model1 [CB]/           ← Added via: python3 Controller.py add model1 CB parent model1 CS
│   └── model1-*.mp4       ← Child recordings (only if CS offline)
└── model2 [SC]/
    └── model2-*.mp4
```

## Command Reference

```bash
# Multiplatform Model Commands
python3 Controller.py add <username> <site>                        # Add parent
python3 Controller.py add <username> <site> parent <parent_username> <parent_site>  # Add child
python3 Controller.py remove <username> [<site>]                   # Remove streamer
python3 Controller.py start <username> [<site>]                    # Start monitoring
python3 Controller.py stop <username> [<site>]                     # Stop monitoring
python3 Controller.py status [<username> [<site>]]                 # View status
python3 Controller.py help                                          # Show help

# Remote execution
python3 Controller.py -h <host:port> <command>                     # Remote command
```

## Summary

✅ **Controller.py now supports:**
- Adding parent streams: `add model1 CS`
- Adding child streams: `add model1 CB parent model1 CS`
- All standard commands work with multiplatform models
- Automatic config.json updates
- Remote control via ZMQ

✅ **File Storage:**
- Each platform gets separate folder
- Automatic priority-based recording
- No duplicate files

✅ **Usage:**
```bash
python3 Controller.py add model1 CB parent model1 CS
```
Works exactly as intended! 🎉
