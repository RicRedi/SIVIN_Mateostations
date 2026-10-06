# SIVIN_Mateostations

A comprehensive meteorological data analysis and visualization toolkit for analyzing multi-sensor weather station networks, with specialized support for viticulture-relevant metrics and automated data collection. This project is designed to help researchers and technicians monitor, process, and visualize meteorological data across distributed sensor networks.

**Author:** Richard Redina  
**Email:** 195715@vut.cz  
**Affiliation:** International Clinical Research Center, Brno; Brno University of Technology  
**GitHub:** RicRedi

## Quick start (package `sivin`)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,ingest,viz]"
cp .env.example .env                 # portal credentials SIVIN_USER, SIVIN_PASSWORD
.venv/bin/sivin sensors check        # registry and off-site log
.venv/bin/sivin run                  # fetch -> ingest -> quality control -> indices
```

Commands, options and exit codes: [docs/cli.md](docs/cli.md); the one configuration file
`config/sivin.yaml`: [docs/configuration.md](docs/configuration.md); architecture:
[docs/architecture.md](docs/architecture.md). The rest of this README describes the legacy
scripts and is rewritten in WP-5.2.

## Operations

The workflow `.github/workflows/pipeline.yml` runs the pipeline every day at 06:00
Europe/Prague (and on demand from the Actions tab), keeps the measurements on the `data`
branch and deploys the map portal to GitHub Pages. One-time setup, the first-run checklist,
manual runs, the job summary and exit codes, editing the sensor registry and the off-site log,
and recovery of the `data` branch: [docs/operations.md](docs/operations.md).

## Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Usage](#usage)
  - [Data Collection](#data-collection)
  - [Data Analysis](#data-analysis)
  - [Data Visualization](#data-visualization)
- [Component Documentation](#component-documentation)
- [Configuration Guide](#configuration-guide)
- [Output Structure](#output-structure)
- [Future Development](#future-development)
- [Troubleshooting](#troubleshooting)

---

## Overview

The SIVIN_Mateostations project provides an integrated workflow for:

1. **Automated Data Collection**: Scrapes meteorological data from remote sensors via web interface
2. **Agricultural Analysis**: Calculates viticulture-specific metrics (Growing Degree Days, Huglin Index, frost risk, etc.)
3. **Data Visualization**: Generates publication-quality plots with bilingual support (Czech/German)
4. **Results Export**: Produces JSON analysis reports and multi-format graphics

### Key Features

- **Multi-sensor Support**: Processes data from multiple weather stations simultaneously
- **Viticulture Metrics**: Specialized calculations for grape growing regions
- **Bilingual Configuration**: Easy switching between Czech (CZ) and German (DE) labels
- **Multiple Export Formats**: PNG, PDF, EPS with configurable resolution
- **YAML-based Configuration**: Human-readable, version-controllable settings
- **Automated Web Scraping**: Selenium-based data collection from SIVIN VUT portal

---

## Project Structure

```
SIVIN_Mateostations/
├── chrome_driver.py              # Automated web scraper for data collection
├── chrome_driver.env             # Environment variables (credentials, paths) - USER-CONFIGURED, KEEP SECURE
├── vineyard_analyst.py           # Core analysis engine with viticulture metrics
├── vineyard_analyst.yaml         # Configuration for vineyard analysis
├── one_variable_plot.py          # Single-variable plotting script
├── two_variable_plot.py          # Dual-axis plotting script
├── sampl_freq_basic.py           # Sampling frequency analysis utility
├── pozice čidel.gpx              # Sensor location data (GPX format)
│
├── config/
│   ├── one_variable_plot.yaml    # Configuration for single plots
│   └── two_variable_plot.yaml    # Configuration for dual-axis plots
│
├── data/
│   └── MeteoData_*.csv           # Raw meteorological data files from sensors
│
├── vystupy/                      # Output directory (results)
│   ├── analysis/
│   │   └── Analysis_*.json       # JSON analysis results (timestamped)
│   └── grafy/                    # Graph exports organized by format
│       ├── eps/
│       ├── pdf/
│       └── png/
│
├── requirements.txt              # Python package dependencies
└── README.md                     # This file
```

**Key Files**:

- **`chrome_driver.env`** - Configuration file (YOU CREATE THIS)
  - Contains portal credentials and download settings
  - Never commit to version control
  - Must be created by each team member with their own credentials
  - See [Step 6: Configure Chrome Driver Environment](#step-6-configure-chrome-driver-environment) for template

- **`chrome_driver.py`** - Web scraper (SYSTEM FILE)
  - Automatically downloads data from SIVIN VUT portal
  - Loads all settings from `chrome_driver.env`
  - Requires Chrome browser installed

- **`vineyard_analyst.py`** - Analysis engine (SYSTEM FILE)
  - Calculates viticulture metrics from downloaded data
  - Configured via `vineyard_analyst.yaml`

- **`data/`** - Input folder
  - Store downloaded Excel files here
  - Path configured in `chrome_driver.env` (`DOWNLOAD_FOLDER` parameter)

- **`vystupy/`** - Output folder
  - Analysis JSON files
  - Generated plots in multiple formats

---

## Installation

### Prerequisites

- **Python 3.8+** (tested on Python 3.10+)
- **Google Chrome** (required for web scraping functionality)
- **Windows OS** (script paths configured for Windows; requires adaptation for Linux/macOS)

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd SIVIN_Mateostations
```

