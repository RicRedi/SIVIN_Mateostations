# SIVIN_Mateostations

A comprehensive meteorological data analysis and visualization toolkit for analyzing multi-sensor weather station networks, with specialized support for viticulture-relevant metrics and automated data collection. This project is designed to help researchers and technicians monitor, process, and visualize meteorological data across distributed sensor networks.

**Author:** Richard Redina  
**Email:** 195715@vut.cz  
**Affiliation:** International Clinical Research Center, Brno; Brno University of Technology  
**GitHub:** RicRedi

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
├── chrome_driver.env             # Environment variables (credentials, paths) - KEEP SECURE
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

### Step 4: Configure Credentials

Create `chrome_driver.env` in the project root with:

```env
SIVIN_USER=your_username
SIVIN_PASSWORD=your_password
DOWNLOAD_FOLDER=C:\absolute\path\to\downloads
```

**Security Note**: Never commit `chrome_driver.env` to version control. Add it to `.gitignore` if not already done.

### Step 5: Create Output Directories

```bash
mkdir vystupy\analysis
mkdir vystupy\grafy\eps
mkdir vystupy\grafy\pdf
mkdir vystupy\grafy\png
```

---

## Usage

### Data Collection

**Purpose**: Automatically download meteorological data from the SIVIN VUT web portal

**File**: `chrome_driver.py`

**How it works**:
1. Authenticate with SIVIN VUT portal (lemon.e-service.cz)
2. Navigate to SIVIN folder structure
3. For each configured sensor, click to the meteorological data tab
4. Download Excel file automatically
5. Store file with timestamp

**To Run**:

```bash
python chrome_driver.py
```

**What happens**:
- Opens Chrome browser (runs in background after initial setup)
- Logs in with credentials from `.env`
- Iterates through all sensors in SIVIN VUT
- Downloads Excel files to configured `DOWNLOAD_FOLDER`
- Closes browser upon completion

**Configuration Requirements**:
- `chrome_driver.env` must exist with valid credentials
- `DOWNLOAD_FOLDER` must exist (script doesn't create it)

**Troubleshooting**:
- If login fails, check credentials in `chrome_driver.env`
- If browser hangs, verify Chrome is installed and up-to-date
- TimeoutException errors indicate slow network or portal slowness

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
