# -*- coding: utf-8 -*-

"""
Vineyard Animation Generator - Meteorological Data Visualization

This module generates animated maps visualizing meteorological parameters across
distributed sensor networks over time. Each frame of the animation displays sensor
values as colored dots on an OpenStreetMap background.

PROJECT STRUCTURE:
    Input: ./data/ folder with CSV files from chrome_driver.py
    Config: ./map_config.yaml
    GPS: ./pozice čidel.gpx (sensor locations)
    Output: ./vystupy/grafy/vinice_animace_[TIMESTAMP].mp4

USAGE:
    python generate_animation.py

CONFIGURABLE PARAMETERS (in map_config.yaml):
    - Date range (start_date, end_date)
    - Target parameter (target_value: "Teplota" or "Vlhkost")
    - Resampling period (resample_period: "1H", "30min", etc.)
    - Video settings (fps, dpi, colormap)

Author: Richard Redina
Email: 195715@vut.cz
Affiliation: International Clinical Research Center, Brno; VUT Brno
GitHub: RicRedi

Created: 29. 03. 2026
"""

# import os
import sys
import re
import logging
from datetime import datetime
from typing import Tuple, Dict, List, Optional
from pathlib import Path
import yaml

import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from contextily import add_basemap
import contextily as cx

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_project_root() -> Path:
    """
    Determine the project root directory.
    
    Returns:
        Path: Absolute path to project root (where generate_animation.py is located)
    """
    return Path(__file__).parent.absolute()


def extract_sensor_id_from_filename(filename: str) -> Optional[str]:
    """
    Extract sensor ID from CSV filename.
    
    Expected format: MeteoData_[ID1] [ID2] (LOCATION)_[TIMESTAMP].csv
    Extracts: [ID2] (LOCATION)
    
    Example:
        Input: "MeteoData_8615620 77678271  (VUT)_20260301_223857.csv"
        Output: "77678271 (VUT)"
    
    Args:
        filename (str): CSV filename
        
    Returns:
        Optional[str]: Extracted sensor ID or None if pattern doesn't match
    """
    # Match pattern: one or more digits, space, optional space, opening paren
    match = re.search(r'\s(\d+)\s+\(([^)]+)\)', filename)
    if match:
        sensor_id = f"{match.group(1)} ({match.group(2)})"
        return sensor_id
    return None