### Step 2: Create Virtual Environment

```bash
# Using venv (recommended)
python -m venv venv
venv\Scripts\activate

# Or using conda
conda create -n sivin python=3.10
conda activate sivin
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Create Output Directories

```bash
mkdir vystupy\analysis
mkdir vystupy\grafy\eps
mkdir vystupy\grafy\pdf
mkdir vystupy\grafy\png
```

### Step 6: Configure Chrome Driver Environment

Create `chrome_driver.env` in the project root directory. This file contains all configuration needed for automated data collection from the SIVIN VUT portal.

**Important**: Never commit `chrome_driver.env` to version control (add it to `.gitignore`). Each team member should create their own copy with their credentials.

#### Template for chrome_driver.env

Create a file named `chrome_driver.env` with the following structure:

```env
# ============================================================
# CREDENTIALS (required)
# ============================================================
SIVIN_USER=your_username
SIVIN_PASSWORD=your_password

# ============================================================
# FILE PATHS (required)
# ============================================================
# Absolute path where Excel files will be downloaded
DOWNLOAD_FOLDER=C:\path\to\your\download\folder

# ============================================================
# TIMING CONFIGURATION (in seconds)
# Adjust these based on your network speed and system performance
# ============================================================
# Maximum time to wait for page elements to appear (login, tabs, buttons)
WAIT_TIMEOUT=15

# Maximum time to wait for file download to complete
DOWNLOAD_WAIT_TIMEOUT=30

# Delay after scrolling the page (prevents timing issues)
SCROLL_WAIT=1

# Delay for element rendering after page navigation
ELEMENT_LOAD_WAIT=3

# ============================================================
# PORTAL CONFIGURATION
# ============================================================
# URL of the SIVIN VUT portal
PORTAL_URL=https://lemon.e-service.cz/

# Exact name of the SIVIN folder in the portal (case-sensitive)
SIVIN_FOLDER_NAME=SIVIN VUT

