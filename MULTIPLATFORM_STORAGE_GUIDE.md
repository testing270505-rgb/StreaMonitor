# Multiplatform Model Feature - File Storage Structure

## Overview
When a model streams on multiple platforms, each stream is saved in **separate directories** to keep recordings organized by platform. This prevents storage waste and keeps downloads organized.

## Directory Structure

```
DOWNLOADS_DIR/
├── modelname [CS]/              # Parent stream - CamSoda
│   ├── modelname-20260529-120000.mp4
│   ├── modelname-20260529-150000.mp4
│   └── ...
│
├── modelname [CB]/              # Child stream - Chaturbate
│   ├── modelname-20260529-180000.mp4
│   └── ...
│
└── anothermodel [SC]/           # Single/Independent stream
    └── anothermodel-20260529-090000.mp4
```

## How It Works

### 1. **Parent-Child Relationship**
```
add modelname CS                              # Add parent (CamSoda)
add modelname CB parent modelname CS          # Add child (Chaturbate)
```

- **modelname [CS]** = Parent stream (higher priority)
- **modelname [CB]** = Child stream (fallback)

### 2. **Recording Priority & File Storage**

#### Scenario 1: Both streams live
```
Time 12:00 - modelname goes live on CS (parent)
    ✓ Recording starts in: modelname [CS]/
    ✓ File: modelname-20260529-120000.mp4

Time 12:10 - modelname goes live on CB (child)
    ✗ Child stream detected but parent already recording
    ✗ CB stream is NOT recorded (no file created)
```

#### Scenario 2: Child comes live first, then parent
```
Time 12:00 - modelname goes live on CB (child)
    ✓ Recording starts in: modelname [CB]/
    ✓ File: modelname-20260529-120000.mp4

Time 12:10 - modelname goes live on CS (parent)
    ✗ Parent detected, stop CB recording
    ✗ Delete or keep? → Currently kept (configurable)
    ✓ Recording starts in: modelname [CS]/
    ✓ File: modelname-20260529-121000.mp4
```

#### Scenario 3: Parent offline, child records
```
Time 12:00 - modelname goes offline on CS (parent)
    ✓ System checks child (CB)
    ✓ CB is live, start recording there
    ✓ File: modelname [CB]/modelname-20260529-120500.mp4

Time 12:15 - modelname comes back online on CS (parent)
    ✗ Stop CB recording immediately
    ✓ Resume CS recording
    ✓ File: modelname [CS]/modelname-20260529-121500.mp4
```

## Configuration Example

**config.json**
```json
[
  {
    "site": "CS",
    "username": "modelname",
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
    "username": "modelname",
    "running": true,
    "country": null,
    "gender": null,
    "priority": 2,
    "is_child": true,
    "parent_username": "modelname",
    "parent_site": "CS"
  }
]
```

## Key Points

✅ **Benefits of Separate Directories:**
- Easy to identify which platform the recording came from
- No duplicate filenames (each platform has its own folder)
- Storage is only used when actually recording
- Clear separation for organization

✅ **Smart Recording Logic:**
- Parent always takes priority
- Only one stream records at a time per model family
- Automatic fallback to child when parent is offline
- Status display shows parent/child relationships

⚠️ **Important:**
- If parent is live, child will NOT record (even if also live)
- If child is recording and parent comes online, child stops immediately
- Each platform gets its own folder: `modelname [SITE]`
- Priority is configurable (lower number = higher priority)

## File Naming Format

All files follow the pattern:
```
{username}-{YYYYMMDD}-{HHMMSS}.{CONTAINER}
```

Examples:
- `modelname-20260529-120000.mp4` (CamSoda)
- `modelname-20260529-180000.mp4` (Chaturbate)

**Same model, different folders, different times = No conflicts!**