def load_and_validate_config(config_path: Path) -> Dict:
    """
    Load and validate configuration from YAML file.
    
    Args:
        config_path (Path): Path to map_config.yaml
        
    Returns:
        Dict: Validated configuration dictionary
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If YAML is malformed
        ValueError: If required config keys are missing
    """
    logger.info("Loading configuration from %s", config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Validate required sections
    required_sections = ['paths', 'analysis', 'video']
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Configuration missing required section: '{section}'")

    # Validate required keys
    required_paths = ['data_folder', 'gpx_file', 'output_video']
    for key in required_paths:
        if key not in config['paths']:
            raise ValueError(f"Configuration missing 'paths.{key}'")

    required_analysis = ['start_date', 'end_date', 'target_value', 'resample_period']
    for key in required_analysis:
        if key not in config['analysis']:
            raise ValueError(f"Configuration missing 'analysis.{key}'")

    required_video = ['fps', 'dpi', 'colormap']
    for key in required_video:
        if key not in config['video']:
            raise ValueError(f"Configuration missing 'video.{key}'")

    # 'format' is optional, default to 'gif' (no FFmpeg required)
    if 'format' not in config['video']:
        config['video']['format'] = 'gif'

    # Validate format choice
    valid_formats = ['mp4', 'gif', 'png_frames']
    if config['video']['format'] not in valid_formats:
        raise ValueError(
            f"Invalid video format '{
                config['video']['format']
                }'. Choose from: {', '.join(valid_formats)}")

    logger.info("Configuration validated successfully")
    return config


def validate_prerequisites(config: Dict, project_root: Path) -> Tuple[Path, Path, Path]:
    """
    Validate that all required files and folders exist.
    
    Args:
        config (Dict): Configuration dictionary
        project_root (Path): Project root directory
        
    Returns:
        Tuple[Path, Path, Path]: Validated paths (data_folder, gpx_file, output_folder)
        
    Raises:
        FileNotFoundError: If required files/folders don't exist
        ValueError: If folder is empty or invalid
    """
    logger.info("Validating prerequisites...")

    # Resolve data folder path
    data_folder = Path(config['paths']['data_folder'])
    if not data_folder.is_absolute():
        data_folder = project_root / data_folder

    if not data_folder.exists():
        raise FileNotFoundError(f"Data folder not found: {data_folder}")

    # Check for CSV files
    csv_files = list(data_folder.glob('*.csv'))
    if not csv_files:
        raise ValueError(f"No CSV files found in {data_folder}")
    logger.info("Found %d CSV files in data folder", len(csv_files))

    # Resolve GPX file path
    gpx_file = Path(config['paths']['gpx_file'])
    if not gpx_file.is_absolute():
        gpx_file = project_root / gpx_file

    if not gpx_file.exists():
        raise FileNotFoundError(f"GPX file not found: {gpx_file}")
    logger.info("GPX file found: {gpx_file.name}")

    # Create output folder if needed
    output_folder = project_root / 'vystupy' / 'grafy' / 'animace'
    output_folder.mkdir(parents=True, exist_ok=True)
    logger.info("Output folder ready: {output_folder}")

    return data_folder, gpx_file, output_folder


def load_sensor_locations(gpx_file: Path) -> gpd.GeoDataFrame:
    """
    Load sensor locations from GPX file.
    
    Args:
        gpx_file (Path): Path to GPX file
        
    Returns:
        gpd.GeoDataFrame: GeoDataFrame with sensor names and geometry in Web Mercator
        
    Raises:
        ValueError: If GPX file doesn't contain waypoints
    """
    logger.info("Loading sensor locations from %s", gpx_file.name)

    try:
        gdf_sensors = gpd.read_file(gpx_file, layer='waypoints')
    except Exception as e:
        raise ValueError(f"Failed to read GPX file: {e}")

    if len(gdf_sensors) == 0:
        raise ValueError("No waypoints found in GPX file")

    # Keep only name and geometry
    gdf_sensors = gdf_sensors[['name', 'geometry']].copy()

    # Convert to Web Mercator for map display
    gdf_sensors = gdf_sensors.to_crs(epsg=3857)

    logger.info("Loaded %d sensor locations:", len(gdf_sensors))
    for _, row in gdf_sensors.iterrows():
        logger.info("  - %s", row['name'])

    return gdf_sensors


def find_matching_sensors(csv_file_path: Path, sensor_names: List[str]) -> Optional[str]:
    """
    Find GPX sensor name that matches a CSV filename.
    
    Args:
        csv_file_path (Path): Path to CSV file
        sensor_names (List[str]): List of sensor names from GPX
        
    Returns:
        Optional[str]: Matching sensor name from GPX or None
    """
    extracted_id = extract_sensor_id_from_filename(csv_file_path.name)
    if extracted_id and extracted_id in sensor_names:
        return extracted_id
    return None


def load_sensor_data(csv_file: Path, target_value: str) -> Optional[pd.DataFrame]:
    """
    Load and validate CSV data from a single sensor file.
    
    Expects CSV with:
    - Semicolon (;) as delimiter
    - First row is header: "Meteo Data;" (skipped)
    - Second row contains column names in Czech: "Datum a čas", "Teplota (°C)", "Vlhkost (%)", etc.
    - Decimal separator is comma
    
    Args:
        csv_file (Path): Path to CSV file
        target_value (str): Name of the column to visualize (e.g., "Teplota")
        
    Returns:
        Optional[pd.DataFrame]: Loaded and validated dataframe or None if loading fails
    """
    try:
        logger.info("Loading data from %s", csv_file.name)

        # Read CSV with semicolon delimiter, skip first row (Meteo Data header)
        # Replace comma decimal separator with period for proper float parsing
        df = pd.read_csv(
            csv_file,
            sep=';',
            skiprows=1,
            encoding='utf-8',
            decimal=','  # Czech format uses comma as decimal separator
        )

        # Validate and find timestamp column (contains 'čas' or 'das' - encoding variants)
        timestamp_col = None
        for col in df.columns:
            if 'čas' in col.lower() or 'das' in col.lower() or 'datum' in col.lower():
                timestamp_col = col
                break

        if timestamp_col is None:
            logger.warning("  ⚠ Skipping %s: Missing timestamp column", csv_file.name)
            return None

        # Validate and find target value column (may have units in parentheses like "Teplota (°C)")
        target_col = None
        for col in df.columns:
            if col.startswith(target_value) or target_value in col:
                target_col = col
                break

        if target_col is None:
            logger.warning("  ⚠ Skipping %s: Missing '%s' column", csv_file.name, target_value)
            return None

        # Create clean dataframe with renamed columns
        df_clean = df[[timestamp_col, target_col]].copy()
        df_clean.columns = ['Čas', target_value]

        # Convert timestamp
        df_clean['Čas'] = pd.to_datetime(
            df_clean['Čas'], format='%Y-%m-%d %H:%M:%S', errors='coerce'
            )

        if df_clean['Čas'].isna().all():
            logger.warning("  ⚠ Skipping %s: Invalid timestamp format", csv_file.name)
            return None

        logger.info("  ✓ Loaded %d rows", len(df_clean))
        return df_clean

    except FileExistsError as e:
        logger.warning("  ⚠ Error reading %s: %s", csv_file.name, e)
        return None


def load_and_process_data(
    data_folder: Path,
    gdf_sensors: gpd.GeoDataFrame,
    target_value: str,
    start_date: str,
    end_date: str,
    resample_period: str,
    ) -> pd.DataFrame:
    """
    Load all CSV files, filter by date range, and resample data.
    
    Args:
        data_folder (Path): Folder containing CSV files
        gdf_sensors (gpd.GeoDataFrame): GeoDataFrame with sensor locations
        target_value (str): Parameter to visualize (e.g., "Teplota")
        start_date (str): Start date in format 'YYYY-MM-DD HH:MM:SS'
        end_date (str): End date in format 'YYYY-MM-DD HH:MM:SS'
        resample_period (str): Resampling period (e.g., '1H', '30min')
        
    Returns:
        pd.DataFrame: Merged and processed data from all sensors
        
    Raises:
        ValueError: If no valid data found
    """
    logger.info("Loading and processing sensor data...")

    sensor_names = gdf_sensors['name'].tolist()
    all_data = []
    loaded_sensors = []

    # Load each CSV file
    for csv_file in sorted(data_folder.glob('*.csv')):
        matching_sensor = find_matching_sensors(csv_file, sensor_names)

        if not matching_sensor:
            logger.debug("No matching sensor for %s", csv_file.name)
            continue

        df = load_sensor_data(csv_file, target_value)
        if df is None:
            continue

        # Filter date range
        try:
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
        except ValueError as e:
            raise ValueError(f"Invalid date format: {e}")

        df_filtered = df[(df['Čas'] >= start_dt) & (df['Čas'] <= end_dt)].copy()

        if len(df_filtered) == 0:
            logger.warning("  ⚠ No data in date range for %s", matching_sensor)
            continue

        # Resample to specified period (e.g., hourly averages)
        try:
            df_resampled = (
                df_filtered
                .set_index('Čas')
                .resample(resample_period)
                .agg({target_value: 'mean'})
                .reset_index()
            )
        except ValueError as e:
            logger.warning("  ⚠ Resampling failed for %s: %s", matching_sensor, e)
            continue

        df_resampled['sensor_name'] = matching_sensor
        all_data.append(df_resampled)
        loaded_sensors.append(matching_sensor)

    if not all_data:
        raise ValueError("No valid data found for specified parameters")

    df_full = pd.concat(all_data, ignore_index=True)
    logger.info("  ✓ Processed data from %d sensors: %s",
                len(loaded_sensors),
                ', '.join(loaded_sensors)
                )
    logger.info(
        "  ✓ Total data points: %d across %d timestamps",
        len(df_full),
        len(df_full['Čas'].unique())
        )

    return df_full


def generate_animation(
    gdf_sensors: gpd.GeoDataFrame,
    df_full: pd.DataFrame,
    config: Dict,
    output_path: Path
    ) -> None:
    """
    Generate animated map and save in specified format.
    
    Supported formats:
    - 'gif': Animated GIF (no external dependencies required)
    - 'mp4': MP4 video (requires FFmpeg installation)
    - 'png_frames': Individual PNG image files (one per frame)
    
    Args:
        gdf_sensors (gpd.GeoDataFrame): Sensor locations with geometry
        df_full (pd.DataFrame): Processed sensor data with Čas and target_value columns
        config (Dict): Configuration dictionary with 'format' key in video section
        output_path (Path): Path where to save output (without extension)
        
    Raises:
        RuntimeError: If generation fails
    """
    logger.info("Preparing animation generation...")

    timestamps = sorted(df_full['Čas'].unique())
    target_value = config['analysis']['target_value']
    fps = config['video']['fps']
    colormap = config['video']['colormap']
    output_format = config['video'].get('format', 'gif')

    logger.info("Animation settings:")
    logger.info("  - Format: %s", output_format.upper())
    logger.info("  - Frames: %d", len(timestamps))
    logger.info("  - Parameter: %s", target_value)
    logger.info("  - FPS: %d", fps)
    logger.info("  - Colormap: %s", colormap)

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8), dpi=100)

    # Calculate color scale from all data
    vmin = df_full[target_value].min()
    vmax = df_full[target_value].max()
    logger.info("  - Value range: %f to %f", vmin, vmax)

    def update(frame: int):
        """
        Update function for animation - called for each frame.
        
        Args:
            frame (int): Frame number (index into timestamps)
        """
        ax.clear()
        current_time = timestamps[frame]

        # Get data for current timestamp
        data_snapshot = df_full[df_full['Čas'] == current_time]

        # Merge sensor locations with data
        merged = gdf_sensors.merge(
            data_snapshot,
            left_on='name',
            right_on='sensor_name',
            how='inner'
        )

        if len(merged) == 0:
            ax.text(0.5, 0.5, 'No data for this timestamp',
                   ha='center', va='center', transform=ax.transAxes)
            ax.set_axis_off()
            return (ax,)

        # Calculate bounds of sensor locations and add padding
        # This ensures the map fetches the correct area from OpenStreetMap
        minx, miny, maxx, maxy = merged.total_bounds
        # Get from config, default 0.15
        padding_factor = config['video'].get('padding_factor', 0.15)
        padding = max(maxx - minx, maxy - miny) * padding_factor

        # Set axis limits BEFORE adding basemap (this tells the basemap what area to fetch)
        ax.set_xlim(minx - padding, maxx + padding)
        ax.set_ylim(miny - padding, maxy + padding)

        # Try to add map background from OpenStreetMap (with error handling for network issues)
        try:
            add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik, zorder=1)
        except Exception as e:
            # If basemap fetch fails (network error, timeout, etc), just use simple background
            logger.warning("  ⚠ Could not fetch OpenStreetMap basemap: %s", str(e)[:100])
            ax.set_facecolor('#e6f2ff')  # Light blue background
            ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)  # Grid lines
            logger.info("  → Using simple background grid instead")

        # Plot sensors as colored points
        sc = ax.scatter(
            merged.geometry.x,
            merged.geometry.y,
            c=merged[target_value],
            s=300,
            cmap=colormap,
            vmin=vmin,
            vmax=vmax,
            edgecolors='black',
            linewidth=1.5,
            zorder=5,
            alpha=0.8
        )

        # Add title
        ax.set_title(
            f"Sensor Network | Time: {current_time}\nParameter: {target_value}",
            fontsize=12,
            fontweight='bold'
        )
        ax.set_axis_off()

        # Add colorbar on first frame
        if frame == 0:
            cbar = plt.colorbar(sc, ax=ax, orientation='vertical', pad=0.02)
            cbar.set_label(target_value, rotation=270, labelpad=20)

        return (ax,)

    # Create animation
    logger.info("Generating animation frames...")
    ani = animation.FuncAnimation(
        fig,
        update,
        frames=len(timestamps),
        interval=1000 / fps,
        blit=False,
        repeat=True
    )

    # Save in specified format
    logger.info("Saving to %s.%s...", output_path.stem, output_format)
    try:
        if output_format == 'gif':
            # GIF format - no external dependencies
            gif_path = output_path.parent / f"{output_path.stem}.gif"
            logger.info("Saving as GIF (this may take a moment)...")
            ani.save(str(gif_path), writer='pillow', fps=fps)
            logger.info("✓ GIF saved successfully: %s", gif_path)

        elif output_format == 'mp4':
            # MP4 format - requires FFmpeg
            mp4_path = output_path.parent / f"{output_path.stem}.mp4"
            logger.info("Saving as MP4 (requires FFmpeg)...")
            writer = animation.FFMpegWriter(fps=fps, bitrate=1800, codec='libx264')
            ani.save(str(mp4_path), writer=writer)
            logger.info("✓ MP4 saved successfully: %s", mp4_path)

        elif output_format == 'png_frames':
            # PNG frames - save individual images
            frames_dir = output_path.parent / f"{output_path.stem}_frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Saving individual PNG frames to %s/", frames_dir.name)

            for frame_num in range(len(timestamps)):
                frame_path = frames_dir / f"frame_{frame_num:04d}.png"
                ani.save(str(frame_path), writer='pillow')

            logger.info("✓ %d PNG frames saved to: %s", len(timestamps), frames_dir)

    except RuntimeError as e:
        logger.error("Failed to save animation: %s", e)
        raise RuntimeError(
            f"Failed to save animation: {e}. \
            Tip: For MP4, ensure FFmpeg is installed (ffmpeg -version)")
    finally:
        plt.close(fig)