# Exact name of the Meteorological Data tab (case-sensitive)
METEO_TAB_NAME=Meteorologická data
```

#### Parameter Reference

| Parameter | Type | Required | Default | Purpose | Example |
|-----------|------|----------|---------|---------|---------|
| `SIVIN_USER` | string | Yes | - | SIVIN VUT portal login username | `195715@vut.cz` |
| `SIVIN_PASSWORD` | string | Yes | - | SIVIN VUT portal login password | `YourSecurePassword123` |
| `DOWNLOAD_FOLDER` | path | Yes | - | Absolute directory path for downloaded Excel files. Must exist. | `C:\Users\Username\Downloads` |
| `WAIT_TIMEOUT` | integer | No | 15 | Max seconds to wait for page elements (buttons, tabs, links). Increase if portal is slow. | `20` |
| `DOWNLOAD_WAIT_TIMEOUT` | integer | No | 30 | Max seconds to wait for file download to complete. Increase for slow connections. | `45` |
| `SCROLL_WAIT` | float | No | 1 | Pause time (seconds) after scrolling page. Prevents timing conflicts. | `1.5` |
| `ELEMENT_LOAD_WAIT` | integer | No | 3 | Pause time (seconds) for elements to render after page navigation. | `5` |
| `PORTAL_URL` | URL | No | `https://lemon.e-service.cz/` | Base URL of SIVIN VUT portal. Change only if portal URL changes. | - |
| `SIVIN_FOLDER_NAME` | string | No | `SIVIN VUT` | Exact name of main folder in portal (portal-specific, match case exactly). | `SIVIN VUT` |
| `METEO_TAB_NAME` | string | No | `Meteorologická data` | Exact name of meteorological data tab (portal-specific, match case exactly). | `Meteorologická data` |

#### Common Configuration Scenarios

**Slow Network / Slow Portal**:
```env
WAIT_TIMEOUT=25
DOWNLOAD_WAIT_TIMEOUT=60
SCROLL_WAIT=2
ELEMENT_LOAD_WAIT=5
```

**Fast Network / Responsive System**:
```env
WAIT_TIMEOUT=10
DOWNLOAD_WAIT_TIMEOUT=20
SCROLL_WAIT=0.5
ELEMENT_LOAD_WAIT=1
```

**Custom Download Location**:
```env
# Windows user folder
DOWNLOAD_FOLDER=C:\Users\YourUsername\Documents\MeteoData

# Network path
DOWNLOAD_FOLDER=\\server\shared\meteorological_data

# Different drive
DOWNLOAD_FOLDER=D:\MeteoData\downloads
```

#### Validation Checklist

Before running `chrome_driver.py`, verify:

- ✓ File is named exactly `chrome_driver.env` (not `.env.txt`)
- ✓ Located in project root directory (same folder as `chrome_driver.py`)
- ✓ `SIVIN_USER` and `SIVIN_PASSWORD` are valid (can login to portal manually)
- ✓ `DOWNLOAD_FOLDER` exists and you have write permissions
- ✓ File has no BOM (Byte Order Mark) - save as UTF-8 without BOM in text editor
- ✓ No trailing spaces after values

#### Troubleshooting

**Error**: `Environment file not found: chrome_driver.env`
- **Cause**: File not in project root or misspelled
- **Solution**: Ensure file is named `chrome_driver.env` in `C:\SIVIN_Mateostations\`

**Error**: `Missing SIVIN_USER or SIVIN_PASSWORD in .env file`
- **Cause**: Credentials not set or empty
- **Solution**: Add valid credentials between the quotes: `SIVIN_USER=username`

**Error**: `Download folder does not exist`
- **Cause**: Path in `DOWNLOAD_FOLDER` doesn't exist
- **Solution**: Create folder first: `mkdir C:\path\to\folder` or change path in .env

**Error**: `Download folder is not writable`
- **Cause**: Insufficient permissions to the folder
- **Solution**: Check folder permissions, run VS Code as Administrator, or use different folder

**Warning**: `Download timeout for sensor`
- **Cause**: Network slow, portal slow, or timeout too short
- **Solution**: Increase `WAIT_TIMEOUT` and `DOWNLOAD_WAIT_TIMEOUT` values

---

## Usage

### Data Collection

**Purpose**: Automatically download meteorological data from the SIVIN VUT web portal

**File**: `chrome_driver.py`

**Prerequisites**:
- `chrome_driver.env` file configured (see [Configure Chrome Driver Environment](#step-6-configure-chrome-driver-environment))
- Valid SIVIN VUT portal credentials
- Chrome browser installed and updated

**How it works**:
1. Loads configuration from `chrome_driver.env` file
2. Authenticates with SIVIN VUT portal (lemon.e-service.cz)
3. Navigates to SIVIN folder and retrieves device list
4. For each sensor:
   - Clicks to sensor details
   - Navigates to meteorological data tab
   - Locates and clicks the Excel export button in "Historie meteorologických dat" section
   - Waits for file download to complete
   - Validates downloaded file size
5. Closes browser and reports results

**To Run**:

```bash
python chrome_driver.py
```

**Output**:
- Downloads timestamped Excel files to `DOWNLOAD_FOLDER` specified in `.env`
- Logs progress and any errors to console
- Returns exit code 0 if ≥1 file downloaded, 1 if no files downloaded

**Log Output Example**:
```
======================================================================
SIVIN VUT DATA DOWNLOADER
======================================================================
✓ Configuration loaded from: c:\SIVIN_Mateostations\chrome_driver.env
  Credentials: ✓ Loaded
  Download folder: C:\SIVIN_Mateostations\data
  Wait timeout: 15 seconds
  Download timeout: 30 seconds
  Portal: https://lemon.e-service.cz/
