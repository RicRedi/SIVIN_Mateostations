# -*- coding: utf-8 -*-

"""
Created on 21. 02. 2026 at 12:26:40

Author: Richard Redina
Email: 195715@vut.cz
Affiliation:
         International Clinical Research Center, Brno
         Brno University of Technology, Brno
GitHub: RicRedi

(._.)
 <|>
_/|_

Description:
    Short description of the script.
"""
import json
import datetime
import yaml
import pandas as pd
import numpy as np


class VineyardAnalyst:
    """
    Vineyard data analyst class.
    """
    def __init__(
        self,
        config_path: str,
        ) -> None:
        # Načtení konfigurace (cesty, prahové hodnoty atd.)
        with open(
            config_path,
            'r',
            encoding='utf-8',
            ) as f:
            self.config = yaml.safe_load(
            f
            )

        self.data = {}  # Dict of data for each sensor unit from "date" to "date"
        self.sensors = self.config.get('sensor', [None])
        if self.sensors is None:
            print("No sensors has been selected!!")
        self.results = {
            "Analysis date from": self.config.get('date_from'),
            "Analysis date to": self.config.get('date_to'),
        }
    def load_data(
        self
        ) -> None:
        """
        Loads data for each sensor defined in the configuration file.
        """
        for sensor_name in self.config.get('sensor', [None]):
            if sensor_name:
                df = pd.read_excel(
                    self.config['file_path'],
                    decimal=',',
                    sheet_name=sensor_name,
                    )
                if self.config.get('date_from'):
                    df = df[df['Datum a čas'] >= pd.to_datetime(self.config['date_from'])]
                if self.config.get('date_to'):
                    df = df[df['Datum a čas'] <= pd.to_datetime(self.config['date_to'])]
                self.data[sensor_name] =  df
                self.results[sensor_name] = {}

        # Spojení dat do jednoho DataFrame
        print(f"Data načtena\n Počet senzorů: {len(self.data)}")

    def calculate_gdd(
        self,
        base_temp: float = 10.
        ) -> None:
        """
        Calculate Growing Degree Days (GDD) for vineyard temperature data.

        This method computes the sum of effective temperatures (Growing Degree Days) 
        across the entire measurement period for each dataset. The calculation uses 
        the standard formula: (Daily Max Temp + Daily Min Temp) / 2 - Base Temperature.

        Only positive values are accumulated; days with mean temperatures below the base 
        temperature threshold contribute zero to the sum.

        Args:
            base_temp (float, optional): The base temperature threshold in degrees Celsius 
                below which no growth is assumed to occur. Defaults to 10.0°C, which is 
                standard for grapevine phenological development.

        Returns:
            None. Results are stored in self.results dictionary, where each key corresponds 
            to a dataset in self.data, and the value is the total accumulated GDD 
            for the entire measurement period.

        Example:
            >>> analyzer.calculate_gdd(base_temp=10.0)
            # Results stored in analyzer.results with cumulative GDD values
        """
        # Denní agregace: (Max + Min) / 2 - base_temp
        for k,df in self.data.items():
            daily = df.groupby(
                df['Datum a čas'].dt.date
                )['Teplota'].agg(
                    ['max', 'min']
                    )
            self.results[k]["gdd"] = (
                (daily['max'] + daily['min']) / 2 - base_temp
                ).clip(
                    lower=0  # Do not count days when the mean temperature was below zero
                    ).sum().item() # Sum the whole period

    def calculate_frost_risk(
        self,
        threshold: float = 0
        ) -> None:
        """
        Calculate frost risk by analyzing temperature data across all vineyard stations.
        This method iterates through temperature records for each station and identifies
        frost events defined as occurrences where temperature falls at or below a specified
        threshold. The count of frost events is stored in the results dictionary for each
        station.
        Parameters
        ----------
        threshold : float, optional
            Temperature threshold in degrees (assumed to be Celsius based on column name 'Teplota').
            Temperatures at or below this value are considered frost events.
            Default is 0.
        Returns
        -------
        pandas.Series or pandas.DataFrame
            The last processed frost events Series from the final iteration through self.data items.
            Note: This represents only the last station's data,
            not aggregated results across all stations.
        Notes
        -----
        - Results are stored in self.results[station_key]["frost_events_count"] for each station.
        - The function assumes self.data is a dictionary where keys are station identifiers
          and values are pandas DataFrames containing a 'Teplota' column.
        - Stored output represents only one station's data, not aggregated results across 
          all stations.
        """
        for k,v in self.data.items():
            frost_events = v[v['Teplota'] <= threshold]
            self.results[k]["frost_events_count"] = len(frost_events)

    def calculate_huglin_index(
        self,
        lat_coeff: float = 1.05
        ) -> None:
        """
        Calculate the Huglin index (heliothermic index) for vineyard sites.
        The Huglin index is a bioclimatic index used to classify wine regions based on
        temperature conditions during the growing season. It measures the heat accumulation
        available for grape ripening.
        Formula: Sum of ((Tavg - 10) + (Tmax - 10)) / 2 * K) for each day
        where:
            - Tavg: average daily temperature (°C)
            - Tmax: maximum daily temperature (°C)
            - K: latitude coefficient (lat_coeff)
        Args:
            lat_coeff (float): Latitude coefficient for adjusting the index based on 
                geographic location. Default is 1.05, typical for Czech Republic 
                (45-50° N latitude). Typical range: 1.02 - 1.05.
        Returns:
            None: Results are stored in self.results[station_key]["huglin_index"]
        Notes:
            - Calculation period: April 1 - September 30 (standard growing season)
            - Only positive daily contributions are summed (clipped at 0)
            - Daily values below 10°C do not contribute to the index
            - Results are stored per weather station in the instance data
        """
        for k, df in self.data.items():
            # Huglin se počítá jen z vegetačního období (duben-září)
            veg_df = df[df['Datum a čas'].dt.month.between(4, 9)].copy()

            if not veg_df.empty:
                daily = veg_df.groupby(
                    veg_df['Datum a čas'].dt.date
                    )['Teplota'].agg(
                        ['max', 'mean']
                        )
                hi_daily = ((daily['mean'] - 10) + (daily['max'] - 10)) / 2
                self.results[k]["huglin_index"] = (
                    hi_daily.clip(lower=0) * lat_coeff
                    ).sum().item()
            else:
                self.results[k]["huglin_index"] = 0

    def calculate_dew_point(
        self
        ) -> None:
        """
        Calculate the dew point for each record using the Magnus formula.
        This method computes the dew point temperature for all records in the dataset
        using the Magnus approximation formula with coefficients a = 17.27 and b = 237.7.
        The calculation process:
        1. Extracts temperature and humidity values from the dataframe
        2. Calculates the intermediate alpha value using the Magnus formula
        3. Computes the final dew point temperature
        4. Stores the average dew point in the results dictionary
        The method handles edge cases by replacing zero or near-zero humidity values
        with a small positive number (0.0001) to avoid logarithm errors.
        Returns:
            None: Updates self.data with a new 'Rosny_bod' column and stores
                  the average dew point value in self.results[k]["avg_dew_point"]
                  for each dataset k.
        Note:
            - Requires 'Teplota' (Temperature) and 'Vlhkost' (Humidity) columns in dataframe
            - Humidity values should be in percentage format (0-100)
            - Results are rounded to 2 decimal places
        """
        a = 17.27
        b = 237.7

        for k, df in self.data.items():
            if 'Teplota' in df.columns and 'Vlhkost' in df.columns:
                # 1. Extrakce hodnot
                t = df['Teplota']
                rh = df['Vlhkost'] / 100.0

                # 2. Výpočet alpha (bezpečně ošetříme logaritmus nuly nebo záporných čísel)
                # Použijeme np.log přímo na celou sérii, je to mnohem rychlejší než lambda
                alpha = ((a * t) / (b + t)) + np.log(rh.replace(0, 0.0001))
                # 3. Finální výpočet rosného bodu
                df['Rosny_bod'] = (b * alpha) / (a - alpha)

                # Uložení průměru do výsledků
                self.results[k]["avg_dew_point"] = round(df['Rosny_bod'].mean(), 2).item()

    def calculate_tropical_extremes(
        self
        ) -> None:
        """
        Calculate the count of tropical days and tropical nights.
        Tropical days are defined as days where the maximum temperature is greater than 
        or equal to 30°C. Tropical nights are defined as days where the minimum temperature 
        is greater than or equal to 20°C.
        This method processes temperature data grouped by date and stores the calculated 
        counts in the results dictionary for each data source.
        Results are stored as:
        - tropical_days_count: Integer count of tropical days
        - tropical_nights_count: Integer count of tropical nights
        """
        for k, df in self.data.items():
            daily = df.groupby(df['Datum a čas'].dt.date)['Teplota'].agg(['max', 'min'])

            tropical_days = (daily['max'] >= 30).sum()
            tropical_nights = (daily['min'] >= 20).sum()

            self.results[k]["tropical_days_count"] = int(tropical_days)
            self.results[k]["tropical_nights_count"] = int(tropical_nights)

    # ==== Save results ====
    def save_results(
        self,
        ) -> None:
        """
        Save analysis results to a JSON file.
        The filename is constructed from the date range specified in the configuration.
        """
        time_stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = "Analysis" + f"_{time_stamp}"
        with open(
            f'vystupy/analysis/{name}.json',
            'w',
            encoding='utf-8'
            ) as f:
            json.dump(
                self.results,
                f,
                indent=4,
                ensure_ascii=False,
                )
    def run_pipeline(
        self
        ) -> None:
        """Spustí sekvenci výpočtů definovanou v plánu."""
        print("Spouštím analytickou pipeline...")
        self.load_data()

        self.calculate_gdd(
            base_temp = self.config.get('gdd_base', 10)
            )
        self.calculate_frost_risk(
            threshold = self.config.get('frost_threshold', 0)
            )
        self.calculate_huglin_index(
            lat_coeff = self.config.get('huglin_lat_coeff', 1.05)
            )
        self.calculate_dew_point()
        self.calculate_tropical_extremes()

        # Can be extended

        self.save_results()
        print("Analysis complete.")


#========= Example =======================
V = VineyardAnalyst('vineyard_analyst.yaml')
V.run_pipeline()
# Příklad konfigurace (config.json)
# {
#    "sensors": [
#        {"id": "severni_svah", "path": "data/sensor_1.csv"},
#        {"id": "jizni_svah", "path": "data/sensor_2.csv"}
#    ],
#    "gdd_base": 10
# }
