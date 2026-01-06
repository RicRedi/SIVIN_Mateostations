# -*- coding: utf-8 -*-
"""
Created on Thu Dec 18 12:55:16 2025

@author: xredin00
"""
import os
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import yaml

def plot_sensor_data(
    df: pd.DataFrame,
    config: dict,
    sensor: str = None,
    ) -> None:
    """
    
    Arguments:
        df -- _description_
        config -- _description_
    """
    x_col = config['axes']['x_axis']
    df[x_col['name']] = pd.to_datetime(
        df[x_col['name']],
        dayfirst=True,
        )

    # 1. Filtrování dat
    if config.get('date_from'):
        df = df[df[x_col['name']] >= pd.to_datetime(config['date_from'])]
    if config.get('date_to'):
        df = df[df[x_col['name']] <= pd.to_datetime(config['date_to'])]

    if df.empty:
        print("Chyba: Žádná data pro vybrané období.")
        return

    # Seřazení dat podle času (důležité pro spojitost čar)
    df = df.sort_values(by=x_col['name'])

    # 2. Nastavení vzhledu a palety
    sns.set_theme(style="whitegrid")
    colors = sns.color_palette(
        config['figure']['color_palette']
        ) # Načtení palety Set2

    fig, ax1 = plt.subplots(
        figsize = tuple(config['figure']['fig_size'])
        )

    left_col = config['axes']['left_y']
    right_col = config['axes']['right_y']

    # 3. Vykreslení - Levá osa (První barva z Set2)
    sns.lineplot(
        data=df,
        x=x_col['name'],
        y=left_col["name"],
        ax=ax1,
        color=colors[0],
        linewidth=left_col["line_width"],
        marker=left_col["marker"],
        markersize = left_col["marker_size"],
        label=left_col["label"],
        )

    ax1.set_ylabel(
        left_col["label"],
        fontweight=left_col['label_weight'],
        color=left_col["label_color"],
        fontsize = config["figure"]["font_size"],
        )

    # 4. Vykreslení - Pravá osa (Druhá barva z Set2)
    ax2 = ax1.twinx()
    sns.lineplot(
        data=df,
        x=x_col['name'],
        y=right_col["name"],
        ax=ax2,
        color=colors[1],
        linewidth=right_col["line_width"],
        marker=right_col["marker"],
        markersize = right_col["marker_size"],
        label=right_col["label"],
        )

    ax2.set_ylabel(
        right_col["label"],
        fontweight=right_col['label_weight'],
        color=right_col["label_color"],
        fontsize = config["figure"]["font_size"],
        )

    # 5. Formátování osy X (pouze dny)
    ax1.xaxis.set_major_formatter(
        mdates.DateFormatter('%d. %m.')
        )
    # Zajistíme, aby na ose X byly značky v rozumných intervalech
    ax1.xaxis.set_major_locator(
        mdates.AutoDateLocator()
        )
    ax1.set_xlabel(
        x_col['label'],
        fontsize=config['figure']['tick_size'],
        fontweight=x_col['label_weight']
        )
    # NASTAVENÍ VELIKOSTI POPISKŮ (TICKS)
    # Osa X (společná pro oba grafy)
    ax1.tick_params(
        axis='x',
        labelsize=config['figure']['tick_size'],
        rotation=config['figure']['x_tick_rotation'],
        )

    # Levá osa Y (Teplota)
    ax1.tick_params(
        axis='y',
        labelsize=config['figure']['tick_size'],
        labelcolor=left_col["label_color"]
        )

    # Pravá osa Y (Vlhkost)
    ax2.tick_params(
        axis='y',
        labelsize=config['figure']['tick_size'],
        labelcolor=right_col["label_color"]
        )


    # 6. Dynamický nadpis s rozptylem času
    min_date = df[x_col['name']].min().strftime('%d.%m.%Y')
    max_date = df[x_col['name']].max().strftime('%d.%m.%Y')
    plt.title(
        f"Senzor {sensor}, analýza: {left_col['name']} a {right_col['name']}\n"
        f"({min_date} - {max_date})",
        fontsize = config["figure"]["title_size"],
        fontweight = config["figure"]['title_weight']
        )

    # Sjednocení legendy (nepovinné, ale vypadá to lépe)
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines + lines2,
        labels + labels2,
        loc=config['figure']['legend_loc'],           # 'upper center'
        bbox_to_anchor=(
            0.5, # Polovina obrázku
            config['figure'].get('legend_y_offset', -0.15)
            ),               # Pozice (x, y) relativně k osám
        ncol=config['figure'].get('legend_cols', 2),  # Počet sloupců
        fontsize=config['figure']['font_size'],
        frameon=True                                  # O rámeček se postaráme podle vkusu
    )
    ax2.get_legend().remove()

    fig.tight_layout()
    # 7. Ukládání (vložte před plt.show())
    save_cfg = config.get('save', {'on_off': False})
    if save_cfg.get('on_off'):
        # Vytvoření cesty, pokud neexistuje
        for fmt in save_cfg.get('format', ['eps']):
            dir_path = os.path.join(
                save_cfg.get('path', '.'),
                fmt,
                )
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

        # Sestavení názvu souboru (prefix + časový rozsah)
        # prefix = save_cfg.get('filename_prefix', 'plot')
        filename = f"{
            save_cfg.get('filename_prefix', 'plot')
            }_{sensor}_{min_date}_{max_date}".replace('.', '-')

        # Cyklus přes požadované formáty
        for fmt in save_cfg.get('format', ['eps']):
            full_path = os.path.join(
                save_cfg.get('path', '.'),
                fmt,
                f"{filename}.{fmt}",
                )

            # Parametr bbox_inches='tight' je KLÍČOVÝ,
            # zajistí, že se legenda pod grafem neořízne!
            fig.savefig(
                full_path,
                format=fmt,
                dpi = save_cfg.get('dpi', 600),
                transparent = save_cfg.get('transparent', False),
                bbox_inches = 'tight',
            )
    else:
        plt.show()

# --- HLAVNÍ ŘÍZENÍ PROGRAMU ---
if __name__ == "__main__":
    # Načtení YAML konfigurace
    with open(
            "two_variable_plot_config.yaml",
            "r",
            encoding="utf-8",
            ) as f:
        cfg = yaml.safe_load(f)

    # Načtení dat z Excelu (používáme cestu z YAML)
    # Přidán decimal=',' pro správné načtení českých čísel
    try:
        # Volání funkce
        for sensor in cfg.get('sensor', [None]):
            if sensor:
                data = pd.read_excel(
                    cfg['file_path'],
                    decimal=',',
                    sheet_name=sensor,
                    )
                plot_sensor_data(
                    data,
                    cfg,
                    sensor,
                    )
    except Exception as e:
        print(f"Nastala chyba: {e}")