✓ Chrome WebDriver initialized
Logging in as: 195715@vut.cz
✓ Login successful - dashboard loaded
✓ Found 4 devices: ['8615620 77678271', '8615620 77680921', '8615620 77799986', '8615620 77800065']

Processing sensor: 8615620 77678271
  ✓ Clicked on sensor
  ✓ Switched to Meteorologická data
  ✓ Found Excel button in historia section
  ✓ Excel export postback initiated
  ✓ File downloaded: MeteoData_8615620 77678271.xlsx
```

**Configuration Requirements** (see `.env` template above):
- `SIVIN_USER`: Portal login username
- `SIVIN_PASSWORD`: Portal login password
- `DOWNLOAD_FOLDER`: Folder where files are saved (must exist and be writable)
- `WAIT_TIMEOUT`: Timeout for page elements (default 15s, increase if network is slow)
- `DOWNLOAD_WAIT_TIMEOUT`: Timeout for downloads (default 30s)
- `ELEMENT_LOAD_WAIT`: Delay for page rendering (default 3s)
- `SCROLL_WAIT`: Delay after scrolling (default 1s)

**Common Issues & Solutions**:

| Issue | Cause | Solution |
|-------|-------|----------|
| `Environment file not found` | `chrome_driver.env` missing | Create file with template above |
| `Missing SIVIN_USER or SIVIN_PASSWORD` | Empty credentials | Add valid username/password |
| `Login timeout` or `Login element not found` | Invalid credentials or slow portal | Verify credentials manually, increase `WAIT_TIMEOUT` |
| `Download timeout for all sensors` | Button click not triggering download | This is expected if you're rerunning on same data; use empty folder first time |
| `No visible Excel button found` | Portal structure changed | Check portal UI, compare with HTML structure, update XPath if needed |
| `TimeoutException: UpdateProgress` | Portal updates taking too long | Increase `ELEMENT_LOAD_WAIT` and `WAIT_TIMEOUT` values |

**Advanced Troubleshooting**:

- For detailed logging, check console output for `✓` (success) and `✗` (failure) indicators
- The script logs every 5 download status checks with elapsed time and file count
- If browser window gets stuck, wait for timeout (30 seconds default) or increase timeouts in `.env`
- Check that Chrome is updated: `chrome://version/` should show recent version

**Security Notes**:
- Never share `chrome_driver.env` file containing credentials
- Each team member should create their own copy with their credentials
- Credentials are loaded from environment variables, not hardcoded in script
- Portal URL can be modified if portal endpoint changes

---

### Data Analysis

**Purpose**: Calculate viticulture-specific metrics from meteorological data

**File**: `vineyard_analyst.py`

**Main Class**: `VineyardAnalyst`

**How it works**:
1. Loads configuration from YAML file
2. Reads Excel data files specified in config
3. Filters data by date range (if specified)
4. Calculates various metrics
5. Exports results to JSON

**To Run**:

```bash
python vineyard_analyst.py
```

Or programmatically:

```python
from vineyard_analyst import VineyardAnalyst

# Initialize with configuration
analyst = VineyardAnalyst('vineyard_analyst.yaml')

# Run the complete pipeline
analyst.run_pipeline()

# Or run specific calculations
analyst.load_data()
analyst.calculate_gdd(base_temp=10)
analyst.calculate_frost_risk(threshold=0)
analyst.calculate_huglin_index(lat_coeff=1.05)
analyst.calculate_dew_point()
analyst.calculate_tropical_extremes()
analyst.save_results()
```