def main() -> None:
    """
    Main entry point. Orchestrates the entire animation generation process.
    
    Flow:
    1. Load and validate configuration
    2. Validate prerequisite files/folders
    3. Load sensor locations from GPX
    4. Load and process CSV data
    5. Generate animation
    
    Raises:
        SystemExit: On any critical error
    """
    logger.info("=" * 70)
    logger.info("VINEYARD ANIMATION GENERATOR")
    logger.info("=" * 70)

    try:
        # Get project root
        project_root = get_project_root()
        logger.info("Project root: %s", project_root)

        # Load and validate config
        config_path = project_root / 'map_config.yaml'
        config = load_and_validate_config(config_path)

        # Validate prerequisites
        data_folder, gpx_file, output_folder = validate_prerequisites(config, project_root)

        # Load sensor locations
        gdf_sensors = load_sensor_locations(gpx_file)

        # Load and process data
        df_full = load_and_process_data(
            data_folder=data_folder,
            gdf_sensors=gdf_sensors,
            target_value=config['analysis']['target_value'],
            start_date=config['analysis']['start_date'],
            end_date=config['analysis']['end_date'],
            resample_period=config['analysis']['resample_period']
        )

        # Generate output filename with timestamp (format will be added by generate_animation)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"vinice_animace_{timestamp}"
        output_path = output_folder / output_filename

        # Generate animation (will add extension based on format)
        generate_animation(gdf_sensors, df_full, config, output_path)

        # Success summary
        logger.info("=" * 70)
        logger.info("✓ ANIMATION GENERATION COMPLETED SUCCESSFULLY")
        logger.info("  Output folder: %s", output_folder)
        logger.info("  Date Range: %s to %s",
                    config['analysis']['start_date'],
                    config['analysis']['end_date'])
        logger.info("  Parameter: %s", config['analysis']['target_value'])
        logger.info("  Format: %s", config['video'].get('format', 'gif').upper())
        logger.info(
            "  Sensors: %d total, %d with data",
            len(gdf_sensors),
            len(df_full['sensor_name'].unique())
        )
        logger.info("=" * 70)

    except FileNotFoundError as e:
        logger.error("✗ FILE NOT FOUND: %s", e)
        logger.error("  Please check that all required files exist")
        sys.exit(1)

    except ValueError as e:
        logger.error("✗ CONFIGURATION ERROR: %s", e)
        logger.error("  Please check map_config.yaml settings")
        sys.exit(1)

    except RuntimeError as e:
        logger.error("✗ RUNTIME ERROR: %s", e)
        sys.exit(1)

    except Exception as e:
        logger.error("✗ UNEXPECTED ERROR: %s", e, exc_info=True)
        sys.exit(1)


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    main()