**Key Calculations**:

1. **Growing Degree Days (GDD)**
   - Formula: Sum of ((Daily Max + Daily Min) / 2 - Base Temp)
   - Only positive contributions counted
   - Default base temperature: 10°C (standard for grapevines)
   - Used to predict phenological development stages

2. **Frost Risk**
   - Counts occurrences where temperature ≤ threshold
   - Default threshold: 0°C
   - Important for predicting frost damage risk

3. **Huglin Index (Heliothermic Index)**
   - Formula: Sum of (((Tavg - 10) + (Tmax - 10)) / 2) × K) for April-September
   - K (latitude coefficient): 1.05 for Czech Republic (45-50°N)
   - Used to classify wine growing regions by temperature suitability
   - Higher values = warmer regions suitable for late-ripening varieties

4. **Dew Point**
   - Magnus formula: α = (a×T)/(b+T) + ln(RH)
   - Dew Point = (b×α)/(a-α)
   - Constants: a=17.27, b=237.7
   - Indicates humidity level and potential condensation

5. **Tropical Extremes**
   - Tropical Days: max temperature ≥ 30°C
   - Tropical Nights: min temperature ≥ 20°C
   - Indicates heat stress periods

**Output**:
JSON file in `vystupy/analysis/` with structure:
```json
{
  "Analysis date from": "2026-01-01 00:00:00",
  "Analysis date to": "2026-01-05 23:59:59",
  "sensor_id": {
    "gdd": 45.3,
    "frost_events_count": 2,
    "huglin_index": 1250.5,
    "avg_dew_point": 3.45,
    "tropical_days_count": 0,
    "tropical_nights_count": 0
  }
}
```

---

### Data Visualization

**Purpose**: Generate publication-quality plots of meteorological variables

#### Single-Variable Plotting

**File**: `one_variable_plot.py`

**Use case**: Plot temperature, humidity, or other single metrics over time

```bash
python one_variable_plot.py
```

**Configuration** (`config/one_variable_plot.yaml`):
```yaml
file_path: 'data.xlsx'
date_from: '2026-01-10 00:00:00'
date_to: '2026-01-14 23:59:59'
language: cz  # or 'de'
sensor: ["0065"]

axes:
  y_axis:
    name: 'Vlhkost'                    # Column name in Excel
    label_cz: 'Vlhkost [%]'            # Czech label
    label_de: 'Feuchtigkeit [%]'       # German label
    marker: 's'                        # Marker style
    line_width: 3
    marker_size: 2
  x_axis:
    name: 'Datum a čas'                # Time column name

figure:
  fig_size: [12, 8]
  font_size: 16
  color_palette: 'Set2'               # Seaborn palette
  
save:
  on_off: true
  path: "vystupy/grafy"
  format: ['eps', 'png', 'pdf']
  dpi: 600
```

#### Dual-Variable Plotting (Two-Axis)

**File**: `two_variable_plot.py`

**Use case**: Compare two related metrics with different scales (e.g., temperature on left axis, humidity on right)

```bash
python two_variable_plot.py
```

**Key difference**: Defines both `left_y` and `right_y` axes

```yaml
axes:
  left_y:
    name: 'Teplota'
    label_cz: 'Teplota [°C]'
  right_y:
    name: 'Vlhkost'
    label_cz: 'Vlhkost [%]'
```

**Output**:
- Files saved to: `vystupy/grafy/{format}/` (format = esp/png/pdf)
- Filename pattern: `{language}_sensor_report_{sensor_id}_{timestamp}.{ext}`
- Transparent background for easy integration into documents

---

### Sampling Frequency Analysis

**File**: `sampl_freq_basic.py`

**Purpose**: Calculate time intervals between measurements to verify sampling consistency

**What it does**:
- Reads timestamp data
- Computes time differences between consecutive measurements
- Reports intervals in seconds, minutes, and hours

**Output Format**:
```
Rozdíl mezi timestamp 1 a 0: 1825.00 s, 30.42 min, 0.51 h
Rozdíl mezi timestamp 2 a 1: 1825.00 s, 30.42 min, 0.51 h
```

---

## Component Documentation

### Chrome Driver

**Location**: `chrome_driver.py`

**Purpose**: Automated web scraper for downloading meteorological data from SIVIN VUT portal

**Architecture**:
- Configuration-driven: All settings loaded from `chrome_driver.env`
- Modular design: Separate functions for login, navigation, and download
- Robust error handling: Specific exception types for debugging
- Smart file detection: Tracks new files by comparing filesystem state before/after download

**Key Functions**:

| Function | Parameters | Returns | Purpose |
|----------|------------|---------|---------|
| `load_config()` | None | dict | Load and validate all configuration from .env file |
| `initialize_driver()` | None | WebDriver | Initialize Chrome WebDriver with download preferences |
| `login_to_portal()` | driver, config | WebElement | Authenticate with portal and return SIVIN folder element |
| `open_sivin_folder()` | driver, folder, config | list | Extract device names from folder |
| `download_sensor_data()` | driver, wait, sensor, config | str | Download Excel file for single sensor |
| `main()` | None | int | Orchestrate entire download pipeline |
| `get_latest_file()` | folder_path | str | Find newest file in directory (helper function) |

**Configuration Loading** (Critical):
```python
# Automatically loads from chrome_driver.env file
config = load_config()

# Returns dictionary with all 10 configuration parameters:
# - username, password
# - download_folder
# - wait_timeout, download_wait_timeout, scroll_wait, element_load_wait
# - portal_url, sivin_folder_name, meteo_tab_name
```

**File Download Logic**:
1. **Before download**: Records all existing files in download folder
2. **After export button click**: Waits for NEW files to appear (not in original list)
3. **Completion detection**: Ignores incomplete `.crdownload` files
4. **Validation**: Checks file size (warns if < 10 KB, likely incomplete)

This approach ensures:
- ✓ Works with empty folders (all downloads are "new")
- ✓ Works with pre-existing files (finds only new downloads)
- ✓ No false positives from old files
- ✓ Handles multiple sensors independently

**Error Handling**:
- `RuntimeError`: Missing/invalid configuration
- `TimeoutError`: Page elements not found within timeout
- `ValueError`: Unexpected element structure
- `FileExistsError`, `OSError`: File system issues

**Important Notes**:

1. **DotVVM Framework**: Portal uses DotVVM which requires proper event handling
   - Uses direct `.click()` method (not JavaScript) to trigger postback
   - Specific button selection using "Historie meteorologických dat" section header

2. **Security**: Credentials in `.env` file never logged or exposed

3. **Browser Management**:
   - Opens Chrome browser for duration of script
   - Automatically closes browser on completion (finally block)
   - Sets download folder to temp directory for safety

4. **Logging**:
   - Comprehensive info, debug, and error logging
   - Progress indicators (✓ success, ✗ error, ⚠ warning)
   - File count tracking during download wait

### VineyardAnalyst Class

**Location**: `vineyard_analyst.py`

**Constructor**:
```python
VineyardAnalyst(config_path: str)
```

**Properties**:
- `config`: Dictionary loaded from YAML configuration file
- `data`: Dictionary mapping sensor names to pandas DataFrames
- `sensors`: List of sensor IDs to process
- `results`: Dictionary storing calculation results

**Key Methods**:

| Method | Parameters | Returns | Purpose |
|--------|-----------|---------|---------|
| `load_data()` | None | None | Load Excel files for each sensor within date range |
| `calculate_gdd()` | base_temp=10.0 | None | Calculate Growing Degree Days |
| `calculate_frost_risk()` | threshold=0 | None | Count frost events |
| `calculate_huglin_index()` | lat_coeff=1.05 | None | Calculate heliothermic index |
| `calculate_dew_point()` | None | None | Calculate dew point using Magnus formula |
| `calculate_tropical_extremes()` | None | None | Count tropical days/nights |
| `save_results()` | None | None | Export results to JSON |
| `run_pipeline()` | None | None | Execute all calculations in sequence |

### Plotting Functions

**Location**: `one_variable_plot.py`, `two_variable_plot.py`

**Main Function**:
```python
plot_sensor_data(df: pd.DataFrame, config: dict, sensor: str = None) -> None
```

**Process**:
1. Convert datetime column to pandas datetime format
2. Filter DataFrame by date range
3. Sort by datetime to ensure continuity
4. Create matplotlib figure with seaborn styling
5. Plot line(s) with configured markers and colors
6. Format axes with bilingual labels
7. Save to multiple formats if configured

---

## Configuration Guide

### vineyard_analyst.yaml

```yaml
# Path to Excel data file
file_path: 'data.xlsx'

# Date filtering (optional - leave empty to include all data)
date_from: '2026-01-01 00:00:00'
date_to: '2026-01-05 23:59:59'

# Output language: 'cz' or 'de'
language: cz

# List of sensor/sheet names to process
sensor:
  - "9986"
  - "8271"
  - "0065"
  - "0921"

# GDD parameter
gdd_base: 10              # Base temperature in °C

# Optional
frost_threshold: 0        # Frost temperature threshold
huglin_lat_coeff: 1.05   # Latitude coefficient for Huglin
```

### one_variable_plot.yaml / two_variable_plot.yaml

**Critical Settings**:

```yaml
file_path: 'data.xlsx'                    # Must match actual file name
language: cz                              # Changes which label_* is used
sensor: ["0065"]                          # Which sheet/sensor to plot

axes:
  y_axis:
    name: 'Vlhkost'                      # Exact column name from Excel
    label_cz: 'Vlhkost [%]'              # Czech label
    label_de: 'Feuchtigkeit [%]'         # German label
    marker: 's'                          # 'o', 's', '^', 'D', etc.
    line_width: 3                        # Line thickness
    marker_size: 2                       # Point size
    label_weight: 'bold'                 # Font weight
    label_color: 'k'                     # Color ('k'=black, 'r'=red, etc.)

figure:
  fig_size: [12, 8]                      # Width, height in inches
  font_size: 16                          # Label font size
  tick_size: 16                          # Axis tick size
  x_tick_rotation: 45                    # X-axis label rotation in degrees
  title_size: 20                         # Title font size
  legend_loc: 'upper center'             # Legend position
  color_palette: 'Set2'                  # Seaborn palette name

save:
  on_off: true                           # Enable/disable saving
  path: "vystupy/grafy"                  # Output directory
  format: ['eps', 'png', 'pdf']          # Formats to save
  dpi: 600                               # Resolution (dots per inch)
  transparent: true                      # Transparent background
```

---

## Output Structure

### Analysis Results

**Location**: `vystupy/analysis/Analysis_*.json`

**Format**: JSON with timestamp-based filenames

```json
{
  "Analysis date from": "2026-01-01 00:00:00",
  "Analysis date to": "2026-01-05 23:59:59",
  "9986": {
    "gdd": 45.3,
    "frost_events_count": 2,
    "huglin_index": 1250.5,
    "avg_dew_point": 3.45,
    "tropical_days_count": 0,
    "tropical_nights_count": 0
  },
  "8271": { ... }
}
```

### Graph Exports

**Locations**:
- PNG (web-friendly): `vystupy/grafy/png/`
- PDF (publication): `vystupy/grafy/pdf/`
- EPS (print-ready): `vystupy/grafy/eps/`

**Naming Convention**:
```
{language}_sensor_report_{sensor_id}_{timestamp}.{format}
cz_sensor_report_0065_20260301_123456.png
```

---

## Future Development

### Recommended Enhancements

1. **Additional Agroclimatic Indices**
   - Winkler Index (similar to Huglin)
   - Helmann Index
   - Cool Night Index
   - Growing Season Length

2. **Interactive Dashboard**
   - Web-based visualization using Plotly/Dash
   - Real-time data updates
   - Multi-sensor comparison views

3. **Database Integration**
   - Replace Excel files with PostgreSQL/SQLite
   - Enable time-series queries
   - Support larger datasets

4. **Advanced Analytics**
   - Anomaly detection for sensor malfunctions
   - Predictive modeling (frost prediction)
   - Correlation analysis between sensors

5. **API Development**
   - REST API for programmatic access
   - Data export formats (CSV, NetCDF)
   - Integration with external agro-advisory systems

6. **Automation**
   - Scheduled daily/weekly runs
   - Email notifications for frost risk alerts
   - Automated report generation

7. **Cross-Platform Support**
   - Linux/macOS compatibility
   - Docker containerization
   - Cloud deployment options

8. **Data Quality**
   - Validation rules for outlier detection
   - Missing data interpolation
   - Sensor calibration tracking

### Code Quality Improvements

- Add comprehensive unit tests (`pytest`)
- Add type hints throughout codebase
- Create logging configuration instead of print statements
- Implement error handling for missing/corrupted data
- Add data validation schemas (Pydantic)
- Create helper classes for common operations

---

## Troubleshooting

### Common Issues

#### Issue: `FileNotFoundError` for config files

**Cause**: Script doesn't find YAML configuration files

**Solution**:
```bash
# Ensure you're running from project root
cd C:\SIVIN_Mateostations
python vineyard_analyst.py

# Or provide absolute path
python vineyard_analyst.py
```

#### Issue: `KeyError` in VineyardAnalyst

**Cause**: Excel file doesn't have expected column names (e.g., 'Datum a čas', 'Teplota')

**Solution**:
1. Open data Excel file and verify column names exactly
2. Update config YAML with correct names
3. Check for hidden rows/columns

#### Issue: Chrome driver fails to download

**Cause**: Credentials expired or portal structure changed

**Solution**:
1. Update credentials in `chrome_driver.env`
2. Test login manually to verify access
3. Check if CSS selectors in script still match portal HTML
4. Update selectors based on current portal structure

#### Issue: Plot axes labels are wrong language

**Cause**: `language` parameter doesn't match labels in YAML

**Solution**:
```yaml
# This must match either label_cz or label_de keys
language: cz  # Use 'cz' or 'de' only
```

#### Issue: Plots saved with low quality

**Cause**: DPI set too low for publication

**Solution**:
```yaml
save:
  dpi: 600      # Use 300+ for publication, 72-150 for web
  format: ['pdf']  # Use PDF/EPS for prints, PNG for web
```

#### Issue: Memory error with large datasets

**Cause**: Loading entire year of high-frequency data

**Solution**:
1. Use date filtering: `date_from`, `date_to`
2. Reduce plotting resolution temporarily
3. Process data in monthly chunks
4. Increase system RAM or use SSD for paging

#### Issue: "UpdateProgress" timeout

**Cause**: Web portal is slow or page didn't load properly

**Solution**:
1. Increase wait timeout in chrome_driver.py:
```python
wait = WebDriverWait(driver, 30)  # Increase from 15 to 30 seconds
```
2. Check your internet connection
3. Try running during off-peak hours

#### Issue: No files appear in download folder

**Cause**: Download folder path is incorrect or doesn't exist

**Solution**:
```bash
# In chrome_driver.env, use absolute path
DOWNLOAD_FOLDER=C:\Users\YourUsername\Downloads\SIVIN

# Verify folder exists
mkdir C:\Users\YourUsername\Downloads\SIVIN
```

### Getting Help

1. **Check existing data files**: Look in `data/` folder to understand structure
2. **Review config examples**: Both YAML files show all available parameters
3. **Read code comments**: Czech comments provide design decisions
4. **Test incrementally**: Run each script independently before chaining

---

## Best Practices

1. **Always backup original data** before processing
2. **Version your configurations** (commit YAML files to git)
3. **Document any custom indices** you add to VineyardAnalyst
4. **Use meaningful sensor IDs** in your data files
5. **Run analysis on complete date ranges** to avoid partial results
6. **Test plotting configs** with single sensor before batch processing
7. **Keep `.env` files secure** and never commit to version control
8. **Archive results regularly** (JSON files are small, can compress)

---

## License & Attribution

Created by Richard Redina, Brno University of Technology  
For academic and research use in viticulture and agricultural monitoring

---

**Last Updated**: March 21, 2026  
**Current Version**: 1.0  
**Status**: Active Development
